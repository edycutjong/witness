"""The ledger: Reductions (agent or human) and Reviews (human), readable with plain relate."""

import pytest

from witness import ledger


def test_record_review_and_unreviewed(tmp_path):
    lp = tmp_path / "ledger.rl"
    rid = ledger.record_reduction(
        lp,
        {
            "statement": "MATCH (n) RETURN n.x AS x",
            "params_json": "{}",
            "verified": True,
            "check_text": "2 of 2 change the answer",
        },
        {"path_rl": "out/w.rl", "path_cypher": "out/w.cypher", "sha256": "ab"},
    )
    assert rid.startswith("r-")
    assert [r["id"] for r in ledger.unreviewed(lp)] == [rid]
    row = ledger.find(lp, rid)
    assert row["r"]["check_text"] == "2 of 2 change the answer" and row["w"]["path_rl"] == "out/w.rl"
    with pytest.raises(ValueError):
        ledger.review(lp, rid, "dispute", "")
    ledger.review(lp, rid, "dispute", "hub TIJ is seasonal")
    assert ledger.unreviewed(lp) == []
    with pytest.raises(KeyError):
        ledger.review(lp, "r-nope", "accept")
