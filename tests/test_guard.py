"""W2: read-only, deterministic queries only. Every user statement passes the guard, through every door."""

import json

import pytest
import relate

from witness.cli import main
from witness.guard import Refused, apply_cut, guard, static_checks

REFUSED = [
    ("MATCH (n) RETURN RAND() AS r", "rand"),
    ("MATCH (n) RETURN rand () AS r", "rand"),
    ("MATCH (n) RETURN `rand`() AS r", "rand"),
    ("RETURN randomUUID() AS u", "random"),
    ("RETURN DateTime.Realtime() AS t", "clock"),
    ("RETURN datetime . statement() AS t", "clock"),
    ("RETURN date() AS d", "clock"),
    ("RETURN datetime({timezone: 'UTC'}) AS d", "clock"),
    ("RETURN date($d) AS d", "clock"),
    ("RETURN timestamp() AS t", "clock"),
    ("MATCH (n) RETURN elementId(n) AS i", "store"),
    ("MATCH (n) RETURN id(n) AS i", "store"),
    ("MATCH p = shortestPath((a)-[*]-(b)) RETURN p", "tied"),
    ("MATCH p = SHORTEST 1 (a)-[]-+(b) RETURN p", "tied"),
    ("MATCH (n) CREATE (m) RETURN n", "CREATE"),
    ("MATCH (n) SET n.x = 1 RETURN n", "SET"),
    ("MATCH (n) DETACH DELETE n", "DETACH"),
    ("MERGE (n:P {name: 'A'}) RETURN n", "MERGE"),
    ("CALL { CREATE (n) RETURN n } RETURN 1", "CREATE"),
    ("MATCH (n) FOREACH (x IN [1] | REMOVE n.y) RETURN n", "FOREACH"),
    ("CALL db.labels()", "procedure"),
    ("LOAD CSV FROM 'file:///x.csv' AS r RETURN r", "LOAD CSV"),
    ("USE other MATCH (n) RETURN n", "USE"),
    ("MATCH (n) CALL { WITH n RETURN n AS m } IN TRANSACTIONS RETURN m", "TRANSACTIONS"),
    ("MATCH (n) RETURN n; MATCH (m) RETURN m", "one statement"),
    ("MATCH (n) RETURN n.name AS x LIMIT 3", "ORDER BY"),
    ("MATCH (n) RETURN n.name AS x SKIP 1", "ORDER BY"),
    ("MATCH (n) WITH n ORDER BY n.name LIMIT 2 RETURN n.name AS x", "final RETURN"),
    ("MATCH (n) RETURN n.name AS x ORDER BY toUpper(n.name) LIMIT 2", "column names"),
]

ALLOWED = [
    "MATCH (n) // rand()\nRETURN n.name AS x",
    "MATCH (n) WHERE n.name = 'rand()' RETURN n.name AS x",
    "MATCH (n {set: 1}) RETURN n.create AS c",
    "MATCH (n:Create) RETURN n.name AS x",
    "RETURN date('2024-01-01') AS d, datetime({year: 2024, month: 1, day: 2}) AS t",
    "MATCH p = allShortestPaths((a)-[*]-(b)) RETURN count(p) AS c",
    "MATCH (n) WHERE EXISTS { MATCH (n)-->(m) RETURN m LIMIT 1 } RETURN n.name AS x",
    "MATCH (n) RETURN n.name AS x ORDER BY x DESC SKIP 1 LIMIT 2",
    "MATCH (n) RETURN coll.sort(collect(n.name)) AS xs;",
]


@pytest.mark.parametrize("stmt,why", REFUSED)
def test_refused(stmt, why):
    with pytest.raises(Refused) as e:
        static_checks(stmt, {"d": "2024-01-01"})
    assert why.lower() in e.value.reason.lower()


@pytest.mark.parametrize("stmt", ALLOWED)
def test_allowed(stmt):
    static_checks(stmt, {})


def test_query_type_from_relate_is_required():
    db = relate.Database(":memory:")
    assert guard("MATCH (n) RETURN count(n) AS c", {}, db).query_type == "r"
    db.close()


def test_cut_is_lifted_and_ties_are_detected():
    g = static_checks("MATCH (n) RETURN n.name AS x, n.v AS v ORDER BY v DESC LIMIT 1", {})
    assert "LIMIT" not in g.exec_text and g.cut.limit == 1 and g.cut.order_cols == ["v"]
    rows = [{"x": "A", "v": 2}, {"x": "B", "v": 1}]
    assert apply_cut(rows, ["x", "v"], g.cut, key=lambda v: v) == [{"x": "A", "v": 2}]
    tied = [{"x": "A", "v": 1}, {"x": "B", "v": 1}]
    assert type(apply_cut(tied, ["x", "v"], g.cut, key=lambda v: v)).__name__ == "Tie"


WRITE = "MATCH (n) CREATE (m) RETURN n.name AS x"
RAND = "MATCH (n) RETURN n.name AS x, rand() AS r"


@pytest.mark.parametrize("bad", [WRITE, RAND])
def test_every_door_refuses(bad, tiny_rl, tmp_path, capsys):
    good = tmp_path / "good.cypher"
    good.write_text("MATCH (a:P {name: 'A'})-[:R]->(h)-[:R]->(:P {name: 'D'}) RETURN count(h) AS hubs")
    badf = tmp_path / "bad.cypher"
    badf.write_text(bad)
    out = str(tmp_path / "out")
    base = ["--store", str(tiny_rl), "--out", out, "--no-cli"]
    # door 1: the query
    assert main(["why", "-f", str(badf), *base]) == 2
    # door 2: the disagree reference
    assert main(["why", "-f", str(good), "--predicate", "disagree", "--other", str(badf), *base]) == 2
    # door 3: a check override without a manifest
    w = tmp_path / "w.rl"
    w.write_bytes(tiny_rl.read_bytes())
    assert main(["check", str(w), "-f", str(badf), "--expect", json.dumps([{"x": "A"}]), "--no-cli"]) == 2
    # door 4: rerun
    assert main(["rerun", str(w), "-f", str(badf)]) == 2
    assert capsys.readouterr().err.count("refused") == 4


def test_storage_order_dependence_is_refused(tiny_rl, tmp_path, capsys):
    q = tmp_path / "first.cypher"
    q.write_text("MATCH (n:P) WITH collect(n.name) AS xs RETURN xs[0] AS first")
    assert main(["why", "-f", str(q), "--store", str(tiny_rl), "--out", str(tmp_path / "o"), "--no-cli"]) == 2
    assert "storage order" in capsys.readouterr().err
