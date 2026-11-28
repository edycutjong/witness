"""One answer, several witnesses: the headline reduction under different seeds.

A witness is deletion-minimal, not unique. The seed sets the order in which deletions are tried, so another seed can
keep other relationships that reproduce the same answer. This script runs the headline reduction
(`queries/two-hub.cypher`, the demo's parameters and `--strict-lists`) under seeds 0 to 5, each into a temp directory,
and records what each run kept, whether `witness check` verified it, and how many of the witnesses are different sets of
relationships:

    uv run python bench/seeds.py   -> evidence/seeds.json

Seed 0 is the committed witness (`witnesses/two-hub.*`); the script stops if its run keeps anything else.
"""

from __future__ import annotations

import json
import platform
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SEEDS = range(6)
PARAMS = {"country": "MX", "dest": "MEX"}


def main() -> None:
    committed = json.loads((ROOT / "witnesses" / "two-hub.manifest.json").read_text())
    kept0 = sorted(p["element"] for p in committed["check"]["probes"])
    assert PARAMS == committed["params"] and committed["comparison"]["strict_lists"]
    runs = []
    for seed in SEEDS:
        with tempfile.TemporaryDirectory(prefix="witness-seeds-") as tmp:
            cmd = [sys.executable, "-m", "witness", "why", "-f", "queries/two-hub.cypher", "--strict-lists", "--no-cli"]
            cmd += [x for k, v in PARAMS.items() for x in ("--param", f"{k}={v}")]
            cmd += ["--seed", str(seed), "--out", tmp]
            done = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
            man = json.loads(next(Path(tmp).glob("*.manifest.json")).read_text())
        kept = sorted(p["element"] for p in man["check"]["probes"])
        assert done.returncode == 0 and man["verified"] and man["seed"] == seed, (seed, done.returncode)
        runs.append(
            {
                "seed": seed,
                "relationships": man["witness"]["relationships"],
                "nodes": man["witness"]["nodes"],
                "trials": man["run"]["trials"],
                "check": man["check"]["check_text"],
                "verified": man["verified"],
                "same_answer": man["baseline"]["sha256"] == committed["baseline"]["sha256"],
                "not_in_the_committed_witness": sorted(set(kept) - set(kept0)),
                "kept": kept,
            }
        )
    assert runs[0]["kept"] == kept0, "seed 0 no longer gives the committed witness"
    out = {
        "schema": "witness.seeds/v1",
        "what": "the headline reduction under seeds 0 to 5: what each kept, and how many of the witnesses differ",
        "statement": "queries/two-hub.cypher",
        "params": PARAMS,
        "distinct_witnesses": len({tuple(r["kept"]) for r in runs}),
        "sizes": sorted({r["relationships"] for r in runs}),
        "all_verified": all(r["verified"] for r in runs),
        "runs": runs,
        "relate_db": committed["versions"]["relate_db"],
        "machine": f"{platform.system()} {platform.machine()}",
        "python": platform.python_version(),
        "recorded": time.strftime("%Y-%m-%d %H:%M %z"),
    }
    (ROOT / "evidence" / "seeds.json").write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
    print(json.dumps({k: out[k] for k in ("distinct_witnesses", "sizes", "all_verified")}))


if __name__ == "__main__":
    main()
