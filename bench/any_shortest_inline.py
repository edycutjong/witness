"""ANY SHORTEST over an unbounded quantified relationship, with and without an inline relationship predicate.

Found by the differential run (queries/differential.jsonl d162): on air-routes, `ANY SHORTEST ... -[r:HAS_ROUTE WHERE
r.dist < 50000]->+ ...`, a predicate every route satisfies, gives no answer and the process grows past 15 GB within
seconds, while the same query without the predicate answers 3 hops in about 13 ms. This script measures it on a small
graph: n nodes in a ring, each with a second edge 7 ahead (2n relationships, every `w` = 1), from node 0 to node 2 (a
2-hop answer). Each run is its own process with a watchdog, so a run that does not return is killed. The watchdog's
clock starts when the child says the graph is built and the query is about to run, so "no answer within 8 s" is 8 s of
the query alone, the same span the reported `ms` covers; a child that ends on its own is recorded as a crash:

    for v in 1.0.1 1.3.0 1.2.0; do uv run --no-project --with relate-db==$v python bench/any_shortest_inline.py; done \\
        > evidence/any-shortest-inline.jsonl
"""

from __future__ import annotations

import json
import os
import platform
import select
import subprocess
import sys
import time

os.environ.setdefault("DO_NOT_TRACK", "1")
WATCHDOG = 8.0
SIZES = (12, 14, 16, 18, 20)
FORMS = {
    "plain": "MATCH p = ANY SHORTEST (a:P {id: 0})-[:K]->+(b:P {id: 2}) RETURN length(p) AS l",
    "inline": "MATCH p = ANY SHORTEST (a:P {id: 0})-[r:K WHERE r.w < 100]->+(b:P {id: 2}) RETURN length(p) AS l",
}


def one(n: int, form: str) -> None:
    import relate

    db = relate.Database(":memory:")
    db.execute(f"UNWIND range(0, {n - 1}) AS i CREATE (:P {{id: i}})")
    db.execute(
        f"UNWIND range(0, {n - 1}) AS i MATCH (a:P {{id: i}}), (b:P {{id: (i + 1) % {n}}}), "
        f"(c:P {{id: (i + 7) % {n}}}) "
        "CREATE (a)-[:K {w: 1}]->(b), (a)-[:K {w: 1}]->(c)"
    )
    print(json.dumps({"ready": True, "rels": db.relationship_count()}), flush=True)  # the watchdog starts here
    t0 = time.perf_counter()
    rows = db.execute(FORMS[form]).data
    ms = round((time.perf_counter() - t0) * 1000, 1)
    print(json.dumps({"rows": rows, "ms": ms}), flush=True)


def line(p: subprocess.Popen, buf: bytearray, timeout: float) -> dict | None:
    """One JSON line from the child (read from the descriptor, so nothing hides in a buffer `select` cannot see);
    None when the child ended without one; TimeoutError when none came in time."""
    assert p.stdout is not None
    fd = p.stdout.fileno()
    deadline = time.monotonic() + timeout
    while b"\n" not in buf:
        left = deadline - time.monotonic()
        if left <= 0 or not select.select([fd], [], [], left)[0]:
            raise TimeoutError
        chunk = os.read(fd, 1 << 16)
        if not chunk:
            return None
        buf += chunk
    raw, _, rest = bytes(buf).partition(b"\n")
    buf[:] = rest
    return json.loads(raw)


def main() -> None:
    if len(sys.argv) == 3:
        one(int(sys.argv[1]), sys.argv[2])
        return
    import relate

    for n in SIZES:
        for form in FORMS:
            rec = {"relate_db": relate.__version__, "nodes": n, "form": form, "query": FORMS[form]}
            p = subprocess.Popen([sys.executable, __file__, str(n), form], stdout=subprocess.PIPE)
            buf = bytearray()
            try:
                ready = line(p, buf, 120.0)  # interpreter start, import and the graph build are not the query
                if ready:
                    rec["rels"] = ready["rels"]
                got = line(p, buf, WATCHDOG) if ready else None
                if got is None:
                    rec["result"] = f"crashed: the process ended (exit {p.wait()}) before answering"
                else:
                    rec.update(got)
            except TimeoutError:
                rec["result"] = f"no answer within {WATCHDOG:g} s (killed)"
            finally:
                p.kill()
                p.wait()
            rec["machine"] = f"{platform.system()} {platform.machine()}"
            print(json.dumps(rec), flush=True)


if __name__ == "__main__":
    main()
