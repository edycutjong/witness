"""The VERIFIED line names what a deletion would end, in the predicate's own words (a2a judge r5)."""

from types import SimpleNamespace

import pytest

from witness.cli import verdict_line


@pytest.mark.parametrize(
    ("check_text", "without"),
    [
        ("22 of 22 change the answer (22 of 22 relationships, 0 of 0 isolated nodes)", "changing the answer"),
        ("5 of 5 end the disagreement (5 of 5 relationships, 0 of 0 isolated nodes)", "ending the disagreement"),
        ("3 of 3 end the mismatch (3 of 3 relationships, 0 of 0 isolated nodes)", "ending the mismatch"),
    ],
)
def test_the_verdict_line_uses_the_predicates_phrase(capsys, check_text, without):
    o = SimpleNamespace(verified=True, manifest={"determinism_claimed": True}, check=SimpleNamespace(text=check_text))
    verdict_line(o)
    out = capsys.readouterr().out
    assert f"can be removed without {without} · determinism claimed" in out
