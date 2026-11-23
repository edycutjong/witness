"""`witness check`: re-proves a witness from its files alone; tampering and missing pieces print NOT verified."""

import json
import shutil
from pathlib import Path

import pytest
import relate

from witness.check import check, cli_param_args, relate_cli, spec_from_manifest
from witness.cli import main
from witness.guard import Refused
from witness.pipeline import Request, reduce_request

NAMES = "MATCH (a:P {name: 'A'})-[:R]->(h)-[:R]->(:P {name: 'D'}) RETURN h.name AS hub"


@pytest.fixture
def reduced(tiny_rl, tmp_path):
    o = reduce_request(
        Request(
            source=Path(tiny_rl),
            statement=NAMES,
            params={},
            out_dir=tmp_path / "out",
            ledger=None,
            use_cli=False,
            name="w",
        )
    )
    assert o.verified
    return o


def test_check_passes_from_the_files(reduced):
    spec = spec_from_manifest(json.loads(Path(reduced.files["manifest"]).read_text()))
    res = check(reduced.files["rl"], spec, use_cli=False)
    assert res.verified and res.text.startswith("4 of 4 change the answer")


def test_a_padded_witness_is_not_verified(reduced, tmp_path):
    """Add one unneeded relationship to W: sufficiency still holds, but one probe is NOT needed."""
    w = tmp_path / "padded.rl"
    shutil.copyfile(reduced.files["rl"], w)
    db = relate.Database(str(w))
    db.execute("MATCH (a:P {name: 'A'}) CREATE (a)-[:R]->(:P {name: 'Extra'})")
    db.close()
    Path(str(w)[:-3] + ".cypher").write_text(Path(reduced.files["cypher"]).read_text() + "\n// padded\n")
    shutil.copyfile(reduced.files["manifest"], str(w)[:-3] + ".manifest.json")
    spec = spec_from_manifest(json.loads(Path(reduced.files["manifest"]).read_text()))
    res = check(w, spec, use_cli=False)
    assert res.sufficient and res.necessary == 4 and len(res.probes) == 5 and not res.verified
    assert "W.rl and W.cypher hold different graphs" in res.disagreements  # the .cypher was not padded


def test_no_cli_path_still_verifies(reduced, monkeypatch, capsys):
    monkeypatch.setenv("WITNESS_RELATE_BIN", "/nonexistent/relate")
    assert relate_cli()[0] is None
    assert main(["check", reduced.files["rl"]]) == 0
    out = capsys.readouterr().out
    assert "CLI cross-check skipped" in out and "VERIFIED" in out and "cross-checked" not in out


def test_require_cli_makes_a_missing_cli_an_error(reduced, monkeypatch):
    monkeypatch.setenv("WITNESS_RELATE_BIN", "/nonexistent/relate")
    assert main(["check", reduced.files["rl"], "--require-cli"]) == 1


def test_check_without_manifest_needs_explicit_inputs(reduced, tmp_path, capsys):
    w = tmp_path / "bare.rl"
    shutil.copyfile(reduced.files["rl"], w)
    shutil.copyfile(reduced.files["cypher"], tmp_path / "bare.cypher")
    assert main(["check", str(w), "--no-cli"]) == 2
    q = tmp_path / "q.cypher"
    q.write_text(NAMES)
    expect = json.dumps([{"hub": "B"}, {"hub": "C"}])
    assert main(["check", str(w), "-f", str(q), "--expect", expect, "--no-cli"]) == 0
    assert main(["check", str(w), "-f", str(q), "--expect", json.dumps([{"hub": "B"}]), "--no-cli"]) == 1
    with pytest.raises(Refused):
        from witness.check import spec_from_args

        spec_from_args(NAMES, {}, None)


def test_cli_param_args():
    assert cli_param_args({"country": "MX", "n": 3, "s": "123", "xs": [1]}) == [
        "--param",
        "country=MX",
        "--param",
        "n=3",
        "--param",
        's="123"',
        "--param",
        "xs=[1]",
    ]


@pytest.mark.skipif(relate_cli()[0] is None, reason="pinned relate CLI not on PATH")
def test_cli_surface_cross_checks_every_probe(reduced):
    spec = spec_from_manifest(json.loads(Path(reduced.files["manifest"]).read_text()))
    res = check(reduced.files["rl"], spec, use_cli=True, require_cli=True)
    assert res.verified and res.cli_used
    assert "4 of 4 necessity probes cross-checked" in res.cli_status
    assert all(p["cli_necessary"] is True for p in res.probes)


def test_an_empty_witness_is_never_verified(tmp_path):
    w = tmp_path / "empty.rl"
    db = relate.Database(str(w))
    db.close()
    (tmp_path / "empty.cypher").write_text("")
    from witness.check import spec_from_args

    res = check(w, spec_from_args("RETURN 1 AS one", {}, '[{"one": 1}]'), use_cli=False)
    assert res.sufficient is True and res.probes == [] and not res.verified


def test_exhibits_header_does_not_claim_necessity_when_not_verified(tiny_rl, tmp_path, capsys):
    q = tmp_path / "hubs.cypher"
    q.write_text(NAMES)
    out = tmp_path / "out"
    assert main(["why", "-f", str(q), "--store", str(tiny_rl), "--out", str(out), "--no-cli", "--max-trials", "3"]) == 3
    text = capsys.readouterr().out
    assert "necessity NOT verified" in text and "every one is needed" not in text
