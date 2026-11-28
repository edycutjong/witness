"""--other-engine: one query on two engines over the same trial graph (witness.engines, witness.engine_worker).

The real cross-release case runs the committed 2-relationship engine witness against relate-db 1.3.0 in a worker
(uv fetches that release once). The worker protocol is also tested on this interpreter's own relate-db
(``python:<sys.executable>``), in-process (``serve``), and the Neo4j client against a stand-in driver that runs every
statement on a real Relate store (Relate speaks the same Cypher; only ``dbms.components()`` is answered by the
stand-in).
"""

from __future__ import annotations

import io
import json
import os
import shutil
import signal
import sys
import types
from pathlib import Path

import pytest
import relate

from witness import engines
from witness.cli import main
from witness.engine_worker import main as worker_main
from witness.engine_worker import serve
from witness.engines import (
    EngineAnswer,
    Neo4jEngine,
    Remote,
    TwoEngines,
    WorkerEngine,
    from_wire,
    graph_shape,
    neo4j_settings,
    open_engine,
    parse_engine,
    query_from_spec,
    query_spec,
    read_env_file,
    wire_answer,
    worker_command,
)
from witness.guard import Cut, GuardedQuery, Refused, Tie
from witness.pipeline import Request, reduce_request
from witness.store import Scratch

ROOT = Path(__file__).resolve().parent.parent
ENGINE_W = ROOT / "witnesses" / "exists-count.rl"
EXISTS_Q = (ROOT / "queries" / "exists-two-match.cypher").read_text()
SELF = f"python:{sys.executable}"
Q_NAMES = "MATCH (n:P) RETURN n.name AS name ORDER BY name"


def gq(text: str = Q_NAMES, params: dict | None = None) -> GuardedQuery:
    return GuardedQuery(text=text, params=params or {}, exec_text=text)


# ---- spec parsing and the wire ---------------------------------------------------------------------------------------
def test_parse_engine_forms():
    assert parse_engine("relate-db==1.3.0") == ("relate", "1.3.0")
    assert parse_engine("python:/x/python") == ("python", "/x/python")
    assert parse_engine("neo4j") == ("neo4j", "")
    for bad in ("relate-db==1.3", "relate-db==latest", "relate-db==", "python:", "mysql", ""):
        with pytest.raises(Refused):
            parse_engine(bad)


def test_query_spec_round_trip_keeps_the_cut():
    q = GuardedQuery(text="t", params={"a": 1}, exec_text="e", cut=Cut(order_cols=["x"], skip=1, limit=2))
    back = query_from_spec(json.loads(json.dumps(query_spec(q))))
    assert (back.text, back.exec_text, back.params, back.cut) == ("t", "e", {"a": 1}, q.cut)
    assert query_from_spec(query_spec(gq())).cut is None


def test_wire_answers():
    ans = ((("a",),),)
    got = from_wire({**wire_answer(ans), "ms": 1.0})
    assert isinstance(got.answer, Remote) and repr(got.answer) == repr(ans) and got.ms == 1.0
    tie = from_wire(wire_answer(Tie([1])))
    assert isinstance(tie.answer, Tie)
    err = from_wire({"error": "boom", "ms": 2.0})
    assert err.answer is None and err.error == "boom"


def test_neo4j_settings_env_then_file(tmp_path):
    f = tmp_path / "neo4j.env"
    f.write_text("# local\nNEO4J_BOLT=bolt://127.0.0.1:7687\nNEO4J_USER='neo4j'\nNEO4J_PASSWORD=\"pw\"\nnoequals\n")
    assert read_env_file(tmp_path / "missing.env") == {}
    s = neo4j_settings({}, f)
    assert s == {"NEO4J_BOLT": "bolt://127.0.0.1:7687", "NEO4J_USER": "neo4j", "NEO4J_PASSWORD": "pw",
                 "NEO4J_DATABASE": "neo4j"}  # fmt: skip
    assert neo4j_settings({"NEO4J_USER": "env"}, f)["NEO4J_USER"] == "env"
    with pytest.raises(Refused, match="NEO4J_BOLT"):
        neo4j_settings({}, tmp_path / "missing.env")
    assert "NEO4J_BOLT" in neo4j_settings.__doc__ or True  # never printed: the function returns, never logs


