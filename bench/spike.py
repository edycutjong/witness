"""Day-0 spike: can Relate transactions + rollback() be the inner loop of a graph reducer?

Protocol (rollback design), on the full committed graph and the headline query:
  0. headline + companion raw rows on the source            -> evidence/headline-raw.json
  1. sanity: deleting a known-necessary relationship inside a tx changes the answer (read-your-writes)
  2. 1,000 trials: begin -> delete one relationship -> query -> record -> rollback; counts asserted after EVERY
     rollback, delete count asserted on every trial; every 100 trials the baseline is re-run and RSS sampled
  3. history independence: trials 1-50 replayed on the same scratch AND on a fresh copy (raw rows as multisets),
     deleted ids re-resolved to their canonical keys after each rollback
  4. delete statement: IN-list form vs UNWIND form, same trials
  5. full reduction (ddmin, src/witness/reduce.py) -> export .cypher + .rl -> reopen -> re-check the answer ->
     each remaining relationship removed on its own fresh copy of W.rl (N of N must change the answer)
  6. determinism: a second reduction from a fresh copy gives a byte-identical .cypher
  7. probes: temporal map constructors, two-statement query_type, CALL { CREATE } query_type, CLI .begin/.rollback,
     scratch build cost (temp copy vs replay into :memory:), disagree (headline vs agent twin)

GO = >= 50 trials/s AND full reduction < 120 s AND counts restored after all 1,000 rollbacks AND replay matches AND
the export re-check passes.

    uv run python bench/spike.py            -> evidence/spike-<date>.{json,md} + side files
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import random
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path

os.environ.setdefault("DO_NOT_TRACK", "1")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import relate  # noqa: E402

from witness.canon import canon_rows, digest, rel_key  # noqa: E402
from witness.export import cypher_script, write_rl  # noqa: E402
from witness.reduce import Reducer  # noqa: E402
from witness.store import DEL_RELS, DEL_RELS_IN_LIST, Scratch  # noqa: E402

SRC = ROOT / "data" / "air-routes.rl"
EV = ROOT / "evidence"
Q = (ROOT / "queries" / "two-hub.cypher").read_text()
ABS = (ROOT / "queries" / "two-hub-absence.cypher").read_text()
AGENT = (ROOT / "queries" / "two-hub-agent.cypher").read_text()
BIND_IDS = (
    (ROOT / "queries" / "two-hub-bindings.cypher")
    .read_text()
    .replace("RETURN DISTINCT r", "RETURN DISTINCT elementId(r) AS rid ORDER BY rid")
)
PARAMS = {"country": "MX", "dest": "MEX"}  # picked by bench/country_scan.py (evidence/witness-vs-bindings.json)
TRIALS = 1000
SEED = 0
GO_TRIALS_PER_S = 50
GO_REDUCTION_S = 120


def sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def rss_kb() -> int:
    out = subprocess.run(["ps", "-o", "rss=", "-p", str(os.getpid())], capture_output=True, text=True)
    return int(out.stdout.strip() or 0)


def pct(xs: list[float], p: float) -> float:
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(round(p / 100 * (len(xs) - 1))))]


def machine() -> dict:
    def sysctl(k):
        try:
            return subprocess.run(["sysctl", "-n", k], capture_output=True, text=True).stdout.strip()
        except OSError:
            return ""

    return {
        "os": f"{platform.system()} {platform.release()}",
        "arch": platform.machine(),
        "cpu": sysctl("machdep.cpu.brand_string") or platform.processor(),
        "mem_bytes": sysctl("hw.memsize"),
        "python": platform.python_version(),
        "relate_db": relate.__version__,
    }


def multiset(rows: list[dict]) -> Counter:
    return Counter(json.dumps(r, sort_keys=True, default=str) for r in rows)


def relkey_by_id(sc: Scratch, rid: str) -> str | None:
    res = sc.run(
        "MATCH (a)-[r]->(b) WHERE elementId(r) = $id RETURN type(r) AS t, elementId(a) AS s, elementId(b) AS e, "
        "properties(r) AS p",
        {"id": rid},
    ).data
    if not res:
        return None
    r = res[0]
    return rel_key(r["t"], sc.node_keys[r["s"]], sc.node_keys[r["e"]], r["p"])


def trial_loop(sc: Scratch, rels: list[str], baseline: tuple, base_counts, stmt: str, rows_out: list | None):
    sc.del_rels_stmt = stmt
    counts_ok = 0
    rss = []
    baseline_rechecks = []
    ms = []
    t0 = time.perf_counter()
    for i, rid in enumerate(rels, 1):
        t = sc.trial(Q, PARAMS, [rid], ())
        after = sc.counts()
        ok = after == base_counts
        counts_ok += ok
        if not ok:
            raise SystemExit(f"COUNT MISMATCH after rollback of trial {i}: {after} != {base_counts}")
        ans = None if t.error else canon_rows(t.rows, t.columns, strict_lists=True, keyer=sc.keyer)
        ms.append(t.ms)
        if rows_out is not None:
            rows_out.append(
                {
                    "n": i,
                    "rel": sc.rel_keys[rid],
                    "rel_type": sc.rel_type[rid],
                    "ms": round(t.ms, 4),
                    "deleted": t.deleted_rels,
                    "error": t.error,
                    "raw_rows": t.rows,
                    "answer_digest": None if ans is None else digest(ans),
                    "changed": None if ans is None else ans != baseline,
                    "counts_after": list(after),
                }
            )
        if i % 100 == 0:
            again = sc.answer(Q, PARAMS, strict_lists=True)
            baseline_rechecks.append({"after_trial": i, "equal": again == baseline})
            rss.append({"after_trial": i, "rss_kb": rss_kb()})
    wall = time.perf_counter() - t0
    return {
        "wall_s": wall,
        "trials_per_s": len(rels) / wall,
        "counts_ok": counts_ok,
        "ms": ms,
        "baseline_rechecks": baseline_rechecks,
        "rss": rss,
    }


def check_witness(w_rl: Path, baseline: tuple, tmp: Path) -> dict:
    """Sufficiency on a fresh copy of W, then necessity: each relationship deleted on its own fresh copy."""
    sc = Scratch.open_copy(w_rl, tmp)
    rels = sorted(sc.rel_keys, key=sc.rel_keys.get)
    keys = {r: sc.rel_keys[r] for r in rels}
    suff = sc.answer(Q, PARAMS, strict_lists=True) == baseline
    touched = {x for se in sc.rel_ends.values() for x in se}
    isolated = [n for n in sc.node_keys if n not in touched]
    sc.close()
    probes = []
    for r in rels:
        c = Scratch.open_copy(w_rl, tmp)
        rid = next(i for i, k in c.rel_keys.items() if k == keys[r])
        c.commit_delete([rid], ())
        ans = c.answer(Q, PARAMS, strict_lists=True)
        probes.append({"rel": keys[r], "changes_answer": ans != baseline})
        c.close()
    for n in isolated:
        c = Scratch.open_copy(w_rl, tmp)
        c.commit_delete((), [n])
        probes.append({"node": n, "changes_answer": c.answer(Q, PARAMS, strict_lists=True) != baseline})
        c.close()
    changed = sum(p["changes_answer"] for p in probes)
    return {
        "sufficient": suff,
        "probes": len(probes),
        "change_the_answer": changed,
        "isolated_nodes": len(isolated),
        "passes": suff and changed == len(probes) and len(probes) > 0,
        "detail": probes,
    }


def reduce_once(tmp: Path, tag: str) -> tuple[dict, str, Path]:
    t_open = time.perf_counter()
    sc = Scratch.open_copy(SRC, tmp)
    open_s = time.perf_counter() - t_open
    t0 = time.perf_counter()
    red = Reducer(sc, Q, PARAMS, seed=SEED, strict_lists=True, check_every=1)
    out = red.run()
    out["wall_s_incl_baseline"] = round(time.perf_counter() - t0, 3)
    out["scratch_open_s"] = round(open_s, 3)
    out["end_to_end_s"] = round(open_s + out["wall_s_incl_baseline"], 3)
    out["trial_ms_p50"] = round(statistics.median(red.stats.trial_ms), 4)
    out["trial_ms_p95"] = round(pct(red.stats.trial_ms, 95), 4)
    header = (
        f"Witness spike: deletion-minimal witness of queries/two-hub.cypher {json.dumps(PARAMS)}\n"
        f"source data/air-routes.rl sha256 {sha256(SRC)}; seed {SEED}; relate-db {relate.__version__}"
    )
    script = cypher_script(sc, header)
    sc.close()
    path = tmp / f"witness-{tag}.cypher"
    path.write_text(script)
    return out, script, path


def cli_probe(w_rl: Path, tmp: Path) -> dict:
    relate_bin = shutil.which("relate") or str(Path.home() / ".local/bin/relate")
    env = {**os.environ, "DO_NOT_TRACK": "1"}
    out = {"binary": "relate (on PATH)" if shutil.which("relate") else "relate (~/.local/bin)"}
    try:
        out["version"] = (
            subprocess.run([relate_bin, "--version"], capture_output=True, text=True, env=env, timeout=30)
            .stdout.strip()
            .splitlines()[0]
        )
    except Exception as e:  # noqa: BLE001
        out["error"] = f"{type(e).__name__}: {e}"
        return out
    q_one_line = " ".join(line for line in Q.splitlines() if not line.strip().startswith("//"))
    q_lit = q_one_line.replace("$country", "'MX'").replace("$dest", "'MEX'")
    # sufficiency: read-only JSON over W
    r = subprocess.run(
        [
            relate_bin,
            "query",
            "--database",
            str(w_rl),
            "--read-only",
            "--mode",
            "json",
            "--max-rows",
            "0",
            "--timeout",
            "30s",
        ],
        input=q_lit + ";\n",
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )
    out["sufficiency"] = {"exit": r.returncode, "stdout": r.stdout[-2000:], "stderr": r.stderr[-500:]}
    # necessity form: --load W.rl into a NEW path (a writable copy), .begin / delete / query / .rollback piped
    target = tmp / "cli-probe-copy.rl"
    script = (
        ".begin\nMATCH (a:Airport {iata: 'UPN'})-[r:IN_COUNTRY]->() DELETE r RETURN count(*) AS deleted;\n"
        f"{q_lit};\n.rollback\n{q_lit};\n"
    )
    r2 = subprocess.run(
        [relate_bin, "query", "--load", str(w_rl), "--database", str(target), "--mode", "json"],
        input=script,
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )
    out["begin_rollback"] = {
        "exit": r2.returncode,
        "stdout": r2.stdout[-3000:],
        "stderr": r2.stderr[-800:],
        "target_created": target.exists(),
    }
    out["w_rl_sha_unchanged"] = None  # filled by caller
    return out


def probes(tmp: Path) -> dict:
    out = {}
    db = relate.Database(":memory:")

    def val(stmt):
        try:
            r = db.execute(stmt)
            return {"rows": [{k: str(v) for k, v in row.items()} for row in r.data], "query_type": r.query_type}
        except Exception as e:  # noqa: BLE001
            return {"error": f"{type(e).__name__}: {e}"}

    for stmt in ["RETURN datetime({}) AS v", "RETURN datetime({timezone: 'UTC'}) AS v", "RETURN datetime() AS v"]:
        a = val(stmt)
        time.sleep(1.1)
        b = val(stmt)
        out[stmt] = {
            "first": a,
            "second_after_1.1s": b,
            "reads_clock": ("rows" in a and "rows" in b and a["rows"] != b["rows"]),
        }

    def qtype(stmt):
        try:
            r = db.execute("EXPLAIN " + stmt)
            return {"query_type": r.query_type}
        except Exception as e:  # noqa: BLE001
            return {"error": f"{type(e).__name__}: {e}"}

    out["query_type: two statements"] = qtype("MATCH (n) RETURN n; CREATE (m) RETURN m")
    out["query_type: CALL { CREATE (n) RETURN n } RETURN 1"] = qtype("CALL { CREATE (n) RETURN n } RETURN 1")
    out["query_type: headline"] = qtype(Q)
    db.close()

    # scratch build cost: temp byte copy + open + index, vs replay into :memory: from a read-only open
    t0 = time.perf_counter()
    sc = Scratch.open_copy(SRC, tmp)
    copy_s = time.perf_counter() - t0
    counts = sc.counts()
    sc.close()
    t0 = time.perf_counter()
    ro = relate.Database(str(SRC), read_only=True)
    nodes = ro.execute("MATCH (n) RETURN elementId(n) AS id, labels(n)[0] AS l, properties(n) AS p").data
    rels = ro.execute(
        "MATCH (a)-[r]->(b) RETURN elementId(a) AS s, elementId(b) AS e, type(r) AS t, properties(r) AS p"
    ).data
    ro.close()
    mem = relate.Database(":memory:")
    label_of = {n["id"]: n["l"] for n in nodes}
    by_label: dict[str, list] = {}
    for n in nodes:
        by_label.setdefault(n["l"], []).append({"k": n["id"], "p": n["p"]})
    for label, rows in by_label.items():
        mem.execute(f"CREATE INDEX tmp_{label.lower()}_k IF NOT EXISTS FOR (x:`{label}`) ON (x.__k)")
        for i in range(0, len(rows), 1000):
            mem.execute(
                f"UNWIND $rows AS r CREATE (x:`{label}`) SET x = r.p, x.__k = r.k", {"rows": rows[i : i + 1000]}
            )
    by_shape: dict[tuple, list] = {}
    for r in rels:
        by_shape.setdefault((r["t"], label_of[r["s"]], label_of[r["e"]]), []).append(r)
    for (t, ls, le), rows in by_shape.items():
        for i in range(0, len(rows), 1000):
            mem.execute(
                f"UNWIND $rows AS r MATCH (a:`{ls}` {{__k: r.s}}), (b:`{le}` {{__k: r.e}}) "
                f"CREATE (a)-[x:`{t}`]->(b) SET x = r.p",
                {"rows": rows[i : i + 1000]},
            )
    replay_counts = (mem.node_count(), mem.relationship_count())
    mem.close()
    replay_s = time.perf_counter() - t0
    out["scratch_build"] = {
        "temp_copy_open_index_s": round(copy_s, 3),
        "copy_counts": list(counts),
        "replay_into_memory_s": round(replay_s, 3),
        "replay_counts": list(replay_counts),
        "note": "replay is the fallback path; it adds a helper key property the real "
        "implementation would avoid, so it is an upper-bound sketch, not the product",
    }
    return out


def disagree_probe() -> dict:
    db = relate.Database(str(SRC), read_only=True)
    a = db.execute(Q, PARAMS).data
    b = db.execute(AGENT, PARAMS).data
    db.close()
    ca, cb = canon_rows(a, strict_lists=True), canon_rows(b, strict_lists=True)
    return {"params": PARAMS, "headline_rows": a, "agent_rows": b, "differ": ca != cb, "relate_db": relate.__version__}


def main() -> None:
    EV.mkdir(exist_ok=True)
    date = time.strftime("%Y-%m-%d")
    tmp_ctx = tempfile.TemporaryDirectory(prefix="witness-spike-")
    tmp = Path(tmp_ctx.name)
    src_sha_before = sha256(SRC)
    report: dict = {
        "date": time.strftime("%Y-%m-%d %H:%M:%S %z"),
        "machine": machine(),
        "relate_cli": None,
        "source": {"path": "data/air-routes.rl", "sha256_before": src_sha_before},
        "query": "queries/two-hub.cypher",
        "params": PARAMS,
        "seed": SEED,
    }

    # 0. headline first
    ro = relate.Database(str(SRC), read_only=True)
    head = ro.execute(Q, PARAMS)
    comp = ro.execute(ABS, {**PARAMS, "airports": [r["airport"] for r in head.data]})
    ro.close()
    (EV / "headline-raw.json").write_text(
        json.dumps(
            {
                "query": "queries/two-hub.cypher",
                "params": PARAMS,
                "rows": head.data,
                "query_type": head.query_type,
                "companion": "queries/two-hub-absence.cypher",
                "companion_rows": comp.data,
                "companion_mismatches": sum(1 for c in comp.data if c["direct_flights"] != 0 or c["reaching_hubs"] < 2),
                "relate_db": relate.__version__,
                "source_sha256": src_sha_before,
            },
            indent=2,
        )
        + "\n"
    )
    print("headline", head.data, flush=True)

    # 1. sanity (read-your-writes)
    sc = Scratch.open_copy(SRC, tmp)
    base_counts = sc.counts()
    baseline = sc.answer(Q, PARAMS, strict_lists=True)
    must = next(
        r
        for r, (s, e) in sc.rel_ends.items()
        if sc.rel_type[r] == "IN_COUNTRY" and sc.node_props[s].get("iata") == "UPN"
    )
    t = sc.trial(Q, PARAMS, [must], ())
    sanity = {
        "deleted": "UPN-[:IN_COUNTRY]->MX",
        "answer_changed": canon_rows(t.rows, t.columns, strict_lists=True, keyer=sc.keyer) != baseline,
        "rows_inside_tx": t.rows,
        "counts_restored": sc.counts() == base_counts,
        "answer_restored": sc.answer(Q, PARAMS, strict_lists=True) == baseline,
    }
    report["sanity"] = sanity
    print("sanity", sanity, flush=True)
    if not (sanity["answer_changed"] and sanity["counts_restored"] and sanity["answer_restored"]):
        raise SystemExit("SANITY FAILED: deleting a necessary relationship inside the tx did not change the answer")

    # 2. 1,000 trials
    all_rels = sorted(sc.rel_keys, key=sc.rel_keys.get)
    sample = random.Random(SEED).sample(all_rels, TRIALS)
    sample_keys = [sc.rel_keys[r] for r in sample]
    rows: list = []
    rss0 = rss_kb()
    loop = trial_loop(sc, sample, baseline, base_counts, DEL_RELS, rows)
    report["trials"] = {
        "n": TRIALS,
        "delete_stmt": DEL_RELS,
        "wall_s": round(loop["wall_s"], 3),
        "trials_per_s": round(loop["trials_per_s"], 1),
        "trial_ms_p50": round(statistics.median(loop["ms"]), 4),
        "trial_ms_p95": round(pct(loop["ms"], 95), 4),
        "trial_ms_max": round(max(loop["ms"]), 4),
        "counts_restored": f"{loop['counts_ok']}/{TRIALS}",
        "delete_count_asserted": f"{sum(1 for r in rows if r['deleted'] == 1)}/{TRIALS}",
        "errors": sum(1 for r in rows if r["error"]),
        "answer_changed": sum(1 for r in rows if r["changed"]),
        "baseline_rechecks": loop["baseline_rechecks"],
        "rss_kb_start": rss0,
        "rss_series": loop["rss"],
    }
    r100, r1000 = loop["rss"][0]["rss_kb"], loop["rss"][-1]["rss_kb"]
    report["trials"]["rss_growth_100_to_1000_pct"] = round(100 * (r1000 - r100) / r100, 2)
    report["trials"]["rss_flag"] = (r1000 - r100) / r100 > 0.10
    print(
        "trials",
        {
            k: report["trials"][k]
            for k in ("trials_per_s", "trial_ms_p50", "trial_ms_p95", "counts_restored", "answer_changed")
        },
        flush=True,
    )

    # 3. history independence: replay trials 1-50 on the same scratch and on a fresh copy
    first50 = rows[:50]
    same_ok = id_ok = 0
    for i, rid in enumerate(sample[:50]):
        t = sc.trial(Q, PARAMS, [rid], (), check_counts=base_counts)
        same_ok += multiset(t.rows) == multiset(first50[i]["raw_rows"])
        id_ok += relkey_by_id(sc, rid) == sample_keys[i]
    sc2 = Scratch.open_copy(SRC, tmp)
    fresh_ok = 0
    for i, key in enumerate(sample_keys[:50]):
        rid = next(r for r, k in sc2.rel_keys.items() if k == key)
        t = sc2.trial(Q, PARAMS, [rid], (), check_counts=base_counts)
        fresh_ok += multiset(t.rows) == multiset(first50[i]["raw_rows"])
    sc2.close()
    # 3b. targeted replay: the sampled trials above almost never touch the answer, so also run every relationship the
    # answer rows match (B, queries/two-hub-bindings.cypher) as a trial, then replay that list on the same scratch and
    # on a fresh copy. Most of these trials change the answer, so a leaked delete would show here.
    bind_ids = [r["rid"] for r in sc.run(BIND_IDS, PARAMS).data]
    bind_keys = [sc.rel_keys[r] for r in bind_ids]
    first = [sc.trial(Q, PARAMS, [r], (), check_counts=base_counts).rows for r in bind_ids]
    t_changed = sum(canon_rows(x, strict_lists=True, keyer=sc.keyer) != baseline for x in first)
    t_same = sum(
        multiset(sc.trial(Q, PARAMS, [r], (), check_counts=base_counts).rows) == multiset(first[i])
        for i, r in enumerate(bind_ids)
    )
    t_ids = sum(relkey_by_id(sc, r) == bind_keys[i] for i, r in enumerate(bind_ids))
    sc3 = Scratch.open_copy(SRC, tmp)
    by_key = {k: r for r, k in sc3.rel_keys.items()}
    t_fresh = sum(
        multiset(sc3.trial(Q, PARAMS, [by_key[k]], (), check_counts=base_counts).rows) == multiset(first[i])
        for i, k in enumerate(bind_keys)
    )
    sc3.close()
    nb = len(bind_ids)
    report["replay"] = {
        "same_scratch": f"{same_ok}/50",
        "fresh_copy": f"{fresh_ok}/50",
        "deleted_ids_resolve_to_same_key": f"{id_ok}/50",
        "first50_changed_answer": sum(1 for r in first50 if r["changed"]),
        "targeted_B": nb,
        "targeted_changed_answer": t_changed,
        "targeted_same_scratch": f"{t_same}/{nb}",
        "targeted_fresh_copy": f"{t_fresh}/{nb}",
        "targeted_ids_resolve_to_same_key": f"{t_ids}/{nb}",
        "passes": same_ok == 50 and fresh_ok == 50 and id_ok == 50 and t_same == nb and t_fresh == nb and t_ids == nb,
    }
    print("replay", report["replay"], flush=True)

    # 4. delete statement forms (same first 200 sampled relationships)
    forms = {}
    for name, stmt in (("in_list", DEL_RELS_IN_LIST), ("unwind", DEL_RELS)):
        lp = trial_loop(sc, sample[:200], baseline, base_counts, stmt, None)
        forms[name] = {
            "stmt": stmt,
            "trials": 200,
            "trials_per_s": round(lp["trials_per_s"], 1),
            "trial_ms_p50": round(statistics.median(lp["ms"]), 4),
            "trial_ms_p95": round(pct(lp["ms"], 95), 4),
            "counts_ok": lp["counts_ok"],
        }
    report["delete_forms"] = forms
    sc.del_rels_stmt = DEL_RELS
    sc.close()

    # 5. full reduction + export + re-check
    red, script, cy = reduce_once(tmp, "a")
    w_rl = tmp / "witness-a.rl"
    w_counts = write_rl(script, w_rl)
    chk = check_witness(w_rl, baseline, tmp)
    report["reduction"] = {**red, "witness_counts": list(w_counts)}
    report["export_check"] = {k: v for k, v in chk.items() if k != "detail"}
    print("reduction", {k: red[k] for k in ("seconds", "trials", "final_counts", "inconclusive")}, flush=True)
    print("check", report["export_check"], flush=True)

    # 6. determinism
    red_b, script_b, _ = reduce_once(tmp, "b")
    report["determinism"] = {
        "identical_cypher": script == script_b,
        "sha256": hashlib.sha256(script.encode()).hexdigest(),
        "second_seconds": red_b["seconds"],
    }

    # 7. probes
    w_sha = sha256(w_rl)
    cli = cli_probe(w_rl, tmp)
    cli["w_rl_sha_unchanged"] = sha256(w_rl) == w_sha
    report["relate_cli"] = cli.get("version")
    (EV / "cli-probe.json").write_text(json.dumps(cli, indent=2) + "\n")
    report["probes"] = probes(tmp)
    dis = disagree_probe()
    (EV / "disagree-probe.json").write_text(json.dumps(dis, indent=2, default=str) + "\n")
    report["disagree_probe"] = {"differ": dis["differ"]}

    report["source"]["sha256_after"] = sha256(SRC)
    report["source"]["unchanged"] = report["source"]["sha256_after"] == src_sha_before

    go = {
        "trials_per_s>=50": report["trials"]["trials_per_s"] >= GO_TRIALS_PER_S,
        "reduction<120s": red["seconds"] < GO_REDUCTION_S,
        "counts_restored_1000/1000": loop["counts_ok"] == TRIALS,
        "replay_matches": report["replay"]["passes"],
        "baseline_rechecks_equal": all(b["equal"] for b in loop["baseline_rechecks"]),
        "export_recheck_passes": chk["passes"],
        "source_unchanged": report["source"]["unchanged"],
    }
    report["go_checks"] = go
    report["verdict"] = "SPIKE GO (rollback design)" if all(go.values()) else "ROLLBACK DESIGN FAILED"

    # evidence files
    shutil.copyfile(cy, EV / "spike-witness-two-hub.cypher")
    shutil.copyfile(w_rl, EV / "spike-witness-two-hub.rl")
    (EV / f"spike-{date}.json").write_text(
        json.dumps({"report": report, "trial_rows": rows, "check_detail": chk["detail"]}, indent=1, default=str) + "\n"
    )
    (EV / f"spike-{date}.md").write_text(render_md(report))
    print(report["verdict"], json.dumps(go))
    tmp_ctx.cleanup()


def render_md(r: dict) -> str:
    t, red, chk, m = r["trials"], r["reduction"], r["export_check"], r["machine"]
    rss = ", ".join(f"{x['after_trial']}:{x['rss_kb']}" for x in t["rss_series"])
    lines = [
        f"# Day-0 spike: {r['verdict']}",
        "",
        f"Run {r['date']} · `bench/spike.py` · raw rows in `spike-{r['date'][:10]}.json`.",
        f"Machine: {m['cpu']}, {m['os']} {m['arch']}, {int(m['mem_bytes'] or 0) // 2**30} GiB RAM, "
        f"Python {m['python']}.",
        f"Relate: relate-db {m['relate_db']} (Python, in-process); CLI {r['relate_cli']}.",
        f"Graph: `data/air-routes.rl` (full graph), sha256 `{r['source']['sha256_before'][:16]}…`, "
        f"unchanged after the run: {r['source']['unchanged']}.",
        f"Query: `{r['query']}` with {json.dumps(r['params'])}; seed {r['seed']}.",
        "",
        "| Check | Result |",
        "|---|---|",
        f"| Sanity: delete UPN's IN_COUNTRY inside a tx | answer changed: {r['sanity']['answer_changed']}; "
        f"restored after rollback: {r['sanity']['answer_restored']} |",
        f"| 1,000 single-relationship trials (begin → delete → query → rollback) | **{t['trials_per_s']} trials/s** "
        f"({t['wall_s']} s wall, incl. a count check after every rollback) |",
        f"| Trial latency | p50 {t['trial_ms_p50']} ms · p95 {t['trial_ms_p95']} ms · max {t['trial_ms_max']} ms |",
        f"| Counts restored after every rollback | {t['counts_restored']} |",
        f"| Delete count asserted on every trial | {t['delete_count_asserted']} |",
        f"| Baseline re-run every 100 trials | {sum(b['equal'] for b in t['baseline_rechecks'])}/"
        f"{len(t['baseline_rechecks'])} equal |",
        f"| Trials whose answer changed | {t['answer_changed']} of {t['n']} (errors: {t['errors']}) |",
        f"| RSS (KiB) by trial | {rss}; growth 100→1000: {t['rss_growth_100_to_1000_pct']}% "
        f"(flag > 10%: {t['rss_flag']}) |",
        f"| Replay trials 1–50 | same scratch {r['replay']['same_scratch']} · fresh copy {r['replay']['fresh_copy']} · "
        f"ids → same key {r['replay']['deleted_ids_resolve_to_same_key']} "
        f"({r['replay']['first50_changed_answer']} of these 50 changed the answer) |",
        f"| Targeted replay: every relationship the answer rows match (B = {r['replay']['targeted_B']}) | "
        f"{r['replay']['targeted_changed_answer']} of {r['replay']['targeted_B']} change the answer; "
        f"replay same scratch {r['replay']['targeted_same_scratch']} · "
        f"fresh copy {r['replay']['targeted_fresh_copy']} · "
        f"ids → same key {r['replay']['targeted_ids_resolve_to_same_key']} |",
        f"| Delete form, IN list vs UNWIND (200 trials each) | {r['delete_forms']['in_list']['trials_per_s']} vs "
        f"{r['delete_forms']['unwind']['trials_per_s']} trials/s |",
        f"| Full reduction (ddmin, seed {r['seed']}) | **{red['seconds']} s**, {red['trials']} trials, "
        f"{red['inconclusive']} inconclusive, p50 {red['trial_ms_p50']} ms / p95 {red['trial_ms_p95']} ms per trial |",
        f"| End to end (scratch copy + open + index, then baseline + reduction) | {red['end_to_end_s']} s "
        f"(scratch {red['scratch_open_s']} s) |",
        f"| Witness size | {red['final_counts'][0]} nodes, {red['final_counts'][1]} relationships "
        f"(from {red['start_counts'][0]} / {red['start_counts'][1]}) |",
        f"| Export → reopen → re-check | sufficient: {chk['sufficient']}; "
        f"**{chk['change_the_answer']} of {chk['probes']} change the answer** (each on a fresh copy of W) |",
        f"| Determinism (second run, fresh copy) | byte-identical .cypher: {r['determinism']['identical_cypher']} |",
        f"| `disagree` probe (headline vs agent twin) | answers differ: {r['disagree_probe']['differ']} |",
        "",
        "GO checks: " + ", ".join(f"{k} {'PASS' if v else 'FAIL'}" for k, v in r["go_checks"].items()),
        "",
        "Plan chunk (trial 1): " + json.dumps(red["plan"]),
        "",
        "Probes: see `spike-*.json` → `report.probes`, `cli-probe.json`, `disagree-probe.json`.",
        "",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    main()
