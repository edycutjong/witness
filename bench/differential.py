"""A differential run: 219 agent-written read queries on up to three engines over the same graph, every disagreement
shrunk.

The queries (`queries/differential.jsonl`) were written by an AI agent from the air-routes schema alone, before any
engine compared them, and none was changed to make engines agree. Each runs on data/air-routes.rl under:

  relate-db 1.0.1 (the pinned release), relate-db 1.3.0 (a uv environment), Neo4j over Bolt (an empty database the
  graph is loaded into, then removed).

What one engine gave for one query is one of five kinds:

  answer        rows, in the canonical form Witness compares (rows as a bag, type-aware: 1 and 1.0 differ)
  error         the engine's own error for the statement
  timeout       no answer within 20 s: the relate-db process was killed (relate-db has no statement timeout), or
                Neo4j ended the transaction
  crash         the relate-db process ended on its own before answering (exit code and last stderr line kept)
  uncomparable  an answer with no engine-neutral form here: a relationship or path, a node from Neo4j, or a temporal
                or spatial value from the Neo4j driver

Two engines are compared only where both gave an answer: `same` or `differ`. Every other pair is named by its two
kinds (`timeout/answer`, `error/error`, ...), so a killed process is never a difference and never an agreement. For a
query with ORDER BY whose rows are the same, the row order is compared as well and tallied apart (`order`): rows that
tie on the sort keys may come in any order, so another order is listed, not counted as another answer.

Every `differ` is then reduced with `--other-engine` (Neo4j, or relate-db 1.3.0 for a change between releases) when
Witness's read-only door admits it, and each Neo4j witness is re-checked against 1.3.0: a disagreement with Neo4j that
1.3.0 still shows on the witness is reported as present on the current release.

    docker run -d --rm --name witness-diff -p 127.0.0.1:7691:7687 -m 4g -e NEO4J_AUTH=neo4j/$NEO4J_PASSWORD \\
        -e NEO4J_server_memory_heap_max__size=2g -e NEO4J_dbms_memory_transaction_total_max=1g \\
        neo4j:2026.10.2-community
    NEO4J_BOLT=bolt://127.0.0.1:7691 NEO4J_USER=neo4j NEO4J_PASSWORD=... \\
        uv run --with neo4j python bench/differential.py [--reduce]
        -> evidence/differential-answers.jsonl, evidence/differential.json, witnesses/differential/
    ... python bench/differential.py --reduce-only   # shrink the disagreements of the committed answers again,
                                                     # without asking the engines the 219 queries a second time

The password is read from the environment (or ~/.config/witness/neo4j.env), never printed and never written. The
memory limits make a runaway query fail inside Neo4j instead of taking the container down.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import platform
import re
import select
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("DO_NOT_TRACK", "1")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from witness.canon import canon_rows, canon_value  # noqa: E402

SRC = Path("data/air-routes.rl")  # relative, so a manifest records no local path (run from the repo root)
QUERIES = ROOT / "queries" / "differential.jsonl"
TIMEOUT = 20.0
START_TIMEOUT = 300.0  # uv may have to download the release first
REDUCE_MAX_SECONDS = 600.0  # one reduction; a run this stops is recorded as not verified
NEO4J_SETTINGS = ("server.memory.heap.max_size", "server.memory.pagecache.size", "dbms.memory.transaction.total.max")
ORDER_BY = re.compile(r"\bORDER\s+BY\b", re.I)


def plain(v):
    if isinstance(v, dict):
        return {k: plain(x) for k, x in v.items()}
    if isinstance(v, list | tuple):
        return [plain(x) for x in v]
    return v if v is None or isinstance(v, bool | int | float | str) else repr(v)


def answer_record(qid: str, rows: list, cols: list, ms: float, keyer=None) -> dict:
    """An answer in canonical form, plus a digest of the rows in the order they came (for ORDER BY queries)."""
    try:
        canon = repr(canon_rows(rows, cols, keyer=keyer))
        in_order = repr(tuple(tuple((c, canon_value(r[c], keyer=keyer)) for c in cols) for r in rows))
    except Exception as e:  # noqa: BLE001 - Witness has no canonical form for it: not the engine's error
        return {"id": qid, "kind": "uncomparable", "error": f"no canonical form: {e}"[:300], "ms": round(ms, 2)}
    return {
        "id": qid,
        "kind": "answer",
        "answer": canon,
        "ordered": hashlib.sha256(in_order.encode("utf-8")).hexdigest()[:16],
        "n": len(rows),
        "head": plain(rows[:3]),
        "ms": round(ms, 2),
    }


# ---- child: one relate-db release answers every query, one JSON line each -----------------------------------------
def child(queries_path: str, store: str, start: int) -> None:
    import relate

    from witness.store import Scratch

    sc = Scratch.open_copy(store)
    qs = [json.loads(x) for x in Path(queries_path).read_text().splitlines()]
    print(json.dumps({"relate_db": relate.__version__}), flush=True)
    for q in qs[start:]:
        t0 = time.perf_counter()
        sc.db.begin_transaction()  # rolled back whatever it does: no query can change the graph for the next one
        try:
            res = sc.db.execute(q["cypher"])
            rec = answer_record(q["id"], res.data, list(res.columns), (time.perf_counter() - t0) * 1000, sc.keyer)
        except Exception as e:  # noqa: BLE001
            ms = round((time.perf_counter() - t0) * 1000, 2)
            rec = {"id": q["id"], "kind": "error", "error": f"{type(e).__name__}: {e}"[:300], "ms": ms}
        finally:
            if sc.db.transaction_active():
                sc.db.rollback_transaction()
        print(json.dumps(rec), flush=True)
    sc.close()


class Lines:
    """JSON lines from a child's stdout, read from the descriptor into our own buffer: `select` cannot see a line a
    buffered reader already holds, which would turn an answered query into a timeout."""

    def __init__(self, stream):
        self.fd = stream.fileno()
        self.buf = b""

    def get(self, timeout: float) -> dict | None:
        """The next line; None when the child has ended; TimeoutError when none came within `timeout` seconds."""
        deadline = time.monotonic() + timeout
        while b"\n" not in self.buf:
            left = deadline - time.monotonic()
            if left <= 0 or not select.select([self.fd], [], [], left)[0]:
                raise TimeoutError
            chunk = os.read(self.fd, 1 << 16)
            if not chunk:
                return None
            self.buf += chunk
        line, _, self.buf = self.buf.partition(b"\n")
        return json.loads(line)


def _end(p: subprocess.Popen) -> int:
    """Kill the child and what it started (uv keeps the interpreter as its own child), then reap it."""
    if p.returncode is None:
        try:
            os.killpg(p.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
    return p.wait()


def run_release(cmd: list[str], qs: list[dict]) -> tuple[str, dict]:
    """Every query on one release under a per-query watchdog. A query that does not answer in time is a `timeout`
    (the child is killed); a child that ends on its own is a `crash`. Either way a new child goes on with the next."""
    out: dict[str, dict] = {}
    version = "?"
    i = 0
    with tempfile.TemporaryDirectory(prefix="witness-differential-") as tmp:
        err_path = Path(tmp) / "stderr.txt"

        def tail() -> str:
            lines = err_path.read_text(errors="replace").strip().splitlines()
            return lines[-1][:200] if lines else "no output"

        while i < len(qs):
            with err_path.open("wb") as errf:
                p = subprocess.Popen(
                    [*cmd, str(Path(__file__).resolve()), "--child", str(QUERIES), str(SRC), str(i)],
                    stdout=subprocess.PIPE,
                    stderr=errf,
                    start_new_session=True,
                    env={**os.environ, "DO_NOT_TRACK": "1"},
                )
            assert p.stdout is not None
            lines = Lines(p.stdout)
            try:
                hello = lines.get(START_TIMEOUT)
            except TimeoutError:
                hello = None
            if not hello:
                code = _end(p)
                raise RuntimeError(f"{' '.join(cmd)}: the child did not start (exit {code}): {tail()}")
            version = hello["relate_db"]
            while i < len(qs):
                qid = qs[i]["id"]
                try:
                    rec = lines.get(TIMEOUT)
                except TimeoutError:
                    _end(p)
                    why = f"timeout: no answer within {TIMEOUT:g} s (the process was killed)"
                    out[qid] = {"id": qid, "kind": "timeout", "error": why}
                    i += 1
                    break
                if rec is None:  # end of file: the child is gone, and not by our hand
                    code = _end(p)
                    why = f"crash: the process ended (exit {code}) before answering: {tail()}"
                    out[qid] = {"id": qid, "kind": "crash", "error": why}
                    i += 1
                    break
                assert rec["id"] == qid, (rec["id"], qid)  # one line per query, in order
                out[qid] = rec
                i += 1
            _end(p)
    return version, out


def run_neo4j(qs: list[dict]) -> tuple[dict, dict]:
    """Every query on Neo4j, each in its own transaction with a 20 s server-side timeout. `ms` is the wall clock on
    this side: Neo4j ends a timed-out transaction at its next check, which can be long after the 20 s."""
    import neo4j
    from neo4j.exceptions import ServiceUnavailable, SessionExpired

    from witness.engines import Neo4jEngine, uncomparable
    from witness.guard import GuardedQuery
    from witness.store import Scratch

    sc = Scratch.open_copy(SRC)
    eng = Neo4jEngine(sc, GuardedQuery(text="RETURN 1", params={}, exec_text="RETURN 1"))
    sc.close()
    out = {}
    try:
        with eng.driver.session(database=eng.database) as s:  # which Cypher the queries are read as, and the limits
            lang = s.run("SHOW DATABASES YIELD name, defaultLanguage WHERE name = $n RETURN defaultLanguage AS l",
                         n=eng.database).single()  # fmt: skip
            show = "SHOW SETTINGS YIELD name, value WHERE name IN $names RETURN name, value"
            settings = {r["name"]: r["value"] for r in s.run(show, names=list(NEO4J_SETTINGS))}
        about = {
            "version": eng.label,
            "default_language": lang["l"] if lang else None,
            "python_driver": neo4j.__version__,
            "settings": settings,
            "transaction_timeout_s": TIMEOUT,
        }
        for q in qs:
            qid = q["id"]
            t0 = time.perf_counter()
            try:
                with eng.driver.session(database=eng.database) as s:
                    tx = s.begin_transaction(timeout=TIMEOUT)  # rolled back whatever it does, as on relate-db
                    try:
                        res = tx.run(q["cypher"])
                        cols = list(res.keys())
                        rows = [dict(zip(cols, r.values(), strict=True)) for r in res]
                    finally:
                        with contextlib.suppress(Exception):  # a transaction the server already ended
                            tx.rollback()
            except (ServiceUnavailable, SessionExpired) as e:  # the server is gone: no row after this would be true
                raise RuntimeError(f"Neo4j went away at {qid}: {type(e).__name__}: {str(e)[:120]}") from e
            except Exception as e:  # noqa: BLE001
                msg = f"{type(e).__name__}: {getattr(e, 'message', None) or e}"
                timed_out = "TransactionTimedOut" in (str(getattr(e, "code", "")) + msg)
                ms = round((time.perf_counter() - t0) * 1000, 2)
                out[qid] = {"id": qid, "kind": "timeout" if timed_out else "error", "error": msg[:300], "ms": ms}
                continue
            ms = (time.perf_counter() - t0) * 1000
            why = uncomparable(rows)
            if why:
                out[qid] = {"id": qid, "kind": "uncomparable", "error": why, "n": len(rows), "ms": round(ms, 2)}
            else:
                out[qid] = answer_record(qid, rows, cols, ms)
        return about, out
    finally:
        eng.close()


def classify(a: dict, b: dict) -> str:
    """`same` or `differ` where both engines answered; otherwise the two kinds, first engine first."""
    if a["kind"] == b["kind"] == "answer":
        return "same" if a["answer"] == b["answer"] else "differ"
    return f"{a['kind']}/{b['kind']}"


def order_of(q: dict, a: dict, b: dict) -> str | None:
    """For a query with ORDER BY whose rows are the same on both engines: did they come in the same order?"""
    if not ORDER_BY.search(q["cypher"]) or classify(a, b) != "same":
        return None
    return "same order" if a["ordered"] == b["ordered"] else "other order"


def reduce_one(q: dict, engine: str, out_dir: Path) -> dict:
    from witness.guard import Refused
    from witness.pipeline import Request, reduce_request

    name = f"{q['id']}-{'neo4j' if engine == 'neo4j' else 'relate-' + engine.split('==')[1]}"
    req = Request(source=SRC, statement=q["cypher"], params={}, other_engine=engine, name=name, out_dir=out_dir,
                  ledger=None, trial_timeout=TIMEOUT, max_seconds=REDUCE_MAX_SECONDS)  # fmt: skip
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
        # the predicate here is "1.0.1 and 1.3.0 differ on W". It fails -> 1.3.0 answers as 1.0.1 does, so the
        # disagreement with Neo4j is still there on 1.3.0; it holds -> 1.3.0 changed this answer; None -> not known
        on_w = {False: "same as 1.0.1", True: "differs from 1.0.1", None: "inconclusive"}
        rec["relate_1_3_0_on_witness"] = on_w[c.sufficient]
    return rec


def cache_key() -> str:
    """What an engine's cached answers depend on: the queries, the store, the watchdog and this script."""
    h = hashlib.sha256()
    for f in (QUERIES, ROOT / SRC, Path(__file__)):
        h.update(f.read_bytes())
    return h.hexdigest()


