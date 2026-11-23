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


@pytest.mark.parametrize(
    "script",
    [
        "CREATE (n0:`A`) WITH 1 AS x LOAD CSV FROM 'file:///etc/hosts' AS r CREATE (:`B` {`v`: r[0]})",
        "CREATE (n0:`A`);\nMATCH (n) DETACH DELETE n",
        "MATCH (n) RETURN n",
        "CREATE (n0:`A` {`v`: $secret})",
        # a2a arch r2: calls in map values, namespaced clocks, constructors without a literal argument
        "CREATE (n0:`N` {p: rand()})",
        "CREATE (n0:`N` {p: datetime.realtime()})",
        "CREATE (n0:`N` {p: datetime()})",
        "CREATE (n0:`N` {p: range(1, 1000000000)})",
        "CREATE (n0:`N` {p: date(toString(1))})",
    ],
)
def test_check_refuses_a_hand_edited_witness_script(script, tiny_rl, tmp_path):
    from witness.check import check, spec_from_args

    w = tmp_path / "w.rl"
    shutil.copyfile(tiny_rl, w)
    (tmp_path / "w.cypher").write_text("// header\n" + script + "\n")
    spec = spec_from_args("MATCH (n:P) RETURN n.name AS n", {}, '[{"n": "A"}]')
    with pytest.raises(Refused, match="witness .cypher"):
        check(w, spec, use_cli=False)


def test_check_text_counts_nothing_when_w_does_not_reproduce_the_answer():
    from witness.check import CheckResult

    probes = [{"i": 1, "kind": "rel", "element": "x", "necessary": True}]
    assert CheckResult(sufficient=False, probes=probes).text.startswith("NOT SUFFICIENT")
    assert CheckResult(sufficient=True, probes=probes).text.startswith("1 of 1 change the answer")


def test_loose_differs_says_what_a_necessary_element_does(tiny_rl):
    from witness.check import CheckSpec
    from witness.predicates import Predicate

    p = Predicate("differs", [], (("x", 1),), expected=(("x", 2),), loose=True)
    assert p.change_phrase == "end the mismatch"
    assert CheckSpec([], "differs", "", None, True).change_phrase == "end the mismatch"


def test_order_check_replays_backtick_names(tmp_path):
    import relate

    from witness.store import Scratch, replay

    src = tmp_path / "bt.rl"
    db = relate.Database(str(src))
    db.execute("CREATE (:`We``ird` {k: 1})-[:`RE``L`]->(:B {k: 2})")
    db.close()
    sc = Scratch.open_copy(src, tmp_path)
    mem = replay(sc, reverse=True)
    try:
        assert mem.execute("MATCH (:`We``ird`)-[r:`RE``L`]->(:B) RETURN count(r) AS c").data == [{"c": 1}]
    finally:
        mem.close()
        sc.close()


def test_a_time_cap_that_never_fired_keeps_the_determinism_claim(tiny_rl, tmp_path):
    q = "MATCH (a:P {name: 'A'})-[:R]->(h)-[:R]->(d:P {name: 'D'}) RETURN h.name AS hub"
    o = reduce_request(
        Request(
            source=tiny_rl,
            statement=q,
            params={},
            name="w",
            out_dir=tmp_path / "o",
            ledger=None,
            use_cli=False,
            max_seconds=600,
        )
    )
    assert o.verified and o.manifest["determinism_claimed"]


def test_mcp_override_is_compared_the_way_the_witness_was():
    from witness.mcp_server import override_spec

    m = {
        "baseline": {"rows": [{"x": [1, 2]}], "sha256": "abc"},
        "comparison": {"strict_lists": True, "float_digits": 6},
    }
    s = override_spec(m, "MATCH (n:P) RETURN [1, 2] AS x", {})
    assert (s.strict_lists, s.digits) == (True, 6)


def test_a_value_with_no_canonical_form_is_refused_not_hashed():
    from witness.canon import canon_value

    with pytest.raises(ValueError, match="no canonical form"):
        canon_value(object())


def test_minus_zero_is_zero_in_answers_but_not_in_element_keys():
    from witness.canon import node_key

    assert same_answer(canon_rows([{"x": -0.0}]), canon_rows([{"x": 0.0}]))
    assert node_key(["A"], {"x": -0.0}) != node_key(["A"], {"x": 0.0})


def test_export_that_loses_an_element_stops_the_run(tiny_rl, tmp_path, monkeypatch):
    import witness.pipeline as pl

    real = pl.write_rl

    def lossy(script, path):  # drop the last CREATE element
        head, _, _ = script.rstrip().rstrip(";").rpartition(",\n")
        return real(head + ";\n", path)

    monkeypatch.setattr(pl, "write_rl", lossy)
    q = "MATCH (a:P {name: 'A'})-[:R]->(h)-[:R]->(d:P {name: 'D'}) RETURN h.name AS hub"
    with pytest.raises(RuntimeError, match="export changed the witness"):
        reduce_request(
            Request(
                source=tiny_rl, statement=q, params={}, name="w", out_dir=tmp_path / "o", ledger=None, use_cli=False
            )
        )


