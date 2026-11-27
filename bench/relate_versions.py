"""One witness, several Relate releases: does the engine you have still show the disagreement?

`witnesses/exists-count.cypher` is the 2-relationship graph Witness shrank from 57,645 relationships, on which two
forms of one condition disagree on relate-db 1.0.1 (`queries/count-two-match.cypher` returns MZT,
`queries/exists-two-match.cypher` returns nothing). This script rebuilds that graph in `:memory:` on whatever
relate-db the interpreter has and runs both forms. It imports nothing from Witness, so it runs under any release:

    for v in 1.0.1 1.1.0 1.2.0 1.3.0; do
      uv run --no-project --with relate-db==$v python bench/relate_versions.py
    done > evidence/relate-versions.jsonl

The v1.3.0 release notes list the fix ("EXISTS over two MATCH clauses agrees with COUNT on relationship uniqueness").
"""

from __future__ import annotations

import json
import os
import platform
from pathlib import Path

os.environ.setdefault("DO_NOT_TRACK", "1")
import relate  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
FORMS = ("count-two-match", "exists-two-match")


def main() -> None:
    script = (ROOT / "witnesses" / "exists-count.cypher").read_text()
    body = "\n".join(ln for ln in script.splitlines() if not ln.startswith("//")).strip().rstrip(";")
    db = relate.Database(":memory:")
    try:
        db.execute(body)
        out = {
            "relate_db": relate.__version__,
            "graph": "witnesses/exists-count.cypher, rebuilt in :memory:",
            "nodes": db.node_count(),
            "relationships": db.relationship_count(),
        }
        for name in FORMS:
            statement = (ROOT / "queries" / f"{name}.cypher").read_text()
            out[name] = db.execute(statement, {"country": "MX"}).data
    finally:
        db.close()
    out["the_two_forms_agree"] = out[FORMS[0]] == out[FORMS[1]]
    out["python"] = platform.python_version()
    out["machine"] = f"{platform.system()} {platform.machine()}"
    print(json.dumps(out))


if __name__ == "__main__":
    main()
