"""What crosses MCP stays small enough for a real client to read (a2a judge r5: a recorded Claude Code session could
not read a 74,771-character `why` reply)."""

import json

from witness.mcp_server import REPLY_ROW_CHARS, REPLY_ROWS, compact_reply, evidence_markdown, lean_check


def _res(n_ex: int, n_rows: int, failing: int = 0) -> dict:
    probes = [{"i": i, "kind": "rel", "element": f"e{i}", "necessary": i > failing} for i in range(1, n_ex + 1)]
    return {
        "answer": {"columns": ["a"], "rows": [{"a": i} for i in range(n_rows)]},
        "exhibits": [
            {
                "n": i,
                "start": "S",
                "start_labels": ["L"],
                "type": "T",
                "end": "E",
                "end_labels": ["L"],
                "key": "k" * 700,
                "id": f"r{i}",
            }
            for i in range(1, n_ex + 1)
        ],
        "check": {"check_text": f"{n_ex} of {n_ex} change the answer", "verified": not failing, "probes": probes},
        "evidence_markdown": "**Evidence:** ...",
    }


def test_a_large_witness_reply_is_bounded_and_keeps_the_totals():
    out = compact_reply(_res(500, 400))
    assert len(out["exhibits"]) == REPLY_ROWS and out["exhibits_total"] == 500
    assert len(out["answer"]["rows"]) == REPLY_ROWS and out["answer"]["rows_total"] == 400
    assert set(out["exhibits"][0]) == {"n", "start", "type", "end"}
    assert "probes" not in out["check"] and out["check"]["not_necessary"] == []
    assert len(json.dumps(out)) < 10_000


def test_a_small_reply_keeps_everything_an_agent_reads():
    out = compact_reply(_res(4, 2))
    assert [e["n"] for e in out["exhibits"]] == [1, 2, 3, 4] and out["answer"]["rows_total"] == 2
    assert out["evidence_markdown"] == "**Evidence:** ..."


def test_lean_check_names_the_probes_that_failed():
    out = lean_check(_res(5, 1, failing=2)["check"])
    assert out["not_necessary"] == ["e1", "e2"] and "probes" not in out
    assert out["not_necessary_total"] == 2
    assert out["probes_total"] == 5 and out["inconclusive_probes"] == [] and out["inconclusive_probes_total"] == 0


def test_a_check_that_did_not_run_is_not_shaped_like_all_needed():
    # a2a arch r7: an empty not_necessary beside probes_total 0 says nothing was probed, not "every one is needed"
    assert lean_check({"check_text": "x"}) == {
        "check_text": "x",
        "probes_total": 0,
        "not_necessary": [],
        "not_necessary_total": 0,
        "inconclusive_probes": [],
        "inconclusive_probes_total": 0,
    }


def test_an_inconclusive_probe_is_never_reported_as_not_necessary():
    # a2a arch r7: necessary None (an errored or timed-out trial) is unknown, not "not needed"
    probes = [
        {"i": 1, "kind": "rel", "element": "e1", "necessary": True},
        {"i": 2, "kind": "rel", "element": "e2", "necessary": None},
        {"i": 3, "kind": "rel", "element": "e3", "necessary": False},
    ]
    out = lean_check({"check_text": "x", "verified": False, "probes": probes})
    assert out["not_necessary"] == ["e3"] and out["not_necessary_total"] == 1
    assert out["inconclusive_probes"] == ["e2"] and out["inconclusive_probes_total"] == 1
    assert out["probes_total"] == 3


def test_answer_rows_are_bounded_by_size_and_sent_whole():
    big = {"hubs": ["X" * 10] * 3000}  # one collect() row of ~39 KB
    res = _res(4, 0)
    res["answer"]["rows"] = [{"hubs": ["A"]}, big, {"hubs": ["B"]}]
    out = compact_reply(res)
    assert out["answer"]["rows"] == [{"hubs": ["A"]}] and out["answer"]["rows_total"] == 3
    assert out["answer"]["rows_truncated"] is True
    assert len(json.dumps(out["answer"])) < REPLY_ROW_CHARS
    assert compact_reply(_res(4, 2))["answer"]["rows_truncated"] is False


def _md_res(n_ex: int, value: str = "v") -> dict:
    return {
        "answer": {"columns": ["a"], "rows": [{"a": value}]},
        "witness": {"relationships": n_ex},
        "check": {"check_text": "not run"},
        "verified": False,
        "source_relationships": 1000,
        "exhibits": [{"n": i, "start": "S", "type": "T", "end": "E"} for i in range(1, n_ex + 1)],
        "files": {"rl": "out/w.rl"},
        "relate_version": "1.0.1",
        "reasons": ["capped at 10 trials"],
    }


def test_the_not_verified_reason_survives_a_long_register():
    # a2a arch r7: with 40+ exhibits the overflow marker pushed the reasons line past the 25-line cut
    for n_ex in (5, 19, 38, 39, 40, 200):
        md = evidence_markdown(_md_res(n_ex)).splitlines()
        assert len(md) <= 25 and md[-1] == "Not verified: capped at 10 trials", n_ex


def test_a_huge_answer_value_is_shortened_in_the_evidence_block():
    md = evidence_markdown(_md_res(3, value="Z" * 5000))
    assert len(md.splitlines()[0]) < 200 and "…" in md.splitlines()[0]


def test_a_large_failing_witness_reply_is_bounded_too():
    out = compact_reply(_res(5000, 1, failing=4000))
    assert len(out["check"]["not_necessary"]) == REPLY_ROWS and out["check"]["not_necessary_total"] == 4000
    assert out["check"]["not_necessary"][:2] == ["e1", "e2"]
    assert len(json.dumps(out)) < 10_000