def reduce_all(rows: list[dict], qs: list[dict]) -> list[dict]:
    """Every `differ` shrunk: against Neo4j, and against relate-db 1.3.0 for a change between releases."""
    out_dir = ROOT / "witnesses" / "differential"
    out_dir.mkdir(parents=True, exist_ok=True)
    reductions = []
    for r, q in zip(rows, qs, strict=True):
        todo = [e for e, name in (("neo4j", "relate_1_0_1_vs_neo4j"), ("relate-db==1.3.0", "relate_1_0_1_vs_1_3_0"))
                if r.get(name) == "differ"]  # fmt: skip
        for engine in todo:
            reductions.append(reduce_one(q, engine, out_dir))
            print(json.dumps(reductions[-1]), flush=True)
    return reductions


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--child", nargs=3, metavar=("QUERIES", "STORE", "START"))
    ap.add_argument("--reduce", action="store_true", help="shrink every disagreement Witness's door admits")
    ap.add_argument("--reduce-only", action="store_true", help="shrink the disagreements of the committed answers")
    ap.add_argument("--cache", metavar="DIR", help="reuse (or write) each engine's answers in DIR")
    a = ap.parse_args()
    if a.child:
        child(a.child[0], a.child[1], int(a.child[2]))
        return
    qs = [json.loads(x) for x in QUERIES.read_text().splitlines()]
    ids = [q["id"] for q in qs]
    assert len(set(ids)) == len(ids), "query ids must be unique"
    report_path = ROOT / "evidence" / "differential.json"
    answers_path = ROOT / "evidence" / "differential-answers.jsonl"
    if a.reduce_only:  # the committed answers are the input: same queries, same order, nothing asked again
        report = json.loads(report_path.read_text())
        rows = [json.loads(x) for x in answers_path.read_text().splitlines()]
        assert report["queries_sha256"] == hashlib.sha256(QUERIES.read_bytes()).hexdigest(), "answers of other queries"
        assert [r["id"] for r in rows] == ids
        report["reductions"] = reduce_all(rows, qs)
        report["reductions_recorded"] = time.strftime("%Y-%m-%d %H:%M %z")
        report_path.write_text(json.dumps(report, indent=1) + "\n")
        return
    key = cache_key() if a.cache else None
    t0 = time.perf_counter()

    def cached(name, fn):
        path = Path(a.cache) / f"{name}.json" if a.cache else None
        if path is not None and path.exists():
            saved = json.loads(path.read_text())
            if saved.get("key") == key:  # answers of other queries, another store or an older script are not reused
                return saved["label"], saved["records"]
        label, records = fn()
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"key": key, "label": label, "records": records}))
        return label, records

    v101, r101 = cached("relate-1.0.1", lambda: run_release([sys.executable], qs))
    uv130 = ["uv", "run", "--no-project", "--quiet", "--with", "relate-db==1.3.0", "python"]
    v130, r130 = cached("relate-1.3.0", lambda: run_release(uv130, qs))
    assert (v101, v130) == ("1.0.1", "1.3.0"), (v101, v130)  # each side is the release this file says it is
    try:
        neo_label, rneo = cached("neo4j", lambda: run_neo4j(qs))
    except Exception as e:  # noqa: BLE001 - no Neo4j reachable: the Relate comparison still stands, and says so
        neo_label, rneo = {"version": None, "not_run": f"{type(e).__name__}: {str(e)[:160]}"}, None
    pairs = [("relate_1_0_1_vs_1_3_0", r101, r130)]
    if rneo is not None:
        pairs += [("relate_1_0_1_vs_neo4j", r101, rneo), ("relate_1_3_0_vs_neo4j", r130, rneo)]
    for _, x, y in pairs:
        assert set(x) == set(y) == set(ids), "every engine has one record per query"
    rows, tally, order = [], {}, {}
    for q in qs:
        i = q["id"]
        row = {"id": i, "feature": q["feature"]}
        for name, x, y in pairs:
            row[name] = c = classify(x[i], y[i])
            tally.setdefault(name, {}).setdefault(c, 0)
            tally[name][c] += 1
            o = order_of(q, x[i], y[i])
            if o:
                row[name + "_order"] = o
                order.setdefault(name, {}).setdefault(o, 0)
                order[name][o] += 1
        rows.append({**row, "relate_1_0_1": r101[i], "relate_1_3_0": r130[i],
                     "neo4j": rneo[i] if rneo is not None else None})  # fmt: skip
    answers_path.write_text("".join(json.dumps(r) + "\n" for r in rows))
    report = {
        "schema": "witness.differential/v2",
        "queries": len(qs),
        "queries_sha256": hashlib.sha256(QUERIES.read_bytes()).hexdigest(),
        "queries_with_order_by": sum(1 for q in qs if ORDER_BY.search(q["cypher"])),
        "timeout_s": TIMEOUT,
        "query_source": "queries/differential.jsonl, written by an AI agent from the schema before any comparison",
        "engines": {"relate_1_0_1": v101, "relate_1_3_0": v130, "neo4j": neo_label},
        "tally": tally,
        "order": order,
        "answer_seconds": round(time.perf_counter() - t0, 1),
        "machine": f"{platform.system()} {platform.machine()}",
        "python": platform.python_version(),
        "recorded": time.strftime("%Y-%m-%d %H:%M %z"),
    }
    if a.reduce:
        report["reductions"] = reduce_all(rows, qs)
        report["reductions_recorded"] = time.strftime("%Y-%m-%d %H:%M %z")
    report_path.write_text(json.dumps(report, indent=1) + "\n")
    print(json.dumps({k: report[k] for k in ("engines", "tally", "order", "answer_seconds")}, indent=1))


if __name__ == "__main__":
    main()
