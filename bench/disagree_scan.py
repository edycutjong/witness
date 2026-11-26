"""Find a real disagreement for the `disagree` predicate: run the headline query (queries/two-hub.cypher) and the
agent's first try (queries/two-hub-agent.cypher: the first hop matched in either direction) for every country paired
with its busiest airport, and record the pairs where the two answers differ (rows compared as a bag, lists in order).
    uv run python bench/disagree_scan.py   -> evidence/disagree-scan.json
"""

from __future__ import annotations

import json
import os
import platform
import sys
import time
from pathlib import Path

os.environ.setdefault("DO_NOT_TRACK", "1")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "bench"))

import relate  # noqa: E402
from country_scan import BUSIEST  # noqa: E402

SRC = ROOT / "data" / "air-routes.rl"
Q1 = (ROOT / "queries" / "two-hub.cypher").read_text()
Q2 = (ROOT / "queries" / "two-hub-agent.cypher").read_text()


def key(rows: list[dict]) -> list[str]:
    return sorted(json.dumps(r, sort_keys=True) for r in rows)


def main() -> None:
    db = relate.Database(str(SRC), read_only=True)
    pairs = db.execute(BUSIEST).data
    differ = []
    for p in pairs:
        params = {"country": p["country"], "dest": p["dest"]}
        a1, a2 = db.execute(Q1, params).data, db.execute(Q2, params).data
        if key(a1) != key(a2):
            only2 = sorted(set(key(a2)) - set(key(a1)))
            only1 = sorted(set(key(a1)) - set(key(a2)))
            differ.append(
                {
                    **params,
                    "rows_headline": len(a1),
                    "rows_agent": len(a2),
                    "only_agent": [json.loads(x) for x in only2],
                    "only_headline": [json.loads(x) for x in only1],
                }
            )
    out = {
        "generated": time.strftime("%Y-%m-%d %H:%M:%S %z"),
        "relate_db": relate.__version__ if hasattr(relate, "__version__") else "see evidence/env.txt",
        "machine": f"{platform.system()} {platform.release()} {platform.machine()}, Python {platform.python_version()}",
        "source": "data/air-routes.rl",
        "queries": ["queries/two-hub.cypher", "queries/two-hub-agent.cypher"],
        "pairs_scanned": len(pairs),
        "pairs_differ": len(differ),
        "differ": sorted(differ, key=lambda d: (len(d["only_agent"]) + len(d["only_headline"]), d["rows_agent"])),
    }
    (ROOT / "evidence" / "disagree-scan.json").write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
    print(f"{len(pairs)} pairs scanned, {len(differ)} differ")
    for d in out["differ"][:8]:
        print(
            d["country"],
            d["dest"],
            d["rows_headline"],
            d["rows_agent"],
            [r["airport"] for r in d["only_agent"]],
            [r["airport"] for r in d["only_headline"]],
        )


if __name__ == "__main__":
    main()
