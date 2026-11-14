"""Build data/air-routes.rl and data/air-routes.cypher from Kelvin Lawrence's air-routes CSVs.

Deterministic: downloads the two CSVs at a pinned commit, checks their SHA-256, sorts every row by key,
and writes a byte-stable Cypher script plus a Relate single-file store. Nobody has to run this to use
Witness; the committed `.rl` is what the demo opens.

    uv run python scripts/build_source.py            # writes data/air-routes.{rl,cypher} + data/source-stats.json
    uv run python scripts/build_source.py --slice    # spike slice: routes with both ends in Asia/Oceania
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import sys
import urllib.request
from pathlib import Path

os.environ.setdefault("DO_NOT_TRACK", "1")

import relate  # noqa: E402

COMMIT = "efd3b1ae636f602577cfbccb16ecfe358a02ee36"
BASE = f"https://raw.githubusercontent.com/krlawrence/graph/{COMMIT}/sample-data/"
FILES = {
    "air-routes-latest-nodes.csv": "f921d4f1dd429418a96c17c49d42b42ce6cf5d6c9772e784556a631760b53579",
    "air-routes-latest-edges.csv": "01749b2717ccca5efe11c4b1f5e25f8c59ab682014104f3fb8bdb67e23b101b5",
}
ROOT = Path(__file__).resolve().parent.parent
BATCH = 500


def fetch(cache: Path) -> dict[str, Path]:
    cache.mkdir(parents=True, exist_ok=True)
    out = {}
    for name, sha in FILES.items():
        path = cache / name
        if not path.exists():
            with urllib.request.urlopen(BASE + name, timeout=60) as resp:  # noqa: S310 (pinned https URL)
                path.write_bytes(resp.read())
        got = hashlib.sha256(path.read_bytes()).hexdigest()
        if got != sha:
            sys.exit(f"SHA-256 mismatch for {name}: {got} != {sha}")
        out[name] = path
    return out


def _int(v: str):
    return int(v) if v != "" else None


def _float(v: str):
    return float(v) if v != "" else None


def parse(files: dict[str, Path], slice_continents: set[str] | None = None) -> dict:
    airports, countries, continents = {}, {}, {}
    with files["air-routes-latest-nodes.csv"].open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            nid = int(row["~id"])
            label = row["~label"]
            if label == "airport":
                props = {
                    "id": nid,
                    "iata": row["code:string"],
                    "icao": row["icao:string"],
                    "city": row["city:string"],
                    "descr": row["desc:string"],
                    "region": row["region:string"],
                    "runways": _int(row["runways:int"]),
                    "longest": _int(row["longest:int"]),
                    "altitude": _int(row["elev:int"]),
                    "lat": _float(row["lat:double"]),
                    "lon": _float(row["lon:double"]),
                }
                airports[nid] = {k: v for k, v in props.items() if v not in (None, "")}
            elif label == "country":
                countries[nid] = {"code": row["code:string"], "name": row["desc:string"]}
            elif label == "continent":
                continents[nid] = {"code": row["code:string"], "name": row["desc:string"]}
            # the single `version` node names the dataset author: dropped (credit lives in data/SOURCE.md)

    routes: dict[tuple[int, int], int] = {}
    in_country: dict[int, int] = {}
    on_continent: dict[int, int] = {}
    unresolved = duplicates = 0
    with files["air-routes-latest-edges.csv"].open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            src, dst, label = int(row["~from"]), int(row["~to"]), row["~label"]
            if label == "route":
                if src not in airports or dst not in airports:
                    unresolved += 1
                    continue
                if (src, dst) in routes:
                    duplicates += 1
                    continue
                routes[(src, dst)] = _int(row["dist:int"])
            elif label == "contains":
                if src in countries and dst in airports:
                    in_country[dst] = src
                elif src in continents and dst in airports:
                    on_continent[dst] = src
                else:
                    unresolved += 1

    if slice_continents is not None:
        cont_by_code = {v["code"]: k for k, v in continents.items()}
        keep_cont = {cont_by_code[c] for c in slice_continents}
        keep = {a for a in airports if on_continent.get(a) in keep_cont}
        routes = {k: v for k, v in routes.items() if k[0] in keep and k[1] in keep}
        airports = {k: v for k, v in airports.items() if k in keep}
        in_country = {a: c for a, c in in_country.items() if a in keep}
        on_continent = {a: c for a, c in on_continent.items() if a in keep}
        countries = {k: v for k, v in countries.items() if k in set(in_country.values())}
        continents = {k: v for k, v in continents.items() if k in set(on_continent.values())}

    # canonical-key collisions are refused (spec: Witness needs distinguishable elements)
    assert len({a["id"] for a in airports.values()}) == len(airports)
    assert len({c["code"] for c in countries.values()}) == len(countries)
    assert len({c["code"] for c in continents.values()}) == len(continents)
    return {
        "airports": [airports[k] for k in sorted(airports)],
        "countries": sorted(countries.values(), key=lambda c: c["code"]),
        "continents": sorted(continents.values(), key=lambda c: c["code"]),
        "routes": [{"s": s, "d": d, "dist": routes[(s, d)]} for s, d in sorted(routes)],
        "in_country": [{"a": a, "c": countries[c]["code"]} for a, c in sorted(in_country.items())],
        "on_continent": [{"a": a, "c": continents[c]["code"]} for a, c in sorted(on_continent.items())],
        "unresolved_dropped": unresolved,
        "duplicate_routes_collapsed": duplicates,
    }


CONSTRAINTS = [
    "CREATE CONSTRAINT airport_id IF NOT EXISTS FOR (a:Airport) REQUIRE a.id IS UNIQUE",
    "CREATE CONSTRAINT country_code IF NOT EXISTS FOR (c:Country) REQUIRE c.code IS UNIQUE",
    "CREATE CONSTRAINT continent_code IF NOT EXISTS FOR (c:Continent) REQUIRE c.code IS UNIQUE",
]
STMTS = {
    "countries": "UNWIND $rows AS r CREATE (:Country {code: r.code, name: r.name})",
    "continents": "UNWIND $rows AS r CREATE (:Continent {code: r.code, name: r.name})",
    "airports": "UNWIND $rows AS r CREATE (a:Airport) SET a = r",
    "in_country": (
        "UNWIND $rows AS r MATCH (a:Airport {id: r.a}), (c:Country {code: r.c}) CREATE (a)-[:IN_COUNTRY]->(c)"
    ),
    "on_continent": (
        "UNWIND $rows AS r MATCH (a:Airport {id: r.a}), (c:Continent {code: r.c}) CREATE (a)-[:ON_CONTINENT]->(c)"
    ),
    "routes": (
        "UNWIND $rows AS r MATCH (s:Airport {id: r.s}), (d:Airport {id: r.d}) "
        "CREATE (s)-[:HAS_ROUTE {dist: r.dist}]->(d)"
    ),
}
ORDER = ["countries", "continents", "airports", "in_country", "on_continent", "routes"]


def lit(v) -> str:
    """A Cypher literal for a JSON-like value (deterministic)."""
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        return repr(v)
    if isinstance(v, str):
        return "'" + v.replace("\\", "\\\\").replace("'", "\\'") + "'"
    if isinstance(v, list):
        return "[" + ", ".join(lit(x) for x in v) + "]"
    if isinstance(v, dict):
        return "{" + ", ".join(f"{k}: {lit(v[k])}" for k in sorted(v)) + "}"
    raise TypeError(type(v))


def batches(rows: list, n: int = BATCH):
    for i in range(0, len(rows), n):
        yield rows[i : i + n]


def write_cypher(data: dict, path: Path) -> None:
    lines = [f"// air-routes v0.89 (krlawrence/graph @ {COMMIT}), Apache-2.0; generated by scripts/build_source.py"]
    lines += [s + ";" for s in CONSTRAINTS]
    for key in ORDER:
        for chunk in batches(data[key]):
            lines.append(STMTS[key].replace("$rows", lit(chunk), 1) + ";")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_rl(data: dict, path: Path) -> dict:
    if path.exists():
        path.unlink()
    db = relate.Database(str(path))
    for s in CONSTRAINTS:
        db.execute(s)
    for key in ORDER:
        for chunk in batches(data[key]):
            db.execute(STMTS[key], {"rows": chunk})
    counts = {"nodes": db.node_count(), "relationships": db.relationship_count()}
    db.close()
    return counts


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", default=str(ROOT / "out" / "csv-cache"))
    ap.add_argument("--slice", action="store_true", help="spike slice: both route ends in AS/OC")
    ap.add_argument("--out", default=None, help="store path (default data/air-routes.rl, or out/slice.rl)")
    args = ap.parse_args()
    files = fetch(Path(args.cache))
    data = parse(files, {"AS", "OC"} if args.slice else None)
    if args.slice:
        rl = Path(args.out or ROOT / "out" / "slice.rl")
        rl.parent.mkdir(parents=True, exist_ok=True)
        counts = write_rl(data, rl)
        print(json.dumps({"store": str(rl), **counts, "routes": len(data["routes"])}))
        return
    rl = Path(args.out or ROOT / "data" / "air-routes.rl")
    cy = rl.with_suffix(".cypher")
    write_cypher(data, cy)
    counts = write_rl(data, rl)
    stats = {
        "source": f"krlawrence/graph@{COMMIT}",
        "csv_sha256": FILES,
        "airports": len(data["airports"]),
        "countries": len(data["countries"]),
        "continents": len(data["continents"]),
        "has_route": len(data["routes"]),
        "in_country": len(data["in_country"]),
        "on_continent": len(data["on_continent"]),
        "unresolved_dropped": data["unresolved_dropped"],
        "duplicate_routes_collapsed": data["duplicate_routes_collapsed"],
        "store_counts": counts,
        "cypher_sha256": hashlib.sha256(cy.read_bytes()).hexdigest(),
        "rl_sha256": hashlib.sha256(rl.read_bytes()).hexdigest(),
        "rl_bytes": rl.stat().st_size,
        "relate_db": relate.__version__,
    }
    (rl.parent / "source-stats.json").write_text(json.dumps(stats, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(stats, indent=2))


if __name__ == "__main__":
    main()
