"""Order cuts: a tie at ORDER BY ... LIMIT is refused on G and makes a trial inconclusive, never proof."""

from pathlib import Path

import pytest
import relate

from witness.guard import Refused
from witness.pipeline import Request, reduce_request

TOP = "MATCH (p:P) OPTIONAL MATCH (p)-[:R]->(q) WITH p, count(q) AS c RETURN p.name AS name, c ORDER BY c DESC LIMIT 1"


def store(tmp_path, create):
    path = tmp_path / "g.rl"
    db = relate.Database(str(path))
    db.execute(create)
    db.close()
    return path


def test_tie_on_the_full_graph_is_refused(tmp_path):
    g = store(tmp_path, "CREATE (a:P {name: 'A'})-[:R]->(:Q {name: 'x'}), (b:P {name: 'B'})-[:R]->(:Q {name: 'y'})")
    with pytest.raises(Refused, match="tie"):
        reduce_request(Request(source=g, statement=TOP, params={}, out_dir=tmp_path / "o", ledger=None, use_cli=False))


CREATE_TIE = (
    "CREATE (a:P {name: 'A'}), (b:P {name: 'B'}), (x:Q {name: 'x'}), (y:Q {name: 'y'}), (z:Q {name: 'z'}),"
    " (a)-[:R]->(x), (a)-[:R]->(y), (b)-[:R]->(z)"
)


def test_deletion_created_tie_is_inconclusive_in_the_reducer(tmp_path):
    """codex's example: A leads 2-1 on G; deleting one of A's routes makes A and B tie at the cut.

    Those trials are logged as ties with no verdict (inconclusive, never proof). The reduction still ends on a
    witness without B, where no tie exists, but it no longer claims determinism.
    """
    g = store(tmp_path, CREATE_TIE)
    o = reduce_request(Request(source=g, statement=TOP, params={}, out_dir=tmp_path / "o", ledger=None, use_cli=False))
    trace = __import__("json").loads(Path(o.files["trace"]).read_text())
    ties = [t for t in trace["trials"] if t.get("tie")]
    assert ties and all(t["holds"] is None for t in ties)
    assert o.run["ties"] == len(ties) and o.run["inconclusive"] >= len(ties)
    assert o.manifest["determinism_claimed"] is False


def test_deletion_created_tie_is_inconclusive_in_check(tmp_path):
    """check on a W that keeps B: deleting either of A's routes ties A and B at the cut: inconclusive."""
    from witness.check import check, spec_from_args

    w = store(tmp_path, CREATE_TIE)
    (tmp_path / "g.cypher").write_text(CREATE_TIE + ";\n")
    res = check(w, spec_from_args(TOP, {}, '[{"name": "A", "c": 2}]'), use_cli=False)
    assert res.sufficient is True
    assert res.inconclusive == 2  # the two A routes
    assert not res.verified
