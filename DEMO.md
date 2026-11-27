# DEMO: reproduce every number

Every figure in `README.md` comes from a file in this repo. Machine for all runs: Apple M1 Max, 32 GiB, Python 3.12.13,
`relate-db` 1.0.1, Relate CLI v1.0.1 (`evidence/env.txt`). Witness starts the `relate` CLI once per probe and sets
`DO_NOT_TRACK=1` for those processes, so its automated runs send Relate no usage events; your own `relate` commands are untouched.

## 1. Headline: 57,645 relationships → 22 (12 nodes), "22 of 22 change the answer"

```bash
git clone https://github.com/edycutjong/witness && cd witness
uv run witness demo
```

Expect exit 0 and a check line `22 of 22 change the answer (22 of 22 relationships, 0 of 0 isolated nodes)`.
Trials (371) and reduction seconds (about 1.1 s; machine dependent) are in `out/two-hub.manifest.json` under `run`. The committed
run of the same command is `witnesses/two-hub.manifest.json` (`run.trials` 371, `run.seconds` 1.095, `witness.relationships` 22,
`witness.nodes` 12, `source.relationships` 57,645). Trials, deletions and the witness repeat exactly (seed 0); wall-clock seconds
do not (0.91 to 1.36 s across the committed runs on this machine), so every page quotes the seconds of the run it names. Raw spike rows: `evidence/spike-2026-11-15.md`, `evidence/headline-raw.json`.

Re-run the witness with plain `relate` (needs the Relate CLI):

```bash
relate query --database witnesses/two-hub.rl --read-only --param country=MX --param dest=MEX < queries/two-hub.cypher
```

Re-prove it on its own: `uv run witness check witnesses/two-hub.rl` (exit 0 = verified).

## 2. Determinism

```bash
uv run python scripts/determinism.py     # writes evidence/determinism.json
```

`byte_identical: true` across runs with seed 0. On other machines: `tests/test_cli.py` requires a fresh reduction to write
the committed `witnesses/two-hub.cypher` byte for byte, and CI runs it on Linux under Python 3.11 and 3.12 on every push.

```bash
uv run python scripts/store_bytes.py     # writes evidence/store-bytes.json
```

The stores as files: `data/air-routes.rl` is 11,079,680 bytes and `witnesses/two-hub.rl` 45,056. A rerun writes the same
rebuild script (3,653 bytes, SHA-256 `6df99e7d…b015`); the `.rl` written from it holds the same graph in the same number of
bytes, but not the same bytes (a few hundred differ between two runs), so the hash to pin is the script's.

## 3. Relate vs Neo4j, same rollback-trial loop: 366.8 vs 90.2 trials/s

Needs Docker. Create the Neo4j the script expects, load the same graph into it, and tell the script where it is
(choose a password of letters and digits):

```bash
docker run -d --name witness-neo4j -p 127.0.0.1:7475:7474 -p 127.0.0.1:7688:7687 \
  -e NEO4J_AUTH=neo4j/<password> neo4j:2026.10.2-community
docker exec -i witness-neo4j cypher-shell -u neo4j -p <password> < data/air-routes.cypher   # about 35 s; 3,748 nodes, 57,645 relationships
mkdir -p ~/.config/witness && printf 'NEO4J_BOLT=bolt://127.0.0.1:7688\nNEO4J_USER=neo4j\nNEO4J_PASSWORD=<password>\n' > ~/.config/witness/neo4j.env
uv run --with neo4j python bench/neo4j_compare.py
```

Median of 3 runs of 1,000 trials; per-trial p50 2.54 vs 6.48 ms; answers identical on 3,000 of 3,000 trials (2 of the 1,000 sampled relationships change the answer) and on the 68
targeted relationships (20 of 68 change it). The 2 sampled relationships that change it are guards, the MEX flights of VSA and CME
(section 9). Raw rows and caveats: `evidence/neo4j-compare-2026-11-24.json`, `.md`, `neo4j-compare-rows.jsonl`.
Throughput depends on the machine and Docker VM; expect the ratio, not the absolute numbers, to carry over.

## 4. Fixture mode: 1,272 pulled → 126 kept, "126 of 126"

