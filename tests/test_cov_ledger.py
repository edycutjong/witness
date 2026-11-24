"""`witness.ledger`: the single-writer retry, the rollback on a failed write, and the review guards, on real stores."""

import re
import threading
import time

import pytest
import relate

from witness import ledger

REDUCTION = {"statement": "MATCH (n) RETURN n.x AS x", "params_json": "{}", "verified": True}
WITNESS = {"path_rl": "out/w.rl", "path_cypher": "out/w.cypher", "sha256": "ab"}


def test_open_waits_out_a_writer_that_releases_the_ledger_within_the_backoff(tmp_path):
    path = tmp_path / "sub" / "ledger.rl"
    path.parent.mkdir()
    held, release = threading.Event(), threading.Event()

    def other_writer():  # a second writer holds the exclusive lock (relate databases are bound to their thread)
        db = relate.Database(str(path))
        held.set()
        release.wait(10)
        db.close()

    th = threading.Thread(target=other_writer)
    th.start()
    assert held.wait(10)
    threading.Timer(0.12, release.set).start()  # released after the first two back-offs (0.05 s + 0.1 s)
    t0 = time.monotonic()
    ledger._open(path).close()
    th.join(10)
    assert time.monotonic() - t0 >= 0.1  # it really slept and retried; it did not fail on the first "locked"


def test_open_gives_up_with_the_engines_message_when_the_ledger_stays_locked(tmp_path):
    path = tmp_path / "ledger.rl"
    holder = relate.Database(str(path))
    try:
        t0 = time.monotonic()
        with pytest.raises(Exception, match="locked"):
            ledger._open(path, attempts=3)
        assert time.monotonic() - t0 >= 0.15  # slept 0.05 s then 0.1 s before the last, raising, attempt
    finally:
        holder.close()
    ledger._open(path, attempts=3).close()  # released: opens at once


def test_open_does_not_retry_an_error_that_is_not_a_lock(tmp_path):
    bad = tmp_path / "file"
    bad.write_text("not a directory")
    with pytest.raises(OSError):
        ledger._open(bad / "ledger.rl")  # the parent "directory" is a file


def test_open_with_no_attempts_left_raises_instead_of_returning_nothing(tmp_path):
    with pytest.raises(RuntimeError, match="unreachable"):
        ledger._open(tmp_path / "ledger.rl", attempts=0)


def test_a_failed_write_rolls_back_and_leaves_the_ledger_unchanged(tmp_path):
    lp = tmp_path / "ledger.rl"
    rid = ledger.record_reduction(lp, dict(REDUCTION), dict(WITNESS))
    with pytest.raises(Exception, match="by zero"):
        # the Reduction is created, then the division fails: the whole transaction must go
        ledger._write(lp, "CREATE (r:Reduction {id: 'half'}) WITH r UNWIND [0] AS z SET r.v = 1 / z", {})
    assert [r["id"] for r in ledger.unreviewed(lp)] == [rid]  # no half-written 'half' Reduction
    ledger._write(lp, "CREATE (r:Reduction {id: 'next'}) RETURN r.id AS id", {})  # and the file is not left locked
    assert sorted(r["id"] for r in ledger.unreviewed(lp)) == sorted([rid, "next"])


def test_a_write_that_fails_after_the_engine_already_ended_the_transaction_still_closes_the_database(
    tmp_path, monkeypatch
):
    lp = tmp_path / "ledger.rl"
    real = relate.Database

    class EndsItsOwnTransaction:
        """A real Database whose execute aborts the open transaction first, as an engine-side abort would."""

        def __init__(self, *a, **k):
            self.db = real(*a, **k)

        def __getattr__(self, name):
            return getattr(self.db, name)

        def execute(self, *a, **k):
            self.db.rollback_transaction()
            raise RuntimeError("engine aborted the transaction")

    monkeypatch.setattr(ledger.relate, "Database", EndsItsOwnTransaction)
    with pytest.raises(RuntimeError, match="engine aborted"):
        ledger._write(lp, "CREATE (r:Reduction)", {})
    monkeypatch.undo()
    ledger._write(lp, "CREATE (r:Reduction {id: 'ok'}) RETURN r.id AS id", {})  # lock released: the next write works
    assert [r["id"] for r in ledger.unreviewed(lp)] == ["ok"]


def test_review_refuses_an_unknown_verdict_and_a_dispute_without_a_reason(tmp_path):
    lp = tmp_path / "ledger.rl"
    rid = ledger.record_reduction(lp, dict(REDUCTION), dict(WITNESS))
    with pytest.raises(ValueError, match="accept or dispute"):
        ledger.review(lp, rid, "maybe")
    with pytest.raises(ValueError, match="needs a reason"):
        ledger.review(lp, rid, "dispute", "   ")
    assert [r["id"] for r in ledger.unreviewed(lp)] == [rid]  # nothing was written by either refusal


def test_review_accept_is_recorded_against_the_reduction_with_who_and_when(tmp_path):
    lp = tmp_path / "ledger.rl"
    rid = ledger.record_reduction(lp, dict(REDUCTION), dict(WITNESS))
    out = ledger.review(lp, rid, "accept", by="reviewer-1")
    assert out == {"id": rid, "verdict": "accept", "reason": ""}
    rows = ledger.read(lp, "MATCH (v:Review)-[:ON]->(r:Reduction {id: $id}) RETURN v.by AS by, v.at AS at", {"id": rid})
    assert rows[0]["by"] == "reviewer-1" and re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", rows[0]["at"])
    assert ledger.unreviewed(lp) == []


def test_find_returns_none_for_an_id_that_was_never_recorded(tmp_path):
    lp = tmp_path / "ledger.rl"
    ledger.record_reduction(lp, dict(REDUCTION), dict(WITNESS))
    assert ledger.find(lp, "r-nope") is None


def test_record_reduction_derives_a_stable_id_from_its_timestamp_and_statement(tmp_path):
    lp = tmp_path / "ledger.rl"
    fields = {**REDUCTION, "created_at": "2026-01-02T03:04:05Z"}
    rid = ledger.record_reduction(lp, fields, dict(WITNESS))
    assert rid == ledger.new_id("2026-01-02T03:04:05Z", REDUCTION["statement"], "{}")
    assert rid.startswith("r-20260102-030405-")
    kept = ledger.record_reduction(lp, {**fields, "id": "r-mine"}, dict(WITNESS))
    assert kept == "r-mine"
