"""cli.py: every command's refusal paths, output modes and entry points, driven through the real `main()`."""

import io
import json
import os
import runpy
import shutil
import subprocess
import sys
import types
from pathlib import Path

import pytest

from witness import cli
from witness.cli import Progress, _bindings, guard_write, main
from witness.guard import Refused

ROOT = Path(__file__).resolve().parent.parent
NAMES = "MATCH (a:P {name: 'A'})-[:R]->(h)-[:R]->(:P {name: 'D'}) RETURN h.name AS hub"
SCALAR = "MATCH (:P {name: 'A'})-[:R]->(h) RETURN count(h) AS n"
ENV = {**os.environ, "DO_NOT_TRACK": "1"}


@pytest.fixture
def hubs(tmp_path):
    q = tmp_path / "hubs.cypher"
    q.write_text(NAMES)
    return q


@pytest.fixture
def reduced(tiny_rl, hubs, tmp_path, capsys):
    """A real `why` run on the tiny graph: returns the out dir holding hubs.* and the ledger."""
    out = tmp_path / "out"
    assert main(["why", "-f", str(hubs), "--store", str(tiny_rl), "--out", str(out), "--no-cli"]) == 0
    capsys.readouterr()
    return out


# ---- parameters and helpers --------------------------------------------------------------------------------------
def test_a_param_without_an_equals_sign_is_refused(hubs, tiny_rl, capsys):
    assert main(["why", "-f", str(hubs), "--store", str(tiny_rl), "--param", "country"]) == 2
    assert "refused (param): --param needs k=v, got 'country'" in capsys.readouterr().err


def test_param_values_are_json_when_they_parse_and_bare_text_otherwise():
    assert cli.parse_params(["n=3", "l=[1, 2]", "s=MX", 'q="7"']) == {"n": 3, "l": [1, 2], "s": "MX", "q": "7"}
    assert cli.parse_params(None) == {}


class _Tty(io.StringIO):
    def isatty(self):
        return True


def test_progress_on_a_terminal_redraws_a_counter_throttled_and_clears_it_when_done():
    stream = _Tty()
    prog = Progress(stream)
    red = types.SimpleNamespace(counts=(5, 1234), stats=types.SimpleNamespace(trials=42))
    prog(red, "ddmin")
    first = stream.getvalue()
    assert "trial    42" in first and "1,234 relationships" in first and "phase ddmin" in first
    prog(red, "ddmin")  # inside the 50 ms window: nothing more is drawn
    assert stream.getvalue() == first
    prog.last = 0.0
    prog(red, "singles")
    assert "phase singles" in stream.getvalue()
    prog.done()
    assert stream.getvalue().endswith("\r" + " " * 92 + "\r")


def test_progress_is_silent_when_stderr_is_not_a_terminal():
    stream = io.StringIO()
    prog = Progress(stream)
    prog(types.SimpleNamespace(counts=(1, 1), stats=types.SimpleNamespace(trials=1)), "ddmin")
    prog.done()
    assert stream.getvalue() == ""


def test_update_lets_the_build_write_a_committed_path_and_nothing_else_does():
    target = ROOT / "witnesses" / "never-written.rl"
    guard_write(target, "--out", update=True)  # the build's own switch: allowed
    with pytest.raises(Refused, match="is a committed path"):
        guard_write(target, "--out")


# ---- why ---------------------------------------------------------------------------------------------------------
def test_why_json_prints_the_manifest_and_files_and_returns_the_exit_code(hubs, tiny_rl, tmp_path, capsys):
    out = tmp_path / "out"
    rc = main(["why", "-f", str(hubs), "--store", str(tiny_rl), "--out", str(out), "--no-cli", "--json"])
    doc = json.loads(capsys.readouterr().out)
    assert rc == 0 and doc["exit"] == 0
    assert doc["manifest"]["verified"] is True and doc["files"]["rl"].endswith("hubs.rl")
    assert doc["ledger_id"]


def test_why_warns_about_a_bare_scalar_answer_and_still_reports_the_ledger_id(tiny_rl, tmp_path, capsys):
    q = tmp_path / "scalar.cypher"
    q.write_text(SCALAR)
    rc = main(["why", "-f", str(q), "--store", str(tiny_rl), "--out", str(tmp_path / "o"), "--no-cli"])
    text = capsys.readouterr().out
    assert rc == 0
    assert "warning: a bare scalar answer" in text and "LEDGER  " in text


