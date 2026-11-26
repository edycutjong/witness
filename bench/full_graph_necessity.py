"""Which of the relationships the headline answer rows bind change the answer when deleted from the FULL graph, and
how: each is deleted ALONE (by elementId, exactly one per trial, asserted) inside a Relate transaction on a scratch
copy, the headline query re-run, then rolled back. "Changes the answer" uses the product's own comparator
(`canon_rows` with the manifest's comparison settings: rows a bag, lists strict, floats to 12 digits).
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

from witness.canon import canon_rows, same_answer  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
Q = (ROOT / "queries" / "two-hub.cypher").read_text()
B = (
    (ROOT / "queries" / "two-hub-bindings.cypher")
    .read_text()
    .replace(
        "RETURN DISTINCT r",
        "RETURN DISTINCT elementId(r) AS id, startNode(r).iata AS s, coalesce(endNode(r).iata, endNode(r).code) AS e,"
        " type(r) AS t",
    )
)
P = {"country": "MX", "dest": "MEX"}


DELETE_ONE = "MATCH ()-[r]->() WHERE elementId(r) = $id DELETE r RETURN count(*) AS n"


def main() -> None:
    man = json.loads((ROOT / "witnesses" / "two-hub.manifest.json").read_text())
    w = {p["element"] for p in man["check"]["probes"]}
    cmp = man["comparison"]

    def canon(rows: list) -> tuple:
        return canon_rows(rows, strict_lists=cmp["strict_lists"], digits=cmp["float_digits"])

    with tempfile.TemporaryDirectory() as d:
        copy = Path(d) / "air-routes.rl"
        shutil.copyfile(ROOT / "data" / "air-routes.rl", copy)
        db = relate.Database(str(copy))
        base_rows = db.execute(Q, P).data
        base_canon = canon(base_rows)
        base = {r["airport"]: r["hub_countries"] for r in base_rows}
        assert len(base) == len(base_rows), "one row per airport"
        bindings = db.execute(B, P).data
        labels = [f"({b['s']})-[:{b['t']}]->({b['e']})" for b in bindings]
        assert len(set(labels)) == len(labels), "two bound relationships share endpoints and type"
        rows = []
        for b, el in zip(bindings, labels, strict=True):
            db.begin_transaction()
            deleted = db.execute(DELETE_ONE, {"id": b["id"]}).data[0]["n"]
            now_rows = db.execute(Q, P).data
            db.rollback_transaction()
            assert deleted == 1, f"{el}: deleted {deleted} relationships, expected exactly 1"
            now = {r["airport"]: r["hub_countries"] for r in now_rows}
            differs = not same_answer(canon(now_rows), base_canon)
            rows.append(
                {
                    "relationship": el,
                    "in_witness": el in w,
                    "added": sorted(set(now) - set(base)),
                    "dropped": sorted(set(base) - set(now)),
                    "lists_changed": sorted(k for k in set(now) & set(base) if now[k] != base[k]),
                    "changes_the_answer": differs,
                }
            )
            detail = bool(rows[-1]["added"] or rows[-1]["dropped"] or rows[-1]["lists_changed"])
            assert detail == differs, f"{el}: the row diff and the comparator disagree"
        after = canon(db.execute(Q, P).data)
    assert same_answer(after, base_canon), "rollback residue"
    changed = [r for r in rows if r["changes_the_answer"]]
    out = {
        "generated": time.strftime("%Y-%m-%d %H:%M:%S %z"),
        "relate_db": getattr(relate, "__version__", "unknown"),
        "machine": f"{platform.system()} {platform.release()} {platform.machine()}, Python {platform.python_version()}",
        "query": "queries/two-hub.cypher",
        "params": P,
        "method": "one relationship deleted per trial by elementId (count asserted == 1), rolled back; "
        "compared with canon_rows (manifest comparison settings)",
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