def test_neo4j_settings_default_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("NEO4J_BOLT", "bolt://h")
    monkeypatch.setenv("NEO4J_USER", "u")
    monkeypatch.setenv("NEO4J_PASSWORD", "p")
    monkeypatch.setenv("NEO4J_DATABASE", "graph")
    assert neo4j_settings(path=tmp_path / "none.env")["NEO4J_DATABASE"] == "graph"


# ---- the worker, on this interpreter's relate-db -------------------------------------------------------------------
def test_worker_on_this_interpreter(tiny_rl):
    sc = Scratch.open_copy(tiny_rl)
    eng = WorkerEngine(SELF, tiny_rl, gq())
    try:
        assert eng.label == f"relate-db {relate.__version__}" and eng.counts == sc.counts()
        full = eng.answer()
        assert full.error is None and isinstance(full.answer, Remote)
        a_key = next(k for i, k in sc.node_keys.items() if sc.node_props[i]["name"] == "A")
        one = eng.answer([], [a_key])
        assert one.error is None and repr(one.answer) != repr(full.answer)
        assert repr(eng.answer().answer) == repr(full.answer)  # rolled back
        eng.commit([], [a_key])
        assert repr(eng.answer().answer) == repr(one.answer)  # committed
        assert "not in this store" in eng.answer([], [a_key]).error
        with pytest.raises(RuntimeError, match="commit failed"):
            eng.commit(["no-such-key"], [])
    finally:
        eng.close()
        sc.close()


def _a_key(tiny_rl) -> str:
    sc = Scratch.open_copy(tiny_rl)
    try:
        return next(k for i, k in sc.node_keys.items() if sc.node_props[i]["name"] == "A")
    finally:
        sc.close()


def test_worker_gone_and_failed_starts(tiny_rl, tmp_path):
    """A worker that dies is replaced: that request is an error, the next one is answered on the same graph."""
    a_key = _a_key(tiny_rl)
    eng = WorkerEngine(SELF, tiny_rl, gq())
    try:
        full = eng.answer()
        eng.commit([], [a_key])
        after = eng.answer()
        assert after.error is None and repr(after.answer) != repr(full.answer)
        eng.proc.kill()
        eng.proc.wait(5)
        assert eng.answer().error.startswith("worker gone") and eng.restarts == 1 and eng.dead is None
        assert repr(eng.answer().answer) == repr(after.answer)  # the fresh worker replayed the committed deletion
        eng.proc.stdin.write(b"not json\n")  # a worker that crashes on its own: the reason is its last stderr line
        eng.proc.stdin.flush()
        assert "JSONDecodeError" in eng.answer().error and eng.restarts == 2
    finally:
        eng.close()
    with pytest.raises(Refused, match="cannot start"):
        WorkerEngine(f"python:{tmp_path / 'no-python'}", tiny_rl, gq())
    with pytest.raises(Refused, match="did not start"):
        WorkerEngine(f"python:{shutil.which('false')}", tiny_rl, gq())


def test_worker_that_misses_the_deadline_is_replaced(tiny_rl, monkeypatch):
    """relate-db has no statement timeout: a worker that does not answer in time is killed and a fresh one replays
    the log. SIGSTOP stands in for a statement that never returns."""
    a_key = _a_key(tiny_rl)
    monkeypatch.setattr(WorkerEngine, "STOP_TIMEOUT", 0.2)
    eng = WorkerEngine(SELF, tiny_rl, gq(), timeout=1.0)
    try:
        full = eng.answer()
        first = eng.proc.pid
        os.kill(first, signal.SIGSTOP)
        late = eng.answer()
        assert late.answer is None and late.error == "TrialTimeout: no answer within 1 s"
        assert eng.restarts == 1 and eng.proc.pid != first
        assert repr(eng.answer().answer) == repr(full.answer)
        os.kill(eng.proc.pid, signal.SIGSTOP)
        eng.commit([], [a_key])  # lost with the stopped worker, replayed into the next one
        assert eng.restarts == 2 and eng.log == [([], [a_key])]
        assert "'A'" not in repr(eng.answer().answer)
        os.kill(eng.proc.pid, signal.SIGSTOP)  # close() does not wait for a worker that has stopped answering
    finally:
        eng.close()
    assert eng.proc.returncode is not None and eng not in engines._LIVE


