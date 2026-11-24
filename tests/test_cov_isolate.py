"""`witness.isolate`: the trial child's protocol and the parent's watchdog, driven against real Relate stores."""

import multiprocessing as mp
import threading
import time
from types import SimpleNamespace

import pytest

from witness import isolate
from witness.guard import static_checks
from witness.isolate import IsolatedTrials, _child
from witness.store import Scratch

HUBS = "MATCH (a:P {name: 'A'})-[:R]->(h)-[:R]->(:P {name: 'D'}) RETURN h.name AS hub"
SLOW = (
    "MATCH (a:P {name: 'A'})-[:R]->(h)-[:R]->(:P {name: 'D'}) WITH collect(h.name) AS hubs "
    "UNWIND range(1, 3000000) AS i WITH hubs, sum(i) AS s RETURN hubs, s"
)


def gq(text):
    return static_checks(text, {}, "query")


def rel_id(source, start, end):
    """The element id of the (start)-[:R]->(end) relationship in a byte copy of `source` (copies keep ids)."""
    sc = Scratch.open_copy(source)
    try:
        return next(
            r
            for r, (s, e) in sc.rel_ends.items()
            if sc.node_props[s]["name"] == start and sc.node_props[e]["name"] == end and sc.rel_type[r] == "R"
        )
    finally:
        sc.close()


def _hang(conn):
    time.sleep(60)  # holds its end of the pipe and never answers


class ChildThread:
    """`_child` run on a thread over a real duplex Pipe, so its lines run inside this (measured) process."""

    def __init__(self, source, log, queries, strict_lists=False, digits=12):
        self.conn, end = mp.Pipe()
        self.thread = threading.Thread(target=_child, args=(end, str(source), log, queries, strict_lists, digits))
        self.thread.start()

    def ask(self, *msg, timeout=60):
        self.conn.send(msg)
        assert self.conn.poll(timeout), "the child did not answer"
        return self.conn.recv()

    def stop(self):
        self.conn.send(("stop",))
        self.thread.join(30)
        assert not self.thread.is_alive()


def test_child_answers_a_trial_with_canonical_answers_and_leaves_the_store_untouched(tiny_rl):
    c = ChildThread(tiny_rl, [], [gq(HUBS)])
    assert c.conn.recv() == ("ready", None)
    b_to_d = rel_id(tiny_rl, "B", "D")
    full = c.ask("trial", [], [], None)
    cut = c.ask("trial", [b_to_d], [], (5, 6))  # B->D deleted inside a rolled-back transaction
    again = c.ask("trial", [], [], (5, 6))
    c.stop()
    assert full[0] == "trial" and full[1][0] is None
    assert len(full[1][2][0]) == 2 and len(cut[1][2][0]) == 1  # two hubs, then only C
    assert again[1][2] == full[1][2]  # the rollback really restored B->D


def test_child_replays_the_commit_log_before_it_says_ready_and_applies_later_commits(tiny_rl):
    b_to_d = rel_id(tiny_rl, "B", "D")
    c_to_d = rel_id(tiny_rl, "C", "D")
    c = ChildThread(tiny_rl, [([b_to_d], [])], [gq(HUBS)])
    assert c.conn.recv() == ("ready", None)
    assert len(c.ask("trial", [], [], None)[1][2][0]) == 1  # B->D was already committed away by the replay
    assert c.ask("commit", [c_to_d], []) == ("ok", None)
    after = c.ask("trial", [], [], None)
    c.stop()
    assert after[1][2][0] == ()  # no hub is left: the answer is the empty bag


def test_child_reports_an_engine_error_as_an_inconclusive_trial_without_answers(tiny_rl):
    boom = gq("UNWIND [0] AS z RETURN 1 / z AS x")
    c = ChildThread(tiny_rl, [], [boom])
    c.conn.recv()
    kind, (err, ms, answers) = c.ask("trial", [], [], None)
    c.stop()
    assert kind == "trial" and err and answers is None and ms >= 0


def test_child_reports_an_answer_that_cannot_be_canonicalised_instead_of_dying(tiny_rl):
    # digits=-1 is an invalid float format: canonicalising the float answer raises inside the child
    c = ChildThread(tiny_rl, [], [gq("RETURN 1.5 AS x")], digits=-1)
    c.conn.recv()
    kind, (err, _ms, answers) = c.ask("trial", [], [], None)
    assert answers is None and err.startswith("ValueError")
    assert c.ask("trial", [], [], None)[1][0] == err  # and the child is still alive to answer the next one
    c.stop()


