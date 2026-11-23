# W5: the same rollback-trial loop, Relate in-process vs Neo4j in Docker

Raw: `neo4j-compare-2026-11-24.json` (3 runs × 1,000 trials, per-run summaries, machine, versions) and `neo4j-compare-rows.jsonl`
(per-trial ms + whether the answer changed, run 1). Reproduce: `uv run --with neo4j python bench/neo4j_compare.py`
(needs the local Neo4j container; the graph in it is `data/air-routes.cypher`).

**Loop, identical on both sides:** begin → delete one relationship → run the headline query (`queries/two-hub.cypher`,
`MX`/`MEX`), fetch every row → rollback → check node and relationship counts are back. Same 1,000 relationships in the same order
(seeded sample, resolved to Neo4j element ids outside the timed loop), 100 warm-up trials discarded on each side.

| | Relate 1.0.1, in-process (`:memory:` copy) | Neo4j 2026.10.2 community, Docker, Bolt over loopback |
|---|---|---|
| trials/s, median of 3 runs (range) | **366.8** (364.1–380.2) | **90.2** (76.9–102.2) |
| trial ms p50 (begin → rollback) | 2.54 | 6.48 |
| trial ms p95 | 2.94 | 13.62 |
| counts restored after rollback | 3000/3000 | 3000/3000 |

Ratio of median trials/s: **4.07×** in this setup. The reduction needs ~371 trials: about 1.0 s on Relate (measured, P1b) and about
4 s at Neo4j's rate here. Neo4j was still speeding up across the three runs (76.9 → 90.2 → 102.2 trials/s), so the gap is the cost of
this setup (a server in a Docker VM, one Bolt round trip per statement, two extra count queries per trial), not a claim that Neo4j
cannot run rollback trials. It runs them fine and returned the same answers.

**Answers agree.** Per-trial answers identical on all 3,000 sampled trials (only 2 of 1,000 change the answer per run, on both
engines). Because that sample barely changes the answer, a targeted pass ran the 68 relationships the headline query actually
binds: 20 change the answer on Relate and the same 20 on Neo4j, 68/68 identical.

**What differs, stated:** (1) dialect: Neo4j has no `coll.sort()`, so `queries/two-hub.neo4j.cypher` orders before `collect()`;
baseline rows are identical (checked before the loop). (2) Neo4j keeps its default heap and page cache; both graphs carry the same
three uniqueness constraints; `Airport.iata` is unindexed on both. (3) Machine: Apple M1 Max, 32 GB; Docker VM 10 CPUs / 9.7 GiB.
(4) Single machine, single query, one graph (57,645 relationships): a measurement, not a benchmark suite.