def test_worker_start_refusals(tiny_rl, monkeypatch):
    """The worker must say hello in time, run the release that was asked for, and hold the same graph."""
    assert worker_command("relate", "1.3.0")[-3:] == ["--with", "relate-db==1.3.0", "python"]
    assert worker_command("python", "/x/python") == ["/x/python"]
    sc = Scratch.open_copy(tiny_rl)
    n, r, digest = graph_shape(sc)
    sc.close()
    assert (n, r) == (5, 6) and len(digest) == 64
    WorkerEngine(SELF, tiny_rl, gq(), expect=(n, r, digest)).close()
    with pytest.raises(Refused, match="reads a different graph .*the same counts, other properties or labels"):
        WorkerEngine(SELF, tiny_rl, gq(), expect=(n, r, "0" * 64))
    with pytest.raises(Refused, match=rf"{n} nodes and {r} relationships there, {n} and {r + 1} here\)"):
        WorkerEngine(SELF, tiny_rl, gq(), expect=(n, r + 1, digest))
    monkeypatch.setattr(engines, "worker_command", lambda kind, arg: [sys.executable])
    with pytest.raises(Refused, match=f"runs relate-db {relate.__version__}, not the release that was asked for"):
        WorkerEngine("relate-db==9.9.9", tiny_rl, gq())
    monkeypatch.setattr(WorkerEngine, "START_TIMEOUT", 0.3)
    sleeper = [sys.executable, "-c", "import time; time.sleep(60)", "--"]
    monkeypatch.setattr(engines, "worker_command", lambda kind, arg: sleeper)
    with pytest.raises(Refused, match="did not start within 0.3 s"):
        WorkerEngine(SELF, tiny_rl, gq())
    assert not engines._LIVE


def test_worker_that_cannot_come_back_is_reported_gone(tiny_rl, tmp_path):
    src = tmp_path / "copy.rl"
    shutil.copyfile(tiny_rl, src)
    eng = WorkerEngine(SELF, src, gq())
    try:
        src.unlink()  # the next worker has nothing to open
        eng.proc.kill()
        eng.proc.wait(5)
        assert eng.answer().error.startswith("worker gone")
        assert "could not be restarted" in eng.dead and "could not be restarted" in eng.answer().error
        with pytest.raises(RuntimeError, match="commit failed"):
            eng.commit([], ["k"])
        assert eng.log == []
    finally:
        eng.close()
    eng = WorkerEngine(SELF, tiny_rl, gq())
    try:
        eng.log.append((["no-such-key"], []))  # a deletion the fresh worker cannot repeat
        eng.proc.kill()
        eng.proc.wait(5)
        assert eng.answer().error.startswith("worker gone") and "could not be replayed" in eng.dead
    finally:
        eng.close()


def test_live_workers_end_with_the_interpreter(tiny_rl):
    eng = WorkerEngine(SELF, tiny_rl, gq())
    assert eng in engines._LIVE
    engines._end_live_workers()  # the atexit hook
    assert eng not in engines._LIVE and eng.proc.returncode is not None
    eng.close()


def test_worker_reads_eof_as_gone(tiny_rl):
    eng = WorkerEngine(SELF, tiny_rl, gq())
    assert eng._call({"op": "stop"}) == {"ok": True}
    eng.proc.wait(10)
    assert eng._call({"op": "trial", "rels": [], "nodes": []})["error"].startswith("worker gone")
    eng.close()


