"""Fixture mode (W4): `relate pull` a slice from Neo4j, shrink it to the smallest fixture a test still needs."""

import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path

import pytest

from witness.cli import main

ROOT = Path(__file__).resolve().parent.parent
CREDS = Path.home() / ".config" / "witness" / "neo4j.env"
EXPECT = ROOT / "fixtures" / "mex-foreign.expected.json"


def _neo4j_up() -> bool:
    if not CREDS.is_file():
        return False
    uri = dict(ln.split("=", 1) for ln in CREDS.read_text().splitlines() if "=" in ln).get("NEO4J_URI", "")
    try:
        urllib.request.urlopen(uri, timeout=2)
        return True
    except Exception:
        return False


needs_neo4j = pytest.mark.skipif(not _neo4j_up(), reason="local Neo4j (Docker) is not running")


def test_committed_fixture_test_passes_offline():
    """The committed fixture needs no Neo4j: its own generated test passes on the committed .rl."""
    env = {**os.environ, "DO_NOT_TRACK": "1"}
    p = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", str(ROOT / "fixtures" / "test_mex_foreign.py")],
        capture_output=True, text=True, env=env, cwd=str(ROOT),
    )
    assert p.returncode == 0, p.stdout + p.stderr
    assert "[100%]" in p.stdout and "F" not in p.stdout.split("[100%]")[0]


def test_committed_fixture_is_deletion_minimal_report():
    rep = json.loads((ROOT / "fixtures" / "mex-foreign.report.json").read_text())
    assert rep["never_pushed"] is True and rep["verified"] is True
    assert rep["fixture"]["relationships"] < rep["slice"]["relationships"]
    assert rep["check"].startswith(f"{rep['fixture']['relationships']} of {rep['fixture']['relationships']} change the answer")
    assert "/Users/" not in json.dumps(rep) and "/var/folders" not in json.dumps(rep)


def test_missing_credentials_refused(tmp_path, capsys):
    rc = main(["fixture", "--from", str(tmp_path / "nope.env"), "--pull", str(ROOT / "queries/fixture-slice.cypher"),
               "--test", str(ROOT / "queries/fixture-test.cypher"), "--expect", "[]", "--out", str(tmp_path)])
    assert rc == 2
    assert "credentials file not found" in capsys.readouterr().err


def test_bad_expect_refused(tmp_path, capsys):
    rc = main(["fixture", "--from", str(CREDS), "--pull", str(ROOT / "queries/fixture-slice.cypher"),
               "--test", str(ROOT / "queries/fixture-test.cypher"), "--expect", "{not json", "--out", str(tmp_path)])
    assert rc == 2
    assert "--expect" in capsys.readouterr().err


@needs_neo4j
def test_live_pull_and_shrink(tmp_path, capsys):
    rc = main(["fixture", "--from", str(CREDS), "--pull", str(ROOT / "queries/fixture-slice.cypher"),
               "--test", str(ROOT / "queries/fixture-test.cypher"), "--expect", str(EXPECT),
               "--name", "t", "--out", str(tmp_path)])
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "VERIFIED" in out and "nothing pushed" in out
    rep = json.loads((tmp_path / "t.report.json").read_text())
    assert rep["fixture"]["relationships"] < rep["slice"]["relationships"]


@needs_neo4j
def test_wrong_expectation_writes_nothing(tmp_path, capsys):
    rc = main(["fixture", "--from", str(CREDS), "--pull", str(ROOT / "queries/fixture-slice.cypher"),
               "--test", str(ROOT / "queries/fixture-test.cypher"),
               "--expect", '[{"foreign_airports": 1, "countries": ["ZZ"]}]', "--name", "bad", "--out", str(tmp_path)])
    assert rc == 2
    assert "Nothing was written" in capsys.readouterr().err
    assert not (tmp_path / "bad.rl").exists()
