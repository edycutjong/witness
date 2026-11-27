"""A differential run: 219 agent-written read queries on three engines over the same graph, every disagreement shrunk.

The queries (`queries/differential.jsonl`) were written by an AI agent from the air-routes schema alone, before any
engine compared them, and none was changed to make engines agree. Each runs on data/air-routes.rl under:

  relate-db 1.0.1 (the pinned release), relate-db 1.3.0 (a uv environment), Neo4j over Bolt (an empty database the
  graph is loaded into, then removed).

Answers are compared the way Witness compares them (canonical rows as a bag, type-aware: 1 and 1.0 differ). Every query
where two engines both answer and disagree is then reduced with `--other-engine` (Neo4j, or relate-db 1.3.0 for a
change between releases) when Witness's read-only door admits it, and each witness is re-checked against 1.3.0: a
disagreement with Neo4j that 1.3.0 still shows on the witness is reported as present on the current release.

    docker run -d --rm --name witness-diff -p 127.0.0.1:7691:7687 -e NEO4J_AUTH=neo4j/$NEO4J_PASSWORD \\
        neo4j:2026.10.2-community
    NEO4J_BOLT=bolt://127.0.0.1:7691 NEO4J_USER=neo4j NEO4J_PASSWORD=... \\
        uv run --with neo4j python bench/differential.py [--reduce]
        -> evidence/differential-answers.jsonl, evidence/differential.json, witnesses/differential/

The password is read from the environment (or ~/.config/witness/neo4j.env), never printed and never written.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import select
import signal
import subprocess
import sys
import time
from pathlib import Path

os.environ.setdefault("DO_NOT_TRACK", "1")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from witness.canon import canon_rows, same_answer  # noqa: E402

SRC = Path("data/air-routes.rl")  # relative, so a manifest records no local path (run from the repo root)
QUERIES = ROOT / "queries" / "differential.jsonl"
TIMEOUT = 20.0


def plain(v):
    if isinstance(v, dict):
        return {k: plain(x) for k, x in v.items()}
    if isinstance(v, list | tuple):
        return [plain(x) for x in v]
    return v if v is None or isinstance(v, bool | int | float | str) else repr(v)


def answer_record(qid: str, rows: list, cols: list, ms: float) -> dict:
    try:
        canon = repr(canon_rows(rows, cols))
    except Exception as e:  # noqa: BLE001
        return {"id": qid, "error": f"no canonical form: {e}"[:300], "ms": ms}
    return {"id": qid, "answer": canon, "n": len(rows), "head": plain(rows[:3]), "ms": round(ms, 2)}


# ---- child: one relate-db release answers every query, one JSON line each -----------------------------------------
def child(queries_path: str, store: str, start: int) -> None:
    import relate

    from witness.store import Scratch

    sc = Scratch.open_copy(store)
    qs = [json.loads(x) for x in Path(queries_path).read_text().splitlines()]
    print(json.dumps({"relate_db": relate.__version__}), flush=True)
    for q in qs[start:]:
        t0 = time.perf_counter()
        try:
            res = sc.db.execute(q["cypher"])
            rec = answer_record(q["id"], res.data, list(res.columns), (time.perf_counter() - t0) * 1000)
        except Exception as e:  # noqa: BLE001
            rec = {"id": q["id"], "error": f"{type(e).__name__}: {e}"[:300], "ms": (time.perf_counter() - t0) * 1000}
        print(json.dumps(rec), flush=True)
    sc.close()


def run_release(cmd: list[str], qs: list[dict]) -> tuple[str, dict]:
    """Every query on one release, a per-query watchdog; a hung query is killed and the child restarted after it."""
    out: dict[str, dict] = {}
    version = "?"
    i = 0
    while i < len(qs):
        p = subprocess.Popen(
            [*cmd, str(Path(__file__).resolve()), "--child", str(QUERIES), str(SRC), str(i)],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            start_new_session=True,
            env={**os.environ, "DO_NOT_TRACK": "1"},
        )
        assert p.stdout is not None
        hello = p.stdout.readline()
        version = json.loads(hello)["relate_db"] if hello else version
        while i < len(qs):
            ready, _, _ = select.select([p.stdout], [], [], TIMEOUT)
            line = p.stdout.readline() if ready else ""
            if not line:
                out[qs[i]["id"]] = {"id": qs[i]["id"], "error": f"timeout: no answer within {TIMEOUT:g} s"}
                os.killpg(p.pid, signal.SIGKILL)
                p.wait()
                i += 1
                break
            rec = json.loads(line)
            out[rec["id"]] = rec
            i += 1
        else:
            p.wait()
    return version, out


def run_neo4j(qs: list[dict]) -> tuple[str, dict]:
    from neo4j import Query

    from witness.engines import Neo4jEngine
    from witness.guard import GuardedQuery
    from witness.store import Scratch

    sc = Scratch.open_copy(SRC)
    eng = Neo4jEngine(sc, GuardedQuery(text="RETURN 1", params={}, exec_text="RETURN 1"))
    sc.close()
    out = {}
    try:
        for q in qs:
            t0 = time.perf_counter()
            try:
                with eng.driver.session(database=eng.database) as s:
                    res = s.run(Query(q["cypher"], timeout=TIMEOUT))
                    cols = list(res.keys())
                    rows = [dict(zip(cols, r.values(), strict=True)) for r in res]
                out[q["id"]] = answer_record(q["id"], rows, cols, (time.perf_counter() - t0) * 1000)
            except Exception as e:  # noqa: BLE001
                msg = f"{type(e).__name__}: {getattr(e, 'message', None) or e}"
                out[q["id"]] = {"id": q["id"], "error": msg[:300], "ms": (time.perf_counter() - t0) * 1000}
        return eng.label, out
    finally:
        eng.close()


def classify(a: dict, b: dict) -> str:
    """same | differ | error:<side> | both-error, for two engines' records of one query."""
    ea, eb = "error" in a, "error" in b
    if ea and eb:
        return "both-error"
    if ea or eb:
        return "error:" + ("first" if ea else "second")
    return "same" if same_answer(a["answer"], b["answer"]) else "differ"


