"""Regression witnesses: Relate fixes and engine disagreements shrunk with --other-engine (witnesses/regress/,
witnesses/differential/). Each committed witness is verified, small, and re-proves against its other engine.

A relate-db engine is re-checked here (uv fetches the release once); a Neo4j one only when Bolt settings are given."""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import pytest

from witness.cli import main

ROOT = Path(__file__).resolve().parent.parent
MANIFESTS = sorted((ROOT / "witnesses" / "regress").glob("*.manifest.json")) + sorted(
    (ROOT / "witnesses" / "differential").glob("*.manifest.json")
)


def _ids(p: Path) -> str:
    return f"{p.parent.name}/{p.name.split('.')[0]}"


@pytest.mark.parametrize("man_path", MANIFESTS, ids=_ids)
def test_committed_regression_witness(man_path, capsys):
    man = json.loads(man_path.read_text())
    pred = man["predicate"]
    assert man["verified"] and pred["kind"] == "disagree" and pred.get("other_engine_spec")
    assert man["source"]["path"].endswith("air-routes.rl") and man["source"]["relationships"] == 57645
    n = man["witness"]["relationships"] + man["witness"]["isolated_nodes"]
    if man_path.parent.name == "regress":
        assert 1 <= n <= 5  # relationships, or isolated nodes when the fix is about node properties
    spec = pred["other_engine_spec"]
    if spec == "neo4j" and not os.environ.get("NEO4J_BOLT"):
        pytest.skip("Neo4j witness: set NEO4J_BOLT / NEO4J_USER / NEO4J_PASSWORD to re-check it")
    if spec.startswith("relate-db==") and shutil.which("uv") is None:
        pytest.skip("needs uv to fetch the other release")
    w = man_path.with_name(man_path.name.replace(".manifest.json", ".rl"))
    # a manifest may name a relate-db release; Neo4j is named here, by the caller who set NEO4J_BOLT
    engine = ["--other-engine", "neo4j"] if spec == "neo4j" else []
    assert main(["check", str(w), "--no-cli", *engine]) == 0
    out = capsys.readouterr().out
    assert f"{n} of {n} end the disagreement" in out and "VERIFIED" in out
