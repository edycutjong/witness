"""Other query shapes: the paste-ready examples in JUDGE.md and DEMO.md give what evidence/other-queries.json records.

Each runs the product's own pipeline on the committed air-routes graph (no CLI needed), so the page a judge reads
and the run a judge makes cannot drift apart: a path question, a top-k with ORDER BY + LIMIT, an EXISTS / NOT EXISTS
pair.
"""

import json
from pathlib import Path

import pytest

from witness.pipeline import Request, reduce_request

ROOT = Path(__file__).resolve().parent.parent
RECORD = json.loads((ROOT / "evidence" / "other-queries.json").read_text())


@pytest.mark.parametrize("example", RECORD["examples"], ids=lambda e: Path(e["query"]).stem)
def test_an_example_query_reduces_to_the_recorded_witness(example, tmp_path, monkeypatch):
    monkeypatch.chdir(ROOT)
    o = reduce_request(
        Request(
            source=Path("data/air-routes.rl"),
            statement=(ROOT / example["query"]).read_text(),
            params=example["params"],
            name=Path(example["query"]).stem,
            out_dir=tmp_path,
            ledger=None,
            use_cli=False,
        )
    )
    assert o.verified and o.exit_code == 0
    assert o.answer_rows == example["answer"]
    assert o.manifest["witness"] == example["witness"]
    assert [f"({x['start']})-[:{x['type']}]->({x['end']})" for x in o.exhibits] == example["exhibits"]
    assert o.check.text == example["check"]


def test_the_recorded_count_runs_were_stopped_and_say_so():
    for key in ("count_bounded", "count_with_the_default_cap"):
        run = RECORD[key]
        assert run["exit_code"] == 3 and run["verified"] is False and run["run"]["capped"]
        assert run["check"].startswith("NOT VERIFIED") and "deletion-minimality NOT verified" in run["reasons"][0]
    assert RECORD["count_with_the_default_cap"]["run"]["trials"] == 20000
