"""Run the headline reduction twice from fresh copies and record whether the .cypher is byte-identical.

Writes evidence/determinism.json. Usage: uv run python scripts/determinism.py
"""

from __future__ import annotations

import hashlib
import json
import platform
import tempfile
from pathlib import Path

from witness import __version__
from witness.pipeline import Request, reduce_request, relate_version

ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    q = (ROOT / "queries" / "two-hub.cypher").read_text()
    runs = []
    with tempfile.TemporaryDirectory() as tmp:
        for i in range(2):
            o = reduce_request(
                Request(
                    source=ROOT / "data" / "air-routes.rl",
                    statement=q,
                    params={"country": "MX", "dest": "MEX"},
                    strict_lists=True,
                    ledger=None,
                    use_cli=False,
                    name="two-hub",
                    out_dir=Path(tmp) / str(i),
                )
            )
            body = Path(o.files["cypher"]).read_bytes()
            runs.append(
                {
                    "run": i + 1,
                    "cypher_sha256": hashlib.sha256(body).hexdigest(),
                    "trials": o.run["trials"],
                    "inconclusive": o.run["inconclusive"],
                    "witness_rels": o.run["final_counts"][1],
                    "reduction_s": o.run["seconds"],
                    "verified": o.verified,
                }
            )
    out = {
        "query": "queries/two-hub.cypher",
        "params": {"country": "MX", "dest": "MEX"},
        "seed": 0,
        "byte_identical": runs[0]["cypher_sha256"] == runs[1]["cypher_sha256"],
        "runs": runs,
        "witness": __version__,
        "relate_db": relate_version(),
        "python": platform.python_version(),
        "machine": f"{platform.machine()} {platform.system()} {platform.release()}",
    }
    (ROOT / "evidence" / "determinism.json").write_text(json.dumps(out, indent=2) + "\n")
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