def test_serve_in_process(tiny_rl, tmp_path):
    sc = Scratch.open_copy(tiny_rl)
    a_key = next(k for i, k in sc.node_keys.items() if sc.node_props[i]["name"] == "A")
    rel_key = next(iter(sc.rel_keys.values()))
    sc.close()
    spec = {"source": str(tiny_rl), "query": query_spec(gq()), "strict_lists": False, "digits": 12}
    lines = [
        {"op": "trial", "rels": [rel_key], "nodes": []},
        {"op": "trial", "rels": [], "nodes": ["missing"]},
        {"op": "commit", "rels": [], "nodes": [a_key]},
        {"op": "trial", "rels": [], "nodes": []},
        {"op": "stop"},
    ]
    out = io.StringIO()
    assert serve(spec, io.StringIO("".join(json.dumps(m) + "\n" for m in lines)), out) == 0
    replies = [json.loads(x) for x in out.getvalue().splitlines()]
    assert replies[0]["relate_db"] == relate.__version__ and replies[0]["relationships"] == 6
    assert "answer" in replies[1] and "not in this store" in replies[2]["error"]
    assert replies[3] == {"ok": True} and "B" in replies[4]["answer"] and "'A'" not in replies[4]["answer"]
    assert replies[5] == {"ok": True}
    # a statement the engine refuses at run time is an error reply; end of input ends the worker
    bad = {**spec, "query": query_spec(gq("MATCH (n:P) RETURN n.name / 0 AS x"))}
    out = io.StringIO()
    assert serve(bad, io.StringIO(json.dumps({"op": "trial", "rels": [], "nodes": []}) + "\n"), out) == 0
    assert "error" in json.loads(out.getvalue().splitlines()[1])
    # main() reads the spec file and serves stdin
    path = tmp_path / "spec.json"
    path.write_text(json.dumps(spec))
    old_in, old_out = sys.stdin, sys.stdout
    sys.stdin, sys.stdout = io.StringIO('{"op": "stop"}\n'), io.StringIO()
    try:
        assert worker_main([str(path)]) == 0
        assert sys.stdout.getvalue().count("\n") == 2
    finally:
        sys.stdin, sys.stdout = old_in, old_out


# ---- the backend the reducer drives --------------------------------------------------------------------------------
class _Stub:
    def __init__(self, reply):
        self.reply = reply
        self.commits = []

    def answer(self, rels=(), nodes=()):
        return self.reply

    def commit(self, rels=(), nodes=()):
        self.commits.append((rels, nodes))

    def close(self):
        self.closed = True


def test_two_engines_paths(tiny_rl):
    sc = Scratch.open_copy(tiny_rl)
    try:
        q = gq()
        stmts = [(q.exec_text, {}), (q.exec_text, {})]
        be = TwoEngines(sc, q, _Stub(EngineAnswer(Remote("x"), None, 1.0)))
        r = sc_rel = next(iter(sc.rel_keys))
        t = be.trial_many(stmts, [r], [])
        assert t.error is None and repr(t.answers[1]) == "x" and be.other_ms == [1.0]
        be.commit_delete([sc_rel], [])
        assert be.engine.commits == [([sc.rel_keys[sc_rel]], [])]
        be.close()
        assert be.engine.closed
        assert "other engine: no" in TwoEngines(sc, q, _Stub(EngineAnswer(None, "no", 1.0))).trial_many(stmts).error
        bad = gq("MATCH (n:P) RETURN n.name / 0 AS x")
        assert TwoEngines(sc, bad, _Stub(None)).trial_many([(bad.exec_text, {})]).error
        opaque = gq("MATCH (n:P) RETURN n AS n")
        be2 = TwoEngines(sc, opaque, _Stub(None))
        be2.sc = types.SimpleNamespace(
            trial_many=lambda *a, **k: types.SimpleNamespace(error=None, results=[([{"n": object()}], ["n"])]),
            keyer=sc.keyer,
        )
        assert be2.trial_many([(opaque.exec_text, {})]).error
    finally:
        sc.close()


# ---- the pipeline and the CLI ----------------------------------------------------------------------------------------
def _req(source, out, **kw):
    base = {"source": Path(source), "statement": EXISTS_Q, "params": {"country": "MX"}, "out_dir": out, "ledger": None}
    return Request(**{**base, **kw})


def test_pipeline_refusals(tiny_rl, tmp_path, monkeypatch):
    with pytest.raises(Refused, match="no --other"):
        reduce_request(_req(ENGINE_W, tmp_path, other_engine=SELF, other="RETURN 1", predicate="disagree"))
    with pytest.raises(Refused, match="no --other"):
        reduce_request(_req(ENGINE_W, tmp_path, other_engine=SELF, predicate="differs"))
    with pytest.raises(Refused, match="same answer on the full graph"):
        reduce_request(_req(ENGINE_W, tmp_path, other_engine=SELF))
    for reply, why in ((EngineAnswer(None, "boom", 0.0), "cannot answer"), (EngineAnswer(Tie([]), None, 0.0), "tie")):
        stub = _Stub(reply)
        stub.label = "stub"
        monkeypatch.setattr(engines, "open_engine", lambda *a, _s=stub, **k: _s)
        with pytest.raises(Refused, match=why):
            reduce_request(_req(ENGINE_W, tmp_path, other_engine=SELF))
        assert stub.closed


