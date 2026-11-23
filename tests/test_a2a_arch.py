"""Regressions from the /a2a arch review (round 1): each test pins one defect the review or its verification found."""

import shutil

import pytest

from witness.canon import canon_rows, same_answer
from witness.fixture import pull_slice
from witness.guard import Refused, strip_comments
from witness.pipeline import Request, reduce_request


def test_answer_equality_is_type_aware_and_nan_safe():
    one, one_f, true = canon_rows([{"x": 1}]), canon_rows([{"x": 1.0}]), canon_rows([{"x": True}])
    assert one == one_f == true  # Python's == conflates them; the proof's sha256 never did
    assert not same_answer(one, one_f) and not same_answer(one, true)
    nan = canon_rows([{"x": float("nan")}])  # two NaN objects, as two trials return them
    other = canon_rows([{"x": float("nan")}])
    assert nan != other and same_answer(nan, other)


def test_strip_comments_keeps_string_literals_exact():
    q = "MATCH (n) // pick\nWHERE n.x = 'a  b\\tc' /* x */ RETURN n.x AS x ;"
    assert strip_comments(q) == "MATCH (n) WHERE n.x = 'a  b\\tc' RETURN n.x AS x"


def test_outputs_never_overwrite_the_source_store(tiny_rl):
    """`why -f tiny.cypher --store tiny.rl --out .` named its output tiny.rl and replaced the source."""
    before = tiny_rl.read_bytes()
    q = "MATCH (a:P {name: 'A'})-[:R]->(h)-[:R]->(d:P {name: 'D'}) RETURN h.name AS hub"
    kw = dict(source=tiny_rl, statement=q, params={}, out_dir=tiny_rl.parent, use_cli=False)
    req = Request(**kw, name="tiny", ledger=None)
    with pytest.raises(Refused, match="overwrite the source"):
        reduce_request(req)
    assert tiny_rl.read_bytes() == before
    req = Request(**kw, name="w", ledger=tiny_rl)
    with pytest.raises(Refused, match="overwrite the source"):
        reduce_request(req)
    with pytest.raises(Refused, match="plain file stem"):
        reduce_request(Request(source=tiny_rl, statement=q, params={}, name="../x", out_dir=tiny_rl.parent))


@pytest.mark.parametrize(
    "slice_query",
    [
        "MATCH (a:Airport) SET a.x = 1 RETURN a",
        "CALL db.labels() YIELD label RETURN label",
        "MATCH (a) RETURN a; MATCH (b) DETACH DELETE b",
        "-",
    ],
)
def test_fixture_slice_is_guarded_before_anything_runs(slice_query, tmp_path):
    with pytest.raises(Refused):
        pull_slice(tmp_path / "creds.env", slice_query, tmp_path / "slice.rl")


def test_mcp_check_is_supervised_and_its_errors_are_objects(tmp_path, tiny_rl):
    """MCP `check` ran in the server process: no request deadline, no lock, a bad manifest escaped as an exception."""
    from witness.mcp_server import WitnessTools

    w = tmp_path / "w.rl"
    shutil.copyfile(tiny_rl, w)
    (tmp_path / "w.manifest.json").write_text("{not json")
    t = WitnessTools(allow=[tmp_path], out_root=tmp_path / "out", use_cli=False, request_timeout=60)
    r = t.check(str(w))
    assert r["verified"] is False and r["error"]["kind"] == "witness" and "manifest" in r["error"]["message"]
    slow = WitnessTools(allow=[tmp_path], out_root=tmp_path / "out", use_cli=False, request_timeout=0.05)
    r = slow.check(str(w))
    assert r["verified"] is False and r["error"]["kind"] == "timeout"


@pytest.mark.skipif(not hasattr(__import__("os"), "killpg"), reason="process groups are POSIX")
def test_request_kill_reaches_the_grandchild(tmp_path):
    """A timed-out request killed only its worker; the isolate trial child it had spawned kept running."""
    import os
    import subprocess
    import sys
    import time

    from witness.mcp_server import _kill_group

    pidfile = tmp_path / "grandchild.pid"
    code = (
        "import os, subprocess, sys, time; os.setsid(); "
        "c = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']); "
        f"open({str(pidfile)!r}, 'w').write(str(c.pid)); time.sleep(60)"
    )
    worker = subprocess.Popen([sys.executable, "-c", code])
    for _ in range(100):
        if pidfile.exists() and pidfile.read_text():
            break
        time.sleep(0.05)
    grandchild = int(pidfile.read_text())

    class Proc:  # the multiprocessing.Process surface _kill_group uses
        pid = worker.pid

        def is_alive(self):
            return worker.poll() is None

        def kill(self):
            worker.kill()

    _kill_group(Proc())
    worker.wait(5)
    for _ in range(100):
        try:
            os.kill(grandchild, 0)
        except ProcessLookupError:
            break
        try:
            os.waitpid(grandchild, os.WNOHANG)
        except ChildProcessError:
            pass
        time.sleep(0.05)
    else:
        pytest.fail("grandchild survived the request kill")
