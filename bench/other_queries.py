"""Other query shapes on the same graph: `witness why` on questions that are not the headline's.

Three that shrink (a path question, a top-k with ORDER BY + LIMIT, an EXISTS / NOT EXISTS pair) and one that cannot:
a count over the whole graph rests on everything it counts, so that run is stopped (here after --max-seconds) and
reported NOT verified. Each run is the product's own pipeline (`reduce_request`), written to a temp dir.

    uv run python bench/other_queries.py                     -> evidence/other-queries.json
    uv run python bench/other_queries.py --with-default-cap  also runs the count with the default 20,000-trial cap
                                                              and no time limit (about 18 minutes on an M1 Max)
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("DO_NOT_TRACK", "1")

from witness import __version__  # noqa: E402
from witness.pipeline import Request, reduce_request, relate_version  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "evidence" / "other-queries.json"
EXAMPLES = [  # (query file stem, parameters, the shape it exercises)
    (
        "fewest-flights",
        {"from": "JOG", "to": "KEF"},
        "a path question: allShortestPaths over a variable-length pattern",
    ),
    ("longest-nonstop", {"from": "CGK"}, "a top-k question: ORDER BY + LIMIT in the final RETURN"),
    ("domestic-only", {"country": "IS"}, "EXISTS and NOT EXISTS with no aggregation"),
]
COUNT = ("count-no-direct", {"dest": "MEX"}, "a count over the whole graph: it rests on everything it counts")
BOUND_S = 20.0


def question(statement: str, params: dict) -> str:
    q = next(ln[2:].strip() for ln in statement.splitlines() if ln.strip().startswith("//"))
    for k, v in params.items():
        q = q.replace(f"${k}", str(v))
    return q


def run(stem: str, params: dict, shape: str, tmp: Path, **limits) -> dict:
    path = f"queries/examples/{stem}.cypher"
    statement = (ROOT / path).read_text()
    t0 = time.perf_counter()
    o = reduce_request(
        Request(
            source=Path("data/air-routes.rl"),
            statement=statement,
            params=params,
            name=stem,
            out_dir=tmp / stem,
            ledger=None,
            **limits,
        )
    )
    assert o.check is not None
    return {
        "query": path,
        "shape": shape,
        "question": question(statement, params),
        "params": params,
        "command": f"uv run witness why -f {path} " + " ".join(f"--param {k}={v}" for k, v in params.items()),
        "answer": o.answer_rows,
        "warnings": o.warnings,
        "witness": o.manifest["witness"],
        "exhibits": [f"({x['start']})-[:{x['type']}]->({x['end']})" for x in o.exhibits][:50],
        "run": {k: o.run.get(k) for k in ("trials", "inconclusive", "seconds", "capped")},
        "check": o.check.text,
        "cli": o.check.cli_status,
        "verified": o.verified,
        "exit_code": o.exit_code,
        "reasons": o.reasons,
        "wall_clock_s": round(time.perf_counter() - t0, 1),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--with-default-cap", action="store_true", help="also run the count with the default trial cap")
    args = ap.parse_args()
    os.chdir(ROOT)
    prev = json.loads(OUT.read_text()) if OUT.exists() else {}
    with tempfile.TemporaryDirectory(prefix="witness-other-") as d:
        tmp = Path(d)
        examples = [run(s, p, shape, tmp) for s, p, shape in EXAMPLES]
        assert all(e["verified"] and e["exit_code"] == 0 for e in examples), examples
        stem, params, shape = COUNT
        bounded = run(stem, params, shape, tmp, max_seconds=BOUND_S, use_cli=False)
        bounded["command"] += f" --max-seconds {BOUND_S:g} --no-cli"
        assert bounded["exit_code"] == 3 and not bounded["verified"], bounded
        default_cap = prev.get("count_with_the_default_cap")
        if args.with_default_cap:
            default_cap = run(stem, params, shape, tmp, use_cli=False)
            default_cap["command"] += " --no-cli"
            assert default_cap["exit_code"] == 3 and not default_cap["verified"], default_cap
    man = json.loads((ROOT / "witnesses" / "two-hub.manifest.json").read_text())
    doc = {
        "schema": "witness.other-queries/v1",
        "what": "witness why on other query shapes, same graph; each run is the product's pipeline in a temp dir",
        "generated": time.strftime("%Y-%m-%d %H:%M:%S %z"),
        "witness": __version__,
        "relate_db": relate_version(),
        "machine": f"{platform.system()} {platform.release()} {platform.machine()}, Python {platform.python_version()}",
        "source": {"path": "data/air-routes.rl", **{k: man["source"][k] for k in ("nodes", "relationships")}},
        "examples": examples,
        "count_bounded": bounded,
        "count_with_the_default_cap": default_cap,
    }
    OUT.write_text(json.dumps(doc, indent=1) + "\n")
    for e in [*examples, bounded, *([default_cap] if default_cap else [])]:
        w = e["witness"]
        print(
            f"{e['query']}: {w['relationships']} relationships, {w['nodes']} nodes · {e['run']['trials']} trials · "
            f"{e['run']['seconds']} s · exit {e['exit_code']} · {e['check']}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
