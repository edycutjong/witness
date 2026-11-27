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
| **57,645 → 22** | **Relationships in the air-routes graph, then in the witness.** 3,748 nodes → 12 nodes in the witness graph. | [`witnesses/two-hub.manifest.json`](witnesses/two-hub.manifest.json) |
| **22 of 22** | **Deleting any one of them from the witness changes the answer.** Checked on relate-db and on the Relate CLI: `22 of 22 change the answer`. | [`witnesses/two-hub.manifest.json`](witnesses/two-hub.manifest.json), [`evidence/pull-each-tag.json`](evidence/pull-each-tag.json) (what each deletion does to the answer) |
| **68 → 22** | **The answer rows bind 68 relationships; the witness keeps 22 of them.** Deleted from the full graph, only 20 of the 68 change the answer; the other 48 change nothing. 11 of those 20 are in the witness; the other 9 are flights of Mexican airports outside it, whose deletion adds that airport to the answer. Deleted from the witness, each of the 22 changes it. | [`evidence/neo4j-compare-2026-11-24.md`](evidence/neo4j-compare-2026-11-24.md) (targeted pass), [`evidence/full-graph-necessity.json`](evidence/full-graph-necessity.json), [`witnesses/two-hub.manifest.json`](witnesses/two-hub.manifest.json), [`queries/two-hub-bindings.cypher`](queries/two-hub-bindings.cypher) (the binding query) |
| **57,645 → 5** | **A second case: two queries disagree.** A plausible agent mistake written for this case (the first flight matched in either direction) and the headline query disagree on IN/DEL; `5 of 5 end the disagreement`. | [`witnesses/direction-bug.manifest.json`](witnesses/direction-bug.manifest.json) |
| **57,645 → 92** | **A third: a smaller repro of a wrong answer (`differs`).** The same mistaken query returns 13 rows where the expected answer has 12, and the repro keeps that wrong answer; `92 of 92 change the answer`. | [`witnesses/wrong-answer.manifest.json`](witnesses/wrong-answer.manifest.json) |
| **371 trials · 1.095 s** | **Delete, re-run, roll back.** 86 deletions kept the answer and were then applied. Trials and deletions repeat exactly; wall-clock seconds do not: the landing's paste reduced in 0.998 s, the video's take in 0.91 s. | [`witnesses/two-hub.manifest.json`](witnesses/two-hub.manifest.json) (this run), [`evidence/demo-2026-11-24.txt`](evidence/demo-2026-11-24.txt) (the landing's paste), [`evidence/video-demo-run-2026-11-27.txt`](evidence/video-demo-run-2026-11-27.txt) (the video's take) |
| **366.8 vs 90.2** | **Trials per second: Relate in-process, then Neo4j 2026.10.2 in Docker.** The same loop and query on one machine, median of 3 runs, the same answer on every trial. It measures this setup (Docker VM, Bolt round trip), not a limit of Neo4j. | [`evidence/neo4j-compare-2026-11-24.md`](evidence/neo4j-compare-2026-11-24.md) |
| **517 tests pass · 100% coverage** | **Tests pass against real Relate, under a 100% line and branch coverage gate.** The graph store, rollback and queries are never mocked. `relate pull` (needs a Neo4j server) is stood in, and a few tests substitute timers, process calls, a failing CLI, a database wrapper that injects engine faults, or one reducer phase to reach rare branches. 2 more tests need a local Neo4j in Docker and skip without it. | [`evidence/pytest-2026-11-27.txt`](evidence/pytest-2026-11-27.txt) (`pytest --cov=witness`), [`pyproject.toml`](pyproject.toml) (the gate) |
| **byte-identical** | **The same query and seed give a byte-identical rebuild script (`.cypher`) on 2 runs.** | [`evidence/determinism.json`](evidence/determinism.json), [`scripts/determinism.py`](scripts/determinism.py) (re-records it) |

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
| 7 | `relate query --mode json` | The independent re-check: when the Relate CLI is installed, sufficiency and the necessity probes run again on it, outside the Python API. In the committed run, all 22. | [`src/witness/check.py`](src/witness/check.py) |
| 8 | `MCP · why · check` | A client answers through Relate's own server, then calls Witness's `why` for the evidence of that answer; `check` re-proves a witness. Recorded twice: a scripted client that calls both, and a real model that calls `why`. | [`src/witness/mcp_server.py`](src/witness/mcp_server.py), [`evidence/mcp-transcript.md`](evidence/mcp-transcript.md), [`evidence/mcp-agent-session.md`](evidence/mcp-agent-session.md) |

