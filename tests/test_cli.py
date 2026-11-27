"""The CLI: demo (the judge path on the real graph), why, export, rerun, review, exit codes."""

import json
from pathlib import Path

from witness.cli import main

ROOT = Path(__file__).resolve().parent.parent
NAMES = "MATCH (a:P {name: 'A'})-[:R]->(h)-[:R]->(:P {name: 'D'}) RETURN h.name AS hub"


def test_version(capsys):
    assert main(["--version"]) == 0
    assert "relate-db" in capsys.readouterr().out


def test_demo_is_the_whole_judge_path(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(ROOT)
    out = tmp_path / "out"
    assert main(["demo", "--out", str(out), "--no-cli"]) == 0
    text = capsys.readouterr().out
    for needle in [
        "QUESTION  Which airports of MX have no direct flight to MEX",
        "ANSWER  4 rows on the full graph",
        "WITNESS  22 relationships · 12 nodes, out of 57,645 · 3,748",
        "68 relationships match the answer rows; 22 of them suffice",
        "EXHIBITS",
        "ABSENT  checked on the full graph, not part of the witness",
        "CHECK  22 of 22 change the answer",
        "PROVE ONE",
        "CHANGED: 4 rows → 3 rows",
        "RE-RUN IT YOURSELF",
        "VERIFIED",
    ]:
        assert needle in text, needle
    for suf in (".rl", ".cypher", ".manifest.json", ".html", ".trace.json"):
        assert (out / f"two-hub{suf}").stat().st_size > 0
    assert (out / "ledger.rl").exists()
    man = json.loads((out / "two-hub.manifest.json").read_text())
    assert man["verified"] and man["witness"]["relationships"] == 22 and man["determinism_claimed"]
    assert [r["airport"] for r in man["baseline"]["rows"]] == ["PBC", "QRO", "TLC", "UPN"]
    # Determinism beyond one machine: this fresh reduction must write the committed rebuild script byte for byte,
    # wherever the suite runs (CI: Linux x86_64, Python 3.11 and 3.12; the committed run: macOS arm64, Python 3.12).
    assert (out / "two-hub.cypher").read_bytes() == (ROOT / "witnesses" / "two-hub.cypher").read_bytes()


def test_why_export_rerun_review(tiny_rl, tmp_path, capsys):
    q = tmp_path / "hubs.cypher"
    q.write_text(NAMES)
    out = tmp_path / "out"
    assert main(["why", "-f", str(q), "--store", str(tiny_rl), "--out", str(out), "--no-cli"]) == 0
    assert (out / "hubs.rl").exists()
    capsys.readouterr()
    assert main(["review", "--ledger", str(out / "ledger.rl")]) == 0
    rid = capsys.readouterr().out.splitlines()[1].split()[0]
    assert main(["export", rid, "--ledger", str(out / "ledger.rl"), "--to", str(tmp_path / "exp")]) == 0
    assert sorted(p.name for p in (tmp_path / "exp").iterdir()) == [
        "hubs.cypher",
        "hubs.html",
        "hubs.manifest.json",
        "hubs.rl",
        "hubs.trace.json",
    ]
    assert main(["rerun", str(tmp_path / "exp" / "hubs.rl"), "-f", str(q)]) == 0
    assert "2 rows" in capsys.readouterr().out
    assert main(["review", rid, "--accept", "--ledger", str(out / "ledger.rl")]) == 0
    assert main(["review", rid, "--ledger", str(out / "ledger.rl")]) == 2  # neither --accept nor --dispute


def test_why_trial_cap_exits_3_and_still_writes_files(tiny_rl, tmp_path):
    q = tmp_path / "hubs.cypher"
    q.write_text(NAMES)
    out = tmp_path / "out"
    assert main(["why", "-f", str(q), "--store", str(tiny_rl), "--out", str(out), "--no-cli", "--max-trials", "3"]) == 3
    man = json.loads((out / "hubs.manifest.json").read_text())
    assert man["verified"] is False and "deletion-minimality NOT verified" in man["reasons"][0]


def test_missing_store_is_refused(tmp_path):
    q = tmp_path / "q.cypher"
    q.write_text(NAMES)
    assert main(["why", "-f", str(q), "--store", str(tmp_path / "nope.rl"), "--no-cli"]) == 2


def test_capped_run_on_the_full_graph_skips_necessity_and_stays_fast(tmp_path, monkeypatch):
    """A capped partial W can hold thousands of relationships: check sufficiency only, never probe each one."""
    import time

    monkeypatch.chdir(ROOT)
    t = time.perf_counter()
    rc = main(
        [
            "why",
            "-f",
            "queries/two-hub.cypher",
            "--param",
            "country=MX",
            "--param",
            "dest=MEX",
            "--strict-lists",
            "--max-trials",
            "5",
            "--out",
            str(tmp_path / "cap"),
            "--no-cli",
        ]
    )
    assert rc == 3 and time.perf_counter() - t < 60
    man = json.loads((tmp_path / "cap" / "two-hub.manifest.json").read_text())
    assert man["verified"] is False and man["check"]["probes"] == []
    assert any("necessity not checked" in r for r in man["reasons"])
