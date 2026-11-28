"""The differential run's query d162 on the air-routes graph, with and without its inline relationship predicate.

d162 (`queries/differential.jsonl`) asks for ANY SHORTEST path from ZQN to AUS over routes shorter than 5,000 miles,
with the distance test written inline in the relationship pattern. No Relate release answered it in the differential
run. This script asks it, and the same question without the predicate, of whatever relate-db the interpreter has: each
form in its own process, on a byte copy of `data/air-routes.rl` opened read-only, under a watchdog that samples the
process's resident memory ten times a second. A run ends in one of three ways, and the line says which: an answer and
its time; the process ended on its own (with its exit code or signal); or the watchdog ended it, after 10 s or once
the process held more than 8 GiB. It imports nothing from Witness, so it runs under any release:

    for v in 1.0.1 1.3.0 1.4.0; do
      uv run --no-project --with relate-db==$v python bench/any_shortest_air_routes.py
    done > evidence/any-shortest-air-routes.jsonl

The small-graph measurement of the same form is `bench/any_shortest_inline.py`.
"""

from __future__ import annotations

import json
import os
import platform
import select
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("DO_NOT_TRACK", "1")
ROOT = Path(__file__).resolve().parent.parent
WATCHDOG = 10.0
RSS_CAP_MB = 8 * 1024
D162 = next(
    json.loads(x)["cypher"]
    for x in (ROOT / "queries" / "differential.jsonl").read_text().splitlines()
    if json.loads(x)["id"] == "d162"
)
INLINE = "-[r:HAS_ROUTE WHERE r.dist < 5000]->+"
assert D162.count(INLINE) == 1, "d162 is no longer the query this script knows"
FORMS = {"plain": D162.replace(INLINE, "-[:HAS_ROUTE]->+"), "inline": D162}


def one(form: str) -> None:
    import relate

    with tempfile.TemporaryDirectory(prefix="witness-any-shortest-") as tmp:
        copy = Path(tmp) / "air-routes.rl"
        shutil.copyfile(ROOT / "data" / "air-routes.rl", copy)
        db = relate.Database(str(copy), read_only=True)
        print(json.dumps({"ready": True, "rels": db.relationship_count()}), flush=True)  # the watchdog starts here
        t0 = time.perf_counter()
        rows = db.execute(FORMS[form]).data
        ms = round((time.perf_counter() - t0) * 1000, 1)
        print(json.dumps({"rows": rows, "ms": ms}), flush=True)
        db.close()


def rss_mb(pid: int) -> float:
    out = subprocess.run(["ps", "-o", "rss=", "-p", str(pid)], capture_output=True, text=True).stdout.strip()
    return round(int(out) / 1024, 1) if out.isdigit() else 0.0


def line(fd: int, buf: bytearray, timeout: float) -> dict | None:
    """One JSON line from the child, read from the descriptor; None at end of file; TimeoutError when none came."""
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


def how_it_ended(code: int) -> str:
    if code < 0:
        return f"signal {-code} ({signal.Signals(-code).name})"
    return f"exit code {code}"


def main() -> None:
    if len(sys.argv) == 2:
        one(sys.argv[1])
        return
    import relate

    for form, query in FORMS.items():
        rec: dict = {"relate_db": relate.__version__, "graph": "data/air-routes.rl", "form": form, "query": query}
        p = subprocess.Popen([sys.executable, __file__, form], stdout=subprocess.PIPE)
        assert p.stdout is not None
        fd, buf, peak = p.stdout.fileno(), bytearray(), 0.0
        try:
            ready = line(fd, buf, 120.0)  # interpreter start, import, the copy and the open are not the query
            assert ready, "the child ended before the query"
            rec["rels"] = ready["rels"]
            t0 = time.monotonic()
            while True:
                peak = max(peak, rss_mb(p.pid))
                waited = round(time.monotonic() - t0, 1)
                try:
                    got = line(fd, buf, 0.1)
                except TimeoutError:
                    if peak > RSS_CAP_MB:
                        rec["result"] = f"no answer: ended by the watchdog after {waited:g} s, holding over 8 GiB"
                        break
                    if waited >= WATCHDOG:
                        rec["result"] = f"no answer within {WATCHDOG:g} s (ended by the watchdog)"
                        break
                    continue
                if got is None:
                    ended = how_it_ended(p.wait())
                    rec["result"] = f"no answer: the process ended on its own after {waited:g} s, {ended}"
                else:
                    rec.update(got)
                break
        finally:
            p.kill()
            p.wait()
        rec["peak_resident_mb"] = peak
        rec["machine"] = f"{platform.system()} {platform.machine()}"
        rec["python"] = platform.python_version()
        print(json.dumps(rec), flush=True)


if __name__ == "__main__":
    main()
