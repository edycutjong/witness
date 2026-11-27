"""The committed stores as files: bytes and SHA-256, and what is (and is not) byte-identical between two runs.

A witness is handed over as a file, so this records the file facts: the size of every committed `.rl`, and, for the
headline, a fresh reduction compared with the committed one. The rebuild script (`.cypher`) is byte-identical; the
`.rl` store written from it is not (the same graph, the same size, different bytes), so the hash to pin is the
script's. `witness check` rebuilds a store from the script and requires the same graph and the same answer.

    uv run python scripts/store_bytes.py     -> evidence/store-bytes.json
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import tempfile
from pathlib import Path

os.environ.setdefault("DO_NOT_TRACK", "1")

from witness import __version__  # noqa: E402
from witness.pipeline import Request, reduce_request, relate_version  # noqa: E402
from witness.store import Scratch  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
STORES = [
    "data/air-routes.rl",
    "witnesses/two-hub.rl",
    "witnesses/direction-bug.rl",
    "witnesses/wrong-answer.rl",
    "fixtures/mex-foreign.rl",
    "witness.rl",
]


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def graph(p: Path) -> tuple[frozenset, frozenset]:
    sc = Scratch.open_copy(p)
    try:
        return frozenset(sc.node_keys.values()), frozenset(sc.rel_keys.values())
    finally:
        sc.close()


def main() -> None:
    os.chdir(ROOT)
    man = json.loads(Path("witnesses/two-hub.manifest.json").read_text())
    committed_rl, committed_cy = Path("witnesses/two-hub.rl"), Path("witnesses/two-hub.cypher")
    with tempfile.TemporaryDirectory(prefix="witness-bytes-") as d:
        o = reduce_request(
            Request(
                source=Path(man["source"]["path"]),
                statement=man["statement"],
                params=man["params"],
                strict_lists=man["comparison"]["strict_lists"],
                seed=man["seed"],
                name="two-hub",
                out_dir=Path(d),
                ledger=None,
                use_cli=False,
            )
        )
        fresh_rl, fresh_cy = Path(o.files["rl"]), Path(o.files["cypher"])
        a, b = committed_rl.read_bytes(), fresh_rl.read_bytes()
        rerun = {
            "what": "the headline reduction run again (same query, parameters and seed), "
            "compared with the committed files",
            "verified": o.verified,
            "cypher_sha256": sha(fresh_cy),
            "cypher_byte_identical": fresh_cy.read_bytes() == committed_cy.read_bytes(),
            "rl_sha256": sha(fresh_rl),
            "rl_bytes": len(b),
            "rl_byte_identical": a == b,
            "rl_bytes_that_differ": sum(x != y for x, y in zip(a, b, strict=True)) if len(a) == len(b) else None,
            "rl_same_graph": graph(fresh_rl) == graph(committed_rl),
        }
    assert rerun["verified"] and rerun["cypher_byte_identical"] and rerun["rl_same_graph"], rerun
    out = {
        "schema": "witness.store-bytes/v1",
        "stores": [{"path": p, "bytes": Path(p).stat().st_size, "sha256": sha(Path(p))} for p in STORES],
        "headline_script": {
            "path": str(committed_cy),
            "bytes": committed_cy.stat().st_size,
            "sha256": sha(committed_cy),
        },
        "rerun": rerun,
        "witness": __version__,
        "relate_db": relate_version(),
        "python": platform.python_version(),
        "machine": f"{platform.machine()} {platform.system()} {platform.release()}",
    }
    Path("evidence/store-bytes.json").write_text(json.dumps(out, indent=1) + "\n")
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
