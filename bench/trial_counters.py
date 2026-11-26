"""Record what is left after every trial of the headline reduction: the numbers the live trial counter of
`uv run witness demo` prints (`reducing · trial N · … relationships, … nodes left`) and the demo video's replay shows,
for all 371 trials instead of the counter's 50 ms samples.

It re-runs the seed-0 reduction of `witness demo` with pass-through wrappers on `Reducer.test` and `Reducer.commit`
(they only record; nothing about the reduction changes), then checks that its per-trial (n, phase, rels, nodes,
holds) sequence is identical to the committed witnesses/two-hub.trace.json and that it ends at the manifest's witness
counts, and stops without writing if either is not. Start counts come from the manifest's source, never from literals.

    uv run python bench/trial_counters.py   -> evidence/trial-counters-2026-11-27.json
"""

from __future__ import annotations

import json
import os
import platform
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("DO_NOT_TRACK", "1")

from witness import cli  # noqa: E402
from witness import reduce as R  # noqa: E402
from witness.pipeline import relate_version  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "evidence" / "trial-counters-2026-11-27.json"


def main() -> int:
    log: list[dict] = []
    orig = R.Reducer.test

    def wrapped(self, rel_ids=(), node_ids=(), phase=""):
        verdict = orig(self, rel_ids, node_ids, phase)
        rec = {"n": self.stats.trials, "phase": phase, "rels": len(rel_ids), "nodes": len(node_ids)}
        log.append({**rec, "holds": verdict})
        return verdict

    R.Reducer.test = wrapped
    counts_after: list[tuple[int, int]] = []
    orig_commit = R.Reducer.commit

    def commit(self, rel_ids=(), node_ids=()):
        orig_commit(self, rel_ids, node_ids)
        counts_after.append((self.stats.trials, *self.counts))

    R.Reducer.commit = commit
    with tempfile.TemporaryDirectory() as td:
        rc = cli.main(["demo", "--out", str(Path(td) / "out"), "--no-cli"])
    if rc != 0:
        print(f"witness demo exited {rc}", file=sys.stderr)
        return 1
    ref = json.loads((ROOT / "witnesses" / "two-hub.trace.json").read_text())["trials"]
    key = ("n", "phase", "rels", "nodes", "holds")
    if [tuple(t[k] for k in key) for t in log] != [tuple(t[k] for k in key) for t in ref]:
        print("per-trial sequence differs from witnesses/two-hub.trace.json; nothing written", file=sys.stderr)
        return 1
    start = json.loads((ROOT / "witnesses" / "two-hub.manifest.json").read_text())
    nodes, rels = start["source"]["nodes"], start["source"]["relationships"]
    by_trial = {n: (a, b) for n, a, b in counts_after}
    rows = []
    for t in log:
        if t["n"] in by_trial:
            nodes, rels = by_trial[t["n"]]
        rows.append({**t, "nodes_left": nodes, "rels_left": rels})
    last = rows[-1]
    final = (last["rels_left"], last["nodes_left"])
    if final != (start["witness"]["relationships"], start["witness"]["nodes"]):
        print(f"final counts {final} differ from witnesses/two-hub.manifest.json; nothing written", file=sys.stderr)
        return 1
    OUT.write_text(
        json.dumps(
            {
                "what": "relationships and nodes left after each trial of `witness demo` (seed 0); "
                "kept trials commit, the rest roll back",
                "matches": "witnesses/two-hub.trace.json, trial by trial (n, phase, rels, nodes, holds)",
                "source_sha256": start["source"]["sha256"],
                "machine": f"{platform.system()} {platform.machine()} · Python {platform.python_version()}",
                "relate_db": relate_version(),
                "trials": rows,
            },
            indent=1,
        )
        + "\n"
    )
    kept = sum(1 for r in rows if r["holds"])
    print(f"{len(rows)} trials, {kept} kept, final {last['rels_left']} rels / {last['nodes_left']} nodes -> {OUT.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
