"""Re-prove the committed witnesses on a second engine: Neo4j.

`witness check` re-proves a witness on two surfaces of Relate (the Python API and the CLI): that rules out a mistake
in Witness, not one in the engine. This script loads each witness's rebuild script (`witnesses/<name>.cypher`, one
literal CREATE) into an EMPTY Neo4j database and repeats the proof there: the predicate holds on the loaded graph
(sufficiency), and with each relationship deleted alone inside a transaction that is rolled back, it stops holding
(necessity). Every verdict is compared with the one the manifest records for Relate.

The statement is the manifest's own, with its comments stripped and nothing else changed. It calls `coll.sort()`,
which Neo4j has in Cypher 25 and not in Cypher 5, so the script refuses a database whose default language is not
Cypher 25. (The first record of this run, 2026-11-27, ordered the hub countries before `collect()` instead; the
verdicts were the same.)

    docker run -d --rm --name witness-recheck -p 127.0.0.1:7690:7687 -e NEO4J_AUTH=neo4j/$NEO4J_PASSWORD \\
        neo4j:2026.10.2-community
    NEO4J_PASSWORD=... uv run --with neo4j python bench/neo4j_recheck.py --bolt bolt://127.0.0.1:7690
        -> evidence/neo4j-recheck.json

The database must be empty (the script refuses otherwise) and is left empty. The password is read from the
environment, never printed and never written.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from neo4j import GraphDatabase  # noqa: E402

from witness.canon import canon_rows, same_answer  # noqa: E402
from witness.export import display_name, validate_witness_script  # noqa: E402
from witness.guard import strip_comments  # noqa: E402
from witness.predicates import answer_sha  # noqa: E402

WITNESSES = ("two-hub", "direction-bug", "wrong-answer")
DELETE_ONE = "MATCH ()-[r]->() WHERE elementId(r) = $id DELETE r RETURN count(*) AS n"
RELS = "MATCH (a)-[r]->(b) RETURN elementId(r) AS id, properties(a) AS a, type(r) AS t, properties(b) AS b"


def recheck(session, name: str) -> dict:
    man = json.loads((ROOT / "witnesses" / f"{name}.manifest.json").read_text())
    script = (ROOT / "witnesses" / f"{name}.cypher").read_text()
    validate_witness_script(script)  # one literal CREATE, the same gate `witness check` applies
    cmp, pred, params = man["comparison"], man["predicate"], man["params"]
    kind = pred["kind"]
    assert kind in ("keep", "disagree") or (kind == "differs" and not pred["loose"]), pred
    statements = [man["statement"]] + ([pred["other_statement"]] if kind == "disagree" else [])
    queries = [strip_comments(s) for s in statements]  # the statement Relate ran, unchanged
    columns = man["baseline"]["columns"]

    def answers(run) -> list:
        return [
            canon_rows(
                [r.data() for r in run(q, params)],
                columns,
                strict_lists=cmp["strict_lists"],
                digits=cmp["float_digits"],
            )
            for q in queries
        ]

    def holds(ans: list) -> bool:
        if kind == "disagree":
            return not same_answer(ans[0], ans[1])
        return answer_sha(ans[0]) == man["baseline"]["sha256"]  # keep, and strict differs (the same wrong answer)

    assert session.run("MATCH (n) RETURN count(n) AS c").single()["c"] == 0, "the Neo4j database is not empty"
    body = "\n".join(ln for ln in script.splitlines() if not ln.startswith("//")).strip().rstrip(";")
    session.run(body).consume()
    try:
        counts = (
            session.run("MATCH (n) RETURN count(n) AS c").single()["c"],
            session.run("MATCH ()-[r]->() RETURN count(r) AS c").single()["c"],
        )
        assert counts == (man["witness"]["nodes"], man["witness"]["relationships"]), counts
        sufficient = holds(answers(session.run))
        rels = {f"({display_name(r['a'])})-[:{r['t']}]->({display_name(r['b'])})": r["id"] for r in session.run(RELS)}
        recorded = {p["element"]: p["necessary"] for p in man["check"]["probes"] if p["kind"] == "rel"}
        assert len(rels) == counts[1] == len(recorded), "two relationships share endpoints and type"
        assert set(rels) == set(recorded), "the loaded graph and the manifest's probes name different relationships"
        probes = []
        for element in sorted(rels):
            tx = session.begin_transaction()
            try:
                deleted = tx.run(DELETE_ONE, id=rels[element]).single()["n"]
                assert deleted == 1, f"{element}: deleted {deleted} relationships, expected exactly 1"
                necessary = not holds(answers(tx.run))
            finally:
                tx.rollback()
            probes.append(
                {"element": element, "necessary_on_neo4j": necessary, "necessary_on_relate": recorded[element]}
            )
        after = session.run("MATCH ()-[r]->() RETURN count(r) AS c").single()["c"]
        assert after == counts[1], "rollback residue on Neo4j"
    finally:
        session.run("MATCH (n) DETACH DELETE n").consume()
    n = len(probes)
    necessary = sum(p["necessary_on_neo4j"] for p in probes)
    return {
        "witness": f"witnesses/{name}.cypher",
        "predicate": kind,
        "relate_check": man["check"]["check_text"],
        "nodes": counts[0],
        "relationships": counts[1],
        "sufficient_on_neo4j": sufficient,
        "necessary_on_neo4j": necessary,
        "probes": n,
        "agree_with_relate": sum(p["necessary_on_neo4j"] == p["necessary_on_relate"] for p in probes),
        "neo4j_check": f"{necessary} of {n} " + man["check"]["check_text"].split(" (")[0].split(" ", 3)[3],
        "rows": probes,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--bolt", default="bolt://127.0.0.1:7690")
    ap.add_argument("--user", default="neo4j")
    a = ap.parse_args()
    password = os.environ.get("NEO4J_PASSWORD")
    if not password:
        raise SystemExit("set NEO4J_PASSWORD in the environment")
    driver = GraphDatabase.driver(a.bolt, auth=(a.user, password))
    driver.verify_connectivity()
    t0 = time.perf_counter()
    with driver.session() as s:
        comps = s.run(
            "CALL dbms.components() YIELD name, versions, edition RETURN name, versions, edition"
        ).data()
        lang = s.run("SHOW DATABASES YIELD name, defaultLanguage, home WHERE home RETURN defaultLanguage AS l").single()
        language = lang["l"] if lang else None
        if language != "CYPHER 25":
            raise SystemExit(f"the database's default language is {language}; the statements need Cypher 25")
        results = [recheck(s, name) for name in WITNESSES]
    driver.close()
    ok = all(
        r["sufficient_on_neo4j"] and r["necessary_on_neo4j"] == r["probes"] == r["agree_with_relate"] for r in results
    )
    out = {
        "schema": "witness.neo4j-recheck/v1",
        "what": "each committed witness's rebuild script loaded into an empty Neo4j database; sufficiency, then every "
        "relationship deleted alone in a rolled-back transaction; verdicts compared with the manifest's (Relate)",
        "generated": time.strftime("%Y-%m-%d %H:%M:%S %z"),
        "neo4j": comps,
        "default_language": language,
        "statement": "each manifest's statement with its comments stripped, otherwise as Relate ran it",
        "machine": f"{platform.system()} {platform.release()} {platform.machine()}, Python {platform.python_version()}",
        "seconds": round(time.perf_counter() - t0, 1),
        "all_agree": ok,
        "witnesses": results,
    }
    (ROOT / "evidence" / "neo4j-recheck.json").write_text(json.dumps(out, indent=1) + "\n")
    for r in results:
        print(
            f"{r['witness']}: sufficient {r['sufficient_on_neo4j']} · {r['neo4j_check']} on Neo4j · "
            f"{r['agree_with_relate']} of {r['probes']} verdicts agree with Relate"
        )
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
