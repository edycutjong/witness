"""Canonical forms: every value kind a result row can carry, taken from real Relate answers."""

import hashlib

import pytest
import relate

from witness.canon import (
    bad_name,
    canon_rows,
    canon_value,
    cypher_name,
    digest,
    node_key,
    same_answer,
)
from witness.store import Scratch


def test_cypher_name_refuses_a_line_break_it_could_not_export_byte_exact():
    with pytest.raises(ValueError, match="control character"):
        cypher_name("a\nb")
    assert bad_name("a\x7fb") and bad_name("a b") and not bad_name("plain name")


def test_cypher_name_doubles_backticks():
    assert cypher_name("we`ird") == "`we``ird`"


def test_a_relationship_value_needs_a_keyer_and_uses_the_stores_key(tiny_rl):
    sc = Scratch.open_copy(tiny_rl)
    res = sc.run("MATCH (:P {name: 'A'})-[r:R]->(:P {name: 'B'}) RETURN r")
    rel = res.data[0]["r"]
    with pytest.raises(ValueError, match="keyer"):
        canon_value(rel)
    kind, key = canon_value(rel, keyer=sc.keyer)
    assert kind == "rel" and key == sc.rel_keys[rel.element_id]
    sc.close()


def test_a_path_value_is_canonical_in_order_and_keeps_node_and_rel_forms(tiny_rl):
    sc = Scratch.open_copy(tiny_rl)
    res = sc.run("MATCH p = (:P {name: 'A'})-[:R]->(:P {name: 'B'})-[:R]->(:P {name: 'D'}) RETURN p")
    c = canon_value(res.data[0]["p"], keyer=sc.keyer)
    assert c[0] == "path" and len(c[1]) == 3 and len(c[2]) == 2
    assert all(n[0] == "node" for n in c[1]) and all(r[0] == "rel" for r in c[2])
    assert c == canon_value(res.data[0]["p"], keyer=sc.keyer)  # stable across calls
    sc.close()


def test_a_path_inside_a_row_compares_equal_across_two_scratch_copies(tiny_rl):
    q = "MATCH p = (:P {name: 'A'})-[:R]->(:P {name: 'B'}) RETURN p AS p"
    a, b = Scratch.open_copy(tiny_rl), Scratch.open_copy(tiny_rl)
    assert a.answer(q) == b.answer(q)
    a.close()
    b.close()


def test_maps_canonicalise_by_sorted_key_and_recurse():
    m1 = canon_value({"b": [2, 1], "a": 1.0})
    m2 = canon_value({"a": 1.0, "b": [1, 2]})
    assert m1 == m2 and m1[0] == "map" and m1[1][0][0] == "a"
    assert canon_value({"a": [1, 2]}, strict_lists=True) != canon_value({"a": [2, 1]}, strict_lists=True)


def test_negative_zero_equals_zero_but_nan_and_infinities_survive_rounding():
    assert canon_value(-0.0) == canon_value(0.0) == 0.0
    nan = canon_value(float("nan"))
    assert nan != nan and same_answer((nan,), (canon_value(float("nan")),))
    assert canon_value(float("inf")) == float("inf") and canon_value(float("-inf")) == float("-inf")


def test_property_values_in_a_node_key_are_plain_json_even_when_nested_or_opaque():
    k = node_key(["A"], {"t": (1, 2), "m": {"z": 1.0000000000001, "a": None}, "f": 1.23456789012345678})
    assert '"f":1.23456789012' in k and '"t":[1,2]' in k
    with pytest.raises(ValueError, match="no canonical form"):
        node_key(["A"], {"o": object()})
    assert '"__repr__":"b\'x\'"' in node_key(["A"], {"o": b"x"})


def test_an_identity_repr_value_in_a_row_is_refused_rather_than_compared_by_address():
    with pytest.raises(ValueError, match="no canonical form"):
        canon_value(object())
    assert canon_value(b"x") == ("other", "b'x'")


def test_canon_rows_honours_an_explicit_column_subset():
    rows = [{"a": 1, "b": 2}, {"a": 3, "b": 4}]
    assert canon_rows(rows, ["b"]) == ((("b", 2),), (("b", 4),))
    assert canon_rows(rows) == canon_rows(rows, ["a", "b"])


def test_same_answer_distinguishes_one_one_point_zero_and_true():
    a, b, c = canon_rows([{"x": 1}]), canon_rows([{"x": 1.0}]), canon_rows([{"x": True}])
    assert not same_answer(a, b) and not same_answer(a, c) and same_answer(a, canon_rows([{"x": 1}]))


def test_digest_is_the_first_16_hex_of_the_sha256_of_the_repr():
    c = canon_rows([{"x": 1}])
    assert digest(c) == hashlib.sha256(repr(c).encode()).hexdigest()[:16] and len(digest(c)) == 16
    assert digest(c) != digest(canon_rows([{"x": 2}]))


def test_a_real_relate_node_value_keys_by_labels_and_properties_not_by_id(tiny_rl):
    db = relate.Database(str(tiny_rl))
    n = db.execute("MATCH (n:P {name: 'A'}) RETURN n").data[0]["n"]
    db.close()
    assert canon_value(n) == ("node", node_key(["P"], {"name": "A"}))
