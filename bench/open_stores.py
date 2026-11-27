"""Open every committed store under whatever relate-db this interpreter has, and ask the headline question.

The repository pins relate-db 1.0.1 and every committed `.rl` was written by it. This script answers one question for a
reader who has a newer Relate: do those files still open, and do they still give the same answer? It imports nothing
from Witness and works on byte copies in a temp dir, so the committed files are never opened by another engine version.

    for v in 1.0.1 1.3.0; do uv run --no-project --with relate-db==$v python bench/open_stores.py; done
"""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

os.environ.setdefault("DO_NOT_TRACK", "1")
import relate  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
STORES = [
    "data/air-routes.rl",
    "witnesses/two-hub.rl",
    "witnesses/direction-bug.rl",
    "witnesses/wrong-answer.rl",
    "witnesses/exists-count.rl",
    "fixtures/mex-foreign.rl",
    "witness.rl",
]
HEADLINE = ("data/air-routes.rl", "witnesses/two-hub.rl")


def main() -> None:
    query = (ROOT / "queries" / "two-hub.cypher").read_text()
    print(f"relate-db {relate.__version__}")
    with tempfile.TemporaryDirectory(prefix="witness-open-") as d:
        for rel in STORES:
            copy = Path(d) / rel.replace("/", "__")
            shutil.copyfile(ROOT / rel, copy)
            db = relate.Database(str(copy), read_only=True)
            try:
                line = f"  {rel}: opens read-only, {db.node_count():,} nodes, {db.relationship_count():,} relationships"
                if rel in HEADLINE:
                    rows = db.execute(query, {"country": "MX", "dest": "MEX"}).data
                    line += "; headline answer " + ", ".join(r["airport"] for r in rows)
            finally:
                db.close()
            print(line)


if __name__ == "__main__":
    main()
