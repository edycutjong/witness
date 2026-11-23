"""The three predicates (W3), one mechanism: P(H) over the canonical answers of one or two guarded queries.

- ``keep``: ans(H) = ans(G).
- ``differs --expected E``: ans(H) = ans(G) where ans(G) != E. It is ``keep`` with a stated wrong-answer precondition;
  E is the reference the report names. ``--loose``: ans(H) != E, ans(H) non-empty, no error.
- ``disagree --other Q2``: ans_Q(H) != ans_Q2(H), where the two differ on G.

Any predicate that holds on the empty graph is refused by the reducer ("the answer does not depend on the data").
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field

from .canon import canon_rows, canon_value, same_answer
from .guard import GuardedQuery, Refused, Tie, apply_cut

KINDS = ("keep", "differs", "disagree")


def answer_of(gq: GuardedQuery, rows: list[dict], columns: list[str], *, keyer=None, strict_lists=False, digits=12):
    """Canonical answer of one guarded query from raw rows; a tie at a lifted SKIP/LIMIT cut returns ``Tie``."""
    if gq.cut is not None:
        cut_rows = apply_cut(
            rows, columns, gq.cut, key=lambda v: canon_value(v, strict_lists=strict_lists, digits=digits, keyer=keyer)
        )
        if isinstance(cut_rows, Tie):
            return cut_rows
        rows = cut_rows
    return canon_rows(rows, columns, strict_lists=strict_lists, digits=digits, keyer=keyer)


def answer_sha(ans: tuple) -> str:
    return hashlib.sha256(repr(ans).encode("utf-8")).hexdigest()


def expected_answer(expected_json: str | list, columns: list[str], *, strict_lists=False, digits=12) -> tuple:
    """--expected as JSON rows (a list of objects keyed by column name) in canonical form."""
    rows = json.loads(expected_json) if isinstance(expected_json, str) else expected_json
    if not isinstance(rows, list) or not all(isinstance(r, dict) for r in rows):
        raise Refused('--expected must be a JSON list of row objects, e.g. \'[{"airport": "PBC"}]\'', "expected")
    bad = [sorted(set(r) - set(columns)) for r in rows if set(r) - set(columns)]
    if bad:
        raise Refused(f"--expected names columns the query does not return: {bad[0]}", "expected")
    return canon_rows([{c: r.get(c) for c in columns} for r in rows], columns, strict_lists=strict_lists, digits=digits)


@dataclass
class Predicate:
    kind: str
    queries: list[GuardedQuery]  # [Q] or [Q, Q2] for disagree
    baseline: tuple  # ans_Q(G)
    other_baseline: tuple | None = None  # ans_Q2(G)
    expected: tuple | None = None
    loose: bool = False
    notes: list[str] = field(default_factory=list)

    def __post_init__(self):
        if self.kind not in KINDS:
            raise Refused(f"unknown predicate {self.kind!r}; use keep, differs or disagree", "predicate")
        if self.kind == "differs":
            if self.expected is None:
                raise Refused("differs needs --expected", "predicate")
            if same_answer(self.baseline, self.expected):
                raise Refused("differs: the query already returns the expected answer on the full graph", "predicate")
        if self.kind == "disagree":
            if len(self.queries) != 2 or self.other_baseline is None:
                raise Refused("disagree needs --other", "predicate")
            if same_answer(self.baseline, self.other_baseline):
                raise Refused("disagree: the two queries give the same answer on the full graph", "predicate")

    def holds(self, answers: list) -> bool | None:
        """True / False, or None (inconclusive) if any answer errored (None) or tied at a cut (Tie)."""
        if any(a is None or isinstance(a, Tie) for a in answers):
            return None
        a = answers[0]
        if self.kind == "keep":
            return same_answer(a, self.baseline)
        if self.kind == "differs":
            if self.loose:
                return not same_answer(a, self.expected) and len(a) > 0
            return same_answer(a, self.baseline)
        return not same_answer(a, answers[1])

    @property
    def change_phrase(self) -> str:
        if self.kind == "disagree":
            return "end the disagreement"
        if self.kind == "differs" and self.loose:
            return "end the mismatch"  # the answer becomes the expected one, or empty
        return "change the answer"

    def describe(self) -> dict:
        d = {"kind": self.kind}
        if self.kind == "differs":
            d["loose"] = self.loose
            d["expected_sha256"] = answer_sha(self.expected)
        if self.kind == "disagree":
            d["other_statement"] = self.queries[1].text
            d["other_baseline_sha256"] = answer_sha(self.other_baseline)
        return d
