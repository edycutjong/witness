"""`python -m witness`: the module entry point, run for real and in-process."""

import os
import runpy
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
ENV = {**os.environ, "DO_NOT_TRACK": "1"}


def test_python_dash_m_witness_prints_the_version_and_exits_zero():
    p = subprocess.run([sys.executable, "-m", "witness", "--version"], capture_output=True, text=True, env=ENV)
    assert p.returncode == 0, p.stderr
    assert p.stdout.startswith("witness ") and "relate-db" in p.stdout


def test_python_dash_m_witness_turns_a_refusal_into_exit_code_2(tmp_path):
    p = subprocess.run(
        [sys.executable, "-m", "witness", "why", "-f", str(tmp_path / "missing.cypher")],
        capture_output=True,
        text=True,
        env=ENV,
        cwd=str(tmp_path),
    )
    assert p.returncode == 2
    assert "refused (query): query file not found" in p.stderr and p.stdout == ""


def test_the_entry_point_exits_with_the_exit_code_main_returns(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["witness", "--version"])
    with pytest.raises(SystemExit) as e:
        runpy.run_module("witness", run_name="__main__")
    assert e.value.code == 0
    assert "relate-db" in capsys.readouterr().out


def test_the_entry_point_propagates_a_nonzero_code(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(sys, "argv", ["witness", "why", "-f", str(tmp_path / "nope.cypher")])
    with pytest.raises(SystemExit) as e:
        runpy.run_module("witness", run_name="__main__")
    assert e.value.code == 2
    assert "query file not found" in capsys.readouterr().err
