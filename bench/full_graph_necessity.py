"""Which of the relationships the headline answer rows bind change the answer when deleted from the FULL graph, and
how: each is deleted inside a Relate transaction on a scratch copy, the headline query re-run, then rolled back.
Compared with the committed witness, it shows that necessity in the witness and necessity in the full graph differ.
    uv run python bench/full_graph_necessity.py   -> evidence/full-graph-necessity.json
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import tempfile
import time
from pathlib import Path

os.environ.setdefault("DO_NOT_TRACK", "1")
import relate  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
Q = (ROOT / "queries" / "two-hub.cypher").read_text()
B = (
    (ROOT / "queries" / "two-hub-bindings.cypher")
    .read_text()
    .replace(
        "RETURN DISTINCT r",
        "RETURN DISTINCT startNode(r).iata AS s, coalesce(endNode(r).iata, endNode(r).code) AS e, type(r) AS t",
    )
)
P = {"country": "MX", "dest": "MEX"}


def main() -> None:
    w = {
        p["element"] for p in json.loads((ROOT / "witnesses" / "two-hub.manifest.json").read_text())["check"]["probes"]
    }
    with tempfile.TemporaryDirectory() as d:
        copy = Path(d) / "air-routes.rl"
        shutil.copyfile(ROOT / "data" / "air-routes.rl", copy)
        db = relate.Database(str(copy))
        base = {r["airport"]: r["hub_countries"] for r in db.execute(Q, P).data}
        rows = []
        for b in db.execute(B, P).data:
            el = f"({b['s']})-[:{b['t']}]->({b['e']})"
            db.begin_transaction()
            db.execute(
                f"MATCH (a:Airport {{iata: $s}})-[r:{b['t']}]->(x) WHERE x.iata = $e OR x.code = $e DELETE r",
                {"s": b["s"], "e": b["e"]},
            )
            now = {r["airport"]: r["hub_countries"] for r in db.execute(Q, P).data}
            db.rollback_transaction()
            rows.append(
                {
                    "relationship": el,
                    "in_witness": el in w,
                    "added": sorted(set(now) - set(base)),
                    "dropped": sorted(set(base) - set(now)),
                    "lists_changed": sorted(k for k in set(now) & set(base) if now[k] != base[k]),
                }
            )
        after = {r["airport"]: r["hub_countries"] for r in db.execute(Q, P).data}
    assert after == base, "rollback residue"
    changed = [r for r in rows if r["added"] or r["dropped"] or r["lists_changed"]]
    out = {
        "generated": time.strftime("%Y-%m-%d %H:%M:%S %z"),
        "machine": f"{platform.system()} {platform.release()} {platform.machine()}, Python {platform.python_version()}",
        "query": "queries/two-hub.cypher",
        "params": P,
        "bound": len(rows),
        "change_the_answer": len(changed),
        "change_and_in_witness": sum(r["in_witness"] for r in changed),
        "change_by_adding_a_row_only": sum(
            1 for r in changed if r["added"] and not r["dropped"] and not r["lists_changed"]
        ),
        "witness_relationships": len(w),
        "rows": rows,
    }
    (ROOT / "evidence" / "full-graph-necessity.json").write_text(json.dumps(out, indent=1) + "\n")
    print({k: v for k, v in out.items() if k != "rows"})


if __name__ == "__main__":
    main()
