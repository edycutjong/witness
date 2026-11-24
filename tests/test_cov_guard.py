"""Guard edge cases: the tokenizer, temporal-constructor rules, cut parsing and tie detection, and the engine net."""

import pytest
import relate

from witness.guard import Refused, Tie, apply_cut, guard, static_checks, strip_comments

# ---- the tokenizer and statement framing -------------------------------------------------------------------------


@pytest.mark.parametrize(
    "stmt",
    ["MATCH (n) WHERE n.name = 'oops RETURN n", "MATCH (n) /* never closed RETURN n", "MATCH (n:`P) RETURN n"],
)
def test_an_unterminated_string_comment_or_identifier_never_reaches_a_run(stmt):
    """The tokenizer takes the stray quote as punctuation, so the token rules pass; the engine net must stop it."""
    static_checks(stmt)
    db = relate.Database(":memory:")
    with pytest.raises(Refused, match="Relate could not plan it"):
        guard(stmt, {}, db)
    db.close()


@pytest.mark.parametrize("stmt", ["", "   ", ";", " ; ; ", "// only a comment"])
def test_guard_refuses_a_statement_with_nothing_in_it(stmt):
    with pytest.raises(Refused, match="empty statement"):
        static_checks(stmt)


def test_guard_ignores_a_stray_closing_brace_instead_of_crashing_on_an_empty_stack():
    g = static_checks("RETURN 1 AS x }")
    assert g.cut is None and g.text == "RETURN 1 AS x }"


# ---- temporal constructors ---------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "stmt",
    [
        "RETURN date({year: -5, month: 1}) AS d",  # a signed literal is still a literal
        "RETURN date.truncate('month', date('2026-11-08')) AS d",  # a namespaced call with an input is fixed
        "RETURN datetime({year: 2024, month: 1}) AS d",
        "RETURN duration.between(date('2024-01-01'), date('2024-02-01')) AS d",
    ],
)
def test_guard_allows_a_temporal_built_only_from_literals(stmt):
    assert static_checks(stmt).cut is None


@pytest.mark.parametrize(
    "stmt,why",
    [
        ("MATCH (n) RETURN datetime({year: n.y}) AS d", "needs a literal"),  # a non-literal field value
        ("RETURN date({year 2024}) AS d", "needs a literal"),  # a key without ':'
        ("RETURN date({1: 2}) AS d", "needs a literal"),  # a key that is not an identifier
        ("RETURN date({year: 2024 month: 1}) AS d", "needs a literal"),  # two values with no comma
        ("RETURN date({foo: 1}) AS d", "needs a literal"),  # no date/time field named
        ("RETURN date({}) AS d", "needs a literal"),
        ("RETURN date(1, 2) AS d", "needs a literal"),  # two arguments
        ("RETURN date(2024) AS d", "needs a literal"),  # one argument, neither a string nor a map
        ("RETURN date('2024-01-01' + 'x') AS d", "needs a literal"),  # a string expression is not a literal
        ("RETURN datetime() AS d", "no argument"),
        ("RETURN date.transaction() AS d", "clock"),
        ("RETURN localdatetime.truncate('day') AS d", "without an input"),
    ],
)
def test_guard_refuses_a_temporal_that_could_read_the_clock(stmt, why):
    with pytest.raises(Refused, match=why):
        static_checks(stmt)


# ---- cut parsing -------------------------------------------------------------------------------------------------


def test_guard_resolves_skip_and_limit_from_integer_parameters():
    g = static_checks("MATCH (n) RETURN n.v AS v ORDER BY v SKIP $s LIMIT $l", {"s": 1, "l": 2})
    assert (g.cut.skip, g.cut.limit, g.cut.order_cols) == (1, 2, ["v"])
    assert "SKIP" not in g.exec_text and "LIMIT" not in g.exec_text and g.exec_text.endswith("ORDER BY v")


@pytest.mark.parametrize("params", [{}, {"l": "two"}, {"l": -1}, {"l": True}, {"l": 1.5}])
def test_guard_refuses_a_limit_parameter_that_is_not_a_non_negative_integer(params):
    with pytest.raises(Refused, match="LIMIT must be a non-negative integer"):
        static_checks("MATCH (n) RETURN n.v AS v ORDER BY v LIMIT $l", params)


def test_guard_refuses_a_limit_given_as_a_float_literal():
    with pytest.raises(Refused, match="LIMIT must be a non-negative integer"):
        static_checks("MATCH (n) RETURN n.v AS v ORDER BY v LIMIT 1.5")


def test_guard_reads_several_order_columns_with_directions_and_a_quoted_name():
    g = static_checks("MATCH (n) RETURN n.a AS a, n.b AS `b c` ORDER BY a ASC, `b c` DESC, a LIMIT 3")
    assert g.cut.order_cols == ["a", "b c", "a"] and g.cut.limit == 3 and g.cut.skip == 0


