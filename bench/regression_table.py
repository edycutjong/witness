"""The release table of every regression witness: which Relate release gives which answer on the few relationships.

Each witness under witnesses/regress/ was shrunk from air-routes with `witness why --other-engine relate-db==<fix>`:
the pinned 1.0.1 and the release that fixed the bug disagree on it, and every relationship in it is needed for that.
This script rebuilds each witness from its .cypher script in `:memory:` on whatever relate-db the interpreter has and
runs the witness's query. It imports only Witness's canonical form, so it runs under any release:

    for v in 1.0.1 1.0.2 1.1.0 1.2.0 1.3.0; do
      uv run --no-project --with relate-db==$v python bench/regression_table.py
    done > evidence/regression-releases.jsonl

One JSON line per witness and release: the rows, their canonical digest, or the error. Each line also carries the
SHA-256 of the .cypher script it rebuilt from (so the table is of the committed witness) and a hash over every node and
relationship the release built from it (`graph_sha256`: labels, types, properties and end nodes). The graph hash is the
same on every release, so where an answer changes it is the query's answer that changed, not what CREATE stored.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import sys
from pathlib import Path

os.environ.setdefault("DO_NOT_TRACK", "1")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import relate  # noqa: E402

from witness.canon import canon_rows, digest, node_key, rel_key  # noqa: E402

NODES = "MATCH (n) RETURN labels(n) AS l, properties(n) AS p"
RELS = (
    "MATCH (a)-[r]->(b) RETURN type(r) AS t, properties(r) AS p, "
    "labels(a) AS al, properties(a) AS ap, labels(b) AS bl, properties(b) AS bp"
)


def graph_sha256(db) -> str:
    """One hash over the graph as this release reads it back: every node and relationship by content, never by id."""
    keys = sorted(node_key(r["l"], r["p"]) for r in db.execute(NODES).data)
    keys += sorted(
        rel_key(r["t"], node_key(r["al"], r["ap"]), node_key(r["bl"], r["bp"]), r["p"]) for r in db.execute(RELS).data
    )
    return hashlib.sha256("\n".join(keys).encode("utf-8")).hexdigest()


def main() -> None:
    for man_path in sorted((ROOT / "witnesses" / "regress").glob("*.manifest.json")):
        man = json.loads(man_path.read_text())
        name = man["name"]
        script = (man_path.parent / f"{name}.cypher").read_text()
        body = "\n".join(ln for ln in script.splitlines() if not ln.startswith("//")).strip().rstrip(";")
        db = relate.Database(":memory:")
        out = {"witness": f"witnesses/regress/{name}", "relate_db": relate.__version__}
        out["cypher_sha256"] = hashlib.sha256(script.encode("utf-8")).hexdigest()
        try:
            db.execute(body)
            out["relationships"] = db.relationship_count()
            out["graph_sha256"] = graph_sha256(db)
            res = db.execute(man["statement"], man["params"])
            out["rows"] = res.data
            out["digest"] = digest(canon_rows(res.data, list(res.columns)))
        except Exception as e:  # noqa: BLE001 - a release that refuses the query is a row of the table too
            out["error"] = f"{type(e).__name__}: {e}"[:200]
        finally:
            db.close()
        out["python"] = platform.python_version()
        out["machine"] = f"{platform.system()} {platform.machine()}"
        print(json.dumps(out, default=str))


if __name__ == "__main__":
    main()
