"""export.py edge behaviour: literals for odd values, empty graphs, rebuild-over-existing, script validation."""

import pytest
import relate

from witness.export import _lit, cypher_script, display_name, validate_witness_script, write_rl
from witness.guard import Refused
from witness.store import Scratch


def test_null_is_written_as_the_cypher_null_literal():
    assert _lit(None) == "null"
    assert _lit([1, None]) == "[1, null]"


def test_a_value_with_no_cypher_literal_is_a_type_error_naming_its_type():
    with pytest.raises(TypeError, match="no Cypher literal for object"):
        _lit(object())
    with pytest.raises(TypeError, match="no Cypher literal for set"):
        _lit({1, 2})


def test_a_vector_with_a_coordinate_type_that_is_not_an_identifier_is_refused_not_injected():
    class Vector:  # shaped like relate-db's Vector: a hostile coordinate type must never reach the script text
        coordinate_type = "INTEGER8); MATCH (n) DETACH DELETE n; //"
        values = [1, 2]

    with pytest.raises(TypeError, match="vector coordinate type"):
        _lit(Vector())


def test_a_vector_with_a_plain_coordinate_type_round_trips_as_a_constructor_call():
    class Vector:
        coordinate_type = "FLOAT32"
        values = [1.5, 2.0]

    assert _lit(Vector()) == "vector([1.5, 2.0], 2, FLOAT32)"


def test_an_empty_graph_exports_only_its_header_lines(tmp_path):
    empty = tmp_path / "empty.rl"
    relate.Database(str(empty)).close()
    sc = Scratch.open_copy(empty, tmp_path)
    try:
        assert cypher_script(sc, "first\n\nsecond") == "// first\n// second\n"
        assert cypher_script(sc) == ""
    finally:
        sc.close()


def test_rebuilding_an_empty_script_makes_an_empty_store(tmp_path):
    assert write_rl("// only a header\n", tmp_path / "e.rl") == (0, 0)


def test_write_rl_replaces_a_store_that_already_exists(tmp_path):
    path = tmp_path / "w.rl"
    assert write_rl("CREATE (a:A {n: 1}), (b:B {n: 2}), (a)-[:T]->(b);", path) == (2, 1)
    assert write_rl("CREATE (c:C {n: 3});", path) == (1, 0)


def test_display_name_prefers_iata_then_code_then_name_and_falls_back():
    assert display_name({"name": "n", "code": "c", "iata": "i"}) == "i"
    assert display_name({"name": "n", "code": "c"}) == "c"
    assert display_name({"id": 7}) == "7"
    assert display_name({"other": 1}) == "?"
    assert display_name({}, fallback="anon") == "anon"


@pytest.mark.parametrize(
    "script",
    [
        "",
        "CREATE (n0:A {p: point({srid: 7203, x: 1.0, y: 2.0})});",
        "CREATE (n0:A {p: point({srid: 4979, x: 1.0, y: 2.0, z: 3.0})});",
    ],
)
def test_a_literal_create_with_a_point_constructor_is_accepted(script):
    validate_witness_script(script)


@pytest.mark.parametrize(
    "script, reason",
    [
        ("CREATE (n0:A {p: point(1)});", "point() in a witness .cypher takes one literal argument"),
        ("CREATE (n0:A {p: point()});", "point() in a witness .cypher takes one literal argument"),
        ("CREATE (n0:A {p: point({x: foo})});", "point() in a witness .cypher takes one literal argument"),
        ("CREATE (n0:A {p: point({x: 1}, {y: 2})});", "point() in a witness .cypher takes one literal argument"),
        ("MATCH (n) RETURN n", "a witness .cypher must be one CREATE statement"),
        ("CREATE (n0:A {p: rand()});", "rand() in a witness .cypher"),
        ("CREATE (n0:A {p: $x});", "no parameters"),
        ("CREATE (n0:A); CREATE (n1:B);", "must be one CREATE statement"),
        ("CREATE (n0:A) DETACH DELETE n0;", "DETACH in a witness .cypher"),
    ],
)
def test_a_hand_edited_script_that_is_not_one_literal_create_is_refused(script, reason):
    with pytest.raises(Refused) as e:
        validate_witness_script(script)
    assert reason in e.value.reason
