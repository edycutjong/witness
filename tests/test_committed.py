"""Sponsor depth 4: the committed headline witness is a single-file .rl that `witness check` re-proves from its
manifest, and that plain `relate` re-runs to the same answer (a separate assertion)."""

import json
import os
import re
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


# ---- the second committed example: two queries disagree (judge review r5) ------------------------------------------
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


# ---- the third committed example: a smaller repro of a wrong answer, `differs` (judge review r6) --------------------
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


def test_every_site_grep_in_ci_matches_the_committed_site():
    # arch review r7: Stage 4 grepped /judge/ for a sentence the generator never wrote, so the stage could not pass
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text()
    greps = re.findall(r"curl -s http://127\.0\.0\.1:8765(\S*) \| grep -q (\"[^\"]*\"|'[^']*')", ci)
    assert len(greps) >= 2
    n = json.loads((ROOT / "witnesses" / "two-hub.manifest.json").read_text())["witness"]["relationships"]
    for path, quoted in greps:
        needle = quoted[1:-1].replace("$N", str(n))
        page = ROOT / "site" / path.strip("/") / "index.html" if path.endswith("/") else ROOT / "site" / path
        assert needle in page.read_text(), (path, needle)


def test_every_third_party_action_is_pinned_to_a_commit():
    # arch review r7: a mutable tag (and astral-sh/setup-uv@v10, a tag that does not exist) is not a pin
    gh = ROOT / ".github"
    files = [*(gh / "workflows").glob("*.yml"), gh / "actions" / "setup-relate" / "action.yml"]
    uses = [u for f in files for u in re.findall(r"uses:\s*(\S+)", f.read_text()) if not u.startswith("./")]
    assert uses and all(re.fullmatch(r"[\w.-]+/[\w./-]+@[0-9a-f]{40}", u) for u in uses), uses


# ---- the fourth committed example: an engine disagreement, observed (Relate 1.0.1; the v1.3.0 notes list the fix) ---
EC = ROOT / "witnesses" / "exists-count.rl"


def test_committed_engine_disagreement_witness_checks():
    m = json.loads((ROOT / "witnesses" / "exists-count.manifest.json").read_text())
    assert m["verified"] and m["witness"]["relationships"] == 2 and m["predicate"]["kind"] == "disagree"
    assert m["source"]["relationships"] == 57645 and m["versions"]["relate_db"] == "1.0.1"
    assert m["statement"].strip() == (ROOT / "queries" / "count-two-match.cypher").read_text().strip()
    assert m["predicate"]["other_statement"] == (ROOT / "queries" / "exists-two-match.cypher").read_text().strip()
    res = check(EC, spec_from_manifest(m), use_cli=False)
    assert res.verified and res.text.startswith("2 of 2 end the disagreement")


def test_the_release_bisect_record_matches_the_committed_witness():
    """evidence/relate-versions.jsonl: the two forms disagree on the witness up to 1.2.0 and agree from 1.3.0 on; the
    row for the pinned engine is what this suite's own Relate returns."""
    import relate

    rows = [json.loads(ln) for ln in (ROOT / "evidence" / "relate-versions.jsonl").read_text().splitlines()]
    assert [(r["relate_db"], r["the_two_forms_agree"]) for r in rows] == [
        ("1.0.1", False),
        ("1.0.2", False),
        ("1.1.0", False),
        ("1.2.0", False),
        ("1.3.0", True),
        ("1.4.0", True),
    ]
    pinned = next(r for r in rows if r["relate_db"] == relate.__version__)
    db = relate.Database(str(EC), read_only=True)
    try:
        for form in ("count-two-match", "exists-two-match"):
            statement = (ROOT / "queries" / f"{form}.cypher").read_text()
            assert db.execute(statement, {"country": "MX"}).data == pinned[form], form
    finally:
        db.close()
