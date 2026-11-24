"""The three predicates on real guarded queries: construction refusals, verdicts, phrases and manifest descriptions."""

import json

import pytest

from witness.canon import canon_rows
from witness.guard import Refused, Tie, static_checks
from witness.predicates import Predicate, answer_of, answer_sha, expected_answer

Q = static_checks("MATCH (n:P) RETURN n.name AS name ORDER BY name LIMIT 1")
Q2 = static_checks("MATCH (n:P) RETURN count(n) AS c")
A = canon_rows([{"name": "A"}])
B = canon_rows([{"name": "B"}])
C = canon_rows([{"c": 4}])


def test_answer_of_returns_the_cut_rows_or_a_tie_at_the_cut():
    rows = [{"name": "A"}, {"name": "B"}]
    assert answer_of(Q, rows, ["name"]) == A
    tie = answer_of(Q, [{"name": "A"}, {"name": "A"}], ["name"])
    assert isinstance(tie, Tie)


def test_answer_of_without_a_cut_keeps_every_row_as_a_bag():
    assert answer_of(Q2, [{"c": 4}], ["c"]) == C
    assert answer_of(Q2, [{"c": 1}, {"c": 2}], ["c"]) == answer_of(Q2, [{"c": 2}, {"c": 1}], ["c"])


def test_expected_answer_accepts_json_text_or_a_list_and_fills_missing_columns_with_null():
    want = canon_rows([{"a": 1, "b": None}])
    assert expected_answer('[{"a": 1}]', ["a", "b"]) == want
    assert expected_answer([{"a": 1}], ["a", "b"]) == want


@pytest.mark.parametrize("bad", ['{"a": 1}', "[1, 2]", '[{"a": 1}, "x"]', '"text"'])
def test_expected_answer_refuses_anything_but_a_list_of_row_objects(bad):
    with pytest.raises(Refused, match="JSON list of row objects"):
        expected_answer(bad, ["a"])


def test_expected_answer_refuses_a_column_the_query_does_not_return():
    with pytest.raises(Refused, match=r"names columns the query does not return: \['zzz'\]"):
        expected_answer('[{"a": 1, "zzz": 2}]', ["a"])


def test_an_unknown_predicate_kind_is_refused():
    with pytest.raises(Refused, match="unknown predicate 'wobble'"):
        Predicate("wobble", [Q], A)


def test_differs_without_an_expected_answer_is_refused():
    with pytest.raises(Refused, match="differs needs --expected"):
        Predicate("differs", [Q], A)


def test_differs_is_refused_when_the_query_already_returns_the_expected_answer():
    with pytest.raises(Refused, match="already returns the expected answer"):
        Predicate("differs", [Q], A, expected=A)


def test_disagree_needs_exactly_two_queries_and_a_second_baseline():
    with pytest.raises(Refused, match="disagree needs --other"):
        Predicate("disagree", [Q], A, other_baseline=C)
    with pytest.raises(Refused, match="disagree needs --other"):
        Predicate("disagree", [Q, Q2], A)


def test_disagree_is_refused_when_both_queries_already_agree():
    with pytest.raises(Refused, match="give the same answer"):
        Predicate("disagree", [Q, Q2], A, other_baseline=A)


def test_keep_holds_only_for_the_baseline_answer():
    p = Predicate("keep", [Q], A)
    assert p.holds([A]) is True and p.holds([B]) is False


def test_differs_strict_holds_for_the_same_wrong_answer_and_loose_for_any_non_empty_other_answer():
    strict = Predicate("differs", [Q], A, expected=B)
    assert strict.holds([A]) is True and strict.holds([B]) is False
    loose = Predicate("differs", [Q], A, expected=B, loose=True)
    assert loose.holds([A]) is True and loose.holds([C]) is True
    assert loose.holds([B]) is False and loose.holds([canon_rows([])]) is False


def test_disagree_holds_while_the_two_answers_still_differ():
    p = Predicate("disagree", [Q, Q2], A, other_baseline=C)
    assert p.holds([A, C]) is True and p.holds([A, A]) is False


@pytest.mark.parametrize("answers", [[None], [A, None], [Tie([])], [A, Tie([])]])
def test_an_errored_or_tied_answer_makes_the_verdict_inconclusive(answers):
    assert Predicate("disagree", [Q, Q2], A, other_baseline=C).holds(answers) is None
    assert Predicate("keep", [Q], A).holds(answers) is None


def test_change_phrase_names_what_the_reduction_ends():
    assert Predicate("keep", [Q], A).change_phrase == "change the answer"
    assert Predicate("differs", [Q], A, expected=B).change_phrase == "change the answer"
    assert Predicate("differs", [Q], A, expected=B, loose=True).change_phrase == "end the mismatch"
    assert Predicate("disagree", [Q, Q2], A, other_baseline=C).change_phrase == "end the disagreement"


def test_describe_records_hashes_not_answers():
    assert Predicate("keep", [Q], A).describe() == {"kind": "keep"}
    d = Predicate("differs", [Q], A, expected=B, loose=True).describe()
    assert d == {"kind": "differs", "loose": True, "expected_sha256": answer_sha(B)}
    d = Predicate("disagree", [Q, Q2], A, other_baseline=C).describe()
    assert d["other_statement"] == Q2.text and d["other_baseline_sha256"] == answer_sha(C)
    assert answer_sha(A) != answer_sha(B) and len(answer_sha(A)) == 64
    assert json.dumps(d)
