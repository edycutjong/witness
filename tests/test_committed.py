"""Sponsor depth 4: the committed headline witness is a single-file .rl that `witness check` re-proves from its
manifest, and that plain `relate` re-runs to the same answer (a separate assertion)."""

import json
import os
import subprocess
from pathlib import Path

import pytest

from witness.check import check, cli_param_args, relate_cli, spec_from_manifest

ROOT = Path(__file__).resolve().parent.parent
W = ROOT / "witnesses" / "two-hub.rl"


def manifest() -> dict:
    return json.loads((ROOT / "witnesses" / "two-hub.manifest.json").read_text())


def test_committed_witness_checks():
    m = manifest()
    assert m["verified"] and m["witness"]["relationships"] == 22
    res = check(W, spec_from_manifest(m), use_cli=False)
    assert res.verified and res.text.startswith("22 of 22 change the answer")


def test_committed_answer_matches_manifest():
    ans = json.loads((ROOT / "answers" / "two-hub.json").read_text())
    assert ans["sha256"] == manifest()["baseline"]["sha256"]
    assert [r["airport"] for r in ans["rows"]] == ["PBC", "QRO", "TLC", "UPN"]


def test_committed_ledger_has_the_reduction():
    from witness import ledger

    rows = ledger.read(
        ROOT / "witness.rl", "MATCH (r:Reduction)-[:PRODUCED]->(w:Witness) RETURN r.check_text AS t, w.path_rl AS p"
    )
    assert {
        "t": "22 of 22 change the answer (22 of 22 relationships, 0 of 0 isolated nodes)",
        "p": "witnesses/two-hub.rl",
    } in rows


@pytest.mark.skipif(relate_cli()[0] is None, reason="pinned relate CLI not on PATH")
def test_plain_relate_rerun_returns_the_same_answer():
    cli = relate_cli()[0]
    m = manifest()
    r = subprocess.run(
        [cli, "query", "--database", str(W), "--read-only", "--mode", "json", *cli_param_args(m["params"])],
        input=(ROOT / "queries" / "two-hub.cypher").read_text(),
        capture_output=True,
        text=True,
        timeout=60,
        env={**os.environ, "DO_NOT_TRACK": "1"},
    )
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout.splitlines()[0])["data"] == m["baseline"]["rows"]


# ---- the second committed example: two queries disagree (a2a judge r5) ------------------------------------------
DB = ROOT / "witnesses" / "direction-bug.rl"


def test_committed_disagreement_witness_checks():
    m = json.loads((ROOT / "witnesses" / "direction-bug.manifest.json").read_text())
    assert m["verified"] and m["witness"]["relationships"] == 5 and m["predicate"]["kind"] == "disagree"
    res = check(DB, spec_from_manifest(m), use_cli=False)
    assert res.verified and res.text.startswith("5 of 5 end the disagreement")


@pytest.mark.skipif(relate_cli()[0] is None, reason="pinned relate CLI not on PATH")
def test_plain_relate_shows_the_two_queries_disagree_on_the_witness():
    cli = relate_cli()[0]

    def rows(query: str) -> list:
        r = subprocess.run(
            [
                cli,
                "query",
                "--database",
                str(DB),
                "--read-only",
                "--mode",
                "json",
                *cli_param_args({"country": "IN", "dest": "DEL"}),
            ],
            input=(ROOT / "queries" / query).read_text(),
            capture_output=True,
            text=True,
            timeout=60,
            env={**os.environ, "DO_NOT_TRACK": "1"},
        )
        assert r.returncode == 0, r.stderr
        return json.loads(r.stdout.splitlines()[0])["data"]

    assert rows("two-hub-agent.cypher") == [
        {"airport": "AGR", "hub_countries": []}
    ]  # hub countries are not needed to disagree
    assert rows("two-hub.cypher") == []


# ---- the third committed example: a smaller repro of a wrong answer, `differs` (a2a judge r6) ----------------------
WA = ROOT / "witnesses" / "wrong-answer.rl"


def test_committed_wrong_answer_witness_checks():
    m = json.loads((ROOT / "witnesses" / "wrong-answer.manifest.json").read_text())
    assert m["verified"] and m["witness"]["relationships"] == 92 and m["predicate"]["kind"] == "differs"
    assert not m["predicate"]["loose"] and m["source"]["relationships"] == 57645
    res = check(WA, spec_from_manifest(m), use_cli=False)
    assert res.verified and res.text.startswith("92 of 92 change the answer")


@pytest.mark.skipif(relate_cli()[0] is None, reason="pinned relate CLI not on PATH")
def test_plain_relate_reproduces_the_same_wrong_answer_on_the_witness():
    cli = relate_cli()[0]
    r = subprocess.run(
        [
            cli,
            "query",
            "--database",
            str(WA),
            "--read-only",
            "--mode",
            "json",
            *cli_param_args({"country": "IN", "dest": "DEL"}),
        ],
        input=(ROOT / "queries" / "two-hub-agent.cypher").read_text(),
        capture_output=True,
        text=True,
        timeout=60,
        env={**os.environ, "DO_NOT_TRACK": "1"},
    )
    assert r.returncode == 0, r.stderr
    got = {row["airport"] for row in json.loads(r.stdout.splitlines()[0])["data"]}
    expected = {row["airport"] for row in json.loads((ROOT / "evidence" / "wrong-answer-expected.json").read_text())}
    # the same wrong answer: the 12 expected rows plus AGR
    assert len(got) == 13 and got - expected == {"AGR"} and expected <= got
