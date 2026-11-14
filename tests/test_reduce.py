import json
from pathlib import Path

import pytest

from witness.export import cypher_script, write_rl
from witness.reduce import EmptyGraphPredicate, Reducer, named_tokens, untyped_rel_pattern
from witness.store import Scratch

ROOT = Path(__file__).resolve().parent.parent
Q2 = (
    "MATCH (a:P {name: 'A'})-[:R]->(h)-[:R]->(:P {name: 'D'}) "
    "WITH a, count(DISTINCT h) AS hubs WHERE hubs >= 2 RETURN a.name AS a"
)


def test_witness_is_deletion_minimal(tiny_rl, tmp_path):
    sc = Scratch.open_copy(tiny_rl)
    red = Reducer(sc, Q2, {})
    out = red.run()
    assert out["inconclusive"] == 0
    assert out["final_counts"] == (4, 4)  # A, B, C, D and the four R routes; E and X dropped
    script = cypher_script(sc)
    sc.close()
    w = tmp_path / "w.rl"
    write_rl(script, w)
    base = red.baseline
    for i in range(4):
        c = Scratch.open_copy(w)
        rid = sorted(c.rel_keys, key=c.rel_keys.get)[i]
        c.commit_delete([rid], ())
        assert c.answer(Q2, {}) != base  # every remaining relationship is necessary
        c.close()


def test_empty_graph_predicate_is_refused(tiny_rl):
    sc = Scratch.open_copy(tiny_rl)
    with pytest.raises(EmptyGraphPredicate):
        Reducer(sc, "MATCH (n:Nope) RETURN count(n) AS c", {}).run()
    sc.close()


def test_plan_names_and_untyped_patterns():
    assert {"P", "R"} <= named_tokens(Q2, None)
    assert untyped_rel_pattern("MATCH (a)-[r]->(b) RETURN a")
    assert untyped_rel_pattern("MATCH (a)-->(b) RETURN a")
    assert not untyped_rel_pattern(Q2)


def test_headline_witness_on_the_full_graph(tmp_path):
    """The real thing: queries/two-hub.cypher on data/air-routes.rl reduces to the committed spike witness."""
    q = (ROOT / "queries" / "two-hub.cypher").read_text()
    params = {"country": "MX", "dest": "MEX"}
    sc = Scratch.open_copy(ROOT / "data" / "air-routes.rl", tmp_path)
    red = Reducer(sc, q, params, strict_lists=True)
    out = red.run()
    assert out["inconclusive"] == 0
    assert out["final_counts"] == (12, 22)
    script = cypher_script(sc)
    sc.close()
    committed = (ROOT / "evidence" / "spike-witness-two-hub.cypher").read_text()
    body = "\n".join(line for line in committed.splitlines() if not line.startswith("//")) + "\n"
    assert script == body
    raw = json.loads((ROOT / "evidence" / "headline-raw.json").read_text())
    assert [r["airport"] for r in raw["rows"]] == ["PBC", "QRO", "TLC", "UPN"]