def test_residue_counts_are_checked_after_every_rollback_by_default(tiny_rl):
    import inspect

    from witness.reduce import Reducer

    assert inspect.signature(Reducer).parameters["check_every"].default == 1


def test_cut_column_with_a_backtick_in_its_name():
    from witness.guard import static_checks

    gq = static_checks("MATCH (n:P) RETURN n.name AS `a``b` ORDER BY `a``b` LIMIT 1")
    assert gq.cut.order_cols == ["a`b"]


def test_outputs_never_overwrite_each_other(tiny_rl, tmp_path):
    """`--name ledger` made the witness the ledger's own file; a symlink x.html -> x.rl overwrote the witness."""
    q = "MATCH (a:P {name: 'A'})-[:R]->(h)-[:R]->(d:P {name: 'D'}) RETURN h.name AS hub"
    out = tmp_path / "out"
    with pytest.raises(Refused, match="same file"):
        reduce_request(
            Request(source=tiny_rl, statement=q, params={}, name="ledger", out_dir=out, ledger=out / "ledger.rl")
        )
    out.mkdir()
    (out / "x.html").symlink_to(out / "x.rl")
    with pytest.raises(Refused, match="same file"):
        reduce_request(
            Request(source=tiny_rl, statement=q, params={}, name="x", out_dir=out, ledger=None, use_cli=False)
        )


def test_cli_params_keep_json_shaped_strings():
    from witness.check import cli_param_args

    args = cli_param_args({"a": "MX", "b": '"MX"', "c": "true", "d": "", "e": " x", "f": 3})
    assert args == [
        "--param",
        "a=MX",
        "--param",
        'b="\\"MX\\""',
        "--param",
        'c="true"',
        "--param",
        'd=""',
        "--param",
        'e=" x"',
        "--param",
        "f=3",
    ]


@pytest.mark.parametrize("stmt", ["DROP INDEX witness_probe", "SHOW INDEXES", "START DATABASE x", "GRANT ROLE r TO u"])
def test_administrative_commands_are_refused_statically(stmt):
    from witness.guard import static_checks

    with pytest.raises(Refused, match="administrative"):
        static_checks(stmt)
    static_checks("MATCH (start:P)-[:R]->(stop) RETURN start.name AS s, stop.name AS t")  # still legal variable names


def test_names_with_control_characters_are_refused_before_reduction(tmp_path):
    import relate

    src = tmp_path / "ctl.rl"
    db = relate.Database(str(src))
    db.execute("CREATE (:`a\nb` {k: 1})-[:R]->(:B {k: 2})")
    db.close()
    with pytest.raises(Refused, match="control character"):
        reduce_request(
            Request(
                source=src,
                statement="MATCH (b:B) RETURN b.k AS k",
                params={},
                name="w",
                out_dir=tmp_path / "o",
                ledger=None,
                use_cli=False,
            )
        )


def test_mcp_reply_receive_has_a_deadline():
    """poll() fired on a frame header; recv() then blocked on a body that never came."""
    import multiprocessing as mp
    import os
    import struct

    from witness.mcp_server import _recv_within

    parent, child = mp.Pipe()
    os.write(child.fileno(), struct.pack("!i", 100))  # a frame header promising 100 bytes, then nothing
    assert parent.poll(1)
    with pytest.raises(TimeoutError):
        _recv_within(parent, 0.3)
    child.close()


def test_partial_temporal_maps_relate_accepts_are_fixed_values():
    """a2a r2 (grok P0, rejected with these values): Relate 1.0.1 refuses a date-bearing map without `year`, and
    time-only maps are fixed values, so the map rule reads no clock. Pinned: a later Relate must keep this."""
    import time

    import relate

    from witness.guard import static_checks

    db = relate.Database(":memory:")
    qs = ["RETURN time({hour: 1}) AS t", "RETURN localtime({hour: 1}) AS t", "RETURN datetime({epochSeconds: 5}) AS t"]
    first = [db.execute(q).data for q in qs]
    time.sleep(1.1)
    assert [db.execute(q).data for q in qs] == first
    for q in qs:
        static_checks(q)
    for q in ["RETURN datetime({hour: 1}) AS t", "RETURN date({day: 1}) AS t"]:
        with pytest.raises(Exception, match="year must be specified"):
            db.execute(q)


def test_check_sentence_is_bare_only_when_verified():
    from witness.check import CheckResult

    probes = [{"i": 1, "kind": "rel", "element": "x", "necessary": True}]
    r = CheckResult(sufficient=True, probes=probes, disagreements=["W.rl and W.cypher hold different graphs"])
    assert not r.verified and r.text.startswith("NOT VERIFIED: 1 of 1 change the answer")
    assert CheckResult(sufficient=True, probes=[]).text.startswith("NOT VERIFIED: 0 of 0")
    two = probes + [{"i": 2, "kind": "rel", "element": "y", "necessary": False}]
    assert CheckResult(sufficient=True, probes=two).text.startswith("NOT VERIFIED: 1 of 2")
    assert CheckResult(sufficient=True, probes=probes).verified