The committed result is checked offline by the test suite: `uv run pytest tests/test_fixture.py`. A fresh run needs the v1.0.1
`relate` CLI (the pinned engine reads what that release's `relate pull` writes). Artifacts:
`fixtures/mex-foreign.{rl,report.json,manifest.json,expected.json}`. The pull is read-only on Neo4j and nothing is pushed back.

To run it end to end you need a Neo4j that holds the graph. With the container of section 3 (its HTTP port is 7475):

```bash
printf 'NEO4J_URI=http://127.0.0.1:7475\nNEO4J_USERNAME=neo4j\nNEO4J_PASSWORD=<password>\nNEO4J_DATABASE=neo4j\n' > neo4j.env
uv run witness fixture --from neo4j.env --pull queries/fixture-slice.cypher --test queries/fixture-test.cypher \
  --expect fixtures/mex-foreign.expected.json --name mex-foreign
```

Expect `PULLED   1,272 relationships · 207 nodes`, `FIXTURE  126 relationships · 88 nodes · 2092 trials`, `126 of 126 change the
answer` and `VERIFIED`. Recorded against a Neo4j created from scratch this way: `evidence/fixture-run-2026-11-27.txt`.

## 5. MCP tools `why` and `check`

```bash
uv run --extra mcp python scripts/mcp_transcript.py
```

Writes `evidence/mcp-transcript.md`: a real stdio session calling both tools from a scripted client.

With a real model in the loop: `evidence/mcp-agent-session.md` records claude-sonnet-5-5 in Claude Code (headless, only the two
MCP servers enabled) writing its own Cypher and attaching the witness; the exact command, `mcp.json` and prompt are in that file.
It needs a Claude Code login, so it is a recorded run, not a step of the judge path.

## 6. Tests: 557 pass, 100% coverage

```bash
uv run pytest --cov=witness   # fails below 100% line + branch coverage (pyproject.toml)
```

The run is recorded in `evidence/pytest-2026-11-28b.txt` (557 passed; the 2 fixture-pull tests need a local Neo4j in Docker and
skip without it). GitHub Actions runs the same suite on every push, on Linux under Python 3.11 and 3.12, with ruff, mypy,
pip-audit, gitleaks, the wheel build and a throughput floor (`.github/workflows/ci.yml`).

## 7. Two queries disagree: 57,645 → 5, "5 of 5 end the disagreement"

```bash
uv run python bench/disagree_scan.py      # 232 pairs, 6 disagree → evidence/disagree-scan.json
uv run witness why -f queries/two-hub-agent.cypher --other queries/two-hub.cypher --predicate disagree \
  --strict-lists --param country=IN --param dest=DEL --name direction-bug
```

Expect exit 0, `5 of 5 end the disagreement`, 139 trials (`witnesses/direction-bug.manifest.json`; recorded run:
`evidence/direction-bug-run.txt`). Plain `relate` on `witnesses/direction-bug.rl` returns AGR for the agent's query and no rows
for the headline query (`tests/test_committed.py`).

## 8. A smaller repro of a wrong answer (`differs`): 57,645 → 92, "92 of 92 change the answer"

```bash
uv run witness why -f queries/two-hub-agent.cypher --predicate differs \
  --expected "$(cat evidence/wrong-answer-expected.json)" \
  --strict-lists --param country=IN --param dest=DEL --name wrong-answer
```

The expected rows are the reference query's answer on the same graph (12 rows, from plain `relate query` on
`data/air-routes.rl` with `queries/two-hub.cypher`; the command is in the header of `evidence/wrong-answer-run.txt`). The mistaken query returns 13 (the 12 plus AGR). Expect exit 0, `92 of 92 change the
answer`, 2,099 trials (`witnesses/wrong-answer.manifest.json`; recorded run: `evidence/wrong-answer-run.txt`). Plain `relate`
on `witnesses/wrong-answer.rl` returns the same 13 rows (`tests/test_committed.py`).

The loose form is a different test. `--loose` only asks for a non-empty answer other than the expected rows, so the reduction
may leave the wrong row behind: on this case it ends on 5 relationships whose answer is IXE, not AGR
(`evidence/differs-loose-run.txt`). Use the strict form above to reproduce a particular wrong answer.

## 9. What each deletion does: in the witness, among the 68, in the full graph

```bash
uv run python scripts/pull_each_tag.py          # the 22, each deleted from the witness      -> evidence/pull-each-tag.json
uv run python bench/full_graph_necessity.py     # the 68, each deleted from the full graph   -> evidence/full-graph-necessity.json
uv run python bench/full_graph_sensitivity.py   # all 57,645, each deleted from the full graph (about 2.5 minutes)
                                                #                                             -> evidence/full-graph-sensitivity.json
```

