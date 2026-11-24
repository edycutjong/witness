"""Pull each exhibit tag: delete ONE witness relationship in a Relate transaction, re-run the query, roll back.

Writes evidence/pull-each-tag.json, the data behind the landing's "pull a tag" exhibit. Every row is a real trial
on a byte copy of the committed witness (witnesses/two-hub.rl); the committed file is never opened for writing.

    DO_NOT_TRACK=1 uv run python scripts/pull_each_tag.py
"""

from __future__ import annotations

import json
import platform
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from witness import __version__  # noqa: E402
from witness.check import plain  # noqa: E402
from witness.export import exhibits  # noqa: E402
from witness.store import Scratch  # noqa: E402

W = ROOT / "witnesses" / "two-hub.rl"
QUERY = ROOT / "queries" / "two-hub.cypher"
OUT = ROOT / "evidence" / "pull-each-tag.json"


def main() -> int:
    import relate

    man = json.loads((ROOT / "witnesses" / "two-hub.manifest.json").read_text())
    params = man["params"]
    statement = QUERY.read_text()
    col = man["baseline"]["columns"][0]
    sc = Scratch.open_copy(W)
    try:
        counts = sc.counts()
        base = plain(sc.run(statement, params).data)
        base_names = sorted(str(r[col]) for r in base)
        assert base_names == sorted(str(r[col]) for r in man["baseline"]["rows"]), (
            "witness no longer gives the baseline"
        )
        rows = []
        for n, ex in enumerate(exhibits(sc), 1):
            t = sc.trial_many([(statement, params)], rel_ids=[ex["id"]], check_counts=counts)
            if t.error:
                raise SystemExit(f"exhibit {n}: trial error {t.error}")
            after = plain(t.rows)
            names = sorted(str(r[col]) for r in after)
            rows.append(
                {
                    "n": n,
                    "rel": f"({ex['start']})-[:{ex['type']}]->({ex['end']})",
                    "rows_after": len(after),
                    "answer_after": names,
                    "rows": [{k: r[k] for k in sorted(r)} for r in sorted(after, key=lambda r: str(r[col]))],
                    "drops": sorted(set(base_names) - set(names)),
                    "appears": sorted(set(names) - set(base_names)),
                    "changed": after != base,
                    "ms": round(t.ms, 3),
                }
            )
        assert sc.counts() == counts, "witness copy changed after rollbacks"
    finally:
        sc.close()
    doc = {
        "schema": "witness.pull-each-tag/v1",
        "what": "each witness relationship deleted alone in a Relate transaction, the query re-run, rolled back",
        "witness": "witnesses/two-hub.rl",
        "query": "queries/two-hub.cypher",
        "params": params,
        "baseline": base_names,
        "baseline_rows": [{k: r[k] for k in sorted(r)} for r in sorted(base, key=lambda r: str(r[col]))],
        "counts": {"nodes": counts[0], "relationships": counts[1]},
        "changed": sum(r["changed"] for r in rows),
        "of": len(rows),
        "tags": rows,
        "run": {
            "utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "witness": __version__,
            "relate_db": getattr(relate, "__version__", "unknown"),
            "python": platform.python_version(),
            "machine": f"{platform.system()} {platform.machine()}",
        },
    }
    OUT.write_text(json.dumps(doc, indent=2) + "\n")
    print(f"{doc['changed']} of {doc['of']} change the answer -> {OUT.relative_to(ROOT)}")
    return 0 if doc["changed"] == doc["of"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