def reduce_one(q: dict, engine: str, out_dir: Path) -> dict:
    from witness.guard import Refused
    from witness.pipeline import Request, reduce_request

    name = f"{q['id']}-{'neo4j' if engine == 'neo4j' else 'relate-' + engine.split('==')[1]}"
    req = Request(source=SRC, statement=q["cypher"], params={}, other_engine=engine, name=name, out_dir=out_dir,
                  ledger=None)  # fmt: skip
    t0 = time.perf_counter()
    try:
        o = reduce_request(req)
    except Refused as e:
        return {"id": q["id"], "engine": engine, "refused": e.reason, "door": e.door}
    except Exception as e:  # noqa: BLE001
        return {"id": q["id"], "engine": engine, "error": f"{type(e).__name__}: {e}"[:300]}
    rec = {
        "id": q["id"],
        "engine": engine,
        "name": name,
        "verified": o.verified,
        "relationships": o.run["final_counts"][1],
        "nodes": o.run["final_counts"][0],
        "trials": o.run["trials"],
        "inconclusive": o.run["inconclusive"],
        "seconds": round(time.perf_counter() - t0, 3),
        "check": o.check.text if o.check else None,
        "reasons": o.reasons,
    }
    if engine == "neo4j" and o.verified:
        from witness.check import check, spec_from_manifest

        spec = spec_from_manifest(o.manifest)
        spec.other_engine = "relate-db==1.3.0"
        c = check(out_dir / f"{name}.rl", spec, use_cli=False, necessity=False)
        # 1.0.1 and 1.3.0 agree on W (the predicate fails) -> the disagreement with Neo4j is still there on 1.3.0
        rec["relate_1_3_0_on_witness"] = "same as 1.0.1" if c.sufficient is False else "differs from 1.0.1"
    return rec


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--child", nargs=3, metavar=("QUERIES", "STORE", "START"))
    ap.add_argument("--reduce", action="store_true", help="shrink every disagreement Witness's door admits")
    ap.add_argument("--cache", metavar="DIR", help="reuse (or write) each engine's answers in DIR")
    a = ap.parse_args()
    if a.child:
        child(a.child[0], a.child[1], int(a.child[2]))
        return
    qs = [json.loads(x) for x in QUERIES.read_text().splitlines()]
    t0 = time.perf_counter()

    def cached(name, fn):
        path = Path(a.cache) / f"{name}.json" if a.cache else None
        if path is not None and path.exists():
            return tuple(json.loads(path.read_text()))
        got = fn()
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(got))
        return got

    v101, r101 = cached("relate-1.0.1", lambda: run_release([sys.executable], qs))
    uv130 = ["uv", "run", "--no-project", "--quiet", "--with", "relate-db==1.3.0", "python"]
    v130, r130 = cached("relate-1.3.0", lambda: run_release(uv130, qs))
    try:
        neo_label, rneo = cached("neo4j", lambda: run_neo4j(qs))
    except Exception as e:  # noqa: BLE001 - no Neo4j reachable: the Relate comparison still stands, and says so
        neo_label, rneo = f"not run: {type(e).__name__}: {str(e)[:120]}", None
    rows, tally = [], {}
    for q in qs:
        i = q["id"]
        c = {"relate_1_0_1_vs_1_3_0": classify(r101[i], r130[i])}
        if rneo is not None:
            c["relate_1_0_1_vs_neo4j"] = classify(r101[i], rneo[i])
            c["relate_1_3_0_vs_neo4j"] = classify(r130[i], rneo[i])
        for k, v in c.items():
            tally.setdefault(k, {}).setdefault(v, 0)
            tally[k][v] += 1
        rows.append({"id": i, "feature": q["feature"], **c, "relate_1_0_1": r101[i], "relate_1_3_0": r130[i],
                     "neo4j": rneo[i] if rneo is not None else None})  # fmt: skip
    (ROOT / "evidence" / "differential-answers.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    report = {
        "schema": "witness.differential/v1",
        "queries": len(qs),
        "query_source": "queries/differential.jsonl, written by an AI agent from the schema before any comparison",
        "engines": {"relate_1_0_1": v101, "relate_1_3_0": v130, "neo4j": neo_label},
        "tally": tally,
        "answer_seconds": round(time.perf_counter() - t0, 1),
        "machine": f"{platform.system()} {platform.machine()}",
        "python": platform.python_version(),
        "recorded": time.strftime("%Y-%m-%d %H:%M %z"),
    }
    if a.reduce:
        out_dir = ROOT / "witnesses" / "differential"
        out_dir.mkdir(parents=True, exist_ok=True)
        reductions = []
        for r, q in zip(rows, qs, strict=True):
            if r.get("relate_1_0_1_vs_neo4j") == "differ":
                reductions.append(reduce_one(q, "neo4j", out_dir))
            if r["relate_1_0_1_vs_1_3_0"] == "differ":
                reductions.append(reduce_one(q, "relate-db==1.3.0", out_dir))
            if reductions and reductions[-1].get("id") == q["id"]:
                print(json.dumps(reductions[-1]), flush=True)
        report["reductions"] = reductions
    (ROOT / "evidence" / "differential.json").write_text(json.dumps(report, indent=1) + "\n")
    print(json.dumps({k: report[k] for k in ("engines", "tally", "answer_seconds")}, indent=1))


if __name__ == "__main__":
    main()
