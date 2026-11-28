"""The differential run's queries on one more Relate release, against the answers that run recorded.

`bench/differential.py` asked 219 queries of relate-db 1.0.1, relate-db 1.3.0 and Neo4j and committed every answer
(`evidence/differential-answers.jsonl`). When Relate ships a release, this script asks the same queries of that release
alone, the same way (a copy of the store, each query in a transaction that is rolled back, 20 s to answer, a fresh
process after a timeout or a crash), and compares each answer with the three recorded ones. Nothing recorded is asked
again, and nothing is rewritten.

    uv run python bench/differential_release.py 1.4.0
        -> evidence/differential-relate-1.4.0.json            the tallies, and every query that is not `same`
           evidence/differential-answers-relate-1.4.0.jsonl   what the release gave, one line per query
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import differential as D  # noqa: E402 - the recorded run's own runner, timeout, answer form and comparison

RECORDED = ("relate_1_0_1", "relate_1_3_0", "neo4j")


def main() -> None:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    ap.add_argument("release", help="a relate-db release number, e.g. 1.4.0 (fetched from PyPI through uv)")
    a = ap.parse_args()
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", a.release, flags=re.ASCII):
        raise SystemExit("the release is a number like 1.4.0")
    qs = [json.loads(x) for x in D.QUERIES.read_text().splitlines()]
    report = json.loads((D.ROOT / "evidence" / "differential.json").read_text())
    sha = hashlib.sha256(D.QUERIES.read_bytes()).hexdigest()
    assert report["queries_sha256"] == sha, "the recorded answers are of other queries"
    recorded = [json.loads(x) for x in (D.ROOT / "evidence" / "differential-answers.jsonl").read_text().splitlines()]
    assert [r["id"] for r in recorded] == [q["id"] for q in qs]

    t0 = time.perf_counter()
    uv = ["uv", "run", "--no-project", "--quiet", "--with", f"relate-db=={a.release}", "python"]
    version, got = D.run_release(uv, qs)
    assert version == a.release, (version, a.release)  # the release that answered is the one that was asked for
    seconds = round(time.perf_counter() - t0, 1)

    tally: dict = {}
    order: dict = {}
    not_same: dict = {}
    for q, rec in zip(qs, recorded, strict=True):
        mine = got[q["id"]]
        for name in RECORDED:
            c = D.classify(rec[name], mine)  # the recorded engine first, this release second
            tally.setdefault(name, {}).setdefault(c, 0)
            tally[name][c] += 1
            o = D.order_of(q, rec[name], mine)
            if o:
                order.setdefault(name, {}).setdefault(o, 0)
                order[name][o] += 1
            if c != "same":
                not_same.setdefault(name, []).append({"id": q["id"], "is": c, "cypher": q["cypher"]})
    out = {
        "schema": "witness.differential-release/v1",
        "what": f"the differential run's {len(qs)} queries on relate-db {version}, each answer compared with the "
        "recorded answer of relate-db 1.0.1, relate-db 1.3.0 and Neo4j (the recorded engine first in every pair)",
        "release": version,
        "queries": len(qs),
        "queries_sha256": sha,
        "timeout_s": D.TIMEOUT,
        "recorded_run": {"engines": report["engines"], "recorded": report["recorded"]},
        "tally": tally,
        "order": order,
        "not_same": not_same,
        "answer_seconds": seconds,
        "machine": f"{platform.system()} {platform.machine()}",
        "python": platform.python_version(),
        "recorded": time.strftime("%Y-%m-%d %H:%M %z"),
    }
    name = f"relate-{version}"
    (D.ROOT / "evidence" / f"differential-answers-{name}.jsonl").write_text(
        "".join(json.dumps(got[q["id"]]) + "\n" for q in qs)
    )
    (D.ROOT / "evidence" / f"differential-{name}.json").write_text(json.dumps(out, indent=1) + "\n")
    print(json.dumps({k: out[k] for k in ("release", "tally", "order", "answer_seconds")}, indent=1))


if __name__ == "__main__":
    main()