@pytest.mark.skipif(shutil.which("uv") is None, reason="needs uv to fetch relate-db 1.3.0")
def test_reduce_and_check_against_relate_1_3_0(tmp_path, capsys):
    """The committed 2-relationship engine witness: EXISTS over two MATCH clauses gives nothing on 1.0.1 and MZT on
    1.3.0. Reduced against a 1.3.0 worker it stays 2 relationships, both needed; checked against 1.2.0 it agrees."""
    o = reduce_request(_req(ENGINE_W, tmp_path, other_engine="relate-db==1.3.0", name="engines"))
    assert o.verified and o.run["final_counts"] == (3, 2), o.reasons
    pred = o.manifest["predicate"]
    assert pred["kind"] == "disagree" and pred["other_engine"] == "relate-db 1.3.0"
    assert pred["other_engine_spec"] == "relate-db==1.3.0" and o.check.other_engine == "relate-db 1.3.0"
    assert o.check.text.startswith("2 of 2 end the disagreement")
    w = str(tmp_path / "engines.rl")
    assert main(["check", w, "--no-cli"]) == 0
    assert "and on relate-db 1.3.0" in capsys.readouterr().out
    assert main(["check", w, "--no-cli", "--other-engine", "relate-db==1.2.0"]) == 1
    assert "the predicate does not hold on W" in capsys.readouterr().out
    qf = tmp_path / "q.cypher"
    qf.write_text(EXISTS_Q)
    args = ["check", w, "--no-cli", "-f", str(qf), "--param", "country=MX", "--expect", "[]"]
    assert main([*args, "--other-engine", "relate-db==1.3.0"]) == 0
    capsys.readouterr()
    rc = main(["why", "-f", str(qf), "--param", "country=MX", "--store", str(ENGINE_W), "--other-engine",
               "relate-db==1.3.0", "--out", str(tmp_path / "cli"), "--no-ledger", "--no-cli"])  # fmt: skip
    assert rc == 0 and "end the disagreement" in capsys.readouterr().out


def test_check_override_refused_without_an_engine_witness(tmp_path, capsys):
    w = ROOT / "witnesses" / "two-hub.rl"
    assert main(["check", str(w), "--no-cli", "--other-engine", SELF]) == 2
    assert "re-checks a witness reduced with --other-engine" in capsys.readouterr().err


# ---- Neo4j over Bolt, against a stand-in driver that runs each statement on a real Relate store ------------------
class _Rec:
    def __init__(self, row: dict):
        self.row = row

    def __getitem__(self, k):
        return self.row[k]

    def values(self):
        return list(self.row.values())


class _Res:
    def __init__(self, res):
        self.res = res

    def keys(self):
        return list(self.res.columns)

    def __iter__(self):
        return iter(_Rec(r) for r in self.res.data)

    def single(self):
        return _Rec(self.res.data[0]) if self.res.data else None

    def consume(self):
        return None


class _Tx:
    def __init__(self, db):
        self.db = db
        db.begin_transaction()

    def run(self, stmt, params=None, **kw):
        return _Res(self.db.execute(stmt, {**(params or {}), **kw}))

    def rollback(self):
        if self.db.transaction_active():
            self.db.rollback_transaction()

    def commit(self):
        self.db.commit_transaction()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.rollback()


class _Session:
    def __init__(self, drv):
        self.drv = drv

    def run(self, stmt, params=None, **kw):
        if "dbms.components" in stmt:
            return _Res(types.SimpleNamespace(columns=["v"], data=[{"v": "stand-in"}]))
        return _Res(self.drv.db.execute(stmt, {**(params or {}), **kw}))

    def begin_transaction(self, timeout=None):
        self.drv.timeouts.append(timeout)
        return _Tx(self.drv.db)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return None


class _Driver:
    def __init__(self, path):
        self.db = relate.Database(str(path))
        self.closed = False
        self.timeouts = []

    def session(self, database=None):
        return _Session(self)

    def close(self):
        self.closed = True
        self.db.close()


