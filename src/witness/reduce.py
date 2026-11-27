"""ddmin reduction to a deletion-minimal witness, with Relate transactions as the inner loop.

Phases: plan chunk (trial 1, never trusted) -> A: ddmin over nodes (DETACH DELETE)
-> B: ddmin over relationships in locality order -> C: ddmin over isolated nodes -> fixpoint.
A trial that errors is inconclusive: its chunk is kept, never counted as proof.
"""

from __future__ import annotations

import random
import re
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from .guard import GuardedQuery, Tie
from .predicates import Predicate, answer_of
from .store import Scratch


class TrialCapReached(RuntimeError):
    pass


class EmptyGraphPredicate(ValueError):
    """The predicate holds on the empty graph: the answer does not depend on the data."""


_NAME = re.compile(r":\s*`?([A-Za-z_][A-Za-z0-9_]*)`?")


def named_tokens(statement: str, plan: dict | None) -> set[str]:
    """Labels and relationship types named in the statement text and in plan operator details (union)."""
    names = set(_NAME.findall(statement))

    def walk(node):
        if not isinstance(node, dict):
            return
        names.update(_NAME.findall(str(node.get("details") or "")))
        for ch in node.get("children") or []:
            walk(ch)

    if plan:
        walk(plan.get("root"))
    return names


def untyped_rel_pattern(statement: str) -> bool:
    """True when some relationship pattern has no type, e.g. -[r]-, -->, -[]-."""
    s = re.sub(r"//[^\n]*", "", statement)
    if re.search(r"-\[\s*[A-Za-z_]?[A-Za-z0-9_]*\s*(\{[^}]*\})?\s*\]-", s):
        return True
    # -{2}> is the Cypher arrow -->, spelled so scanners do not read it as an HTML comment end.
    return bool(re.search(r"(?<![\]\w])-{2}>|<-{2}(?![\[\w])|\)-{2}\(", s))


@dataclass
class Stats:
    trials: int = 0
    inconclusive: int = 0
    ties: int = 0
    committed: int = 0
    trial_ms: list[float] = field(default_factory=list)
    log: list[dict] = field(default_factory=list)