def test_why_with_no_ledger_writes_no_ledger_and_prints_no_ledger_line(hubs, tiny_rl, tmp_path, capsys):
    out = tmp_path / "o"
    assert main(["why", "-f", str(hubs), "--store", str(tiny_rl), "--out", str(out), "--no-cli", "--no-ledger"]) == 0
    assert "LEDGER" not in capsys.readouterr().out
    assert (out / "hubs.rl").exists() and not (out / "ledger.rl").exists()


def test_why_prints_a_not_verified_verdict_with_its_reasons_when_the_cap_stops_it(hubs, tiny_rl, tmp_path, capsys):
    rc = main(
        ["why", "-f", str(hubs), "--store", str(tiny_rl), "--out", str(tmp_path / "o"), "--no-cli", "--max-trials", "3"]
    )
    text = capsys.readouterr().out
    assert rc == 3
    assert "NOT verified" in text and "deletion-minimality NOT verified" in text
    assert "necessity probes inconclusive:" in text and "necessity NOT verified" in text


# ---- check -------------------------------------------------------------------------------------------------------
def test_check_of_a_missing_witness_is_refused(tmp_path, capsys):
    assert main(["check", str(tmp_path / "gone.rl")]) == 2
    assert "refused (check): witness not found" in capsys.readouterr().err


def test_check_without_a_manifest_or_a_query_says_what_to_pass(reduced, tmp_path, capsys):
    bare = tmp_path / "bare"
    bare.mkdir()
    shutil.copyfile(reduced / "hubs.rl", bare / "hubs.rl")
    assert main(["check", str(bare / "hubs.rl"), "--no-cli"]) == 2
    assert "no hubs.manifest.json beside hubs.rl: pass -f, --param and --expect" in capsys.readouterr().err


