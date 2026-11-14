# Day-0 spike, run 1 (superseded): the IN-list delete statement

Same machine, data, query, seed and protocol as `spike-2026-11-15.md`, with the trial delete written as
`MATCH ()-[r]->() WHERE elementId(r) IN $ids DELETE r RETURN count(*) AS c`. The raw rows of this run were overwritten
by run 2 (same file name); the numbers below are copied from the run-1 console output.

| Check | Run 1 (IN list) |
|---|---|
| 1,000 trials | 24.0 trials/s, p50 41.11 ms, p95 42.18 ms (below the 50 trials/s GO bar) |
| Counts restored after every rollback | 1000/1000 |
| Replay trials 1–50 | same scratch 50/50 · fresh copy 50/50 · ids → same key 50/50 |
| Full reduction | 3.35 s, 371 trials, 12 nodes / 22 relationships |
| Export re-check | 22 of 22 change the answer |
| Delete form comparison, 200 trials each | IN list 24.0 trials/s · UNWIND 363.3 trials/s (p50 2.55 ms) |

The IN-list form scans every relationship on each trial; the UNWIND form resolves each `elementId` directly. Run 2 uses
the UNWIND form for the trial loop (`src/witness/store.py` `DEL_RELS`) and still re-measures the IN-list form side by
side (`delete_forms` in `spike-2026-11-15.json`). The GO thresholds were not changed.