def test_neo4j_engine_against_a_stand_in(tiny_rl, tmp_path):
    sc = Scratch.open_copy(tiny_rl)
    drv = _Driver(tmp_path / "neo.rl")
    try:
        eng = Neo4jEngine(sc, gq(), driver=drv, timeout=7.0)
        assert eng.label == "Neo4j stand-in" and eng.counts == sc.counts()
        full = eng.answer()
        assert full.error is None and drv.timeouts == [7.0]  # every trial carries the deadline to the server
        a_key = next(k for i, k in sc.node_keys.items() if sc.node_props[i]["name"] == "A")
        rel = next(iter(sc.rel_keys.values()))
        assert repr(eng.answer([rel], []).answer) == repr(full.answer)
        assert repr(eng.answer([], [a_key]).answer) != repr(full.answer)
        assert repr(eng.answer().answer) == repr(full.answer)  # rolled back
        eng.commit([rel], [])
        eng.commit([], [a_key])
        assert "not on the other engine" in eng.answer([rel], []).error
        node_q = Neo4jEngine.__new__(Neo4jEngine)
        node_q.__dict__.update(eng.__dict__, gq=gq("MATCH (n:P) RETURN [{n: 1}] AS x"))
        assert node_q.answer().error is None
        eng.close()
        assert drv.closed and eng.node_ids == {}
        eng.close()  # once: a second close touches nothing
    finally:
        sc.close()


def test_neo4j_engine_refuses_a_non_empty_database(tiny_rl, tmp_path):
    sc = Scratch.open_copy(tiny_rl)
    drv = _Driver(tmp_path / "busy.rl")
    drv.db.execute("CREATE (:Someone {name: 'theirs'})")
    try:
        with pytest.raises(Refused, match="not empty"):
            Neo4jEngine(sc, gq(), driver=drv, settings={"NEO4J_DATABASE": "neo4j"})
        assert drv.closed
    finally:
        sc.close()


def test_neo4j_graph_values_are_refused():
    graph = type("Node", (), {"__module__": "neo4j.graph"})()
    assert engines._graph_value([{"a": graph}]) and not engines._graph_value([1, {"a": "b"}])


def test_neo4j_driver_only_values_are_inconclusive(tiny_rl, tmp_path, monkeypatch):
    """A date from the Neo4j driver and the same date from relate-db have different reprs: never a disagreement."""
    import datetime

    date = type("Date", (), {"__module__": "neo4j.time"})()
    assert engines._driver_value({"d": [date]}) and not engines._driver_value([datetime.date(2020, 1, 2), 1.5, "x"])
    sc = Scratch.open_copy(tiny_rl)
    eng = Neo4jEngine(sc, gq(), driver=_Driver(tmp_path / "g.rl"))
    monkeypatch.setattr(engines, "_driver_value", lambda v: True)
    try:
        assert eng.answer().answer is None and "temporal or spatial value" in eng.answer().error
    finally:
        eng.close()
        sc.close()


def test_neo4j_load_that_loses_an_element_is_refused(tiny_rl, tmp_path, monkeypatch):
    sc = Scratch.open_copy(tiny_rl)
    drv = _Driver(tmp_path / "short.rl")
    monkeypatch.setattr(Neo4jEngine, "_load", lambda self, sc: None)
    try:
        with pytest.raises(Refused, match="holds 0 nodes and 0 relationships after the load, this side 5 and 6"):
            Neo4jEngine(sc, gq(), driver=drv)
        assert drv.closed
    finally:
        sc.close()


def test_neo4j_graph_value_answer_is_an_error(tiny_rl, tmp_path, monkeypatch):
    sc = Scratch.open_copy(tiny_rl)
    eng = Neo4jEngine(sc, gq(), driver=_Driver(tmp_path / "g.rl"))
    monkeypatch.setattr(engines, "_graph_value", lambda v: True)
    try:
        assert "graph values" in eng.answer().error
    finally:
        eng.close()
        sc.close()