def test_check_json_reports_the_reproved_verdict_and_exits_zero(reduced, capsys):
    assert main(["check", str(reduced / "hubs.rl"), "--no-cli", "--json"]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["verified"] is True and doc["sufficient"] is True


def test_check_json_exits_one_when_the_witness_no_longer_gives_the_answer(reduced, hubs, capsys):
    rc = main(["check", str(reduced / "hubs.rl"), "--no-cli", "--json", "-f", str(hubs), "--expect", '[{"hub": "Z"}]'])
    doc = json.loads(capsys.readouterr().out)
    assert rc == 1 and doc["verified"] is False


# ---- fixture (argument handling; the pull itself is in test_cov_fixture) -----------------------------------------
def test_fixture_expect_must_be_a_list_or_an_object_with_rows(tmp_path, capsys):
    args = ["fixture", "--from", str(tmp_path / "c.env"), "--pull", "p", "--test", "t", "--out", str(tmp_path / "o")]
    assert main([*args, "--expect", "7"]) == 2
    assert "refused (expected): --expect must be a JSON list of row objects" in capsys.readouterr().err
    assert main([*args, "--expect", '{"rows": 7}']) == 2
    assert "must be a JSON list of row objects" in capsys.readouterr().err
    # a rows list gets past the expectation check and meets the next refusal: no credentials file
    assert main([*args, "--expect", '{"rows": []}']) == 2
    assert "credentials file not found" in capsys.readouterr().err


# ---- mcp ---------------------------------------------------------------------------------------------------------
def test_mcp_refuses_an_out_dir_that_is_a_committed_path_before_serving(capsys):
    assert main(["mcp", "--out", str(ROOT / "witnesses" / "agent")]) == 2
    assert "refused (out): --out " in capsys.readouterr().err


def test_mcp_refuses_a_ledger_that_is_the_committed_ledger(capsys):
    assert main(["mcp", "--no-cli", "--ledger", str(ROOT / "witness.rl")]) == 2
    assert "refused (out): --ledger " in capsys.readouterr().err


def test_mcp_passes_uncommitted_options_through_to_the_server(tmp_path, capsys):
    with pytest.raises(SystemExit) as e:  # the server's own --help: proves the options reached mcp_server.main
        main(["mcp", "--out", str(tmp_path / "o"), "--ledger", str(tmp_path / "l.rl"), "--help"])
    assert e.value.code == 0
    assert "witness mcp" in capsys.readouterr().out


def test_mcp_with_a_trailing_out_flag_and_no_value_is_left_to_the_server_to_reject(capsys):
    with pytest.raises(SystemExit) as e:
        main(["mcp", "--out"])
    assert e.value.code == 2
    assert "expected one argument" in capsys.readouterr().err


# ---- rerun -------------------------------------------------------------------------------------------------------
def test_rerun_print_cli_prints_the_equivalent_relate_command_without_opening_anything(tmp_path, hubs, capsys):
    rc = main(["rerun", str(tmp_path / "w.rl"), "-f", str(hubs), "--param", "n=3", "--param", "s=MX", "--print-cli"])
    out = capsys.readouterr().out.strip()
    assert rc == 0
    assert out.startswith("relate query --database ") and "--read-only" in out and out.endswith(f"< {hubs}")
    assert "n=3" in out and "s=MX" in out


def test_rerun_of_a_missing_witness_is_refused(tmp_path, hubs, capsys):
    assert main(["rerun", str(tmp_path / "gone.rl"), "-f", str(hubs)]) == 2
    assert "refused (rerun): witness not found" in capsys.readouterr().err


# ---- export ------------------------------------------------------------------------------------------------------
def test_export_of_an_out_directory_copies_its_single_witness(reduced, tmp_path, capsys):
    to = tmp_path / "exp"
    assert main(["export", str(reduced), "--to", str(to)]) == 0
    assert "EXPORT  5 files" in capsys.readouterr().out
    assert sorted(p.name for p in to.iterdir()) == [
        "hubs.cypher",
        "hubs.html",
        "hubs.manifest.json",
        "hubs.rl",
        "hubs.trace.json",
    ]


def test_export_of_a_directory_with_two_witnesses_needs_a_name(reduced, tiny_rl, tmp_path, capsys):
    other = tmp_path / "second.cypher"
    other.write_text(NAMES)
    assert main(["why", "-f", str(other), "--store", str(tiny_rl), "--out", str(reduced), "--no-cli"]) == 0
    capsys.readouterr()
    assert main(["export", str(reduced), "--to", str(tmp_path / "exp")]) == 2
    assert "2 manifests in" in capsys.readouterr().err and not (tmp_path / "exp").exists()
    assert main(["export", str(reduced), "--name", "second", "--to", str(tmp_path / "exp")]) == 0
    assert (tmp_path / "exp" / "second.rl").exists() and not (tmp_path / "exp" / "hubs.rl").exists()


def test_export_of_a_directory_without_any_manifest_is_refused(tmp_path, capsys):
    empty = tmp_path / "empty"
    empty.mkdir()
    assert main(["export", str(empty), "--to", str(tmp_path / "exp")]) == 2
    assert "0 manifests in" in capsys.readouterr().err


def test_export_of_an_id_without_a_ledger_is_refused(tmp_path, capsys):
    assert main(["export", "abc123", "--ledger", str(tmp_path / "none.rl"), "--to", str(tmp_path / "exp")]) == 2
    assert "not a .rl, a directory, or an id in" in capsys.readouterr().err


def test_export_of_an_unknown_id_names_the_ledger_it_searched(reduced, tmp_path, capsys):
    rc = main(["export", "no-such-id", "--ledger", str(reduced / "ledger.rl"), "--to", str(tmp_path / "exp")])
    assert rc == 2
    assert "no reduction 'no-such-id' in" in capsys.readouterr().err


def test_export_of_a_bare_rl_copies_only_the_files_that_exist(tiny_rl, tmp_path, capsys):
    to = tmp_path / "exp"
    assert main(["export", str(tiny_rl), "--to", str(to)]) == 0
    assert "EXPORT  1 files" in capsys.readouterr().out
    assert [p.name for p in to.iterdir()] == ["tiny.rl"]


def test_export_into_the_witnesss_own_directory_copies_nothing_and_still_lists_it(reduced, capsys):
    assert main(["export", str(reduced / "hubs.rl"), "--to", str(reduced)]) == 0
    assert "EXPORT  5 files" in capsys.readouterr().out


def test_export_of_a_manifest_whose_store_is_missing_is_refused(tmp_path, capsys):
    d = tmp_path / "half"
    d.mkdir()
    (d / "w.manifest.json").write_text("{}")
    assert main(["export", str(d), "--to", str(tmp_path / "exp")]) == 2
    assert "w.rl not found" in capsys.readouterr().err


# ---- review ------------------------------------------------------------------------------------------------------
def test_review_of_a_missing_ledger_is_refused(tmp_path, capsys):
    assert main(["review", "--ledger", str(tmp_path / "none.rl")]) == 2
    assert "refused (review): ledger not found" in capsys.readouterr().err


def test_review_dispute_records_the_reason(reduced, capsys):
    ledger = str(reduced / "ledger.rl")
    assert main(["review", "--ledger", ledger]) == 0
    rid = capsys.readouterr().out.splitlines()[1].split()[0]
    assert main(["review", rid, "--dispute", "wrong airport", "--ledger", ledger]) == 0
    assert f"REVIEW  {rid}: dispute — wrong airport" in capsys.readouterr().out
    assert main(["review", "--ledger", ledger]) == 0
    assert "UNREVIEWED  0 in" in capsys.readouterr().out


# ---- demo --------------------------------------------------------------------------------------------------------
def test_bindings_counts_the_matches_and_gives_up_quietly_on_a_refused_query(tiny_rl, hubs, tmp_path):
    assert _bindings(tiny_rl, hubs, {}) == 2
    bad = tmp_path / "bad.cypher"
    bad.write_text("CREATE (z:Z) RETURN z")
    assert _bindings(tiny_rl, bad, {}) is None


def test_demo_update_writes_the_committed_artifacts_of_the_checkout_it_runs_in(tmp_path, monkeypatch, capsys):
    """The build's `demo --update`, run in a throwaway checkout (the real data read through a symlink)."""
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "air-routes.rl").symlink_to(ROOT / "data" / "air-routes.rl")
    shutil.copyfile(ROOT / "data" / "source-stats.json", tmp_path / "data" / "source-stats.json")
    shutil.copytree(ROOT / "queries", tmp_path / "queries")
    monkeypatch.chdir(tmp_path)
    assert main(["demo", "--update", "--no-cli"]) == 0
    text = capsys.readouterr().out
    assert "UPDATED  witnesses · witness.rl · answers/two-hub.json" in text
    ans = json.loads((tmp_path / "answers" / "two-hub.json").read_text())
    assert [r["airport"] for r in ans["rows"]] == ["PBC", "QRO", "TLC", "UPN"]
    assert ans["query"] == "queries/two-hub.cypher" and len(ans["sha256"]) == 64
    man = json.loads((tmp_path / "witnesses" / "two-hub.manifest.json").read_text())
    assert man["verified"] is True and man["witness"]["relationships"] == 22
    assert (tmp_path / "witness.rl").exists()
    assert not (ROOT / "answers" / "never.json").exists()


