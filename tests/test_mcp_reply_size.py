"""What crosses MCP stays small enough for a real client to read (a2a judge r5: a recorded Claude Code session could
not read a 74,771-character `why` reply)."""

import json

from witness.mcp_server import REPLY_ROWS, compact_reply, lean_check


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
    assert lean_check({"check_text": "x"}) == {"check_text": "x", "not_necessary": [], "not_necessary_total": 0}


def test_a_large_failing_witness_reply_is_bounded_too():
    out = compact_reply(_res(5000, 1, failing=4000))
    assert len(out["check"]["not_necessary"]) == REPLY_ROWS and out["check"]["not_necessary_total"] == 4000
    assert out["check"]["not_necessary"][:2] == ["e1", "e2"]
    assert len(json.dumps(out)) < 10_000
