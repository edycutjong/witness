from witness.canon import canon_rows, canon_value, node_key, rel_key


def test_rows_are_a_bag():
    a = [{"x": 1}, {"x": 2}, {"x": 2}]
    b = [{"x": 2}, {"x": 1}, {"x": 2}]
    assert canon_rows(a) == canon_rows(b)
    assert canon_rows(a) != canon_rows([{"x": 1}, {"x": 2}])  # multiplicity counts


def test_lists_are_bags_unless_strict():
    assert canon_value([1, 2]) == canon_value([2, 1])
    assert canon_value([1, 2], strict_lists=True) != canon_value([2, 1], strict_lists=True)


def test_floats_round_to_12_significant_digits():
    assert canon_value(0.1 + 0.2) == canon_value(0.3)
    assert canon_value(1.0) != canon_value(1.0 + 1e-9)


def test_keys_ignore_property_order_and_include_endpoints():
    k1 = node_key(["A"], {"x": 1, "y": 2})
    assert k1 == node_key(["A"], {"y": 2, "x": 1})
    k2 = node_key(["A"], {"x": 2})
    assert rel_key("R", k1, k2, {}) != rel_key("R", k2, k1, {})
