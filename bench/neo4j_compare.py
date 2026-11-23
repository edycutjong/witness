"""W5: the same rollback-trial loop, Relate in-process vs Neo4j in Docker over Bolt. A measured number, not a claim.

For each trial (same relationship on both sides, same query, same parameters, same order):
    begin -> delete that one relationship -> run the headline query, fetch every row -> rollback -> counts restored?
Relate runs in this process (`:memory:` copy of data/air-routes.rl). Neo4j runs in Docker (loopback Bolt, one explicit
transaction per trial; driver round trips are included, which is the honest cost of a server). Neither side is tuned:
Neo4j keeps its default heap and page cache, with the Airport.id/Country.code/Continent.code constraints.
The ONLY query difference is dialect: Neo4j has no coll.sort(), so queries/two-hub.neo4j.cypher orders before collect().

    uv run --with neo4j python bench/neo4j_compare.py [--trials 1000] [--runs 3]
        -> evidence/neo4j-compare-<date>.json + neo4j-compare-rows.jsonl

Credentials come from ~/.config/witness/neo4j.env (never printed, never written to evidence).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import random
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
from neo4j import GraphDatabase  # noqa: E402

from witness.store import DEL_RELS, Scratch  # noqa: E402

SRC = ROOT / "data" / "air-routes.rl"
EV = ROOT / "evidence"
Q_RELATE = (ROOT / "queries" / "two-hub.cypher").read_text()
Q_NEO4J = (ROOT / "queries" / "two-hub.neo4j.cypher").read_text()
BIND_IDS = (
    (ROOT / "queries" / "two-hub-bindings.cypher")
    .read_text()
    .replace("RETURN DISTINCT r", "RETURN DISTINCT elementId(r) AS rid ORDER BY rid")
)
PARAMS = {"country": "MX", "dest": "MEX"}
SEED = 0
IDENT = {"Airport": "id", "Country": "code", "Continent": "code"}


def pct(xs, p):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(round(p / 100 * (len(xs) - 1))))]


def multiset(rows):
    return Counter(json.dumps(r, sort_keys=True, default=str) for r in rows)


def sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def read_env(path: Path) -> dict:
    return dict(ln.split("=", 1) for ln in path.read_text().splitlines() if "=" in ln and not ln.startswith("#"))


def ident(labels, props):
    lab = next(label for label in labels if label in IDENT)
    return lab, props[IDENT[lab]]


def summarize(ms, wall, n):
    return {
        "trials": n,
        "wall_s": round(wall, 3),
        "trials_per_s": round(n / wall, 1),
        "trial_ms_p50": round(statistics.median(ms), 3),
        "trial_ms_p95": round(pct(ms, 95), 3),
        "trial_ms_max": round(max(ms), 3),
    }


def machine() -> dict:
    def sysctl(k):
        try:
            return subprocess.run(["sysctl", "-n", k], capture_output=True, text=True).stdout.strip()
        except OSError:
            return ""

    docker = (
        subprocess.run(
            ["docker", "info", "--format", "{{.ServerVersion}}|{{.NCPU}}|{{.MemTotal}}"], capture_output=True, text=True
        )
        .stdout.strip()
        .split("|")
    )
    return {
        "os": f"{platform.system()} {platform.release()}",
        "arch": platform.machine(),
        "cpu": sysctl("machdep.cpu.brand_string"),
        "mem_bytes": sysctl("hw.memsize"),
        "python": platform.python_version(),
        "relate_db": relate.__version__,
        "docker_server": docker[0] if docker else None,
        "docker_vm_cpus": docker[1] if len(docker) > 1 else None,
        "docker_vm_mem_bytes": docker[2] if len(docker) > 2 else None,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--trials", type=int, default=1000)
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--warmup", type=int, default=100)
    a = ap.parse_args()
    env = read_env(Path.home() / ".config" / "witness" / "neo4j.env")
    bolt = env["NEO4J_BOLT"]
    driver = GraphDatabase.driver(bolt, auth=(env["NEO4J_USER"], env["NEO4J_PASSWORD"]))
    driver.verify_connectivity()
    sha_before = sha256(SRC)
    tmp_ctx = tempfile.TemporaryDirectory(prefix="witness-w5-")
    sc = Scratch.open_copy(SRC, Path(tmp_ctx.name))
    base_counts = sc.counts()

    # the same relationships on both sides, resolved to Neo4j element ids once, outside every timed loop
    keys = sorted(sc.rel_keys, key=sc.rel_keys.get)
    sample = random.Random(SEED).sample(keys, a.trials + a.warmup)
    with driver.session() as s:
        n_nodes = s.run("MATCH (n) RETURN count(n) AS c").single()["c"]
        n_rels = s.run("MATCH ()-[r]->() RETURN count(r) AS c").single()["c"]
        if (n_nodes, n_rels) != base_counts:
            raise SystemExit(f"Neo4j graph {n_nodes, n_rels} != Relate graph {base_counts}")
        ambiguous = 0

        def resolve(rids):
            nonlocal ambiguous
            out = []
            for rid in rids:
                sid, eid = sc.rel_ends[rid]
                (sl, sv), (el, ev) = (ident(sc.node_labels[x], sc.node_props[x]) for x in (sid, eid))
                sk, ek = IDENT[sl], IDENT[el]
                props = sc.rel_props[rid]
                where = "".join(f" AND r.`{k}` = $p_{i}" for i, k in enumerate(props))
                q = (
                    f"MATCH (a:`{sl}` {{`{sk}`: $sv}})-[r:`{sc.rel_type[rid]}`]->(b:`{el}` {{`{ek}`: $ev}}) "
                    f"WHERE true{where} RETURN elementId(r) AS id"
                )
                ps = {"sv": sv, "ev": ev, **{f"p_{i}": v for i, v in enumerate(props.values())}}
                got = [r["id"] for r in s.run(q, ps)]
                if not got:
                    raise SystemExit(f"relationship not found in Neo4j: {sc.rel_keys[rid][:120]}")
                ambiguous += len(got) > 1
                out.append(got[0])
            return out

        neo_ids = resolve(sample)
        bound = [r["rid"] for r in sc.run(BIND_IDS, PARAMS).data]
        bound_neo = resolve(bound)
        base_neo = s.run(Q_NEO4J, PARAMS).data()
    base_relate = sc.run(Q_RELATE, PARAMS).data
    if multiset(base_neo) != multiset(base_relate):
        raise SystemExit(f"baseline answers differ: neo4j {base_neo} vs relate {base_relate}")

    del_neo = "UNWIND $ids AS i MATCH ()-[r]->() WHERE elementId(r) = i DELETE r RETURN count(*) AS c"

    def relate_trial(rid):
        t = sc.trial(Q_RELATE, PARAMS, [rid], ())
        ok = sc.counts() == base_counts
        return t.ms, t.rows, ok

    def neo_trial(session, nid):
        t0 = time.perf_counter()
        tx = session.begin_transaction()
        try:
            deleted = tx.run(del_neo, ids=[nid]).single()["c"]
            rows = tx.run(Q_NEO4J, PARAMS).data()
        finally:
            tx.rollback()
        ms = (time.perf_counter() - t0) * 1000
        return ms, rows, deleted

    runs, rows_out = [], []
    with driver.session() as session:
        for _ in range(a.warmup):  # warm both engines the same way, discarded
            relate_trial(sample[_])
            neo_trial(session, neo_ids[_])
        for run in range(a.runs):
            meas = slice(a.warmup, a.warmup + a.trials)
            # Relate (in-process)
            ms_r, changed_r, counts_ok_r, ans_r = [], 0, 0, []
            t0 = time.perf_counter()
            for rid in sample[meas]:
                ms, rows, ok = relate_trial(rid)
                ms_r.append(ms)
                counts_ok_r += ok
                ans_r.append(multiset(rows))
                changed_r += multiset(rows) != multiset(base_relate)
            wall_r = time.perf_counter() - t0
            # Neo4j (Docker, Bolt); counts checked after every rollback, inside the wall like Relate's
            ms_n, changed_n, counts_ok_n, deleted_ok, ans_n = [], 0, 0, 0, []
            t0 = time.perf_counter()
            for nid in neo_ids[meas]:
                ms, rows, deleted = neo_trial(session, nid)
                c = (
                    session.run("MATCH (n) RETURN count(n) AS n").single()["n"],
                    session.run("MATCH ()-[r]->() RETURN count(r) AS r").single()["r"],
                )
                ms_n.append(ms)
                counts_ok_n += c == base_counts
                deleted_ok += deleted == 1
                ans_n.append(multiset(rows))
                changed_n += multiset(rows) != multiset(base_neo)
            wall_n = time.perf_counter() - t0
            agree = sum(x == y for x, y in zip(ans_r, ans_n, strict=True))
            runs.append(
                {
                    "run": run + 1,
                    "relate": {
                        **summarize(ms_r, wall_r, a.trials),
                        "counts_restored": f"{counts_ok_r}/{a.trials}",
                        "answer_changed": changed_r,
                    },
                    "neo4j": {
                        **summarize(ms_n, wall_n, a.trials),
                        "counts_restored": f"{counts_ok_n}/{a.trials}",
                        "delete_count_asserted": f"{deleted_ok}/{a.trials}",
                        "answer_changed": changed_n,
                    },
                    "answers_identical_per_trial": f"{agree}/{a.trials}",
                }
            )
            print(json.dumps(runs[-1]), flush=True)
            if run == 0:
                for i, rid in enumerate(sample[meas], 1):
                    rows_out.append(
                        {
                            "n": i,
                            "rel": sc.rel_keys[rid][:200],
                            "relate_ms": round(ms_r[i - 1], 4),
                            "neo4j_ms": round(ms_n[i - 1], 4),
                            "relate_changed": ans_r[i - 1] != multiset(base_relate),
                            "neo4j_changed": ans_n[i - 1] != multiset(base_neo),
                        }
                    )
    # targeted agreement: the answer-relevant relationships (the headline query's own bindings), where many trials
    # DO change the answer, so "identical answers per trial" is a real check and not 1,000 unchanged rows
    tg = {"rels": len(bound), "relate_changed": 0, "neo4j_changed": 0, "identical": 0}
    with driver.session() as session:
        for rid, nid in zip(bound, bound_neo, strict=True):
            _, rr, _ok = relate_trial(rid)
            _, nr, _d = neo_trial(session, nid)
            tg["relate_changed"] += multiset(rr) != multiset(base_relate)
            tg["neo4j_changed"] += multiset(nr) != multiset(base_neo)
            tg["identical"] += multiset(rr) == multiset(nr)
    print("targeted", tg, flush=True)
    versions = (
        driver.session()
        .run("CALL dbms.components() YIELD name, versions, edition RETURN name, versions[0] AS v, edition")
        .data()
    )
    driver.close()
    sc.close()
    tmp_ctx.cleanup()
    med = lambda k, side: statistics.median(r[side][k] for r in runs)  # noqa: E731
    report = {
        "date": time.strftime("%Y-%m-%d %H:%M:%S %z"),
        "machine": machine(),
        "neo4j": {
            "image": env.get("NEO4J_IMAGE"),
            "components": versions,
            "transport": "Bolt over loopback, Docker Desktop VM",
        },
        "source": {
            "path": "data/air-routes.rl",
            "sha256_before": sha_before,
            "sha256_after": sha256(SRC),
            "nodes": base_counts[0],
            "relationships": base_counts[1],
        },
        "queries": {
            "relate": "queries/two-hub.cypher",
            "neo4j": "queries/two-hub.neo4j.cypher",
            "params": PARAMS,
            "baseline_rows": base_relate,
        },
        "protocol": {
            "trials_per_run": a.trials,
            "runs": a.runs,
            "warmup_discarded": a.warmup,
            "seed": SEED,
            "sample": "random.Random(0).sample over relationships sorted by canonical key; same ones on both sides",
            "neo4j_ambiguous_matches": ambiguous,
            "relate_delete_stmt": DEL_RELS,
            "neo4j_delete_stmt": del_neo,
        },
        "runs": runs,
        "targeted_agreement": tg,
        "median_trials_per_s": {
            "relate_in_process": med("trials_per_s", "relate"),
            "neo4j_docker": med("trials_per_s", "neo4j"),
        },
        "median_trial_ms_p50": {
            "relate_in_process": med("trial_ms_p50", "relate"),
            "neo4j_docker": med("trial_ms_p50", "neo4j"),
        },
        "median_trial_ms_p95": {
            "relate_in_process": med("trial_ms_p95", "relate"),
            "neo4j_docker": med("trial_ms_p95", "neo4j"),
        },
    }
    report["ratio_trials_per_s"] = round(
        report["median_trials_per_s"]["relate_in_process"] / report["median_trials_per_s"]["neo4j_docker"], 2
    )
    date = time.strftime("%Y-%m-%d")
    (EV / f"neo4j-compare-{date}.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    (EV / "neo4j-compare-rows.jsonl").write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in rows_out))
    print(
        json.dumps(
            {
                k: report[k]
                for k in ("median_trials_per_s", "median_trial_ms_p50", "median_trial_ms_p95", "ratio_trials_per_s")
            },
            indent=1,
        )
    )


if __name__ == "__main__":
    main()