The graph is persisted. Stores committed in this repository:

| Store | What it is | Nodes | Relationships |
|---|---|---|---|
| [`data/air-routes.rl`](data/air-routes.rl) | the source graph, never opened for writing | 3,748 | 57,645 |
| [`witnesses/two-hub.rl`](witnesses/two-hub.rl) | the headline witness | 12 | 22 |
| [`witnesses/direction-bug.rl`](witnesses/direction-bug.rl) | the witness of a disagreement between two queries | 5 | 5 |
| [`witnesses/wrong-answer.rl`](witnesses/wrong-answer.rl) | the smaller repro of a wrong answer | 45 | 92 |
| [`fixtures/mex-foreign.rl`](fixtures/mex-foreign.rl) | a test fixture: pulled from Neo4j once, then shrunk | 88 | 126 |

Also committed: [`witness.rl`](witness.rl), the ledger of reductions, where a review verdict is recorded.

The question: Which airports of MX have no direct flight to MEX, yet would still reach it in two flights if any one hub closed? The answer: PBC, QRO, TLC, UPN.

## Verify it yourself

1. **Run the whole path.** Needs uv. The committed graph is copied, never modified; the output goes to `out/`. The recorded run reports 5.78 s end to end on an Apple M1 Max ([`evidence/demo-2026-11-24.txt`](evidence/demo-2026-11-24.txt)).

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

3. **Re-run it with plain Relate.** Needs the Relate CLI. No Witness code runs: the witness is an ordinary `.rl` file.

   ```bash
   relate query --database witnesses/two-hub.rl --read-only \
     --param country=MX --param dest=MEX \
     < queries/two-hub.cypher
   ```

   Expect the same 4 airports the full graph gives: PBC, QRO, TLC, UPN.

4. **Run the tests.** CI and deterministic replay, not the product path.

   ```bash
   uv run pytest --cov=witness
   ```

   Expect 517 passed and 100% line and branch coverage; 2 more need a local Neo4j in Docker and skip without it.

More commands, one section per set of numbers: [`DEMO.md`](DEMO.md). The two receipts it does not cover have their own scripts: [`scripts/pull_each_tag.py`](scripts/pull_each_tag.py) and [`bench/full_graph_necessity.py`](bench/full_graph_necessity.py). The files behind every figure on this page: [`evidence/`](evidence/), [`witnesses/`](witnesses/).

## By criterion

