"""W3: three predicates, one mechanism (keep · differs · disagree); the empty graph is never a witness."""

import json
from pathlib import Path

import pytest

from witness.guard import GuardedQuery, Refused
from witness.pipeline import Request, reduce_request
from witness.predicates import Predicate

HUBS = "MATCH (a:P {name: 'A'})-[:R]->(h)-[:R]->(:P {name: 'D'}) RETURN count(DISTINCT h) AS hubs"
NAMES = "MATCH (a:P {name: 'A'})-[:R]->(h)-[:R]->(:P {name: 'D'}) RETURN h.name AS hub"


def req(tiny_rl, tmp_path, statement, **kw):
    return Request(
        source=Path(tiny_rl),
        statement=statement,
        params={},
        out_dir=tmp_path / "out",
        ledger=None,
        use_cli=False,
        name=kw.pop("name", "w"),
        **kw,
    )


def test_keep(tiny_rl, tmp_path):
    o = reduce_request(req(tiny_rl, tmp_path, NAMES))
    assert o.verified and o.run["final_counts"] == (4, 4)
    assert o.check.text.startswith("4 of 4 change the answer")


def test_differs_strict_keeps_the_same_wrong_answer(tiny_rl, tmp_path):
    # the "agent" expected one hub; the graph says two: the witness explains the wrong-vs-expected gap
    o = reduce_request(req(tiny_rl, tmp_path, HUBS, predicate="differs", expected=json.dumps([{"hubs": 1}])))
    assert o.verified and o.manifest["predicate"]["kind"] == "differs"
    assert o.run["final_counts"][1] == 4


def test_differs_refuses_when_already_expected(tiny_rl, tmp_path):
    with pytest.raises(Refused, match="already returns"):
        reduce_request(req(tiny_rl, tmp_path, HUBS, predicate="differs", expected=json.dumps([{"hubs": 2}])))


def test_differs_loose_never_empty(tiny_rl, tmp_path):
    """--loose is 'any non-empty answer other than E': the reduction must not end on the empty answer."""
    o = reduce_request(
        req(tiny_rl, tmp_path, NAMES, predicate="differs", loose=True, expected=json.dumps([{"hub": "Z"}]))
    )
    assert o.verified
    assert o.run["final_counts"][1] >= 2  # one path A->h->D survives: a non-empty answer needs two routes
    p = Predicate("differs", [GuardedQuery("x", {}, "x")], (("r",),), expected=((),), loose=True)
    assert p.holds([()]) is False  # the empty answer never satisfies --loose


def test_disagree(tiny_rl, tmp_path):
    other = "MATCH (a:P {name: 'A'})-[:R]-(h)-[:R]->(:P {name: 'D'}) RETURN count(DISTINCT h) AS hubs"
    # the undirected first hop also counts E (A-[:R]->E, E has no R to D) ... so make the twin really differ:
    other = "MATCH (a:P {name: 'A'})-[:R]->(h) RETURN count(DISTINCT h) AS hubs"
    o = reduce_request(req(tiny_rl, tmp_path, HUBS, predicate="disagree", other=other))
    assert o.verified
    assert "end the disagreement" in o.check.text


def test_disagree_refuses_agreeing_queries(tiny_rl, tmp_path):
    with pytest.raises(Refused, match="same answer"):
        reduce_request(req(tiny_rl, tmp_path, HUBS, predicate="disagree", other=HUBS))


def test_empty_graph_predicate_is_refused(tiny_rl, tmp_path):
    with pytest.raises(Refused, match="empty graph"):
        reduce_request(req(tiny_rl, tmp_path, "MATCH (n:Nope) RETURN count(n) AS c"))


def test_empty_answer_is_refused(tiny_rl, tmp_path):
    with pytest.raises(Refused, match="nothing to witness"):
        reduce_request(req(tiny_rl, tmp_path, "MATCH (n:Nope) RETURN n.name AS x"))
