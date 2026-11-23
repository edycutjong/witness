"""Regressions from the /a2a arch review (round 1): each test pins one defect the review or its verification found."""

import pytest

from witness.canon import canon_rows, same_answer
from witness.fixture import pull_slice
from witness.guard import Refused, strip_comments
from witness.pipeline import Request, reduce_request


def test_answer_equality_is_type_aware_and_nan_safe():
    one, one_f, true = canon_rows([{"x": 1}]), canon_rows([{"x": 1.0}]), canon_rows([{"x": True}])
    assert one == one_f == true  # Python's == conflates them; the proof's sha256 never did
    assert not same_answer(one, one_f) and not same_answer(one, true)
    nan = canon_rows([{"x": float("nan")}])  # two NaN objects, as two trials return them
    other = canon_rows([{"x": float("nan")}])
    assert nan != other and same_answer(nan, other)


def test_strip_comments_keeps_string_literals_exact():
    q = "MATCH (n) // pick\nWHERE n.x = 'a  b\\tc' /* x */ RETURN n.x AS x ;"
    assert strip_comments(q) == "MATCH (n) WHERE n.x = 'a  b\\tc' RETURN n.x AS x"


def test_outputs_never_overwrite_the_source_store(tiny_rl):
    """`why -f tiny.cypher --store tiny.rl --out .` named its output tiny.rl and replaced the source."""
    before = tiny_rl.read_bytes()
    q = "MATCH (a:P {name: 'A'})-[:R]->(h)-[:R]->(d:P {name: 'D'}) RETURN h.name AS hub"
    kw = dict(source=tiny_rl, statement=q, params={}, out_dir=tiny_rl.parent, use_cli=False)
    req = Request(**kw, name="tiny", ledger=None)
    with pytest.raises(Refused, match="overwrite the source"):
        reduce_request(req)
    assert tiny_rl.read_bytes() == before
    req = Request(**kw, name="w", ledger=tiny_rl)
    with pytest.raises(Refused, match="overwrite the source"):
        reduce_request(req)
    with pytest.raises(Refused, match="plain file stem"):
        reduce_request(Request(source=tiny_rl, statement=q, params={}, name="../x", out_dir=tiny_rl.parent))


@pytest.mark.parametrize(
    "slice_query",
    [
        "MATCH (a:Airport) SET a.x = 1 RETURN a",
        "CALL db.labels() YIELD label RETURN label",
        "MATCH (a) RETURN a; MATCH (b) DETACH DELETE b",
        "-",
    ],
)
def test_fixture_slice_is_guarded_before_anything_runs(slice_query, tmp_path):
    with pytest.raises(Refused):
        pull_slice(tmp_path / "creds.env", slice_query, tmp_path / "slice.rl")
