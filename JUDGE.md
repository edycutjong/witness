# For judges

**The claim.** When an agent answers from a graph, Witness hands back a small graph that reproduces the answer (here, 57,645 relationships → 22), and proves that deleting any one of its relationships changes the answer.

Witness is a Python CLI and MCP server built on Relate. Every trial is a Relate transaction, and the witness is one `.rl` file you open with plain `relate`. Built for the Relate by Neo4j hackathon.

## The 30-second path

1. [Open the landing page](https://witness.edycu.dev/): the answer, the 22 relationships that reproduce it, and the check line; nothing to install.
2. [Open the exhibit page](https://witness.edycu.dev/exhibit/two-hub.html): the register of kept relationships, each tagged as one whose deletion changes the answer.
3. Optional, one command: `git clone https://github.com/edycutjong/witness && cd witness && uv run witness demo` (needs uv). Expect `22 of 22 change the answer` and exit 0.

Prefer to watch? [Demo video (1:55)](https://youtu.be/GYbci7TseJw) · [pitch deck](https://witness.edycu.dev/deck/)

## The receipts

| Number | What it is | Recorded in |
|---|---|---|
| **57,645 → 22** | **Relationships in the air-routes graph, then in the witness.** 3,748 nodes → 12 nodes in the witness graph. As files: 11,079,680 bytes → 45,056. | [`witnesses/two-hub.manifest.json`](witnesses/two-hub.manifest.json), [`evidence/store-bytes.json`](evidence/store-bytes.json) (the files) |
| **22 of 22** | **Deleting any one of them from the witness changes the answer.** Checked on relate-db and on the Relate CLI: `22 of 22 change the answer`. | [`witnesses/two-hub.manifest.json`](witnesses/two-hub.manifest.json), [`evidence/pull-each-tag.json`](evidence/pull-each-tag.json) (what each deletion does to the answer) |
| **22 of 22 live** | **The same pulls, run in a browser by Relate 1.0.1 compiled to WebAssembly.** The landing's pull-a-tag runs `@relate/relate-wasm` 1.0.1, pinned and served from the site, in a module worker: it rebuilds the witness from [`witnesses/two-hub.cypher`](witnesses/two-hub.cypher), deletes the tag and re-runs the query, where the Python run rolls back a transaction (the browser build has none). In headless Chrome 158.0.8127.38 ([`scripts/browser_live.mjs`](scripts/browser_live.mjs)) the page showed all 22 pulls live and the same as the recording, both engine releases live with their recorded rows, a write refused and a runaway query stopped after 4 s, with no request off the site (each engine's worker reports what it fetched), no failed response and no console error; under Node, [`scripts/wasm_parity.mjs`](scripts/wasm_parity.mjs) runs the page's own steps ([`site/relate/live.js`](site/relate/live.js)) on the same engine files and gets the recorded rows on 22 of 22 pulls. A query box runs your own Cypher on the witness; a statement that writes runs on a throwaway copy and is refused. | [`evidence/browser-live.json`](evidence/browser-live.json) (the browser run), [`evidence/wasm-parity.json`](evidence/wasm-parity.json) (under Node), [`site/relate/engines.json`](site/relate/engines.json) (the pinned engines) |
| **68 → 22** | **The answer rows match 68 relationships; the witness keeps 22 of them.** Deleted from the full graph one at a time, 20 of the 68 change the answer and the other 48 do not, because other routes back them up. Deleted from the witness, each of the 22 changes it. | [`evidence/full-graph-necessity.json`](evidence/full-graph-necessity.json), [`evidence/neo4j-compare-2026-11-24.md`](evidence/neo4j-compare-2026-11-24.md) (targeted pass), [`witnesses/two-hub.manifest.json`](witnesses/two-hub.manifest.json), [`queries/two-hub-bindings.cypher`](queries/two-hub-bindings.cypher) (the matching query) |
| **45 of 57,645** | **What the answer depends on in the full graph, and what a witness leaves out.** Every relationship of the full graph was deleted alone: 45 change the answer. 10 are supports, whose deletion drops or alters an answer row, and all 10 are in the witness. 35 are guards, each the direct flight to MEX of an airport of MX that is not in the answer, whose deletion adds that airport as a row. A witness holds what reproduces its rows, not what keeps other rows out. | [`evidence/full-graph-sensitivity.json`](evidence/full-graph-sensitivity.json), [`bench/full_graph_sensitivity.py`](bench/full_graph_sensitivity.py) (re-records it) |
| **57,645 → 2** | **An engine disagreement, observed and shrunk.** Relate's v1.3.0 release notes list a fix for `EXISTS` and `COUNT` over two `MATCH` clauses. On the pinned 1.0.1 the two ways of writing one condition return 59 and 0 airports of MX; `2 of 2 end the disagreement`. The 2-relationship script separates the releases: the two disagree on relate-db 1.0.1, 1.1.0 and 1.2.0 and agree on 1.3.0. | [`witnesses/exists-count.manifest.json`](witnesses/exists-count.manifest.json), [`evidence/exists-count-run.txt`](evidence/exists-count-run.txt) (the run), [`evidence/relate-versions.jsonl`](evidence/relate-versions.jsonl) (the releases) |
| **72 → 7 → 5** | **Relate's own release notes, as regression fixtures.** Every read-path fix entry from v1.0.2 to v1.3.0 (72) was tried on air-routes against the pinned release: 7 change an answer, and 5 of those fixes shrink with `--other-engine` against the release that fixed them, to 6 witnesses of at most 3 relationships (3 of them hold only one or two nodes: those answers turn on a property or a column name). Rebuilt on 1.0.1, 1.0.2, 1.1.0, 1.2.0 and 1.3.0, each changes its answer exactly at the release its notes name. | [`evidence/release-notes-fixes.json`](evidence/release-notes-fixes.json) (all the entries), [`evidence/regress-runs.txt`](evidence/regress-runs.txt) (the runs), [`evidence/regression-releases.jsonl`](evidence/regression-releases.jsonl) (the releases) |
| **219 queries** | **A differential run of agent-written queries.** 219 read queries written by an AI agent from the schema before any engine compared them, each run in a transaction that is rolled back. relate-db 1.0.1 against 1.3.0: 207 agree, 8 end in an error on both, 1 gives no answer within 20 s on either, 2 answer only on 1.3.0, 1 differs in value type (a float on 1.0.1, an integer on 1.3.0) and shrinks to 1 node. Against Neo4j 2026.10.2 (Cypher 25, in a Docker container with a 2.00GiB heap and 1.00GiB of transaction memory, the graph loaded without the store's constraints and indexes, one run): 204 agree with 1.0.1, 8 end in an error on both, 2 differ, and 5 shortest-path queries are not compared because Neo4j did not finish them within the run's 20 s (3 of those 1.0.1 did not finish either; why was not investigated, so read it as a limit of this setup, not of Neo4j). One difference is the same value type: there Neo4j answers as 1.3.0 does, and it shrinks to 1 node against Neo4j too. The other is how `toString` prints a float (`100000000000000000000.0` on Relate is `1.0E20` on Neo4j and `0.0000001` on Relate is `1.0E-7` on Neo4j), the same on both Relate releases; it holds on an empty graph, so there is nothing to shrink. Wherever a query with `ORDER BY` gives the same rows on two engines, it gives them in the same order (89 of 89 on every pair of engines). | [`evidence/differential.json`](evidence/differential.json), [`evidence/differential-answers.jsonl`](evidence/differential-answers.jsonl) (the answers per query), [`queries/differential.jsonl`](queries/differential.jsonl) (the queries) |
| **5,566.7 ms** | **A slowdown still present on Relate 1.3.0, found by that run.** `ANY SHORTEST` over `->+` with an inline relationship predicate that every relationship satisfies: 5,566.7 ms on 36 relationships, no answer within 8 s on 40; without the predicate, under 1 ms. The same on 1.0.1 and 1.2.0. | [`evidence/any-shortest-inline.jsonl`](evidence/any-shortest-inline.jsonl), [`bench/any_shortest_inline.py`](bench/any_shortest_inline.py) (re-records it) |
| **57,645 → 5** | **A query mistake: two queries disagree.** A plausible agent mistake written for this case (the first flight matched in either direction) and the headline query disagree on IN/DEL; `5 of 5 end the disagreement`. | [`witnesses/direction-bug.manifest.json`](witnesses/direction-bug.manifest.json) |
| **57,645 → 92** | **A wrong answer, reproduced smaller (`differs`).** The same mistaken query returns 13 rows where the expected answer has 12, and the repro holds that wrong answer fixed; `92 of 92 change the answer`. | [`witnesses/wrong-answer.manifest.json`](witnesses/wrong-answer.manifest.json) |
| **371 trials · 1.095 s** | **Delete, re-run, roll back.** 86 deletions kept the answer and were then applied. Trials and deletions repeat exactly; wall-clock seconds do not: the landing's paste reduced in 0.998 s, the video's take in 0.91 s. | [`witnesses/two-hub.manifest.json`](witnesses/two-hub.manifest.json) (this run), [`evidence/demo-2026-11-24.txt`](evidence/demo-2026-11-24.txt) (the landing's paste), [`evidence/video-demo-run-2026-11-27.txt`](evidence/video-demo-run-2026-11-27.txt) (the video's take) |
| **366.8 vs 90.2** | **Trials per second: Relate in-process, then Neo4j 2026.10.2 in Docker.** The same loop and query on one machine, median of 3 runs, the same answer on every trial. It measures this setup (Docker VM, Bolt round trip), not a limit of Neo4j. | [`evidence/neo4j-compare-2026-11-24.md`](evidence/neo4j-compare-2026-11-24.md) |
| **22 · 5 · 92** | **Re-proved on a second engine: Neo4j 2026.10.2.** `witness check` runs on two surfaces of Relate, which rules out a mistake in Witness, not one in the engine. Each rebuild script was loaded into an empty Neo4j and every relationship deleted alone in a rolled-back transaction: 22 of 22, 5 of 5 and 92 of 92, each verdict the same as Relate's. | [`evidence/neo4j-recheck.json`](evidence/neo4j-recheck.json), [`bench/neo4j_recheck.py`](bench/neo4j_recheck.py) (re-records it) |
| **557 tests pass · 100% coverage** | **Tests pass against real Relate, under a 100% line and branch coverage gate.** The graph store, rollback and queries are never mocked. `relate pull` (needs a Neo4j server) is stood in, and a few tests substitute timers, process calls, a failing CLI, a database wrapper that injects engine faults, or one reducer phase to reach rare branches. 2 more tests need a local Neo4j in Docker and skip without it. | [`evidence/pytest-2026-11-28b.txt`](evidence/pytest-2026-11-28b.txt) (`pytest --cov=witness`), [`pyproject.toml`](pyproject.toml) (the gate) |
| **byte-identical** | **The same query and seed give a byte-identical rebuild script (`.cypher`) on 2 runs, and CI re-derives it on Linux.** A test requires a fresh reduction to write the committed script byte for byte, under Python 3.11 and 3.12 on every push. The `.rl` written from the script is not byte-identical between runs (the same graph and size, 319 bytes differ in the recorded pair), so the hash to pin is the script's. | [`evidence/determinism.json`](evidence/determinism.json), [`evidence/store-bytes.json`](evidence/store-bytes.json) (the `.rl` comparison), [`tests/test_cli.py`](tests/test_cli.py) (the test) |

## How it uses Relate

- **Mode:** Single file (`.rl`). Reductions run on a file-backed scratch copy in a temp dir; the committed source is copied byte for byte, never opened for writing, and its SHA-256 is checked unchanged after every run.
- **Why this mode:** The unit of evidence is a file. One `.rl` per witness can be committed, handed over and re-run by a reviewer with `relate` alone, with no server. A directory store is many files; `:memory:` disappears when the process ends and cannot be inspected.
- **What the graph models:** The air-routes network by Kelvin Lawrence (Apache-2.0): 3,748 nodes and 57,645 relationships, `(:Airport)-[:HAS_ROUTE]->(:Airport)`, `(:Airport)-[:IN_COUNTRY]->(:Country)` and `(:Airport)-[:ON_CONTINENT]->(:Continent)` ([`data/SOURCE.md`](data/SOURCE.md)).

One trial is `begin_transaction`, delete, re-run the query, compare the answer, `rollback_transaction`. In the headline run 86 deletions kept the answer and were then applied; the other 285 changed it and stayed rolled back ([`witnesses/two-hub.trace.json`](witnesses/two-hub.trace.json)). Relate in-process ran 366.8 trials/s, Neo4j 2026.10.2 in Docker 90.2. Same loop and query, one machine, median of 3 runs, identical answers ([`evidence/neo4j-compare-2026-11-24.md`](evidence/neo4j-compare-2026-11-24.md)). It measures this setup (Docker VM, Bolt round trip), not a limit of Neo4j.

The 8 Relate capabilities it uses:

| | Relate capability | What Witness does with it | In the source |
|---|---|---|---|
| 1 | `begin_transaction · rollback_transaction` | One transaction per trial: begin, delete, re-run the query, compare, roll back. 371 trials in the headline run; the 86 deletions that kept the answer are then committed on the scratch copy. | [`src/witness/store.py`](src/witness/store.py) |
| 2 | `QueryResult.query_type` | After Witness's own token check, Relate has to report the query as read-only (`query_type` is `"r"`); anything else is refused with exit 2. | [`src/witness/guard.py`](src/witness/guard.py) |
| 3 | `EXPLAIN` | Labels and types that neither the query nor its plan names go in one verified step: `:ON_CONTINENT`, 3,504 relationships, in trial 2. | [`src/witness/reduce.py`](src/witness/reduce.py) |
| 4 | `read_only=True` | The rerun, ledger-reader and fixture-test paths open their store read-only, so they cannot write. | [`src/witness/cli.py`](src/witness/cli.py), [`src/witness/ledger.py`](src/witness/ledger.py), [`src/witness/fixture.py`](src/witness/fixture.py) |
| 5 | `single-file .rl` | The witness, the source and the ledger are each one `.rl` file: commit it, hand it over, open it with plain `relate`. | [`src/witness/export.py`](src/witness/export.py), [`src/witness/ledger.py`](src/witness/ledger.py) |
| 6 | `relate pull` | Fixture mode: one pull from Neo4j, then shrink; nothing is pushed back. The committed run pulled 1,272 relationships and kept 126. | [`src/witness/fixture.py`](src/witness/fixture.py), [`fixtures/mex-foreign.report.json`](fixtures/mex-foreign.report.json) |
| 7 | `relate query --mode json` | A second surface: when the Relate CLI is installed, sufficiency and the necessity probes run again on it, outside the Python API (in the committed run, all 22). It is the same engine, so it rules out a mistake in Witness, not one in Relate; for that see the Neo4j re-proof in the receipts. | [`src/witness/check.py`](src/witness/check.py) |
| 8 | `MCP · why · check` | A client answers through Relate's own server, then calls Witness's `why` for the evidence of that answer; `check` re-proves a witness. Recorded twice: a scripted client that calls both, and a real model that calls `why`. | [`src/witness/mcp_server.py`](src/witness/mcp_server.py), [`evidence/mcp-transcript.md`](evidence/mcp-transcript.md), [`evidence/mcp-agent-session.md`](evidence/mcp-agent-session.md) |

The graph is persisted. Stores committed in this repository:

| Store | What it is | Nodes | Relationships | Bytes |
|---|---|---|---|---|
| [`data/air-routes.rl`](data/air-routes.rl) | the source graph, never opened for writing | 3,748 | 57,645 | 11,079,680 |
| [`witnesses/two-hub.rl`](witnesses/two-hub.rl) | the headline witness | 12 | 22 | 45,056 |
| [`witnesses/direction-bug.rl`](witnesses/direction-bug.rl) | the witness of a disagreement between two queries | 5 | 5 | 36,864 |
| [`witnesses/wrong-answer.rl`](witnesses/wrong-answer.rl) | the smaller repro of a wrong answer | 45 | 92 | 65,536 |
| [`witnesses/exists-count.rl`](witnesses/exists-count.rl) | the witness of an engine disagreement (Relate 1.0.1) | 3 | 2 | 36,864 |
| [`fixtures/mex-foreign.rl`](fixtures/mex-foreign.rl) | a test fixture: pulled from Neo4j once, then shrunk | 88 | 126 | 90,112 |

Also committed: [`witness.rl`](witness.rl) (40,960 bytes), the ledger, a small graph of its own: `(:Reduction)-[:PRODUCED]->(:Witness)`, and `(:Review)-[:ON]->(:Reduction)` when a person accepts or disputes one with `witness review`. It holds 1 reduction, no review recorded yet.

The question: Which airports of MX have no direct flight to MEX, yet would still reach it in two flights if any one hub closed? The answer: PBC, QRO, TLC, UPN, each with the countries of its hubs (MX, US). Of the 22 relationships, 13 are flights and 9 are country links: 4 place the answer's airports in MX, 5 give the hub countries.

## Verify it yourself

1. **Run the whole path.** Needs uv. The committed graph is copied, never modified; the output goes to `out/`. The recorded run reports 5.78 s end to end on an Apple M1 Max ([`evidence/demo-2026-11-24.txt`](evidence/demo-2026-11-24.txt)). With a `relate` CLI other than v1.0.1 on your PATH the first lines say the CLI cross-check is skipped; the Python checks and the result are the same.

   ```bash
   git clone https://github.com/edycutjong/witness
   cd witness
   uv run witness demo
   ```

   Expect `22 of 22 change the answer`, a last line that starts `VERIFIED`, and exit 0.

2. **Re-prove the committed witness.** One fresh copy of the witness per probe; nothing is shared with the reduction.

   ```bash
   uv run witness check witnesses/two-hub.rl
   ```

   Expect `22 of 22 change the answer`, then `VERIFIED`, exit 0. Exit 1 would mean not verified.

3. **Re-run it with plain Relate.** Needs the Relate CLI (checked with v1.0.1 and v1.3.0, [`evidence/relate-1.3.0-2026-11-27.txt`](evidence/relate-1.3.0-2026-11-27.txt)). No Witness code runs: the witness is an ordinary `.rl` file.

   ```bash
   relate query --database witnesses/two-hub.rl --read-only \
     --param country=MX --param dest=MEX \
     < queries/two-hub.cypher
   ```

   Expect the same 4 airports the full graph gives: PBC, QRO, TLC, UPN.

4. **Ask it something else.** Three other query shapes on the same graph: a path question (what is the smallest number of flights that gets you from JOG to KEF), a top-k with `ORDER BY` + `LIMIT` (which two nonstop flights out of CGK are the longest) and an `EXISTS` / `NOT EXISTS` pair (which airports of IS have flights, but none that leave the country). Or bring your own graph: `uv run witness why -f Q.cypher --store YOUR.rl`.

   ```bash
   uv run witness why -f queries/examples/fewest-flights.cypher --param from=JOG --param to=KEF
   uv run witness why -f queries/examples/longest-nonstop.cypher --param from=CGK
   uv run witness why -f queries/examples/domestic-only.cypher --param country=IS
   ```

   Expect `3 of 3 change the answer`, `2 of 2 change the answer` and `4 of 4 change the answer`, each ending `VERIFIED`, exit 0.

5. **Run the tests.** CI and deterministic replay, not the product path.

   ```bash
   uv run pytest --cov=witness
   ```

   Expect 557 passed and 100% line and branch coverage; 2 more need a local Neo4j in Docker and skip without it.

More commands, one section per set of numbers: [`DEMO.md`](DEMO.md). The files behind every figure on this page: [`evidence/`](evidence/), [`witnesses/`](witnesses/).

## By criterion

The [listing](https://relate.devpost.com/)'s five criteria, each with the files and sections that answer it. Nothing below is a score; it is where the evidence is.

### Creativity

- **Rollback as the search loop.** 371 delete, re-run, roll-back trials take 57,645 relationships down to 22 ([`src/witness/reduce.py`](src/witness/reduce.py), [`witnesses/two-hub.trace.json`](witnesses/two-hub.trace.json)).
- **Not a path lookup.** The headline question uses aggregation, `NOT EXISTS` and `OPTIONAL MATCH`, and the witness still reproduces its answer ([`queries/two-hub.cypher`](queries/two-hub.cypher)).
- **One loop, more than one thing to hold on to.** An answer (22 relationships), a disagreement between two queries (5, and 2 for the engine case), or an answer you say is wrong (92; the same test as the first, applied to a wrong answer) ([`witnesses/two-hub.manifest.json`](witnesses/two-hub.manifest.json), [`witnesses/direction-bug.manifest.json`](witnesses/direction-bug.manifest.json), [`witnesses/exists-count.manifest.json`](witnesses/exists-count.manifest.json), [`witnesses/wrong-answer.manifest.json`](witnesses/wrong-answer.manifest.json)).
- **What is borrowed is named.** The search is delta debugging (Zeller and Hildebrandt, 2002) and the word witness is from data provenance (Buneman, Khanna and Tan, 2001). What Witness does with them: the thing shrunk is a graph store, the test is a Cypher answer found by search (so `NOT EXISTS` and aggregation are covered), each trial is a Relate transaction, and the result is a `.rl` file ([`README.md`](README.md)).

### Relate and connected context

- **Mode: single-file `.rl`.** The unit of evidence is a file a reviewer opens with plain `relate`: 45,056 bytes for the headline witness. Mode, reason and capabilities are in [How it uses Relate](#how-it-uses-relate) ([`evidence/store-bytes.json`](evidence/store-bytes.json)).
- **Which relationships matter is measured.** Each of the 22 is deleted in turn and the query re-run; all 22 change the answer ([`evidence/pull-each-tag.json`](evidence/pull-each-tag.json)).
- **Relate runs in the reader's tab.** On the landing, Relate 1.0.1 compiled to WebAssembly re-runs each pull, the reader's own read queries and the engine case on two releases; in headless Chrome all 22 pulls ran live and gave the recorded rows ([`evidence/browser-live.json`](evidence/browser-live.json), [`evidence/wasm-parity.json`](evidence/wasm-parity.json)).
- **The graph is persisted in the repository.** The source, 4 witnesses, a fixture and the ledger of reductions are committed `.rl` stores ([`data/air-routes.rl`](data/air-routes.rl), [`witnesses/two-hub.rl`](witnesses/two-hub.rl), [`witness.rl`](witness.rl)).
- **The same verdicts on Neo4j.** The rebuild scripts load into Neo4j 2026.10.2, where the same single deletions change the answer: 22 of 22, 5 of 5, 92 of 92 ([`evidence/neo4j-recheck.json`](evidence/neo4j-recheck.json)).
- **Beside Relate's own MCP server.** A scripted client and, separately, a real model answer through `relate serve --mcp`, then call Witness's `why` for the evidence; the scripted client also calls `check` ([`evidence/mcp-transcript.md`](evidence/mcp-transcript.md), [`evidence/mcp-agent-session.md`](evidence/mcp-agent-session.md)).

### Functionality and completeness

- **One command, the whole path.** On a fresh clone: copy, guard, order check, reduce, check, then the exhibit page and a ledger row. The commands are in [Verify it yourself](#verify-it-yourself).
- **More than the demo.** `witness why` on any read-only query and any `.rl` (`--store`), `check`, `rerun`, `export`, `review`, fixture mode and an MCP server ([`src/witness/cli.py`](src/witness/cli.py), [`src/witness/mcp_server.py`](src/witness/mcp_server.py)).
- **Other query shapes.** A path question (`allShortestPaths`, 57,645 relationships → 3), a top-k with `ORDER BY` + `LIMIT` (→ 2) and an `EXISTS` / `NOT EXISTS` pair (→ 4), each re-run by a test; and one that does not shrink, a count over the whole graph, which stops at the trial cap and says NOT verified ([`evidence/other-queries.json`](evidence/other-queries.json), [`tests/test_examples.py`](tests/test_examples.py)).
- **Tested against real Relate.** 557 tests pass under a 100% line and branch coverage gate; CI runs 6 stages, one of them the built wheel running `witness demo` and plain `relate` re-running the committed witness ([`evidence/pytest-2026-11-28b.txt`](evidence/pytest-2026-11-28b.txt), [`.github/workflows/ci.yml`](.github/workflows/ci.yml)).
- **It refuses what it cannot do.** Writes, procedures, clocks and randomness exit 2 with a one-line reason ([`src/witness/guard.py`](src/witness/guard.py), [`tests/test_guard.py`](tests/test_guard.py), [`tests/test_errors.py`](tests/test_errors.py)).

### Usefulness

- **Who it is for.** The developer whose agent answers from a graph and who has to show what an answer rests on before anyone acts on it: a reviewer reads 22 relationships, not 57,645 and not the 68 a listing of the matched paths would show. And the developer who has to hand a wrong or surprising answer to someone else as a graph small enough to read.
- **A real engine disagreement, shrunk to a repro.** On Relate 1.0.1 two ways of writing one condition return 59 and 0 rows on the air-routes graph (the v1.3.0 release notes list the fix). Witness hands back the 2 relationships that still show it, and that script tells the releases apart: 1.0.1, 1.1.0 and 1.2.0 disagree, 1.3.0 agrees ([`witnesses/exists-count.manifest.json`](witnesses/exists-count.manifest.json), [`evidence/relate-versions.jsonl`](evidence/relate-versions.jsonl)).
- **For the people who maintain the engine, and anyone moving a query between releases.** `--other-engine` shrinks what makes two engines answer one query differently. Relate's own release notes became 6 regression fixtures of at most 3 relationships, each changing its answer exactly at the release that fixed it, and a differential run of 219 agent-written queries (Relate 1.0.1, Relate 1.3.0 and Neo4j 2026.10.2) found a slowdown still present on Relate 1.3.0 ([`evidence/release-notes-fixes.json`](evidence/release-notes-fixes.json), [`evidence/regression-releases.jsonl`](evidence/regression-releases.jsonl), [`evidence/differential.json`](evidence/differential.json)).
- **An agent attached the evidence itself.** In a recorded session a real model (claude-sonnet-5-5 in Claude Code) wrote its own Cypher, called `why` over MCP and attached the witness of its answer: `68 of 68 change the answer`. Its answer also reports hub counts, so all 68 relationships the answer rows bind are needed ([`evidence/mcp-agent-session.md`](evidence/mcp-agent-session.md)).
- **It shows where a wrong query goes wrong.** Two versions of the question disagree on 6 of 232 country and busiest-airport pairs; for India and DEL, 5 relationships keep them disagreeing, one of them the flight the mistaken query read backwards ([`evidence/disagree-scan.json`](evidence/disagree-scan.json), [`witnesses/direction-bug.manifest.json`](witnesses/direction-bug.manifest.json)).
- **A second use: test fixtures.** `relate pull` brought 1,272 relationships in from Neo4j once, and Witness kept the 126 the test needs. The same run, repeated against a Neo4j created from scratch, wrote the same fixture ([`fixtures/mex-foreign.manifest.json`](fixtures/mex-foreign.manifest.json), [`evidence/fixture-run-2026-11-27.txt`](evidence/fixture-run-2026-11-27.txt)).

### Documentation and reproducibility

- **The README answers the listing's question.** How Witness uses Relate, which mode, and why ([`README.md`](README.md)).
- **Commands, not only claims.** [`DEMO.md`](DEMO.md) gives the command or the recorded run for 15 sets of numbers: the headline, determinism, the Neo4j comparison, fixture mode (with the commands to create the Neo4j it pulls from), the MCP tools, the tests, the query disagreement, the wrong-answer repro, what each deletion does, the engine disagreement, other query shapes, the Neo4j re-proof, the two-engine door with the changelog fixtures, the differential run, and the live pulls in the browser against the recording.
- **The page cannot drift from the evidence.** This page and [`JUDGE.md`](JUDGE.md) are written by [`scripts/build_site.py`](scripts/build_site.py) from the committed files; CI rebuilds both and fails on any difference ([`.github/workflows/ci.yml`](.github/workflows/ci.yml)).
- **Shown running.** The [demo video (1:55)](https://youtu.be/GYbci7TseJw) and the [pitch deck](https://witness.edycu.dev/deck/). What the stamp does not say is in [Honest limitations](#honest-limitations).

## Honest limitations

- Verified is about the evidence, not the query: exit 0 says the witness is deletion-minimal for its predicate. It does not say the query asks the right question; the repro of a wrong answer is verified too.
- Supports, not guards: a witness holds what reproduces the rows it has, not what keeps other rows out. In the full graph 35 single relationships each keep another airport out of the headline answer, and 34 of them are not in the witness ([`evidence/full-graph-sensitivity.json`](evidence/full-graph-sensitivity.json)).
- Deletion-minimal, not smallest: no single remaining relationship can be removed without changing the answer; a smaller witness may exist.
- Its own answer, on its own file: because a query with `NOT EXISTS` or aggregation is not monotone, a witness does not prove that every graph containing it gives the same answer. It also leaves out true facts the answer does not need: MEX has no country link in [`witnesses/two-hub.rl`](witnesses/two-hub.rl).
- Read-only Cypher only, with no clock or randomness: Witness refuses writes, procedures, clocks and randomness (exit 2) rather than guess. Dependence on storage order is caught by a heuristic (the same answer from a store built in reverse order), not proven absent.
- Answers that rest on thousands of facts do not shrink: a count over the whole graph ran to the default cap of 20,000 trials (18 minutes here) and exited 3, NOT verified, with 38,521 relationships left ([`evidence/other-queries.json`](evidence/other-queries.json)).
- One graph (a public air-routes dataset, Apache-2.0): the headline query, three more cases and three more query shapes. The one mistaken query was written for the case; the engine disagreement is observed, and only on Relate 1.0.1, 1.1.0 and 1.2.0. The Neo4j comparison is one machine, one query, one graph; it measures this setup (Docker VM, Bolt round trip), not a limit of Neo4j.

## Links

- Repository: https://github.com/edycutjong/witness · the source, the evidence and the commit history
- Live site: https://witness.edycu.dev/ · the landing: replay the reduction, pull a tag yourself
- Demo video: https://youtu.be/GYbci7TseJw · watch it run (1:55)
- Pitch deck: https://witness.edycu.dev/deck/ · 10 slides, every number read from the same files
- Exhibit page: https://witness.edycu.dev/exhibit/two-hub.html · the page Witness writes beside every witness
- README: https://github.com/edycutjong/witness/blob/main/README.md · how it uses Relate, and why
- DEMO.md: https://github.com/edycutjong/witness/blob/main/DEMO.md · the commands behind the numbers, section by section
- JUDGE.md: https://github.com/edycutjong/witness/blob/main/JUDGE.md · this page as Markdown, in the repository
- Relate: https://relatedb.ai · the embedded graph database it is built on