def test_plugin_namespaces_are_refused_statically():
    from pathlib import Path

    from witness.guard import static_checks

    for q in ["RETURN apoc.load.json('http://x') AS j", "RETURN gds.version() AS v", "RETURN dbms.components() AS c"]:
        with pytest.raises(Refused, match="namespace"):
            static_checks(q)
    root = Path(__file__).parents[1]
    static_checks((root / "queries" / "two-hub.cypher").read_text(), {"country": "MX", "dest": "MEX"})  # coll.sort


def test_vector_properties_and_c1_controls_round_trip(tmp_path):
    import relate

    from witness.export import _lit, cypher_script, validate_witness_script, write_rl
    from witness.store import Scratch

    src = tmp_path / "v.rl"
    db = relate.Database(str(src))
    db.execute("CREATE (:V {v: vector([1.0, 2.5], 2, FLOAT32), s: $s})", {"s": "a\x90b\x9fc"})
    db.close()
    sc = Scratch.open_copy(src, tmp_path)
    script = cypher_script(sc)
    keys = set(sc.node_keys.values())
    sc.close()
    validate_witness_script(script)
    write_rl(script, tmp_path / "re.rl")
    sc2 = Scratch.open_copy(tmp_path / "re.rl", tmp_path)
    try:
        assert set(sc2.node_keys.values()) == keys
    finally:
        sc2.close()
    assert "\\u0090" in _lit("a\x90b")


def test_mcp_evidence_line_says_what_the_predicate_kept():
    from witness.mcp_server import evidence_markdown

    res = {
        "answer": {"columns": ["x"], "rows": [{"x": 1}]},
        "witness": {"relationships": 2},
        "check": {"check_text": "2 of 2 end the disagreement (2 of 2 relationships, 0 of 0 isolated nodes)"},
        "source_relationships": 10,
        "verified": True,
        "exhibits": [],
        "files": {"rl": "w.rl"},
        "relate_version": "1.0.1",
    }
    text = evidence_markdown(res)
    assert "keep the two queries disagreeing" in text and "reproduce it" not in text


def test_manifest_rows_render_graph_values_by_content_not_store_id():
    import relate

    from witness.check import plain

    db = relate.Database(":memory:")
    db.execute("CREATE (:P {name: 'A'})-[:R {w: 1}]->(:P {name: 'B'})")
    row = db.execute("MATCH p = (a:P)-[r:R]->(b) RETURN a, r, p").data[0]
    out = plain(row)
    assert out["a"] == {"labels": ["P"], "properties": {"name": "A"}}
    assert out["r"] == {"type": "R", "properties": {"w": 1}}
    assert "id=" not in repr(out)


def test_mcp_override_works_on_a_graph_valued_witness(tmp_path):
    """The override re-parsed display rows: a witness whose answer holds nodes could never pass its own query."""
    import json

    import relate

    from witness.check import check
    from witness.mcp_server import override_spec

    src = tmp_path / "g.rl"
    db = relate.Database(str(src))
    db.execute("CREATE (:P {name: 'A'})-[:R]->(:P {name: 'B'}), (:P {name: 'C'})-[:R]->(:P {name: 'D'})")
    db.close()
    q = "MATCH (a:P {name: 'A'})-[:R]->(b) RETURN b"
    o = reduce_request(
        Request(source=src, statement=q, params={}, name="w", out_dir=tmp_path / "o", ledger=None, use_cli=False)
    )
    assert o.verified
    manifest = json.loads(open(o.files["manifest"]).read())
    res = check(o.files["rl"], override_spec(manifest, q, {}), use_cli=False)
    assert res.verified, res.text
    other = check(o.files["rl"], override_spec(manifest, "MATCH (b:P {name: 'X'}) RETURN b", {}), use_cli=False)
    assert not other.verified and other.text.startswith("NOT SUFFICIENT")


def test_unverified_evidence_line_does_not_claim_reproduction():
    from witness.mcp_server import evidence_markdown

    res = {
        "answer": {"columns": ["x"], "rows": [{"x": 1}]},
        "witness": {"relationships": 2},
        "check": {"check_text": "NOT SUFFICIENT: W does not reproduce the answer; 2 necessity probes not counted"},
        "source_relationships": 10,
        "verified": False,
        "reasons": ["the predicate does not hold on W"],
        "warnings": [],
        "exhibits": [],
        "files": {"rl": "w.rl"},
        "relate_version": "1.0.1",
    }
    text = evidence_markdown(res)
    assert "reproduce it" not in text and "NOT SUFFICIENT" in text and "NOT verified" in text