@pytest.mark.parametrize("tail", ["LIMIT 1 foo", "LIMIT", "LIMIT 1 LIMIT 2 ,", "SKIP", "LIMIT 1 SKIP 1 x"])
def test_guard_refuses_stray_tokens_after_the_skip_limit_cut(tail):
    with pytest.raises(Refused, match="unsupported tokens"):
        static_checks(f"MATCH (n) RETURN n.v AS v ORDER BY v {tail}")


def test_guard_refuses_a_cut_under_union():
    with pytest.raises(Refused, match="final RETURN"):
        static_checks("MATCH (n) RETURN n.v AS v ORDER BY v LIMIT 1 UNION MATCH (m) RETURN m.v AS v")


# ---- apply_cut and Tie -------------------------------------------------------------------------------------------


def test_a_tie_straddling_the_cut_reports_itself_and_prints_the_tied_rows():
    g = static_checks("MATCH (n) RETURN n.name AS x, n.v AS v ORDER BY v LIMIT 1")
    rows = [{"x": "A", "v": 1}, {"x": "B", "v": 1}, {"x": "C", "v": 2}]
    tie = apply_cut(rows, ["x", "v"], g.cut, key=lambda v: v)
    assert isinstance(tie, Tie) and tie.rows == rows[:2]
    assert repr(tie) == f"Tie({rows[:2]!r})"


def test_a_tie_at_the_skip_boundary_is_detected_too_and_a_clean_cut_slices():
    g = static_checks("MATCH (n) RETURN n.v AS v ORDER BY v SKIP 1")
    assert isinstance(apply_cut([{"v": 1}, {"v": 1}, {"v": 2}], ["v"], g.cut, key=lambda v: v), Tie)
    assert apply_cut([{"v": 1}, {"v": 2}, {"v": 3}], ["v"], g.cut, key=lambda v: v) == [{"v": 2}, {"v": 3}]


def test_apply_cut_refuses_an_order_column_the_query_does_not_return():
    g = static_checks("MATCH (n) RETURN n.v AS v ORDER BY v LIMIT 1")
    with pytest.raises(Refused, match="not returned"):
        apply_cut([{"w": 1}], ["w"], g.cut, key=lambda v: v)


# ---- the engine net ----------------------------------------------------------------------------------------------


def test_the_engine_refuses_a_statement_it_cannot_plan_even_when_the_token_rules_pass():
    db = relate.Database(":memory:")
    with pytest.raises(Refused, match="Relate could not plan it"):
        guard("RETURN 1 +", {}, db)
    db.close()


def test_the_engine_query_type_catches_a_subquery_the_token_rules_let_through():
    """CALL { RETURN 1 } has no write keyword, so only Relate's own classification ('rw') stops it."""
    stmt = "CALL { RETURN 1 AS x } RETURN x"
    static_checks(stmt)
    db = relate.Database(":memory:")
    with pytest.raises(Refused, match="query_type 'rw'"):
        guard(stmt, {}, db)
    db.close()


# ---- strip_comments ----------------------------------------------------------------------------------------------


def test_strip_comments_keeps_string_literals_byte_exact_and_drops_comments_and_the_semicolon():
    out = strip_comments("MATCH (n) // line\nWHERE n.s = 'a  // b'  /* c */ RETURN n ;")
    assert out == "MATCH (n) WHERE n.s = 'a  // b' RETURN n"


def test_strip_comments_leaves_an_unterminated_string_as_it_found_it():
    assert strip_comments("RETURN 'open") == "RETURN 'open"


@pytest.mark.parametrize("word", ["DROP", "ALTER", "GRANT", "SHOW", "TERMINATE", "start"])
def test_guard_refuses_a_statement_that_opens_with_an_administrative_command(word):
    with pytest.raises(Refused, match="administrative command"):
        static_checks(f"{word} anything here")


@pytest.mark.parametrize("call", ["apoc.text.join(['a'], ',')", "gds.version()", "dbms.components()"])
def test_guard_refuses_a_function_from_a_plugin_or_server_namespace(call):
    with pytest.raises(Refused, match="plugin or server namespace"):
        static_checks(f"RETURN {call} AS x")


def test_guard_refuses_a_function_call_whose_parenthesis_never_closes():
    with pytest.raises(Refused, match="no argument"):
        static_checks("RETURN date(")


def test_a_property_named_limit_fails_closed_instead_of_running_a_truncated_query():
    """`n.limit` counts as a LIMIT word, so the lifted text is cut at it; the engine must refuse, not run it."""
    stmt = "MATCH (n) RETURN n.limit AS x ORDER BY x"
    assert static_checks(stmt).exec_text == "MATCH (n) RETURN n."
    db = relate.Database(":memory:")
    with pytest.raises(Refused, match="could not plan"):
        guard(stmt, {}, db)
    db.close()