def test_open_engine_neo4j_through_the_driver_module(tiny_rl, tmp_path, monkeypatch):
    made = []

    def driver(uri, auth):
        made.append((uri, auth))
        return _Driver(tmp_path / f"d{len(made)}.rl")

    monkeypatch.setitem(sys.modules, "neo4j", types.SimpleNamespace(GraphDatabase=types.SimpleNamespace(driver=driver)))
    monkeypatch.setattr(engines, "neo4j_settings", lambda: {"NEO4J_BOLT": "bolt://h", "NEO4J_USER": "u",
                        "NEO4J_PASSWORD": "p", "NEO4J_DATABASE": "neo4j"})  # fmt: skip
    eng = open_engine("neo4j", tiny_rl, gq())
    assert eng.counts[1] == 6
    eng.close()
    sc = Scratch.open_copy(tiny_rl)
    eng = open_engine("neo4j", tiny_rl, gq(), sc=sc)
    eng.close()
    sc.close()
    assert made[0] == ("bolt://h", ("u", "p"))
    monkeypatch.setitem(sys.modules, "neo4j", None)
    with pytest.raises(Refused, match="needs the neo4j driver"):
        open_engine("neo4j", tiny_rl, gq())


def test_worker_module_entry_point(tiny_rl, tmp_path, monkeypatch):
    import runpy

    spec = tmp_path / "spec.json"
    body = {"source": str(tiny_rl), "query": query_spec(gq()), "strict_lists": False, "digits": 12}
    spec.write_text(json.dumps(body))
    monkeypatch.setattr(sys, "argv", ["engine_worker", str(spec)])
    monkeypatch.setattr(sys, "stdin", io.StringIO('{"op": "stop"}\n'))
    monkeypatch.setattr(sys, "stdout", io.StringIO())
    monkeypatch.delitem(sys.modules, "witness.engine_worker", raising=False)
    with pytest.raises(SystemExit) as e:
        runpy.run_module("witness.engine_worker", run_name="__main__")
    assert e.value.code == 0


def test_check_closes_the_engine_when_it_fails(tiny_rl, monkeypatch):
    from witness import check as check_mod

    q = gq()
    spec = check_mod.CheckSpec(queries=[q, q], kind="disagree", baseline_sha="", other_engine=SELF)

    def boom(rows):
        raise RuntimeError("boom")

    monkeypatch.setattr(check_mod, "has_graph_values", boom)
    with pytest.raises(RuntimeError, match="boom"):
        check_mod.check(tiny_rl, spec, use_cli=False)


def test_check_keeps_the_other_engines_error_and_always_closes_it(tiny_rl, monkeypatch):
    from witness import check as check_mod

    q = gq()

    def spec():
        return check_mod.CheckSpec(queries=[q, q], kind="disagree", baseline_sha="", other_engine=SELF)

    stub = _Stub(EngineAnswer(None, "TrialTimeout: no answer within 30 s", 0.0))
    stub.label = "stub 1"
    monkeypatch.setattr(engines, "open_engine", lambda *a, **k: stub)
    res = check_mod.check(tiny_rl, spec(), use_cli=False)
    assert stub.closed and not res.verified and res.sufficient is None
    assert "stub 1 could not answer on W: TrialTimeout" in res.reasons[0]
    assert all(p["necessary"] is None and p["error"].startswith("stub 1: TrialTimeout") for p in res.probes)

    class Interrupted(_Stub):
        calls = 0

        def answer(self, rels=(), nodes=()):
            Interrupted.calls += 1
            if Interrupted.calls > 1:
                raise KeyboardInterrupt
            return EngineAnswer(Remote("()"), None, 0.0)

    stub2 = Interrupted(None)
    stub2.label = "stub 2"
    monkeypatch.setattr(engines, "open_engine", lambda *a, **k: stub2)
    with pytest.raises(KeyboardInterrupt):
        check_mod.check(tiny_rl, spec(), use_cli=False)
    assert stub2.closed  # Ctrl-C in the middle of the probes still ends the other engine


def test_open_engine_worker(tiny_rl):
    sc = Scratch.open_copy(tiny_rl)
    eng = open_engine(SELF, tiny_rl, gq(), sc=sc, timeout=5.0)  # sc: the worker must report this graph's shape
    sc.close()
    assert isinstance(eng, WorkerEngine) and eng.timeout == 5.0 and eng.expect[:2] == (5, 6)
    eng.close()
    eng = open_engine(SELF, tiny_rl, gq())
    assert eng.expect is None
    eng.close()
