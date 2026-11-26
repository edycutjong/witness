"""`witness.mcp_server`: the workers run in this process over a real Pipe, the supervisor against real child
processes, `serve` through the real MCPServer with only its stdio transport left out, and `main` end to end."""

import asyncio
import json
import multiprocessing as mp
import os
import signal
import struct
import subprocess
import sys
import time
from pathlib import Path

import pytest

from witness import mcp_server
from witness.mcp_server import (
    ToolError,
    WitnessTools,
    _check_worker,
    _kill_group,
    _own_group,
    _recv_within,
    _why_worker,
    evidence_markdown,
    override_spec,
    resolve_store,
)

ROOT = Path(__file__).resolve().parent.parent
HUBS = "MATCH (a:P {name: 'A'})-[:R]->(h)-[:R]->(:P {name: 'D'}) RETURN h.name AS hub ORDER BY hub"
ONLY_B = "MATCH (a:P {name: 'A'})-[:R]->(h)-[:R]->(:P {name: 'D'}) WHERE h.name = 'B' RETURN h.name AS hub"
WITNESS = ROOT / "witnesses" / "two-hub.rl"


@pytest.fixture
def tools(tmp_path):
    return WitnessTools(
        allow=[tmp_path], out_root=tmp_path / "out", use_cli=False, trial_timeout=20, request_timeout=120
    )


@pytest.fixture
def stay_in_this_session(monkeypatch):
    """The workers run inside the pytest process here: never let `_own_group` detach it from its session."""
    monkeypatch.setattr(os, "setsid", lambda: None)


def run_inline(worker, args):
    """Run a worker function in this process (so it is measured) over a real Pipe; returns what it sent."""
    parent, child = mp.Pipe()
    worker(child, args)
    assert parent.poll(1)
    return parent.recv()


def why_args(tmp_path, source, statement=HUBS, **over):
    req = {
        "source": str(source),
        "statement": statement,
        "params": {},
        "predicate": "keep",
        "expected": None,
        "other": None,
        "isolate": False,
        "trial_timeout": 20,
        "max_seconds": 60,
        "name": "witness",
        "out_dir": str(tmp_path / "out" / "one"),
        "ledger": str(tmp_path / "out" / "ledger.rl"),
        "requester": "mcp:pytest",
        "use_cli": False,
        "claimed": None,
    }
    return {**req, **over}


def check_args(statement=None, parameters=None, manifest=None):
    return {
        "witness": str(WITNESS),
        "manifest": str(manifest or WITNESS.with_suffix(".manifest.json")),
        "statement": statement,
        "parameters": parameters or {},
        "use_cli": False,
    }


# ---- resolve_store / ToolError -------------------------------------------------------------------------------------
def test_a_relative_store_path_resolves_against_the_package_root():
    p = resolve_store("data/air-routes.rl", [(ROOT / "data").resolve()], ROOT / "data" / "air-routes.rl")
    assert p == (ROOT / "data" / "air-routes.rl").resolve()


def test_the_package_root_is_the_working_directory_when_it_holds_the_committed_data(tmp_path, monkeypatch):
    # a2a arch r7: from a wheel install, parents[2] of the module is the venv's lib dir; a clone as cwd is the root
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "air-routes.rl").write_bytes(b"")
    monkeypatch.chdir(tmp_path)
    assert mcp_server.package_root() == tmp_path