def test_isolated_trials_apply_commits_and_a_trial_sees_them(tiny_rl):
    it = IsolatedTrials(tiny_rl, [gq(HUBS)], timeout=60)
    try:
        before = it.trial_many([])
        it.commit_delete([rel_id(tiny_rl, "B", "D")])
        after = it.trial_many([])
        assert before.error is None and len(before.answers[0]) == 2
        assert after.error is None and len(after.answers[0]) == 1
        assert it.log == [([rel_id(tiny_rl, "B", "D")], [])] and it.restarts == 0
    finally:
        it.close()
    assert not it.proc.is_alive()


def test_a_commit_that_overruns_the_timeout_restarts_the_child_which_replays_the_commit(tiny_rl):
    it = IsolatedTrials(tiny_rl, [gq(SLOW)], timeout=60)
    old = it.proc
    try:
        it.conn.send(("trial", [], [], None))  # keep the child busy for ~1 s so the commit cannot be answered
        it.timeout = 0.2
        it.commit_delete([rel_id(tiny_rl, "B", "D")])
        assert it.restarts == 1 and it.proc is not old and not old.is_alive()
        it.timeout = 60
        t = it.trial_many([])
        assert t.error is None  # the new child is up, built from the source plus the log that holds the commit
        assert len(it.log) == 1
    finally:
        it.close()


def test_a_trial_that_overruns_the_timeout_is_reported_inconclusive_and_the_child_restarted(tiny_rl):
    it = IsolatedTrials(tiny_rl, [gq(SLOW)], timeout=0.2)
    try:
        t = it.trial_many([])
        assert t.error.startswith("TrialTimeout") and t.answers is None and t.ms >= 200
        assert it.restarts == 1
    finally:
        it.close()


def test_a_child_that_never_becomes_ready_before_the_deadline_raises_instead_of_hanging(tiny_rl, monkeypatch):
    spawn = mp.get_context("spawn")
    # a child process that is alive but never sends "ready" (a hung start-up), still holding its end of the pipe
    hung = SimpleNamespace(
        Pipe=spawn.Pipe, Process=lambda target, args, daemon: spawn.Process(target=_hang, args=(args[0],), daemon=True)
    )
    it = IsolatedTrials.__new__(IsolatedTrials)  # skip __init__ so the half-started child stays reachable to clean up
    it.source, it.queries, it.strict_lists, it.digits, it.log, it._ctx = str(tiny_rl), [], False, 12, [], hung
    ticks = iter([0.0, 1.0, 1000.0])  # still within the 300 s start deadline on the first look, past it on the next
    monkeypatch.setattr(isolate, "time", SimpleNamespace(monotonic=lambda: next(ticks), perf_counter=time.perf_counter))
    try:
        with pytest.raises(RuntimeError, match="did not start"):
            it._start()
    finally:
        it.proc.kill()
        it.proc.join(10)


def test_a_child_that_dies_while_starting_surfaces_as_a_closed_pipe_not_a_hang(tmp_path):
    with pytest.raises(EOFError):
        IsolatedTrials(tmp_path / "missing.rl", [gq(HUBS)], timeout=5)


def test_close_is_idempotent_and_survives_a_pipe_whose_child_is_gone(tiny_rl):
    it = IsolatedTrials(tiny_rl, [gq(HUBS)], timeout=60)
    it.close()
    assert not it.proc.is_alive()
    it.close()  # the stop message has nowhere to go (broken pipe): swallowed, nothing left to kill
    assert not it.proc.is_alive()


def test_close_kills_a_child_that_ignores_the_stop_message(tiny_rl, monkeypatch):
    it = IsolatedTrials(tiny_rl, [gq(SLOW)], timeout=60)
    it.conn.send(("trial", [], [], None))  # the child is busy for ~1 s, so it cannot honour "stop" yet
    monkeypatch.setattr(it.proc, "join", lambda *_a, **_k: None)  # as if the 10 s stop grace had already run out
    it.close()
    monkeypatch.undo()
    it.proc.join(10)
    assert it.proc.exitcode == -9  # SIGKILL