class Reducer:
    """ddmin over one scratch store. ``predicate`` decides each trial; ``backend`` runs it (in-process by default,
    or an ``isolate.IsolatedTrials`` child process with a per-trial timeout)."""

    def __init__(
        self,
        scratch: Scratch,
        query: str | None = None,
        params: dict | None = None,
        *,
        predicate: Predicate | None = None,
        seed: int = 0,
        strict_lists: bool = False,
        digits: int = 12,
        max_trials: int = 20000,
        max_seconds: float | None = None,
        check_every: int = 1,
        progress: Callable[[Reducer, str], None] | None = None,
        backend=None,
    ):
        self.sc = scratch
        self.seed = seed
        self.strict_lists = strict_lists
        self.digits = digits
        self.max_trials = max_trials
        self.max_seconds = max_seconds
        self.check_every = check_every
        self.progress = progress
        self.backend = backend or scratch
        self.stats = Stats()
        self._t0 = time.perf_counter()
        if predicate is None:
            assert query is not None  # a bare query is the only way to build the default keep predicate
            gq = GuardedQuery(text=query, params=params or {}, exec_text=query)
            base = self._answers_now([gq])[0]
            predicate = Predicate("keep", [gq], base)
        self.pred = predicate
        self.baseline = predicate.baseline
        self.query = predicate.queries[0].text
        self.params = predicate.queries[0].params
        self.counts = self.sc.counts()

    def _answers_now(self, queries) -> list:
        out = []
        for gq in queries:
            res = self.sc.run(gq.exec_text, gq.params)
            out.append(self._ans(gq, res.data, res.columns))
        return out

    def _ans(self, gq, rows, cols):
        return answer_of(gq, rows, cols, keyer=self.sc.keyer, strict_lists=self.strict_lists, digits=self.digits)

    # ---- one trial ----------------------------------------------------------------------------
    def test(self, rel_ids=(), node_ids=(), phase: str = "") -> bool | None:
        if self.stats.trials >= self.max_trials:
            raise TrialCapReached(f"trial cap {self.max_trials} reached")
        if self.max_seconds is not None and time.perf_counter() - self._t0 > self.max_seconds:
            raise TrialCapReached(f"--max-seconds {self.max_seconds} reached")
        self.stats.trials += 1
        check = self.counts if (self.stats.trials % self.check_every == 0) else None
        stmts = [(gq.exec_text, gq.params) for gq in self.pred.queries]
        t = self.backend.trial_many(stmts, list(rel_ids), list(node_ids), check_counts=check)
        self.stats.trial_ms.append(t.ms)
        verdict = None
        tie = False
        if t.error is None:
            try:
                answers = getattr(t, "answers", None)  # an isolated child returns canonical answers
                if answers is None:
                    assert t.results is not None  # error is None, so the trial returned its results
                    answers = [self._ans(gq, r, c) for gq, (r, c) in zip(self.pred.queries, t.results, strict=True)]
                tie = any(isinstance(a, Tie) for a in answers)
                verdict = self.pred.holds(answers)
            except Exception:  # noqa: BLE001 - a comparison failure is inconclusive, never proof
                verdict = None
        if verdict is None:
            self.stats.inconclusive += 1
            self.stats.ties += int(tie)
        rec = {"n": self.stats.trials, "phase": phase, "rels": len(rel_ids), "nodes": len(node_ids), "holds": verdict}
        rec["ms"] = round(t.ms, 3)
        if t.error:
            rec["error"] = t.error[:200]
        if tie:
            rec["tie"] = True
        self.stats.log.append(rec)
        if self.progress is not None:
            self.progress(self, phase)
        return verdict

    def commit(self, rel_ids=(), node_ids=()) -> None:
        self.sc.commit_delete(rel_ids, node_ids)
        if self.backend is not self.sc:
            self.backend.commit_delete(rel_ids, node_ids)
        self.counts = self.sc.counts()
        self.stats.committed += 1

    # ---- generic ddmin ------------------------------------------------------------------------
    def ddmin(self, items: list[str], kind: str, phase: str, start_n: int | None = None) -> int:
        """Delete as many of ``items`` as the predicate allows. Returns the number removed.

        Sweep-and-continue ddmin: at granularity n, every chunk is tried once; a chunk whose deletion keeps the
        predicate is committed and the sweep continues with the next chunk. A sweep with any commit is repeated at
        the same granularity (with negation, a removal can make an earlier chunk deletable); a sweep without a
        commit doubles n. It stops only after a commit-free sweep at n = |C|, i.e. every single-element deletion
        was tried on the final set and none kept the predicate (1-minimality over ``items``, if all conclusive).
        """
        C = list(items)
        removed = 0
        if not C:
            return 0
        n = start_n if start_n is not None else (1 if len(C) == 1 else 2)
        n = min(n, len(C))
        while C:
            size = len(C)
            chunks = [C[i * size // n : (i + 1) * size // n] for i in range(n)]
            chunks = [c for c in chunks if c]
            gone: set[str] = set()
            for ch in chunks:
                ch = [x for x in ch if x not in gone and (kind == "node" or x in self.sc.rel_keys)]
                if not ch:
                    continue
                args: tuple[Sequence[str], Sequence[str]] = ((), ch) if kind == "node" else (ch, ())
                if self.test(*args, phase=phase) is True:
                    self.commit(*args)
                    gone.update(ch)
                    removed += len(ch)
            if gone:
                C = [x for x in C if x not in gone and (kind == "node" or x in self.sc.rel_keys)]
                n = min(n, len(C)) if C else 1
                continue
            if n >= len(C):
                break
            n = min(2 * n, len(C))
        return removed

    # ---- phases -------------------------------------------------------------------------------
    def node_order(self) -> list[str]:
        ids = sorted(self.sc.node_keys, key=lambda i: self.sc.node_keys[i])
        random.Random(self.seed).shuffle(ids)
        return ids

    def rel_locality_order(self, node_rank: dict[str, int]) -> list[str]:
        sc = self.sc

        def k(r):
            s, e = sc.rel_ends[r]
            return (node_rank.get(s, 1 << 30), sc.rel_type[r], sc.node_keys[e], sc.rel_keys[r])

        return sorted(sc.rel_keys, key=k)

    def isolated_nodes(self, rank: dict[str, int]) -> list[str]:
        touched = set()
        for s, e in self.sc.rel_ends.values():
            touched.add(s)
            touched.add(e)
        iso = [n for n in self.sc.node_keys if n not in touched]
        return sorted(iso, key=lambda n: rank.get(n, 1 << 30))

    def empty_graph_check(self) -> None:
        if self.test((), list(self.sc.node_keys), phase="empty-graph") is True:
            raise EmptyGraphPredicate("the predicate holds on the empty graph")

    def plan_chunk(self) -> dict:
        names: set[str] = set()
        for gq in self.pred.queries:
            plan = self.sc.run("EXPLAIN " + gq.exec_text, gq.params).plan
            names |= named_tokens(gq.text, plan)
        info = {"names": sorted(names), "dropped_rels": 0, "dropped_nodes": 0, "kept": None}
        if any(untyped_rel_pattern(gq.text) for gq in self.pred.queries):
            info["kept"] = "untyped relationship pattern: type pruning disabled"
            return info
        u_rels = [r for r, t in self.sc.rel_type.items() if t not in names]
        u_set = set(u_rels)
        left = set()
        for r, (s, e) in self.sc.rel_ends.items():
            if r not in u_set:
                left.add(s)
                left.add(e)
        u_nodes = [n for n, labels in self.sc.node_labels.items() if n not in left and not (set(labels) & names)]
        if not u_rels and not u_nodes:
            info["kept"] = "nothing unreachable"
            return info
        dropped_types = sorted({self.sc.rel_type[r] for r in u_rels})
        dropped_labels = sorted({lb for n in u_nodes for lb in self.sc.node_labels[n]})
        if self.test(u_rels, u_nodes, phase="plan") is True:
            self.commit(u_rels, u_nodes)
            info.update(
                dropped_rels=len(u_rels),
                dropped_nodes=len(u_nodes),
                kept=False,
                dropped_types=dropped_types,
                dropped_labels=dropped_labels,
            )
        else:
            info["kept"] = "plan chunk changed the answer: ignored"
        return info

    def singleton_pass(self, phase: str) -> int:
        """Try every relationship alone; commit and continue; repeat until a sweep commits nothing."""
        removed = 0
        while True:
            swept = 0
            rank = {n: i for i, n in enumerate(self.node_order())}
            for r in self.rel_locality_order(rank):
                if self.test([r], (), phase=phase) is True:
                    self.commit([r], ())
                    swept += 1
            removed += swept
            if not swept:
                return removed

    def run(self) -> dict:
        t0 = self._t0 = time.perf_counter()
        out: dict[str, Any] = {"seed": self.seed, "start_counts": self.counts}
        self.empty_graph_check()
        out["plan"] = self.plan_chunk()
        out["after_plan"] = self.sc.counts()
        order = self.node_order()
        out["phase_a_removed"] = self.ddmin(order, "node", "A")
        out["after_a"] = self.sc.counts()
        rank = {n: i for i, n in enumerate(order)}
        out["phase_b_removed"] = self.ddmin(self.rel_locality_order(rank), "rel", "B")
        out["after_b"] = self.sc.counts()
        c_removed = self.ddmin(self.isolated_nodes(rank), "node", "C")
        out["phase_c_removed"] = c_removed
        # Fixpoint: Phase C changed the graph, so re-run the singleton relationship pass, then Phase C, until Phase C
        # removes nothing. singleton_pass() itself ends on a commit-free sweep, so when C* then removes nothing the
        # graph is unchanged since that sweep: every relationship and every isolated node was tried on the final set.
        rounds = 0
        while c_removed:
            rounds += 1
            out.setdefault("fixpoint", []).append({"b": self.singleton_pass("B*")})
            c_removed = self.ddmin(self.isolated_nodes(rank), "node", "C*")
            out["fixpoint"][-1]["c"] = c_removed
        out["fixpoint_rounds"] = rounds
        out["final_counts"] = self.sc.counts()
        out["trials"] = self.stats.trials
        out["inconclusive"] = self.stats.inconclusive
        out["ties"] = self.stats.ties
        out["commits"] = self.stats.committed
        out["seconds"] = round(time.perf_counter() - t0, 3)
        return out
