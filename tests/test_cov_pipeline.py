"""One reduction end to end: refusals before anything is written, caps, a moving source, inconclusive trials."""

import json
import platform
import sys
from pathlib import Path

import pytest
import relate

from witness import pipeline
from witness.guard import Refused
from witness.pipeline import EXIT_CAP, EXIT_NOT_VERIFIED, Request, python_line, reduce_request, relate_version

HUBS = "MATCH (a:P {name: 'A'})-[:R]->(h)-[:R]->(:P {name: 'D'}) RETURN count(DISTINCT h) AS hubs"
NAMES = "MATCH (a:P {name: 'A'})-[:R]->(h)-[:R]->(:P {name: 'D'}) RETURN h.name AS hub"


def req(source, tmp_path, statement=NAMES, **kw):
    return Request(
        source=Path(source),
        statement=statement,
        params=kw.pop("params", {}),
        out_dir=tmp_path / "out",
        ledger=kw.pop("ledger", None),
        use_cli=False,
        name=kw.pop("name", "w"),
        **kw,
    )


def make_rl(tmp_path, script, name="g.rl"):
    path = tmp_path / name
    db = relate.Database(str(path))
    db.execute(script)
    db.close()
    return path


def test_the_relate_version_is_unknown_when_the_package_does_not_say(monkeypatch):
    assert relate_version() == relate.__version__
    monkeypatch.delattr(relate, "__version__")
    assert relate_version() == "unknown"


def test_python_line_names_the_interpreter_and_platform():
    assert python_line() == f"Python {platform.python_version()} ({sys.platform})"


def test_two_content_identical_nodes_are_refused_before_anything_is_written(tmp_path):
    src = make_rl(tmp_path, "CREATE (:P {name: 'same'}), (:P {name: 'same'})")
    with pytest.raises(Refused, match=r"content-identical nodes; Witness needs distinguishable elements") as e:
        reduce_request(req(src, tmp_path, "MATCH (n:P) RETURN n.name AS x"))
    assert e.value.door == "store" and not (tmp_path / "out").exists()


def test_disagree_without_a_second_statement_is_refused(tiny_rl, tmp_path):
    with pytest.raises(Refused, match="disagree needs --other") as e:
        reduce_request(req(tiny_rl, tmp_path, HUBS, predicate="disagree"))
    assert e.value.door == "predicate" and not (tmp_path / "out").exists()


def test_an_answer_that_cannot_be_compared_is_refused_with_its_reason(tiny_rl, tmp_path):
    """`ORDER BY n` passes the engine but sorts by a column the query does not return, so the cut cannot be applied."""
    with pytest.raises(Refused, match="the answer cannot be compared: refused .*not returned: \\['n'\\]"):
        reduce_request(req(tiny_rl, tmp_path, "MATCH (n:P) RETURN n.name AS x ORDER BY n LIMIT 1"))


def test_a_run_capped_before_its_first_trial_is_exit_3_with_no_timing_figures(tiny_rl, tmp_path):
    o = reduce_request(req(tiny_rl, tmp_path, max_trials=0))
    assert o.exit_code == EXIT_CAP and not o.verified
    assert o.run["capped"] == "trial cap 0 reached" and o.run["trials"] == 0
    assert "trial_ms_p50" not in o.run and "trial_ms_p95" not in o.run
    assert o.run["final_counts"] == (5, 6)  # nothing was removed
    assert o.reasons[0].startswith("trial cap 0 reached: reduced to 6 relationships, deletion-minimality NOT verified")
    assert o.manifest["verified"] is False and o.manifest["determinism_claimed"] is False
    assert o.check.reasons == ["necessity not checked (partial witness from a capped run)"]


def test_a_source_that_changes_during_the_run_is_an_error_not_a_witness(tiny_rl, tmp_path):
    def tamper(red, phase):
        if red.stats.trials == 1:
            with open(tiny_rl, "ab") as f:
                f.write(b"\0")

    with pytest.raises(RuntimeError, match="source store changed during the run"):
        reduce_request(req(tiny_rl, tmp_path), progress=tamper)


def test_a_query_whose_every_deletion_errors_ends_inconclusive_and_never_verified(tmp_path):
    """12 / (count - 1) divides by zero as soon as one of A's two edges goes: no deletion can be proven safe."""
    src = make_rl(tmp_path, "CREATE (a:P {name: 'A'}), (a)-[:R]->(:P {name: 'B'}), (a)-[:R]->(:P {name: 'C'})")
    q = "MATCH (:P {name: 'A'})-[:R]->(h) WITH count(h) AS c RETURN 12 / (c - 1) AS q"
    o = reduce_request(req(src, tmp_path, q))
    assert o.exit_code == EXIT_NOT_VERIFIED and not o.verified
    assert o.run["inconclusive"] > 0 and o.run["final_counts"] == (3, 2)
    assert o.check.inconclusive == 2
    assert "inconclusive: 2" in o.reasons and o.manifest["determinism_claimed"] is False
    manifest = json.loads(Path(o.files["manifest"]).read_text())
    assert manifest["verified"] is False and "inconclusive: 2" in manifest["reasons"]


@pytest.mark.parametrize("name", ["", ".", "..", "a/b", "a\\b", "a\nb", "a\x00b"])
def test_an_output_name_that_is_not_a_plain_file_stem_is_refused(tiny_rl, tmp_path, name):
    with pytest.raises(Refused, match="plain file stem") as e:
        reduce_request(req(tiny_rl, tmp_path, name=name))
    assert e.value.door == "out" and not (tmp_path / "out").exists()


def test_a_windows_drive_qualified_name_is_not_a_plain_stem_there(monkeypatch, tmp_path):
    """On Windows `C:evil` has no separator yet `Path('C:evil').name` is `evil`: the name must still be refused."""
    import pathlib

    monkeypatch.setattr(pipeline, "Path", pathlib.PureWindowsPath)
    r = Request(source=tmp_path / "s.rl", statement="RETURN 1 AS x", params={}, name="C:evil")
    with pytest.raises(Refused, match="plain file stem"):
        pipeline._refuse_aliased_outputs(r, tmp_path / "s.rl")


def test_a_checker_that_finds_a_deletable_element_makes_the_run_not_verified_and_says_how_many(
    tiny_rl, tmp_path, monkeypatch
):
    """The reducer proved every element necessary; if the independent check disagrees without saying why, the
    manifest must still explain the exit code (this state needs a reducer/checker inconsistency to occur)."""
    real_check = pipeline.check

    def checker_that_finds_slack(*a, **k):
        res = real_check(*a, **k)
        res.probes[0]["necessary"] = False
        return res

    monkeypatch.setattr(pipeline, "check", checker_that_finds_slack)
    o = reduce_request(req(tiny_rl, tmp_path))
    assert o.exit_code == EXIT_NOT_VERIFIED and not o.verified
    assert o.reasons == ["1 element(s) can be deleted without changing the answer"]
    assert o.manifest["verified"] is False and o.manifest["reasons"] == o.reasons
    assert o.check.text.startswith("NOT VERIFIED: 3 of 4 change the answer")