In the witness, 22 of 22 change the answer. Of the 68 relationships the answer rows match, 20 change it in the full graph.
Of all 57,645, 45 change it: 10 supports (their deletion drops or alters an answer row; all 10 are in the witness) and 35
guards (each the direct flight to MEX of a Mexican airport that is not in the answer; its deletion adds that airport as a
row). 25 of the guards are outside the 68, and 34 are outside the witness.

## 10. An engine disagreement, observed: 57,645 → 2, and the releases it separates

```bash
uv run witness why -f queries/count-two-match.cypher --other queries/exists-two-match.cypher --predicate disagree \
  --param country=MX --name exists-count
for v in 1.0.1 1.1.0 1.2.0 1.3.0; do
  uv run --no-project --python 3.12 --with relate-db==$v python bench/relate_versions.py
done
```

The two query files state one condition two ways, `EXISTS { MATCH … MATCH … }` and `COUNT { MATCH … MATCH … } > 0`. On the
pinned Relate 1.0.1 they return 0 and 59 Mexican airports; Relate's v1.3.0 release notes list the fix ("`EXISTS` over two
`MATCH` clauses agrees with `COUNT` on relationship uniqueness"). Expect exit 0, `2 of 2 end the disagreement`, 49 trials
(`witnesses/exists-count.manifest.json`; recorded run: `evidence/exists-count-run.txt`). The loop rebuilds that
2-relationship graph under four releases: the two forms disagree on 1.0.1, 1.1.0 and 1.2.0 and agree on 1.3.0
(`evidence/relate-versions.jsonl`).

## 11. Other query shapes, and one that does not shrink

```bash
uv run witness why -f queries/examples/fewest-flights.cypher --param from=JOG --param to=KEF    # 3 of 3
uv run witness why -f queries/examples/longest-nonstop.cypher --param from=CGK                  # 2 of 2
uv run witness why -f queries/examples/domestic-only.cypher --param country=IS                  # 4 of 4
uv run python bench/other_queries.py                     # the three above, and the count stopped after 20 s
uv run python bench/other_queries.py --with-default-cap  # also the count with the default cap: about 18 minutes
```

A path question (`allShortestPaths`), a top-k with `ORDER BY` + `LIMIT` (the CLI cross-check covers sufficiency only for a
query with such a cut, and the check line says so) and an `EXISTS` / `NOT EXISTS` pair: 57,645 relationships → 3, 2 and 4.
`tests/test_examples.py` re-runs the three. A count over the whole graph (`queries/examples/count-no-direct.cypher`, 3,388)
does not shrink: with the default cap it stops at 20,000 trials after 1,102 s, exit 3, NOT verified, 38,521 relationships left
(`evidence/other-queries.json`).

## 12. Re-proved on a second engine: 22 of 22, 5 of 5 and 92 of 92 on Neo4j

```bash
docker run -d --rm --name witness-recheck -p 127.0.0.1:7690:7687 -e NEO4J_AUTH=neo4j/<password> neo4j:2026.10.2-community
NEO4J_PASSWORD=<password> uv run --with neo4j python bench/neo4j_recheck.py --bolt bolt://127.0.0.1:7690
docker stop witness-recheck
```

The script needs an empty database and leaves it empty. It loads each witness's rebuild script (`witnesses/<name>.cypher`),
checks that the predicate holds, then deletes every relationship alone in a rolled-back transaction and compares each verdict
with the one the manifest records for Relate (`evidence/neo4j-recheck.json`). The only statement difference is dialect:
Neo4j has no `coll.sort()`, so the hub countries are ordered before `collect()`. The engine-disagreement witness of section 10
is not part of this: its claim is about Relate 1.0.1.

## 13. One query on two engines, and Relate's changelog as regression fixtures

```bash
uv run witness why -f queries/exists-two-match.cypher --param country=MX --other-engine relate-db==1.3.0 \
  --name exists-engines --out /tmp/w --no-ledger                     # 57,645 -> 2 in 49 trials (evidence/exists-engines-run.txt)
uv run witness check witnesses/regress/cycle-repeated-variable.rl    # 3 of 3, against relate-db 1.3.0 (from the manifest)
uv run witness check witnesses/regress/cycle-repeated-variable.rl --other-engine relate-db==1.2.0   # NOT verified: on this witness 1.2.0 gives 1.0.1's row (evidence/regression-releases.jsonl)
for v in 1.0.1 1.0.2 1.1.0 1.2.0 1.3.0; do
  uv run --no-project --with relate-db==$v python bench/regression_table.py
done                                                                 # = evidence/regression-releases.jsonl (one row per witness and release)
```

