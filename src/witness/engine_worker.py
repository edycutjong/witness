"""The other-engine worker: ``python -m witness.engine_worker spec.json`` on any relate-db release.

It opens its own byte copy of the store, says hello (its relate-db version and counts), then answers one JSON line per
request on stdin: ``trial`` (delete the elements named by canonical key, run the query, roll back, return the canonical
answer), ``commit`` (delete them for good) and ``stop``. It imports only the parts of Witness that need nothing but
relate-db, so it runs under whichever release the interpreter has.
"""

from __future__ import annotations

import json
import os
import sys
import time

os.environ.setdefault("DO_NOT_TRACK", "1")


def serve(spec: dict, inp, out) -> int:
    import relate

    from .engines import query_from_spec, wire_answer
    from .predicates import answer_of
    from .store import Scratch

    gq = query_from_spec(spec["query"])
    sc = Scratch.open_copy(spec["source"])

    def send(d: dict) -> None:
        out.write(json.dumps(d) + "\n")
        out.flush()

    def ids(msg: dict) -> tuple[list[str], list[str]]:
        rel_by_key = {k: i for i, k in sc.rel_keys.items()}
        node_by_key = {k: i for i, k in sc.node_keys.items()}
        missing = [k for k in msg["rels"] if k not in rel_by_key] + [k for k in msg["nodes"] if k not in node_by_key]
        if missing:
            raise KeyError(f"{len(missing)} element(s) not in this store")
        return [rel_by_key[k] for k in msg["rels"]], [node_by_key[k] for k in msg["nodes"]]

    try:
        n, r = sc.counts()
        send({"relate_db": relate.__version__, "nodes": n, "relationships": r})
        for line in inp:
            msg = json.loads(line)
            op = msg.get("op")
            if op == "stop":
                send({"ok": True})
                return 0
            t0 = time.perf_counter()
            try:
                rels, nodes = ids(msg)
                if op == "commit":
                    sc.commit_delete(rels, nodes)
                    send({"ok": True})
                    continue
                t = sc.trial_many([(gq.exec_text, gq.params)], rels, nodes)
                if t.error is not None:
                    send({"error": t.error[:300], "ms": t.ms})
                    continue
                assert t.results is not None  # error is None, so the trial returned its results
                rows, cols = t.results[0]
                ans = answer_of(
                    gq, rows, cols, keyer=sc.keyer, strict_lists=spec["strict_lists"], digits=spec["digits"]
                )
                send({**wire_answer(ans), "ms": t.ms})
            except Exception as e:  # noqa: BLE001 - reported to the parent as an inconclusive trial
                send({"error": f"{type(e).__name__}: {str(e)[:300]}", "ms": (time.perf_counter() - t0) * 1000})
        return 0
    finally:
        sc.close()


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    with open(argv[0]) as f:
        spec = json.load(f)
    return serve(spec, sys.stdin, sys.stdout)


if __name__ == "__main__":
    sys.exit(main())
