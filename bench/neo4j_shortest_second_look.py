"""A second look at the shortest-path queries of the differential run that Neo4j did not finish.

The recorded run (`bench/differential.py`, `evidence/differential-answers.jsonl`) loads the graph into an empty Neo4j
without the store's three uniqueness constraints, and Neo4j did not finish five shortest-path queries within the run's
20 s. This script reads the plan Neo4j chooses for each of them and asks them again, in the same container settings,
in three setups:

    as recorded     no constraint: the plan only (the recorded run holds what running them gave)
    store           the store's three uniqueness constraints (Airport.id, Country.code, Continent.code)
    store + iata    those, and a uniqueness constraint on Airport.iata, the property each of the five looks its two
                    airports up by. The committed store has no such constraint, so this setup gives Neo4j an index
                    that Relate does not have: it is here to find out why the queries did not finish, and to compare
                    the answers once they do.

Each query runs in its own transaction with the run's 20 s timeout and is rolled back. Every answer is compared with
what relate-db 1.0.1 and 1.3.0 answered in the recorded run. The setup that gives Neo4j the extra index runs first and
the slow one last; `--skip-slow` leaves the slow one out (its plans are still read).

    docker run -d --rm --name witness-diff -p 127.0.0.1:7691:7687 -m 4g -e NEO4J_AUTH=neo4j/$NEO4J_PASSWORD \\
        -e NEO4J_server_memory_heap_max__size=2g -e NEO4J_dbms_memory_transaction_total_max=1g \\
        neo4j:2026.10.2-community
    NEO4J_BOLT=bolt://127.0.0.1:7691 NEO4J_USER=neo4j NEO4J_PASSWORD=... \\
        uv run --with neo4j python bench/neo4j_shortest_second_look.py
        -> evidence/neo4j-shortest-second-look.json

The password is read from the environment (or ~/.config/witness/neo4j.env), never printed and never written.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import platform
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import differential as D  # noqa: E402 - the recorded run's own loader settings, timeout and answer form

ROOT = D.ROOT
ANSWERS = ROOT / "evidence" / "differential-answers.jsonl"
OUT = ROOT / "evidence" / "neo4j-shortest-second-look.json"
STORE_CONSTRAINTS = {  # as scripts/build_source.py creates them in the committed store
    "airport_id": "CREATE CONSTRAINT airport_id IF NOT EXISTS FOR (a:Airport) REQUIRE a.id IS UNIQUE",
    "country_code": "CREATE CONSTRAINT country_code IF NOT EXISTS FOR (c:Country) REQUIRE c.code IS UNIQUE",
    "continent_code": "CREATE CONSTRAINT continent_code IF NOT EXISTS FOR (c:Continent) REQUIRE c.code IS UNIQUE",
}
IATA_CONSTRAINT = {
    "airport_iata": "CREATE CONSTRAINT airport_iata IF NOT EXISTS FOR (a:Airport) REQUIRE a.iata IS UNIQUE"
}


def operators(plan: dict) -> list[str]:
    """The plan's operators, root first, children in order (`@neo4j` and the like dropped)."""
    out = [str(plan.get("operatorType", "?")).split("@")[0]]
    for child in plan.get("children") or []:
        out += operators(child)
    return out


def read_plans(eng, qs: list[dict]) -> dict:
    plans = {}
    with eng.driver.session(database=eng.database) as s:
        for q in qs:
            plan = s.run("EXPLAIN " + q["cypher"]).consume().plan or {}
            ops = operators(plan)
            plans[q["id"]] = {"operators": ops, "shortest": next((o for o in ops if "Shortest" in o), None)}
    return plans


def ask(eng, qs: list[dict]) -> dict:
    """Each query in its own transaction with the run's timeout, rolled back: an answer, a timeout or an error."""
    out = {}
    for q in qs:
        qid = q["id"]
        t0 = time.perf_counter()
        try:
            with eng.driver.session(database=eng.database) as s:
                tx = s.begin_transaction(timeout=D.TIMEOUT)
                try:
                    res = tx.run(q["cypher"])
                    cols = list(res.keys())
                    rows = [dict(zip(cols, r.values(), strict=True)) for r in res]
                finally:
                    with contextlib.suppress(Exception):  # a transaction the server already ended
                        tx.rollback()
        except Exception as e:  # noqa: BLE001
            msg = f"{type(e).__name__}: {getattr(e, 'message', None) or e}"
            timed_out = "TransactionTimedOut" in (str(getattr(e, "code", "")) + msg)
            ms = round((time.perf_counter() - t0) * 1000, 2)
            out[qid] = {"id": qid, "kind": "timeout" if timed_out else "error", "error": msg[:300], "ms": ms}
            continue
        out[qid] = D.answer_record(qid, rows, cols, (time.perf_counter() - t0) * 1000)
        print(f"  {qid}: {out[qid]['kind']} in {out[qid]['ms']} ms", flush=True)
    return out


def against(recorded: dict, got: dict) -> dict:
    """Per query: this answer against what each relate-db release answered in the recorded run."""
    return {
        qid: {
            "relate_1_0_1": D.classify(recorded[qid]["relate_1_0_1"], rec),
            "relate_1_3_0": D.classify(recorded[qid]["relate_1_3_0"], rec),
        }
        for qid, rec in got.items()
    }


