"""Fixture mode without a Neo4j: a stand-in `relate` executable answers `pull` by copying a prepared slice and hands
every other subcommand (`--version`, `query`, ...) to the REAL relate CLI, so the guard, the reducer, the check and the
generated test all run for real. Only the remote pull is faked: there is no Neo4j to pull from."""

import json
import os
import shutil
import subprocess
import sys

import pytest

from witness.cli import main
from witness.fixture import build_fixture, pull_slice, which_docker_note
from witness.guard import Refused

HUBS = "MATCH (a:P {name: 'A'})-[:R]->(h)-[:R]->(:P {name: 'D'}) RETURN h.name AS hub"
SLICE = "MATCH (a)-[r]->(b) RETURN a, r, b"
EXPECTED = [{"hub": "B"}, {"hub": "C"}]

STUB = """#!{python}
import json, os, shutil, sys

args = sys.argv[1:]
if args and args[0] == "pull":
    with open(os.environ["FAKE_PULL_LOG"], "a") as f:
        f.write(json.dumps(args) + "\\n")
    mode = os.environ.get("FAKE_PULL_MODE", "ok")
    if mode == "fail":
        sys.stderr.write("first line\\nconnection refused by neo4j\\n")
        sys.exit(3)
    if mode == "silent-fail":
        sys.exit(5)
    if mode == "no-file":
        print("pulled nothing")
        sys.exit(0)
    shutil.copyfile(os.environ["FAKE_PULL_SLICE"], args[args.index("--database") + 1])
    print("pull started")
    print("copied slice to " + args[args.index("--database") + 1])
    print("checkpoint")
    sys.exit(0)
os.execv("{real}", ["{real}"] + args)
"""


@pytest.fixture
def pull_env(tmp_path, tiny_rl, monkeypatch):
    """Put the stand-in relate first in WITNESS_RELATE_BIN; return its call log path."""
    stub = tmp_path / "bin" / "relate"
    stub.parent.mkdir()
    stub.write_text(STUB.format(python=sys.executable, real=shutil.which("relate")))
    stub.chmod(0o755)
    log = tmp_path / "pull.log"
    monkeypatch.setenv("WITNESS_RELATE_BIN", str(stub))
    monkeypatch.setenv("FAKE_PULL_LOG", str(log))
    monkeypatch.setenv("FAKE_PULL_SLICE", str(tiny_rl))
    monkeypatch.delenv("FAKE_PULL_MODE", raising=False)
    return log


@pytest.fixture
def files(tmp_path):
    creds = tmp_path / "neo4j.env"
    creds.write_text("NEO4J_URI=http://127.0.0.1:1\nNEO4J_USERNAME=u\nNEO4J_PASSWORD=p\nNEO4J_IMAGE=neo4j:5-test\n")
    pull = tmp_path / "slice.cypher"
    pull.write_text(SLICE)
    test = tmp_path / "hubs.cypher"
    test.write_text(HUBS)
    return creds, pull, test


def _argv(files, out, expect, *extra):
    creds, pull, test = files
    return [
        "fixture",
        "--from",
        str(creds),
        "--pull",
        str(pull),
        "--test",
        str(test),
        "--expect",
        expect,
        "--out",
        str(out),
        *extra,
    ]


def test_fixture_pulls_shrinks_and_writes_a_passing_pytest_file(files, pull_env, tmp_path, capsys):
    out = tmp_path / "fx"
    out.mkdir()
    rc = main(_argv(files, out, json.dumps({"rows": EXPECTED}), "--name", "hubs-fx"))
    text = capsys.readouterr().out
    assert rc == 0, text
    assert "PULLED   6 relationships · 5 nodes" in text and "nothing pushed" in text
    assert "VERIFIED" in text and "test_hubs_fx.py" in text
    rep = json.loads((out / "hubs-fx.report.json").read_text())
    assert rep["never_pushed"] is True and rep["verified"] is True
    assert rep["neo4j_image"] == "neo4j:5-test"
    assert rep["fixture"]["relationships"] < rep["slice"]["relationships"]
    assert rep["pull_tail"] == ["pull started", "copied slice to <slice.rl>", "checkpoint"]
    man = json.loads((out / "hubs-fx.manifest.json").read_text())
    assert man["source"]["path"] == "<slice.rl: temp store pulled from Neo4j>"
    assert "witness-fixture-" not in json.dumps(man)
    # the generated test is real: it passes on the fixture beside it, with no Neo4j
    p = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", str(out / "test_hubs_fx.py")],
        capture_output=True,
        text=True,
        env={**os.environ, "DO_NOT_TRACK": "1"},
    )
    assert p.returncode == 0, p.stdout + p.stderr
    pulls = [json.loads(ln) for ln in pull_env.read_text().splitlines()]
    assert len(pulls) == 1 and pulls[0][0] == "pull" and "--from" in pulls[0] and SLICE in pulls[0]


def test_fixture_expect_given_as_a_json_file_with_a_plain_list(files, pull_env, tmp_path, capsys):
    expect = tmp_path / "expected.json"
    expect.write_text(json.dumps(EXPECTED))
    out = tmp_path / "fx"
    out.mkdir()
    assert main(_argv(files, out, str(expect), "--name", "f")) == 0
    assert "VERIFIED" in capsys.readouterr().out