The [listing](https://relate.devpost.com/)'s five criteria, each with the files and sections that answer it. Nothing below is a score; it is where the evidence is.

### Creativity

- **Rollback as the search loop.** 371 delete, re-run, roll-back trials take 57,645 relationships down to 22 ([`src/witness/reduce.py`](src/witness/reduce.py), [`witnesses/two-hub.trace.json`](witnesses/two-hub.trace.json)).
- **Not a path lookup.** The headline question uses aggregation, `NOT EXISTS` and `OPTIONAL MATCH`, and the witness still reproduces its answer ([`queries/two-hub.cypher`](queries/two-hub.cypher)).
- **One loop, three predicates.** It can hold on to an answer (22 relationships), a disagreement between two queries (5), or a wrong answer (92) ([`witnesses/two-hub.manifest.json`](witnesses/two-hub.manifest.json), [`witnesses/direction-bug.manifest.json`](witnesses/direction-bug.manifest.json), [`witnesses/wrong-answer.manifest.json`](witnesses/wrong-answer.manifest.json)).

### Relate and connected context

- **Mode: single-file `.rl`.** The unit of evidence is a file a reviewer opens with plain `relate`. Mode, reason and capabilities are in [How it uses Relate](#how-it-uses-relate).
- **Which relationships matter is measured.** Each of the 22 is deleted in turn and the query re-run; all 22 change the answer ([`evidence/pull-each-tag.json`](evidence/pull-each-tag.json)).
- **The graph is persisted in the repository.** The source, the witness and the ledger of reductions are committed `.rl` stores ([`data/air-routes.rl`](data/air-routes.rl), [`witnesses/two-hub.rl`](witnesses/two-hub.rl), [`witness.rl`](witness.rl)).
- **Beside Relate's own MCP server.** A scripted client and, separately, a real model answer through `relate serve --mcp`, then call Witness's `why` for the evidence; the scripted client also calls `check` ([`evidence/mcp-transcript.md`](evidence/mcp-transcript.md), [`evidence/mcp-agent-session.md`](evidence/mcp-agent-session.md)).

### Functionality and completeness

- **One command, the whole path.** On a fresh clone: copy, guard, order check, reduce, check, then the exhibit page and a ledger row. The commands are in [Verify it yourself](#verify-it-yourself).
- **More than the demo.** `witness why` on any read-only query, `check`, `rerun`, `export`, `review`, fixture mode and an MCP server ([`src/witness/cli.py`](src/witness/cli.py), [`src/witness/mcp_server.py`](src/witness/mcp_server.py)).
- **Tested against real Relate.** 517 tests pass under a 100% line and branch coverage gate; CI runs 6 stages, one of them the built wheel running `witness demo` and plain `relate` re-running the committed witness ([`evidence/pytest-2026-11-27.txt`](evidence/pytest-2026-11-27.txt), [`.github/workflows/ci.yml`](.github/workflows/ci.yml)).
- **It refuses what it cannot do.** Writes, procedures, clocks and randomness exit 2 with a one-line reason ([`src/witness/guard.py`](src/witness/guard.py), [`tests/test_guard.py`](tests/test_guard.py), [`tests/test_errors.py`](tests/test_errors.py)).

### Usefulness

- **Who it is for.** The developer whose agent answers from a graph and who has to show why an answer is right before anyone acts on it: a reviewer reads 22 relationships instead of 57,645.
- **An agent attached the evidence itself.** In a recorded session a real model (claude-sonnet-5-5 in Claude Code) wrote its own Cypher, called `why` over MCP and attached the witness of its answer: `68 of 68 change the answer`. Its answer also reports hub counts, so all 68 relationships the answer rows bind are needed ([`evidence/mcp-agent-session.md`](evidence/mcp-agent-session.md)).
- **It shows where a wrong query goes wrong.** Two versions of the question disagree on 6 of 232 country and busiest-airport pairs; for India and DEL, 5 relationships keep them disagreeing, one of them the flight the mistaken query read backwards ([`evidence/disagree-scan.json`](evidence/disagree-scan.json), [`witnesses/direction-bug.manifest.json`](witnesses/direction-bug.manifest.json)).
- **A second use: test fixtures.** `relate pull` brought 1,272 relationships in from Neo4j once, and Witness kept the 126 the test needs ([`fixtures/mex-foreign.manifest.json`](fixtures/mex-foreign.manifest.json)).

### Documentation and reproducibility

- **The README answers the listing's question.** How Witness uses Relate, which mode, and why ([`README.md`](README.md)).
- **Commands, not only claims.** [`DEMO.md`](DEMO.md) gives the command or the recorded run for 8 sets of numbers: the headline, determinism, the Neo4j comparison, fixture mode, the MCP tools, the tests, the disagreement and the wrong-answer repro.
- **The page cannot drift from the evidence.** This page and [`JUDGE.md`](JUDGE.md) are written by [`scripts/build_site.py`](scripts/build_site.py) from the committed files; CI rebuilds both and fails on any difference ([`.github/workflows/ci.yml`](.github/workflows/ci.yml)).
- **Shown running.** The [demo video (1:55)](https://youtu.be/GYbci7TseJw) and the [pitch deck](https://witness.edycu.dev/deck/). What the stamp does not say is in [Honest limitations](#honest-limitations).

## Honest limitations

- Deletion-minimal, not smallest: no single remaining relationship can be removed without changing the answer; a smaller witness may exist.
- Its own answer, on its own file: because a query with `NOT EXISTS` or aggregation is not monotone, a witness does not prove that every graph containing it gives the same answer. It also leaves out true facts the answer does not need: MEX has no country link in [`witnesses/two-hub.rl`](witnesses/two-hub.rl).
- Read-only Cypher only, with no clock or randomness: Witness refuses writes, procedures, clocks and randomness (exit 2) rather than guess. Dependence on storage order is caught by a heuristic (the same answer from a store built in reverse order), not proven absent.
- One graph (a public air-routes dataset, Apache-2.0): the headline query, one disagreement case and one wrong-answer repro. The Neo4j comparison is one machine, one query, one graph; it measures this setup (Docker VM, Bolt round trip), not a limit of Neo4j.

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