def constraints_now(eng) -> list[str]:
    with eng.driver.session(database=eng.database) as s:
        q = "SHOW CONSTRAINTS YIELD name, labelsOrTypes, properties RETURN name, labelsOrTypes AS l, properties AS p"
        return sorted(f"{r['name']}: {r['l'][0]}.{r['p'][0]}" for r in s.run(q))


def run_statements(eng, statements) -> None:
    with eng.driver.session(database=eng.database) as s:
        for st in statements:
            s.run(st).consume()
        s.run("CALL db.awaitIndexes(300)").consume()


def main() -> None:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    ap.add_argument("--skip-slow", action="store_true", help="do not run the five with the store's constraints only")
    args = ap.parse_args()

    import neo4j

    from witness.engines import Neo4jEngine
    from witness.guard import GuardedQuery
    from witness.store import Scratch

    recorded = {}
    for line in ANSWERS.read_text().splitlines():
        r = json.loads(line)
        if r["neo4j"]["kind"] == "timeout":
            recorded[r["id"]] = r
    by_id = {q["id"]: q for q in map(json.loads, D.QUERIES.read_text().splitlines())}
    qs = [by_id[i] for i in recorded]
    print(f"{len(qs)} queries Neo4j did not finish in the recorded run: {', '.join(recorded)}", flush=True)

    sc = Scratch.open_copy(D.SRC)
    eng = Neo4jEngine(sc, GuardedQuery(text="RETURN 1", params={}, exec_text="RETURN 1"))
    sc.close()
    created: list[str] = []
    doc: dict = {
        "schema": "witness.neo4j-second-look/v1",
        "what": "the shortest-path queries Neo4j did not finish in the differential run: the plan Neo4j chooses and "
        "what it answers, without constraints, with the store's three, and with one more on Airport.iata",
        "queries": {i: by_id[i]["cypher"] for i in recorded},
        "timeout_s": D.TIMEOUT,
        "recorded_run": {
            i: {"kind": r["neo4j"]["kind"], "ended_after_ms": r["neo4j"]["ms"]} for i, r in recorded.items()
        },
        "setups": {},
    }

    def save() -> None:
        OUT.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n")

    try:
        with eng.driver.session(database=eng.database) as s:
            lang = s.run(
                "SHOW DATABASES YIELD name, defaultLanguage WHERE name = $n RETURN defaultLanguage AS l", n=eng.database
            ).single()
            show = "SHOW SETTINGS YIELD name, value WHERE name IN $names RETURN name, value"
            settings = {r["name"]: r["value"] for r in s.run(show, names=list(D.NEO4J_SETTINGS))}
            iata = s.run("MATCH (a:Airport) RETURN count(a) AS airports, count(DISTINCT a.iata) AS distinct_iata")
            doc["airport_iata"] = dict(iata.single() or {})
        doc["neo4j"] = {
            "version": eng.label,
            "default_language": lang["l"] if lang else None,
            "python_driver": neo4j.__version__,
            "settings": settings,
            "graph": "loaded by Witness from data/air-routes.rl, as in the recorded run",
        }
        assert constraints_now(eng) == [], "the database must start without constraints"

        print("as recorded (no constraint): plans", flush=True)
        doc["setups"]["as_recorded"] = {"constraints": [], "plans": read_plans(eng, qs), "ran": False}
        save()

        print("store constraints: plans", flush=True)
        run_statements(eng, STORE_CONSTRAINTS.values())
        created += list(STORE_CONSTRAINTS)
        store_setup = {"constraints": constraints_now(eng), "plans": read_plans(eng, qs), "ran": False}
        doc["setups"]["store"] = store_setup
        save()

        print("store + Airport.iata: plans, then the five", flush=True)
        run_statements(eng, IATA_CONSTRAINT.values())
        created += list(IATA_CONSTRAINT)
        got = ask(eng, qs)
        doc["setups"]["store_iata"] = {
            "constraints": constraints_now(eng),
            "plans": read_plans(eng, qs),
            "ran": True,
            "answers": got,
            "against_the_recorded_relate_answers": against(recorded, got),
        }
        save()

        if not args.skip_slow:
            print("store constraints only: the five (each may run long past its 20 s)", flush=True)
            run_statements(eng, [f"DROP CONSTRAINT {name} IF EXISTS" for name in IATA_CONSTRAINT])
            created = [c for c in created if c not in IATA_CONSTRAINT]
            assert constraints_now(eng) == store_setup["constraints"]
            got = ask(eng, qs)
            store_setup.update(ran=True, answers=got, against_the_recorded_relate_answers=against(recorded, got))
            save()
    finally:
        with contextlib.suppress(Exception):
            run_statements(eng, [f"DROP CONSTRAINT {name} IF EXISTS" for name in created])
        eng.close()
    doc.update(
        machine=f"{platform.system()} {platform.machine()}",
        python=platform.python_version(),
        recorded=time.strftime("%Y-%m-%d %H:%M %z"),
    )
    save()
    print(f"wrote {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
