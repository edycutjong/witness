"""Performance gate for CI: run the headline reduction and fail if throughput falls off a cliff.

CI runners are slower and noisier than the recorded machine (evidence/), so the floor is deliberately low: it catches a
10x regression, not a few percent. The measured numbers go to the job summary and are never quoted as results.

uv run python scripts/perf_gate.py [--min-trials-per-s 40]
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-trials-per-s", type=float, default=40.0)
    args = ap.parse_args()
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run(["uv", "run", "witness", "demo", "--out", tmp], cwd=ROOT, check=True, stdout=subprocess.DEVNULL)
        man = json.loads((Path(tmp) / "two-hub.manifest.json").read_text())
    run = man["run"]
    rate = run["trials"] / run["seconds"]
    line = f"{run['trials']} trials in {run['seconds']} s = {rate:.1f} trials/s (floor {args.min_trials_per_s})"
    print(line)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a") as fh:
            fh.write(f"### Performance gate\n\n{line}\n")
    return 0 if rate >= args.min_trials_per_s else 1


if __name__ == "__main__":
    sys.exit(main())