def test_fixture_refuses_an_expectation_that_is_not_a_list_of_rows(files, tmp_path, capsys):
    assert main(_argv(files, tmp_path / "fx", '{"hub": "B"}')) == 2
    err = capsys.readouterr().err
    assert "refused (expected)" in err and "must be a JSON list of row objects" in err
    assert not (tmp_path / "fx").exists()


def test_fixture_with_a_wrong_expectation_writes_nothing(files, pull_env, tmp_path, capsys):
    out = tmp_path / "fx"
    out.mkdir()
    assert main(_argv(files, out, '[{"hub": "ZZ"}]', "--name", "bad")) == 2
    assert "Nothing was written" in capsys.readouterr().err
    assert list(out.iterdir()) == []


def test_fixture_test_query_that_writes_is_refused_by_the_guard_not_reported_as_a_wrong_answer(
    files, pull_env, tmp_path, capsys
):
    creds, pull, test = files
    test.write_text("CREATE (z:Z) RETURN z")
    out = tmp_path / "fx"
    out.mkdir()
    assert main(_argv(files, out, json.dumps(EXPECTED), "--name", "w")) == 2
    err = capsys.readouterr().err
    assert err.startswith("refused (") and "Nothing was written" not in err
    assert list(out.iterdir()) == []


def test_fixture_fails_cleanly_when_the_pull_exits_nonzero(files, pull_env, tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("FAKE_PULL_MODE", "fail")
    assert main(_argv(files, tmp_path / "fx", json.dumps(EXPECTED))) == 2
    assert "relate pull failed (exit 3): connection refused by neo4j" in capsys.readouterr().err


def test_pull_failure_without_any_output_says_no_output(files, pull_env, tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_PULL_MODE", "silent-fail")
    with pytest.raises(Refused, match=r"relate pull failed \(exit 5\): no output"):
        pull_slice(files[0], SLICE, tmp_path / "s.rl")


def test_pull_that_exits_zero_but_creates_no_store_is_a_failure(files, pull_env, tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_PULL_MODE", "no-file")
    with pytest.raises(Refused, match=r"relate pull failed \(exit 0\): pulled nothing"):
        pull_slice(files[0], SLICE, tmp_path / "s.rl")


def test_pull_refuses_a_destination_that_already_exists(files, pull_env, tmp_path):
    dest = tmp_path / "s.rl"
    dest.write_text("occupied")
    with pytest.raises(Refused, match="pull refuses a non-empty destination"):
        pull_slice(files[0], SLICE, dest)
    assert dest.read_text() == "occupied" and not pull_env.exists()


def test_pull_passes_each_parameter_to_relate_as_text_or_json(files, pull_env, tmp_path):
    q = "MATCH (a)-[r]->(b) WHERE a.name = $s AND $n > 0 AND size($l) >= 0 RETURN a, r, b"
    pull_slice(files[0], q, tmp_path / "s.rl", {"s": "A", "n": 3, "l": [1, 2]})
    argv = json.loads(pull_env.read_text().splitlines()[0])
    pairs = [argv[i + 1] for i, a in enumerate(argv) if a == "--param"]
    assert pairs == ["s=A", "n=3", "l=[1, 2]"]


def test_pull_needs_the_relate_cli_and_says_why_when_it_is_missing(files, tmp_path, monkeypatch):
    monkeypatch.setenv("WITNESS_RELATE_BIN", str(tmp_path / "no-such-relate"))
    with pytest.raises(Refused, match="fixture mode needs the relate CLI for `relate pull`"):
        pull_slice(files[0], SLICE, tmp_path / "s.rl")


def test_build_fixture_returns_the_outcome_and_a_report_that_names_the_relate_versions(files, pull_env, tmp_path):
    out = tmp_path / "fx"
    out.mkdir()
    o, rep = build_fixture(
        creds=files[0],
        slice_query=SLICE,
        statement=HUBS,
        params={},
        expected=EXPECTED,
        name="b",
        out_dir=out,
    )
    assert o.verified and rep["check"].startswith(f"{rep['fixture']['relationships']} of ")
    assert rep["relate_cli"].startswith("relate CLI v") and rep["neo4j_image"] is None


def test_docker_note_follows_whether_docker_is_on_path(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", str(tmp_path))
    assert which_docker_note() == "no docker"
    exe = tmp_path / "docker"
    exe.write_text("#!/bin/sh\n")
    exe.chmod(0o755)
    assert which_docker_note() == "docker"


def test_pull_refuses_a_slice_that_names_a_file_instead_of_giving_statement_text(files, pull_env, tmp_path):
    # `relate pull --query` would read the file, so the guarded text and the pulled text could differ
    with pytest.raises(Refused, match="pass the slice statement text, not a file path"):
        pull_slice(files[0], str(files[1]), tmp_path / "s.rl")
    with pytest.raises(Refused, match="pass the slice statement text, not a file path"):
        pull_slice(files[0], "-", tmp_path / "s.rl")
    assert not pull_env.exists()


def test_a_slice_too_long_to_be_a_path_is_treated_as_statement_text(files, pull_env, tmp_path):
    long_slice = "MATCH (a)-[r]->(b) RETURN a, r, b //" + "x" * 5000
    got = pull_slice(files[0], long_slice, tmp_path / "s.rl")
    assert (tmp_path / "s.rl").exists() and got["cli"].startswith("relate CLI v")
