"""Every relationship of the FULL graph, deleted alone: which single deletions change the headline answer, and how.

`bench/full_graph_necessity.py` asks this of the 68 relationships the answer rows bind. This asks it of all 57,645:
each is deleted ALONE (by elementId, exactly one per trial, asserted) inside a Relate transaction on a scratch copy,
the headline query re-run, then rolled back. "Changes the answer" uses the product's own comparator (`canon_rows` with
the manifest's comparison settings: rows a bag, lists strict, floats to 12 digits).

A changing relationship is a SUPPORT when its deletion drops a row or changes a row's list, and a GUARD when its
deletion only ADDS a row: it is a fact that keeps another airport OUT of the answer (for this query, that airport's
own direct flight to $dest). A witness holds supports of its own answer; it holds no guards. This file measures both.

    uv run python bench/full_graph_sensitivity.py   -> evidence/full-graph-sensitivity.json   (about 3 minutes)
"""

from __future__ import annotations

import json
import os
import platform
import time
from pathlib import Path

os.environ.setdefault("DO_NOT_TRACK", "1")
import relate  # noqa: E402

from witness.canon import canon_rows, same_answer  # noqa: E402
from witness.export import display_name  # noqa: E402
from witness.store import Scratch  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
Q = (ROOT / "queries" / "two-hub.cypher").read_text()
B = (
    (ROOT / "queries" / "two-hub-bindings.cypher")
    .read_text()
    .replace("RETURN DISTINCT r", "RETURN DISTINCT elementId(r) AS id")
)
OUT = ROOT / "evidence" / "full-graph-sensitivity.json"


def main() -> None:
    man = json.loads((ROOT / "witnesses" / "two-hub.manifest.json").read_text())
    params, cmp = man["params"], man["comparison"]
    in_witness = {p["element"] for p in man["check"]["probes"]}
    assert len(in_witness) == man["witness"]["relationships"]

    def canon(rows: list) -> tuple:
        return canon_rows(rows, strict_lists=cmp["strict_lists"], digits=cmp["float_digits"])

    sc = Scratch.open_copy(ROOT / "data" / "air-routes.rl")
    try:
        counts = sc.counts()
        assert counts == (man["source"]["nodes"], man["source"]["relationships"]), counts
        base_rows = sc.run(Q, params).data
        base_canon = canon(base_rows)
        assert [r["airport"] for r in base_rows] == [r["airport"] for r in man["baseline"]["rows"]]
        base = {r["airport"]: r["hub_countries"] for r in base_rows}
        bound = {r["id"] for r in sc.run(B, params).data}

        def label(rid: str) -> str:
            s, e = sc.rel_ends[rid]
            return f"({display_name(sc.node_props[s])})-[:{sc.rel_type[rid]}]->({display_name(sc.node_props[e])})"

        labels = {rid: label(rid) for rid in sc.rel_keys}
        assert len(set(labels.values())) == len(labels), "two relationships share endpoints and type"
        assert in_witness <= set(labels.values()), "a witness relationship is missing from the source"
        order = sorted(sc.rel_keys, key=lambda r: sc.rel_keys[r])
        changing = []
        t0 = time.perf_counter()
        for i, rid in enumerate(order, 1):
            t = sc.trial(Q, params, rel_ids=[rid], check_counts=counts if i % 500 == 0 else None)
            if t.error:
                raise SystemExit(f"{labels[rid]}: trial error {t.error}")
            assert t.deleted_rels == 1, f"{labels[rid]}: deleted {t.deleted_rels} relationships, expected exactly 1"
            if same_answer(canon(t.rows), base_canon):
                continue
            now = {r["airport"]: r["hub_countries"] for r in t.rows}
            added = sorted(set(now) - set(base))
            dropped = sorted(set(base) - set(now))
            lists = sorted(k for k in set(now) & set(base) if now[k] != base[k])
            assert added or dropped or lists, f"{labels[rid]}: the comparator saw a change the row diff does not"
            changing.append(
                {
                    "relationship": labels[rid],
                    "type": sc.rel_type[rid],
                    "kind": "guard" if added and not dropped and not lists else "support",
                    "added": added,
                    "dropped": dropped,
                    "lists_changed": lists,
                    "bound_by_the_answer_rows": rid in bound,
                    "in_witness": labels[rid] in in_witness,
                }
            )
        seconds = time.perf_counter() - t0
        assert sc.counts() == counts and same_answer(canon(sc.run(Q, params).data), base_canon), "rollback residue"
    finally:
        sc.close()

    guards = [c for c in changing if c["kind"] == "guard"]
    supports = [c for c in changing if c["kind"] == "support"]
    out = {
        "generated": time.strftime("%Y-%m-%d %H:%M:%S %z"),
        "relate_db": getattr(relate, "__version__", "unknown"),
        "machine": f"{platform.system()} {platform.release()} {platform.machine()}, Python {platform.python_version()}",
        "query": "queries/two-hub.cypher",
        "params": params,
        "method": "every relationship of data/air-routes.rl deleted alone by elementId (count asserted == 1) in a "
        "Relate transaction on a scratch copy, the query re-run, rolled back; compared with canon_rows (manifest "
        "settings)",
        "relationships_tried": len(order),
        "seconds": round(seconds, 1),
        "trials_per_s": round(len(order) / seconds, 1),
        "change_the_answer": len(changing),
        "supports": len(supports),
        "guards": len(guards),
        "bound_by_the_answer_rows": len(bound),
        "change_and_bound": sum(c["bound_by_the_answer_rows"] for c in changing),
        "change_and_in_witness": sum(c["in_witness"] for c in changing),
        "supports_in_witness": sum(c["in_witness"] for c in supports),
        "guards_in_witness": sum(c["in_witness"] for c in guards),
        "guards_outside_the_bound": sum(not c["bound_by_the_answer_rows"] for c in guards),
        "airports_a_guard_keeps_out": sorted({a for c in guards for a in c["added"]}),
        "witness_relationships": len(in_witness),
        "changing": changing,
    }
    OUT.write_text(json.dumps(out, indent=1) + "\n")
    print({k: v for k, v in out.items() if k != "changing"})


if __name__ == "__main__":
    main()
