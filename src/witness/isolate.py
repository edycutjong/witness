"""``--isolate``: run every trial in a child process with a watchdog (``--trial-timeout``).

``relate-db`` has no statement timeout or cancel, so the only way to bound one trial is to run it somewhere that can be
killed. The child holds its own temp copy of the source with the same committed deletions applied (a byte copy keeps
element ids, so both sides speak the same ids). When a trial overruns, the child is killed, a new one is started from
the source plus the committed-deletion log, and the trial is reported as an error: inconclusive, never proof. A run
with any such trial does not claim determinism (machine- and load-dependent).
"""

from __future__ import annotations

import multiprocessing as mp
import time
from dataclasses import dataclass


@dataclass
class IsolatedResult:
    error: str | None
    ms: float
    answers: list | None = None  # canonical answers computed in the child
    results: list | None = None


def _child(conn, source: str, log: list, queries: list, strict_lists: bool, digits: int) -> None:
    import os

    os.environ.setdefault("DO_NOT_TRACK", "1")
    from .predicates import answer_of
    from .store import Scratch

    sc = Scratch.open_copy(source)
    for rels, nodes in log:
        sc.commit_delete(rels, nodes)
    conn.send(("ready", None))
    while True:
        msg = conn.recv()
        op = msg[0]
        if op == "stop":
            sc.close()
            return
        if op == "commit":
            sc.commit_delete(msg[1], msg[2])
            conn.send(("ok", None))
            continue
        _, rels, nodes, check = msg
        t = sc.trial_many([(q.exec_text, q.params) for q in queries], rels, nodes, check_counts=check)
        answers = None
        if t.error is None:
            try:
                answers = [
                    answer_of(q, r, c, keyer=sc.keyer, strict_lists=strict_lists, digits=digits)
                    for q, (r, c) in zip(queries, t.results, strict=True)
                ]
            except Exception as e:  # noqa: BLE001
                t.error = f"{type(e).__name__}: {e}"
        conn.send(("trial", (t.error, t.ms, answers)))


class IsolatedTrials:
    """Same ``trial_many`` / ``commit_delete`` surface as ``Scratch``, backed by a killable child process."""

    def __init__(self, source, queries, *, timeout: float = 30.0, strict_lists: bool = False, digits: int = 12):
        self.source = str(source)
        self.queries = list(queries)
        self.timeout = timeout
        self.strict_lists = strict_lists
        self.digits = digits
        self.log: list[tuple[list, list]] = []
        self.restarts = 0
        self._ctx = mp.get_context("spawn")
        self._start()

    def _start(self) -> None:
        self.conn, child = self._ctx.Pipe()
        args = (child, self.source, self.log, self.queries, self.strict_lists, self.digits)
        self.proc = self._ctx.Process(target=_child, args=args, daemon=True)
        self.proc.start()
        child.close()  # only the child holds its end, so a dead child reads as EOF here instead of a hang
        deadline = time.monotonic() + 300
        while not self.conn.poll(0.2):
            if not self.proc.is_alive() or time.monotonic() > deadline:
                raise RuntimeError(f"isolated trial process did not start (exit code {self.proc.exitcode})")
        self.conn.recv()

    def _restart(self) -> None:
        self.proc.kill()
        self.proc.join(5)
        self.restarts += 1
        self._start()

    def trial_many(self, statements, rel_ids=(), node_ids=(), check_counts=None) -> IsolatedResult:
        t0 = time.perf_counter()
        self.conn.send(("trial", list(rel_ids), list(node_ids), check_counts))
        if not self.conn.poll(self.timeout):
            self._restart()
            ms = (time.perf_counter() - t0) * 1000
            return IsolatedResult(f"TrialTimeout: no answer within {self.timeout:g} s", ms)
        _, (err, ms, answers) = self.conn.recv()
        return IsolatedResult(err, ms, answers)

    def commit_delete(self, rel_ids=(), node_ids=()) -> None:
        self.log.append((list(rel_ids), list(node_ids)))
        self.conn.send(("commit", list(rel_ids), list(node_ids)))
        if not self.conn.poll(self.timeout):
            self._restart()  # the restarted child replays the log, which already holds this commit
            return
        self.conn.recv()

    def close(self) -> None:
        try:
            self.conn.send(("stop",))
            self.proc.join(10)
        except Exception:  # noqa: BLE001
            pass
        if self.proc.is_alive():
            self.proc.kill()