def test_the_package_root_falls_back_to_the_source_checkout(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert mcp_server.package_root() == Path(mcp_server.__file__).resolve().parents[2]


def test_a_tool_error_is_an_object_the_agent_can_read():
    assert ToolError("store", "nope").to_dict() == {"error": {"kind": "store", "message": "nope"}, "verified": False}


def test_the_allowlist_message_shows_package_relative_and_absolute_directories(tmp_path):
    outside = tmp_path / "x.rl"
    outside.write_bytes(b"")
    with pytest.raises(ToolError, match=r"allowlisted directories \(data, "):
        resolve_store(str(outside), [(ROOT / "data").resolve(), tmp_path / "elsewhere"], outside)
    with pytest.raises(ToolError) as e:
        resolve_store(str(outside), [(ROOT / "data").resolve(), tmp_path / "elsewhere"], outside)
    assert str(tmp_path / "elsewhere") in e.value.message


# ---- evidence_markdown ---------------------------------------------------------------------------------------------
def res_for(*, verified=True, check_text="3 of 3 change the answer (3 of 3 relationships)", reasons=(), n_rows=2, ex=3):
    return {
        "answer": {"rows": [{"a": i} for i in range(n_rows)]},
        "witness": {"relationships": ex},
        "check": {"check_text": check_text},
        "verified": verified,
        "source_relationships": 12345,
        "exhibits": [{"n": i, "start": "S", "type": "T", "end": "E"} for i in range(1, ex + 1)],
        "files": {"rl": "out/w.rl"},
        "relate_version": "1.0.1",
        "reasons": list(reasons),
    }


def test_evidence_markdown_says_how_many_answer_rows_were_not_shown():
    md = evidence_markdown(res_for(n_rows=9))
    assert "**Answer** (9 rows): 0; 1; 2; 3; 4; 5; … (+3 more)" in md


def test_evidence_markdown_names_what_the_witness_keeps_for_each_predicate():
    assert "12,345" in evidence_markdown(res_for())
    assert "reproduce it" in evidence_markdown(res_for())
    dis = evidence_markdown(res_for(check_text="2 of 2 end the disagreement (2 of 2 relationships)"))
    assert "keep the two queries disagreeing" in dis
    mis = evidence_markdown(res_for(check_text="2 of 2 end the mismatch (2 of 2 relationships)"))
    assert "keep the mismatch" in mis


def test_evidence_markdown_for_a_short_register_has_no_overflow_line():
    md = evidence_markdown(res_for(ex=3))
    assert "more lines in the file" not in md and md.count("\n") < 25
    assert " 1 (S)-[:T]->(E)" in md and "verified deletion-minimal" in md


def test_evidence_markdown_for_an_unverified_answer_says_so_and_gives_the_first_two_reasons():
    md = evidence_markdown(res_for(verified=False, check_text="NOT SUFFICIENT: x", reasons=["r1", "r2", "r3"]))
    assert "were kept" in md and "NOT verified." in md and "NOT SUFFICIENT: x" in md
    assert md.splitlines()[-1] == "Not verified: r1; r2"
    bare = evidence_markdown(res_for(verified=False, check_text="NOT SUFFICIENT: x"))
    assert bare.splitlines()[-1] == "Not verified."


# ---- process-group helpers -----------------------------------------------------------------------------------------
def test_own_group_makes_the_process_a_group_leader():
    out = subprocess.run(
        [
            sys.executable,
            "-c",
            "import os; from witness.mcp_server import _own_group; _own_group(); print(os.getpgrp() == os.getpid())",
        ],
        capture_output=True,
        text=True,
        timeout=60,
        cwd=ROOT,
        env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
    )
    assert out.stdout.strip() == "True", out.stderr


def test_own_group_calls_setsid_and_survives_the_os_refusing_it(monkeypatch):
    calls = []
    monkeypatch.setattr(os, "setsid", lambda: calls.append("setsid"))
    _own_group()

    def refused():
        calls.append("refused")
        raise PermissionError("already a group leader")

    monkeypatch.setattr(os, "setsid", refused)
    _own_group()  # an OSError is swallowed: the worker still runs
    assert calls == ["setsid", "refused"]


def test_own_group_does_nothing_on_a_platform_without_setsid(monkeypatch):
    monkeypatch.delattr(os, "setsid")
    _own_group()


def _group_leader_with_a_grandchild(conn):
    os.setsid()
    grandchild = subprocess.Popen(["sleep", "60"])
    conn.send(grandchild.pid)
    time.sleep(60)


def _plain_sleeper():
    time.sleep(60)


def _alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def test_kill_group_takes_the_whole_process_group_down_with_the_worker():
    ctx = mp.get_context("spawn")
    parent, child = ctx.Pipe()
    proc = ctx.Process(target=_group_leader_with_a_grandchild, args=(child,))
    proc.start()
    child.close()
    assert parent.poll(60)
    grandchild = parent.recv()
    assert _alive(grandchild)
    _kill_group(proc)
    proc.join(10)
    assert proc.exitcode == -signal.SIGKILL
    deadline = time.monotonic() + 10
    while _alive(grandchild) and time.monotonic() < deadline:  # the orphan is reaped by init: give it a moment
        time.sleep(0.05)
    assert not _alive(grandchild)  # the isolate trial child would die with its request process


def test_kill_group_falls_back_to_killing_the_process_when_it_leads_no_group():
    ctx = mp.get_context("spawn")
    proc = ctx.Process(target=_plain_sleeper)
    proc.start()
    _kill_group(proc)  # killpg(pid) finds no such group; the process itself is killed instead
    proc.join(10)
    assert proc.exitcode == -signal.SIGKILL


def test_kill_group_leaves_a_process_that_never_started_alone():
    proc = mp.get_context("spawn").Process(target=_plain_sleeper)
    _kill_group(proc)  # no pid, not alive: nothing to signal
    assert proc.pid is None and proc.exitcode is None


# ---- _recv_within --------------------------------------------------------------------------------------------------
def test_recv_within_returns_what_the_worker_sent():
    a, b = mp.Pipe()
    b.send(("ok", {"x": 1}))
    assert _recv_within(a, 5) == ("ok", {"x": 1})


def test_recv_within_reraises_the_workers_death_in_the_caller():
    a, b = mp.Pipe()
    b.close()
    with pytest.raises(EOFError):
        _recv_within(a, 5)


def test_recv_within_times_out_when_the_reply_never_completes():
    a, b = mp.Pipe()
    t0 = time.monotonic()
    with pytest.raises(TimeoutError):
        _recv_within(a, 0.2)
    assert time.monotonic() - t0 < 2
    b.close()  # lets the abandoned reader thread finish


# ---- override_spec -------------------------------------------------------------------------------------------------
def test_override_spec_compares_against_the_baseline_hash_the_way_the_witness_was_compared():
    manifest = json.loads(WITNESS.with_suffix(".manifest.json").read_text())
    spec = override_spec(manifest, "MATCH (a:Airport) RETURN count(a) AS n", None)
    assert spec.kind == "keep" and spec.baseline_sha == manifest["baseline"]["sha256"]
    assert spec.strict_lists is True and spec.digits == 12  # from the manifest, not the defaults
    assert spec.queries[0].params == {} and spec.queries[0].door == "check"
    manifest["comparison"] = {"float_digits": 6}
    spec = override_spec(manifest, "MATCH (a:Airport) WHERE a.iata = $c RETURN a.iata AS i", {"c": "MEX"})
    assert spec.strict_lists is False and spec.digits == 6 and spec.queries[0].params == {"c": "MEX"}
    del manifest["comparison"]
    assert override_spec(manifest, "RETURN 1 AS x", {}).digits == 12


def test_override_spec_refuses_a_write_statement_at_the_check_door():
    from witness.guard import Refused

    manifest = json.loads(WITNESS.with_suffix(".manifest.json").read_text())
    with pytest.raises(Refused) as e:
        override_spec(manifest, "CREATE (n:X) RETURN n", None)
    assert e.value.door == "check"


# ---- the check worker (in process) ---------------------------------------------------------------------------------
def test_check_worker_reproves_a_committed_witness_from_its_files(stay_in_this_session):
    kind, payload = run_inline(_check_worker, check_args())
    assert kind == "ok" and payload["verified"] is True
    assert payload["check_text"].startswith("22 of 22 change the answer")


def test_check_worker_runs_an_agents_own_statement_against_the_baseline(stay_in_this_session):
    manifest = json.loads(WITNESS.with_suffix(".manifest.json").read_text())
    kind, payload = run_inline(
        _check_worker, check_args(statement=manifest["statement"], parameters=manifest["params"])
    )
    assert kind == "ok" and payload["verified"] is True
    kind, payload = run_inline(_check_worker, check_args(statement="MATCH (a:Airport) RETURN count(a) AS n"))
    assert kind == "ok" and payload["verified"] is False  # a different answer is not the baseline


def test_check_worker_turns_a_refused_statement_into_a_refusal_not_a_crash(stay_in_this_session):
    kind, payload = run_inline(_check_worker, check_args(statement="CREATE (n:X) RETURN n"))
    assert kind == "refused" and payload["kind"] == "check" and payload["message"]


def test_check_worker_reports_an_unreadable_manifest_as_a_witness_refusal(tmp_path, stay_in_this_session):
    bad = tmp_path / "bad.manifest.json"
    bad.write_text("{}")  # valid JSON, but no baseline/predicate: KeyError
    kind, payload = run_inline(_check_worker, check_args(manifest=bad))
    assert kind == "refused" and payload["kind"] == "witness"
    assert payload["message"].startswith("unreadable manifest: KeyError")
    bad.write_text("not json")
    kind, payload = run_inline(_check_worker, check_args(manifest=bad))
    assert kind == "refused" and "unreadable manifest: JSONDecodeError" in payload["message"]


def test_check_worker_reports_an_unexpected_failure_as_an_internal_error(tmp_path, stay_in_this_session):
    kind, payload = run_inline(_check_worker, check_args(manifest=tmp_path / "gone.manifest.json"))
    assert kind == "error" and payload["kind"] == "internal" and "FileNotFoundError" in payload["message"]


# ---- the why worker (in process) -----------------------------------------------------------------------------------
def test_why_worker_returns_the_whole_evidence_object_and_records_the_ledger(tmp_path, tiny_rl, stay_in_this_session):
    kind, res = run_inline(_why_worker, why_args(tmp_path, tiny_rl))
    assert kind == "ok" and res["verified"] is True
    assert res["answer"] == {
        "columns": ["hub"],
        "rows": [{"hub": "B"}, {"hub": "C"}],
        "rows_total": 2,
        "rows_truncated": False,
    }
    assert res["witness"] == {"relationships": 4, "nodes": 4, "deletion_minimal_verified": True}
    assert res["source_relationships"] == 6 and res["check"]["check_text"].startswith("4 of 4 change the answer")
    assert [e["n"] for e in res["exhibits"]] == [1, 2, 3, 4]
    assert Path(res["files"]["rl"]).is_file() and res["out_dir"] == str(tmp_path / "out" / "one")
    assert res["ledger_path"] == str(tmp_path / "out" / "ledger.rl") and res["ledger_id"].startswith("r-")
    assert res["determinism_claimed"] is True and res["trials"] > 0 and res["inconclusive"] == 0
    assert res["evidence_markdown"].startswith("**Answer** (2 rows): B; C")
    from witness import ledger

    assert ledger.find(res["ledger_path"], res["ledger_id"])["r"]["requester"] == "mcp:pytest"


def test_why_worker_without_a_ledger_writes_none(tmp_path, tiny_rl, stay_in_this_session):
    kind, res = run_inline(_why_worker, why_args(tmp_path, tiny_rl, ledger=None))
    assert kind == "ok" and res["ledger_path"] is None and res["ledger_id"] is None
    assert not (tmp_path / "out" / "ledger.rl").exists()


def test_why_worker_runs_the_disagree_predicate_with_the_second_query(tmp_path, tiny_rl, stay_in_this_session):
    kind, res = run_inline(_why_worker, why_args(tmp_path, tiny_rl, predicate="disagree", other=ONLY_B, ledger=None))
    assert kind == "ok" and res["verified"] is True
    assert "end the disagreement" in res["check"]["check_text"]
    assert "keep the two queries disagreeing" in res["evidence_markdown"]


def test_why_worker_reports_a_stopped_reduction_as_not_verified_with_its_reasons(
    tmp_path, tiny_rl, stay_in_this_session
):
    kind, res = run_inline(_why_worker, why_args(tmp_path, tiny_rl, max_trials=1, ledger=None))
    assert kind == "ok" and res["verified"] is False and res["reasons"]
    assert "NOT verified." in res["evidence_markdown"] and "Not verified: " in res["evidence_markdown"]


def test_why_worker_turns_a_guard_refusal_into_a_refusal_with_its_door(tmp_path, tiny_rl, stay_in_this_session):
    kind, payload = run_inline(_why_worker, why_args(tmp_path, tiny_rl, statement="CREATE (n:P) RETURN n"))
    assert kind == "refused" and payload["kind"] == "query" and payload["message"]


def test_why_worker_reports_an_unexpected_failure_as_an_internal_error(tmp_path, tiny_rl, stay_in_this_session):
    blocker = tmp_path / "blocker"
    blocker.write_text("a file where the out directory should be")
    kind, payload = run_inline(_why_worker, why_args(tmp_path, tiny_rl, out_dir=str(blocker / "one")))
    assert kind == "error" and payload["kind"] == "internal" and payload["message"]


# ---- WitnessTools --------------------------------------------------------------------------------------------------
def test_default_tools_allow_the_committed_data_and_witnesses_and_write_under_out(tmp_path):
    t = WitnessTools()
    assert t.allow == [(ROOT / "data").resolve(), (ROOT / "witnesses").resolve()]
    assert t.out_root == (ROOT / "out").resolve() and t.ledger == t.out_root / "ledger.rl"
    assert t.default_store == ROOT / "data" / "air-routes.rl" and t.isolate is True
    t2 = WitnessTools(out_root=tmp_path / "o", ledger=tmp_path / "led.rl", isolate=False)
    assert t2.ledger == tmp_path / "led.rl" and t2.isolate is False


def test_why_refuses_an_empty_statement_before_starting_a_worker(tools, tiny_rl):
    for blank in ("", "   \n"):
        r = tools.why(blank, store=str(tiny_rl))
        assert r["error"] == {"kind": "query", "message": "statement must be a non-empty Cypher string"}
    assert tools._n == 0


def test_why_with_the_disagree_predicate_through_a_real_worker_says_what_the_witness_keeps(tools, tiny_rl):
    r = tools.why(HUBS, store=str(tiny_rl), predicate="disagree", other_statement=ONLY_B)
    assert r["verified"] is True and "end the disagreement" in r["check"]["check_text"]
    assert "keep the two queries disagreeing" in r["evidence_markdown"]
    assert r["request_seconds"] > 0


def test_check_resolves_a_relative_witness_path_against_the_package_and_reproves_it():
    t = WitnessTools(use_cli=False, request_timeout=120)
    r = t.check("witnesses/two-hub.rl")
    assert r["verified"] is True and r["witness_path"] == str(WITNESS.resolve())
    assert r["overridden"] == [] and "request_seconds" not in r


def test_check_refuses_parameters_without_a_statement(tools, tmp_path, tiny_rl):
    r = tools.why(HUBS, store=str(tiny_rl))
    c = tools.check(r["files"]["rl"], parameters={"x": 1})
    assert c["error"]["kind"] == "check" and "pass both or neither" in c["error"]["message"]


def test_check_returns_a_worker_refusal_as_an_error_object(tools, tmp_path, tiny_rl):
    r = tools.why(HUBS, store=str(tiny_rl))
    c = tools.check(r["files"]["rl"], statement="CREATE (n:P) RETURN n")
    assert c["verified"] is False and c["error"]["kind"] == "check" and "overridden" not in c
    bad = Path(r["files"]["rl"]).with_suffix(".manifest.json")
    bad.write_text("{}")
    c = tools.check(r["files"]["rl"])
    assert c["error"]["kind"] == "witness" and "unreadable manifest" in c["error"]["message"]


# ---- _supervise: a worker that misbehaves --------------------------------------------------------------------------
def _worker_replies_ok_then_lingers(conn, req):
    conn.send(("ok", {"echo": req["n"]}))
    time.sleep(60)  # never exits on its own


def _worker_dies_silently(conn, req):
    os._exit(3)


def _worker_sends_garbage(conn, req):
    _own_group()
    conn.send_bytes(b"this is not a pickle")
    time.sleep(60)


def _worker_stalls_mid_frame(conn, req):
    _own_group()
    os.write(conn.fileno(), struct.pack("!i", 1000) + b"partial")  # a header that promises 1000 bytes, then silence
    time.sleep(60)


def _worker_refuses(conn, req):
    conn.send(("refused", {"kind": "query", "message": "no"}))


def test_a_worker_that_replies_and_then_lingers_is_reaped_and_its_reply_returned():
    t = WitnessTools(request_timeout=60)
    t0 = time.monotonic()
    r = t._supervise(_worker_replies_ok_then_lingers, {"n": 7})
    assert r["echo"] == 7 and r["request_seconds"] >= 0
    assert time.monotonic() - t0 < 30  # the lingering worker was killed after the 5 s join, not waited out


def test_a_worker_that_dies_without_replying_is_an_internal_error_with_its_exit_code():
    r = WitnessTools(request_timeout=60)._supervise(_worker_dies_silently, {})
    assert r["verified"] is False and r["error"]["kind"] == "internal"
    assert r["error"]["message"].startswith("the reduction process died (exit code")


def test_a_reply_that_cannot_be_unpickled_is_an_internal_error_and_the_worker_is_killed():
    r = WitnessTools(request_timeout=60)._supervise(_worker_sends_garbage, {})
    assert r["error"]["kind"] == "internal"
    assert r["error"]["message"].startswith("unreadable reply from the worker: ")


def test_a_reply_that_stalls_mid_frame_hits_the_request_deadline_instead_of_blocking_forever():
    t = WitnessTools(request_timeout=5)
    t0 = time.monotonic()
    r = t._supervise(_worker_stalls_mid_frame, {})
    assert r["error"]["kind"] == "timeout" and "did not complete within 5 s" in r["error"]["message"]
    assert time.monotonic() - t0 < 30


def test_a_worker_refusal_comes_back_as_a_tool_error_with_its_kind():
    r = WitnessTools(request_timeout=60)._supervise(_worker_refuses, {})
    assert r == {"error": {"kind": "query", "message": "no"}, "verified": False}


# ---- serve (the real MCPServer, minus the stdio transport) ---------------------------------------------------------
def served(monkeypatch, tools):
    from mcp.server.mcpserver import MCPServer

    seen = {}

    def no_transport(self, transport="stdio", **kw):
        seen["server"], seen["transport"] = self, transport

    monkeypatch.setattr(MCPServer, "run", no_transport)
    mcp_server.serve(tools)
    return seen


def test_serve_registers_why_and_check_on_stdio_and_they_reach_the_tools(monkeypatch, tmp_path, tiny_rl):
    both = WitnessTools(
        allow=[tmp_path, ROOT / "witnesses"], out_root=tmp_path / "out", use_cli=False, request_timeout=120
    )
    seen = served(monkeypatch, both)
    server = seen["server"]

    async def go():
        listed = await server.list_tools()
        why = await server.call_tool(
            "why",
            {"statement": HUBS, "store": str(tiny_rl), "predicate": "disagree", "other_statement": ONLY_B},
        )
        chk = await server.call_tool("check", {"witness_path": "witnesses/two-hub.rl"})
        return listed, why, chk

    listed, why, chk = asyncio.run(asyncio.wait_for(go(), 240))
    assert seen["transport"] == "stdio" and server.name == "witness"
    assert sorted(t.name for t in listed) == ["check", "why"]
    w, c = json.loads(why.content[0].text), json.loads(chk.content[0].text)
    assert w["verified"] is True and "end the disagreement" in w["check"]["check_text"]
    assert c["verified"] is True and c["check_text"].startswith("22 of 22")


# ---- main ----------------------------------------------------------------------------------------------------------
def capture_tools(monkeypatch):
    got = []
    monkeypatch.setattr(mcp_server, "serve", lambda t: got.append(t))
    return got


def test_main_builds_the_tools_from_its_flags_and_serves_them(monkeypatch, tmp_path):
    got = capture_tools(monkeypatch)
    rc = mcp_server.main(
        [
            "--out", str(tmp_path / "o"),
            "--ledger", str(tmp_path / "l.rl"),
            "--allow", str(tmp_path / "a"),
            "--allow", str(tmp_path / "b"),
            "--no-isolate",
            "--trial-timeout", "7",
            "--request-timeout", "9",
            "--no-cli",
        ]
    )  # fmt: skip
    t = got[0]
    assert rc == 0
    assert t.allow == [(tmp_path / "a").resolve(), (tmp_path / "b").resolve()]
    assert t.out_root == (tmp_path / "o").resolve() and t.ledger == tmp_path / "l.rl"
    assert (t.isolate, t.trial_timeout, t.request_timeout, t.use_cli) == (False, 7.0, 9.0, False)


def test_main_defaults_isolate_on_the_cli_on_and_the_package_directories(monkeypatch):
    got = capture_tools(monkeypatch)
    assert mcp_server.main([]) == 0
    t = got[0]
    assert t.allow == [(ROOT / "data").resolve(), (ROOT / "witnesses").resolve()]
    assert (t.isolate, t.trial_timeout, t.request_timeout, t.use_cli) == (True, 30.0, 300.0, True)
    assert t.out_root == (ROOT / "out").resolve()


def test_main_says_how_to_install_the_sdk_and_exits_2_when_mcp_is_missing(monkeypatch, capsys):
    got = capture_tools(monkeypatch)
    monkeypatch.setitem(sys.modules, "mcp", None)  # `import mcp` now raises ImportError
    assert mcp_server.main([]) == 2
    err = capsys.readouterr().err
    assert "uv run --extra mcp witness mcp" in err and "pip install -e '.[mcp]'" in err and got == []
    assert "not on PyPI" in err  # a2a arch r7: `pip install witness` is an unrelated PyPI package
