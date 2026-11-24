"""The reducer's edge paths: plan walking, trial caps, inconclusive trials, ddmin bookkeeping, the singleton sweep."""

import pytest

from witness.reduce import Reducer, TrialCapReached, named_tokens
from witness.store import Scratch

A_ONLY = "MATCH (a:P {name: 'A'}) RETURN a.name AS a"
UNTYPED = "MATCH (a:P {name: 'A'})-->(h)-->(:P {name: 'D'}) RETURN count(DISTINCT h) AS hubs"
TYPED = "MATCH (a:P {name: 'A'})-[:R]->(h)-[:R]->(:P {name: 'D'}) RETURN count(DISTINCT h) AS hubs"


def test_named_tokens_walks_every_operator_detail_in_a_plan_and_ignores_non_dict_children():
    plan = {
        "root": {
            "details": "(a:P)",
            "children": [{"details": "Expand (a)-[r:`R`]->(b:Q)", "children": [None, "junk", {"details": None}]}, 7],
        }
    }
    assert named_tokens("MATCH (n:Z) RETURN n", plan) == {"Z", "P", "R", "Q"}
    assert named_tokens("RETURN 1", {"root": None}) == set()
    assert named_tokens("RETURN 1", {}) == set()


def test_the_trial_cap_stops_the_run_before_another_trial_is_spent(tiny_rl):
    sc = Scratch.open_copy(tiny_rl)
    red = Reducer(sc, TYPED, {}, max_trials=1)
    assert red.test((), (), phase="x") is True and red.stats.trials == 1
    with pytest.raises(TrialCapReached, match="trial cap 1 reached"):
        red.test((), (), phase="x")
    assert red.stats.trials == 1 and sc.counts() == (5, 6)
    sc.close()


def test_the_time_budget_stops_the_run_with_its_own_message(tiny_rl):
    sc = Scratch.open_copy(tiny_rl)
    red = Reducer(sc, TYPED, {}, max_seconds=-1.0)  # already over budget
    with pytest.raises(TrialCapReached, match=r"--max-seconds -1\.0 reached"):
        red.test((), (), phase="x")
    assert red.stats.trials == 0
    sc.close()


class CorruptingBackend:
    """Runs every trial on the real scratch store, then drops the columns from the rows of the chosen trial."""

    def __init__(self, sc, corrupt_on):
        self.sc = sc
        self.corrupt_on = corrupt_on
        self.calls = 0

    def trial_many(self, statements, rel_ids, node_ids, check_counts=None):
        self.calls += 1
        t = self.sc.trial_many(statements, rel_ids, node_ids, check_counts)
        if self.calls == self.corrupt_on and t.results:
            t.results = [([{"unexpected": 1}], cols) for _, cols in t.results]
        return t

    def commit_delete(self, rel_ids, node_ids):
        pass


def test_a_trial_whose_answer_cannot_be_compared_is_inconclusive_and_never_proof(tiny_rl):
    sc = Scratch.open_copy(tiny_rl)
    backend = CorruptingBackend(sc, corrupt_on=1)
    red = Reducer(sc, TYPED, {}, backend=backend)
    assert red.test((), (), phase="x") is None  # would be True (nothing deleted) if the answer were readable
    assert red.stats.inconclusive == 1 and red.stats.ties == 0
    assert red.stats.log[0]["holds"] is None and "error" not in red.stats.log[0]
    assert red.test((), (), phase="x") is True  # the next, intact trial is trusted again
    sc.close()


def test_a_trial_that_errors_in_the_engine_is_logged_as_inconclusive_with_its_error(tiny_rl):
    sc = Scratch.open_copy(tiny_rl)
    red = Reducer(sc, TYPED, {})
    red.pred.queries[0].exec_text = "RETURN 1 +"  # the engine cannot run it
    assert red.test((), (), phase="x") is None
    rec = red.stats.log[0]
    assert rec["holds"] is None and rec["error"].startswith("RelateNativeError")
    sc.close()


def test_an_untyped_relationship_pattern_disables_type_pruning(tiny_rl):
    sc = Scratch.open_copy(tiny_rl)
    red = Reducer(sc, UNTYPED, {})
    info = red.plan_chunk()
    assert info["kept"] == "untyped relationship pattern: type pruning disabled"
    assert info["dropped_rels"] == 0 and info["dropped_nodes"] == 0 and sc.counts() == (5, 6)
    sc.close()


def test_ddmin_deletes_everything_when_the_answer_does_not_depend_on_it_and_then_stops(tiny_rl):
    sc = Scratch.open_copy(tiny_rl)
    red = Reducer(sc, A_ONLY, {})
    rels = list(sc.rel_keys)
    assert red.ddmin(rels, "rel", "B") == 6
    assert sc.counts() == (5, 0) and not sc.rel_keys
    others = [n for n, p in sc.node_props.items() if p["name"] != "A"]
    assert red.ddmin(others, "node", "A") == 4 and sc.counts() == (1, 0)
    assert red.ddmin([], "node", "A") == 0
    sc.close()


def test_ddmin_skips_a_relationship_that_is_already_gone(tiny_rl):
    sc = Scratch.open_copy(tiny_rl)
    red = Reducer(sc, A_ONLY, {})
    rels = list(sc.rel_keys)
    red.commit(rels[:1], ())
    trials = red.stats.trials
    assert red.ddmin(rels[:1], "rel", "B") == 0  # the only chunk is stale: no trial is spent on it
    assert red.stats.trials == trials
    assert red.ddmin(rels, "rel", "B") == 5
    sc.close()


def test_singleton_pass_drops_every_unneeded_relationship_and_sweeps_until_none_commit(tiny_rl):
    sc = Scratch.open_copy(tiny_rl)
    red = Reducer(sc, TYPED, {})
    removed = red.singleton_pass("B*")
    assert removed == 2 and sc.counts() == (5, 4)  # A-R->E and E-X->D carry no hub; the four R routes stay
    before = red.stats.trials
    assert red.singleton_pass("B*") == 0 and red.stats.trials == before + 4  # one commit-free sweep over 4 rels
    assert {r["phase"] for r in red.stats.log} == {"B*"}
    sc.close()


def test_a_progress_callback_sees_each_trial_and_check_every_spaces_the_count_check(tiny_rl):
    sc = Scratch.open_copy(tiny_rl)
    seen = []
    red = Reducer(sc, TYPED, {}, progress=lambda r, ph: seen.append((r.stats.trials, ph)), check_every=2)
    red.test((), (), phase="p1")
    red.test((), (), phase="p2")
    assert seen == [(1, "p1"), (2, "p2")]
    sc.close()