class _Exited(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


def test_demo_watchdog_reports_where_the_partial_files_are_and_exits_4(tmp_path, monkeypatch, capsys):
    """The watchdog kills the process with os._exit, so this run swaps the timer for an immediate fire and os._exit for
    an exception. The same exit really happens in the subprocess test below."""

    class FiresAtOnce:
        def __init__(self, interval, fn):
            self.fn = fn

        daemon = False

        def start(self):
            self.fn()

        def cancel(self):
            raise AssertionError("the watchdog fired; nothing should cancel it")

    def fake_exit(code):
        raise _Exited(code)

    monkeypatch.chdir(ROOT)
    monkeypatch.setattr(cli.threading, "Timer", FiresAtOnce)
    monkeypatch.setattr(cli.os, "_exit", fake_exit)
    out = tmp_path / "out"
    with pytest.raises(_Exited) as e:
        main(["demo", "--no-cli", "--watchdog", "1.5", "--out", str(out)])
    assert e.value.code == 4
    err = capsys.readouterr().err
    assert "witness demo: aborted by the watchdog after 1.5 s" in err and "partial files in" in err


def test_demo_watchdog_really_kills_a_run_that_outlives_it_with_exit_4(tmp_path):
    p = subprocess.run(
        [sys.executable, "-m", "witness", "demo", "--no-cli", "--watchdog", "0.05", "--out", str(tmp_path / "o")],
        capture_output=True,
        text=True,
        env=ENV,
        cwd=str(ROOT),
        timeout=120,
    )
    assert p.returncode == 4, p.stdout + p.stderr
    assert "aborted by the watchdog after 0.05 s" in p.stderr


# ---- entry points ------------------------------------------------------------------------------------------------
def test_no_command_prints_the_help_and_exits_zero(capsys):
    assert main([]) == 0
    out = capsys.readouterr().out
    assert "usage: witness" in out and "demo" in out and "fixture" in out


@pytest.mark.filterwarnings("ignore::RuntimeWarning")
def test_running_the_module_as_a_script_exits_with_main_s_code(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["witness", "--version"])
    with pytest.raises(SystemExit) as e:
        runpy.run_module("witness.cli", run_name="__main__")
    assert e.value.code == 0
    assert "relate-db" in capsys.readouterr().out