The six regression witnesses and how each was made: `evidence/regress-runs.txt` (one `witness why --other-engine` per
query in `queries/regress/`, against the release that fixed it). The triage of all 72 read-path fix entries in the v1.0.2
to v1.3.0 release notes, with the status of each: `evidence/release-notes-fixes.json`. `uv` fetches each Relate release
once; the worker opens its own byte copy of the store.

## 14. The differential run, and a slowdown still on Relate 1.3.0

```bash
uv run --with neo4j python bench/differential.py --reduce           # = evidence/differential.json + differential-answers.jsonl
for v in 1.0.1 1.3.0 1.2.0; do
  uv run --no-project --with relate-db==$v python bench/any_shortest_inline.py
done                                                                 # = evidence/any-shortest-inline.jsonl
```

`bench/differential.py` runs the 219 queries of `queries/differential.jsonl` on relate-db 1.0.1, relate-db 1.3.0 and,
when `NEO4J_BOLT` / `NEO4J_USER` / `NEO4J_PASSWORD` point at an empty Neo4j, Neo4j; each query has a 20 s watchdog. The
committed run has no Neo4j leg (`"neo4j": "not run: ..."` in `evidence/differential.json`). `bench/any_shortest_inline.py`
runs each size in its own process with an 8 s watchdog, because the slow form does not return on 40 relationships.


## 15. Relate in the tab: the landing's pulls, run live, against the recording

```bash
uv run python scripts/vendor_relate_wasm.py --check   # the self-hosted engines match their pinned checksums (offline)
node scripts/wasm_parity.mjs --out /tmp/wasm-parity.json   # = evidence/wasm-parity.json, timings and run header aside
PUPPETEER_MODULE=<path to puppeteer's ESM entry> CHROME=<path to Chrome> \
  node scripts/browser_live.mjs https://witness.edycu.dev/ --out /tmp/browser-live.json   # same verdicts as evidence/browser-live.json; timings and run header differ
```

The landing (https://witness.edycu.dev/#exhibit) runs `@relate/relate-wasm` 1.0.1, the release the witness was reduced
on, in a module worker. The engine files are served from the site (`site/relate/1.0.1/`, unchanged from npm, pinned by
version and by the registry's sha512 in `scripts/vendor_relate_wasm.py`), so the page makes no third-party request to run
it. Relate's browser build has no transactions, so a pull rebuilds the witness from `witnesses/two-hub.cypher`, deletes
that one relationship and re-runs `queries/two-hub.cypher`; every answer is marked Live and compared with
`evidence/pull-each-tag.json` on screen. If the engine cannot start, the pull replays the recording and is marked
Recorded. A query box runs the reader's own Cypher on a fresh copy of the witness, minus the pulled tag; a statement that
writes is refused (it ran on a throwaway copy, and its write counters are shown instead of rows), and a statement still
running after 4 s is stopped by ending the worker (the browser build has no statement timeout). The engine case
(section 10) runs both forms on 1.0.1 and on 1.3.0, each its own engine.

`scripts/wasm_parity.mjs` imports the page's own steps (`site/relate/live.js`) and the same engine files under Node,
loading the engine with `initSync` and its bytes (Relate's WebAssembly API reference), and checks: all 22 pulls give the recorded rows; the
unpulled witness gives the manifest's answer; the engine case gives the recorded rows on 1.0.1 (the forms disagree) and
1.3.0 (they agree); a `CREATE` in the query box is refused. `tests/test_wasm_parity.py` runs it under pytest when Node
is installed and requires the committed evidence to match the fresh run. `scripts/browser_live.mjs` drives the page itself
in headless Chrome (puppeteer is not a dependency of this repository) and records what it showed: in the committed run,
all 22 pulls live and the same as the recording, the four example queries answered (on the witness with the last tag
pulled), a write refused, a runaway query stopped after 4 s and the next one answered, and both engine releases live with
their recorded rows; no engine worker before the visitor reaches the exhibit; no request to a third party other than the
version chip's call to GitHub's releases API, and no console error. The run records the SHA-256 of the served page and
of `site/relate/live.js` and `worker.js`; the site build refuses a browser run older than the live steps it ships.
