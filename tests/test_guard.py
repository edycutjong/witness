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
    # QA r2: calls used as map values, and LIMIT inside a subquery body before more reading
    ("MATCH (n) RETURN {k: rand()} AS m", "rand"),
    ("MATCH (n) RETURN {k: timestamp()} AS m", "clock"),
    ("MATCH (n) RETURN {k: id(n)} AS m", "store"),
    ("MATCH (n) RETURN n {.name, k: elementId(n)} AS m", "store"),
    ("MATCH (a) WHERE EXISTS { MATCH (b) WITH b LIMIT 1 MATCH (b)-->(c) RETURN c } RETURN a.x AS x", "ORDER BY"),
    (
        "MATCH (a) WHERE COUNT { MATCH (b) WITH b ORDER BY b.x LIMIT 1 MATCH (b)-->(c) RETURN c } > 0 RETURN a.x AS x",
        "final RETURN",
    ),
    # QA r3: OFFSET is a SKIP synonym; a CALL { } nested in an EXISTS body does not inherit the exemption
    ("MATCH (a) RETURN a.x AS x OFFSET 1", "ORDER BY"),
    ("MATCH (a) WITH a.x AS x OFFSET 1 RETURN x", "ORDER BY"),
    (
        "MATCH (a:X) WHERE EXISTS { MATCH (a)-->(b) CALL { MATCH (c:Y) RETURN c LIMIT 1 } WITH b, c WHERE c.v > b.v "
        "RETURN a } RETURN a.id AS i",
        "ORDER BY",
    ),
    ("RETURN COUNT { MATCH (b) CALL { MATCH (c:Y) RETURN c LIMIT 1 } RETURN c } AS n", "ORDER BY"),
    # arch review r1: *.truncate(unit) without an input temporal truncates "now"
    ("RETURN date.truncate('day') AS d", "clock"),
    ("INSERT (n:P {name: 'Z'})", "INSERT"),
    # arch review r2: a backtick identifier spelled like punctuation hid a LIMIT or a write keyword from the token rules
    ("MATCH (n:P) RETURN n.name AS `{` LIMIT 2", "ORDER BY"),
    ("MATCH (n:P) WITH n AS `{` LIMIT 1 RETURN `{`.name AS x", "ORDER BY"),
    ("MATCH (n:P) WITH n AS `:` CREATE (m:Q) RETURN 1 AS x", "CREATE"),
    ("MATCH (n) RETURN n.x AS x, DateTime.Truncate('second') AS t", "clock"),
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
    "MATCH (n:P {name: 'A'}) RETURN {k: n.name, v: size([1, 2])} AS m",
    "RETURN date.truncate('month', date('2026-11-08')) AS d",
    "MATCH (n:P) RETURN n.name AS `{`, n.name AS `order` ORDER BY `order` LIMIT 2",
    "RETURN datetime({`year`: 2024, month: 1}) AS d",
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


def test_ordered_offset_is_a_cut():
    g = static_checks("MATCH (n) RETURN n.name AS x ORDER BY x OFFSET 1", {})
    assert g.cut.skip == 1 and g.cut.limit is None and "OFFSET" not in g.exec_text


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


def test_judge_commands_never_write_into_committed_witnesses(tiny_rl, tmp_path, monkeypatch, capsys):
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    monkeypatch.chdir(root)
    q = tmp_path / "q.cypher"
    q.write_text("MATCH (a:P {name: 'A'})-[:R]->(h) RETURN h.name AS hub")
    assert main(["why", "-f", str(q), "--store", str(tiny_rl), "--out", "witnesses", "--no-cli"]) == 2
    assert main(["demo", "--out", "witnesses", "--no-cli"]) == 2
    out = str(tmp_path / "o")
    assert main(["why", "-f", str(q), "--store", str(tiny_rl), "--out", out, "--ledger", "witness.rl", "--no-cli"]) == 2
    assert main(["why", "-f", str(q), "--store", str(tiny_rl), "--out", out, "--name", "../x", "--no-cli"]) == 2
    assert main(["why", "-f", str(q), "--store", str(tiny_rl), "--out", "data", "--no-cli"]) == 2
    assert main(["export", "witnesses/two-hub.rl", "--to", "witnesses"]) == 2
    assert main(["export", "witnesses/two-hub.rl", "--to", "answers"]) == 2
    assert main(["review", "r-x", "--accept", "--ledger", "witness.rl"]) == 2
    assert capsys.readouterr().err.count("is a committed path") == 7


def test_rerun_missing_param_is_a_clean_refusal(capsys):
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    assert main(["rerun", str(root / "witnesses/two-hub.rl"), "-f", str(root / "queries/two-hub.cypher")]) == 2
    assert "refused (rerun): Relate:" in capsys.readouterr().err
