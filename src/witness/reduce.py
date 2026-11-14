"""ddmin reduction to a deletion-minimal witness, with Relate transactions as the inner loop.

Phases (spec "The algorithm"): plan chunk (trial 1, never trusted) -> A: ddmin over nodes (DETACH DELETE)
-> B: ddmin over relationships in locality order -> C: ddmin over isolated nodes -> fixpoint.
A trial that errors is inconclusive: its chunk is kept, never counted as proof.
"""

from __future__ import annotations

import random
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from .canon import canon_rows
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
    return bool(re.search(r"(?<![\]\w])-->|<--(?![\[\w])|\)--\(", s))


@dataclass
class Stats:
    trials: int = 0
    inconclusive: int = 0
    committed: int = 0
    trial_ms: list[float] = field(default_factory=list)
    log: list[dict] = field(default_factory=list)


class Reducer:
    def __init__(
        self,
        scratch: Scratch,
        query: str,
        params: dict,
        *,
        seed: int = 0,
        strict_lists: bool = False,
        max_trials: int = 20000,
        check_every: int = 1,
        predicate: Callable[[tuple | None], bool] | None = None,
    ):
        self.sc = scratch
        self.query = query
        self.params = params
        self.seed = seed
        self.strict_lists = strict_lists
        self.max_trials = max_trials
        self.check_every = check_every
        self.stats = Stats()
        self.baseline = self.sc.answer(query, params, strict_lists)
        self.predicate = predicate or (lambda ans: ans == self.baseline)
        self.counts = self.sc.counts()

    # ---- one trial ----------------------------------------------------------------------------
    def test(self, rel_ids=(), node_ids=(), phase: str = "") -> bool | None:
        if self.stats.trials >= self.max_trials:
            raise TrialCapReached(self.stats.trials)
        self.stats.trials += 1
        check = self.counts if (self.stats.trials % self.check_every == 0) else None
        t = self.sc.trial(self.query, self.params, rel_ids, node_ids, check_counts=check)
        self.stats.trial_ms.append(t.ms)
        if t.error is not None:
            self.stats.inconclusive += 1
            verdict = None
        else:
            ans = canon_rows(t.rows, t.columns, strict_lists=self.strict_lists, keyer=self.sc.keyer)
            verdict = bool(self.predicate(ans))
        self.stats.log.append(
            {
                "n": self.stats.trials,
                "phase": phase,
                "rels": len(rel_ids),
                "nodes": len(node_ids),
                "holds": verdict,
                "ms": round(t.ms, 3),
            }
        )
        return verdict

    def commit(self, rel_ids=(), node_ids=()) -> None:
        self.sc.commit_delete(rel_ids, node_ids)
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
                args = ((), ch) if kind == "node" else (ch, ())
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
        plan = self.sc.run("EXPLAIN " + self.query, self.params).plan
        names = named_tokens(self.query, plan)
        info = {"names": sorted(names), "dropped_rels": 0, "dropped_nodes": 0, "kept": None}
        if untyped_rel_pattern(self.query):
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
        removed = 0
        restart = True
        while restart:
            restart = False
            rank = {n: i for i, n in enumerate(self.node_order())}
            for r in self.rel_locality_order(rank):
                if r not in self.sc.rel_keys:
                    continue
                if self.test([r], (), phase=phase) is True:
                    self.commit([r], ())
                    removed += 1
                    restart = True
                    break
        return removed

    def run(self) -> dict:
        t0 = time.perf_counter()
        out = {"seed": self.seed, "start_counts": self.counts}
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
        rounds = 0
        while c_removed:
            rounds += 1
            b2 = self.singleton_pass("B*")
            c_removed = self.ddmin(self.isolated_nodes(rank), "node", "C*")
            if not b2 and not c_removed:
                break
        out["fixpoint_rounds"] = rounds
        out["final_counts"] = self.sc.counts()
        out["trials"] = self.stats.trials
        out["inconclusive"] = self.stats.inconclusive
        out["commits"] = self.stats.committed
        out["seconds"] = round(time.perf_counter() - t0, 3)
        return out
