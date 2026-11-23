# DEMO: reproduce every number

Every figure in `README.md` comes from a file in this repo. Machine for all runs: Apple M1 Max, 32 GiB, Python 3.12.13,
`relate-db` 1.0.1, Relate CLI v1.0.1 (`evidence/env.txt`). Run Relate with `DO_NOT_TRACK=1`.

## 1. Headline: 57,645 relationships → 22 (12 nodes), "22 of 22 change the answer"

```bash
git clone https://github.com/edycutjong/witness && cd witness
DO_NOT_TRACK=1 uv run witness demo
```

Expect exit 0 and a check line `22 of 22 change the answer (22 of 22 relationships, 0 of 0 isolated nodes)`.
Trials (371) and reduction seconds (about 1.1 s; machine dependent) are in `out/two-hub.manifest.json` under `run`. The committed
copy of the same run is `witnesses/two-hub.manifest.json` (`run.trials` 371, `run.seconds` 1.095, `witness.relationships` 22,
`witness.nodes` 12, `source.relationships` 57,645). Raw spike rows: `evidence/spike-2026-11-15.md`, `evidence/headline-raw.json`.

Re-run the witness with plain `relate` (needs the Relate CLI):

```bash
relate query --database witnesses/two-hub.rl --read-only --param country=MX --param dest=MEX < queries/two-hub.cypher
```

Re-prove it on its own: `uv run witness check witnesses/two-hub.rl` (exit 0 = verified).

## 2. Determinism

```bash
uv run python scripts/determinism.py     # writes evidence/determinism.json
```

`byte_identical: true` across runs with seed 0.

## 3. Relate vs Neo4j, same rollback-trial loop: 366.8 vs 90.2 trials/s

Needs Docker with a local Neo4j 2026.10.2 container loaded from `data/air-routes.cypher`.

```bash
uv run --with neo4j python bench/neo4j_compare.py
```

Median of 3 runs of 1,000 trials; per-trial p50 2.54 vs 6.48 ms; answers identical on 3,000 of 3,000 trials (2 of the 1,000 sampled relationships change the answer) and on the 68
targeted relationships (20 of 68 change it). Raw rows and caveats: `evidence/neo4j-compare-2026-11-24.json`, `.md`, `neo4j-compare-rows.jsonl`.
Throughput depends on the machine and Docker VM; expect the ratio, not the absolute numbers, to carry over.

## 4. Fixture mode: 1,272 pulled → 126 kept, "126 of 126"

The committed result is checked offline by the test suite: `uv run pytest tests/test_fixture.py`. Artifacts:
`fixtures/mex-foreign.{rl,report.json,manifest.json,expected.json}`. Re-pulling needs your own Neo4j credentials
(`witness fixture --from neo4j.env …`, see the README command table); the pull is read-only on Neo4j and never pushed back.

## 5. MCP tools `why` and `check`

```bash
uv run --extra mcp python scripts/mcp_transcript.py
```

Writes `evidence/mcp-transcript.md`: a real stdio session calling both tools.

## 6. Tests: 194 pass

```bash
uv run pytest
```
