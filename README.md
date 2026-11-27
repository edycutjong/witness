<div align="center">
  <img src="docs/assets/icon.svg" alt="Witness Icon" width="144">
  <h1>Witness 🔎</h1>
  <p><em>Witness: why does this query return this row? A deletion-minimal graph that reproduces the answer (57,645 relationships → 22): deleting any one of its relationships changes the answer.</em></p>
  <img src="docs/assets/readme-hero-animated.svg" alt="Witness reduces the graph behind an agent's answer to the relationships that reproduce it. Thousands of graphite lines fade; a handful stay, each tagged with a red exhibit number; the answer above never moves." width="100%">

  <br/>

  [![Live Site](https://img.shields.io/badge/🚀_Live-Site-B42318?style=for-the-badge)](https://witness-wheat.vercel.app)
  [![For judges](https://img.shields.io/badge/For_judges-open_%2Fjudge-1F1A14?style=for-the-badge)](https://witness-wheat.vercel.app/judge/)
  [![Relate by Neo4j Hackathon](https://img.shields.io/badge/Devpost-Relate_by_Neo4j_Hackathon-1F1A14?style=for-the-badge)](https://relate.devpost.com/)

  <br/>

  [![CI](https://github.com/edycutjong/witness/actions/workflows/ci.yml/badge.svg)](https://github.com/edycutjong/witness/actions/workflows/ci.yml)
  [![Release](https://img.shields.io/github/v/release/edycutjong/witness?sort=semver)](https://github.com/edycutjong/witness/releases/latest)
  ![Python](https://img.shields.io/badge/Python_3.11_|_3.12-3776AB?style=flat&logo=python&logoColor=white)
  ![Relate](https://img.shields.io/badge/Relate_1.0.1-1F1A14?style=flat)
  ![Tests](https://img.shields.io/badge/tests-517_passed-2ea043?style=flat)
  [![License](https://img.shields.io/badge/License-Apache_2.0-yellow)](LICENSE)

</div>

---

## 💡 The Problem & Solution

**Use case:** checking an agent's graph answer by reading 22 relationships instead of 57,645.

**Run it:** `git clone https://github.com/edycutjong/witness && cd witness && uv run witness demo` (needs [`uv`](https://docs.astral.sh/uv/)).
Expect `22 of 22 change the answer` and exit 0; details in [Getting Started](#-getting-started-setup-and-run).

### The Problem

An agent answers a question from a graph of tens of thousands of relationships. A reviewer cannot read them all, so the
answer is taken on trust. "Show the path" is not enough either: a path can include relationships that change nothing.

### The Solution

**Who benefits:** the developer whose agent answers from a graph and who has to show why an answer is right before anyone
acts on it.
Witness takes a read-only query and its answer and deletes relationships, with Relate transactions as the inner loop, until
no single remaining relationship can go without changing the answer. What is left is a witness: a small `.rl` file anyone can
re-run with plain `relate`.

On the committed air-routes graph, the headline question (`queries/two-hub.cypher`: which Mexican airports have no direct flight to MEX, yet reach it in two flights through at least two different hubs, so they would still reach it if any one hub closed; a hub is
any intermediate airport)
shrinks **57,645 relationships to 22** (12 nodes) in 371 trials and 1.1 s, and `witness check` confirms "22 of 22 change the
answer" on the Python API and on the Relate CLI (`witnesses/two-hub.manifest.json`).

**Against "show the path".** The answer rows bind 68 relationships (`queries/two-hub-bindings.cypher`). Deleting each of
those 68 from the full graph changes the answer for only 20 of them; the other 48 change nothing, because other routes back
them up (`evidence/neo4j-compare-2026-11-24.md`, targeted pass). The witness keeps 22 of the 68, and deleting any one of them
from the witness changes the answer. Necessity is proven inside the witness, not in the full graph: 11 of those 20 are in the witness,
and each of the other 9 is the direct flight to MEX of a Mexican airport outside the witness (CUN, DGO, GDL, MTY, MZT, PVR,
SJD, TGZ, ZIH), whose deletion adds that airport to the answer (it no longer has a direct flight). The witness does not contain
those nine airports, so it does not need their flights (`bench/full_graph_necessity.py`,
`evidence/full-graph-necessity.json`).

**Deletion-minimal** means: no single remaining relationship (or kept isolated node) can be removed without changing the
answer. It does not mean "smallest possible". Because a query with `NOT EXISTS` or aggregation is not monotone, a witness proves its own
answer on its own file; it does not prove that every superset of it gives the same answer. A witness also leaves out true
facts the answer does not need: MEX has no country link in `witnesses/two-hub.rl`. It reproduces an answer, not the world.

**What it refuses (exit 2):** anything outside a read-only, deterministic subset. Witness's own token check refuses writes,
procedures, `LOAD CSV`, clocks, randomness and store ids, then Relate's own `query_type` must be `"r"`; plus a heuristic check
for storage-order dependence. Witness never writes to the source.

### A second case: two queries disagree

A plausible agent mistake, written for this case: the same question with the first
flight matched in either direction (`queries/two-hub-agent.cypher`). On 6 of 232 country and busiest-airport pairs the two queries disagree
(`bench/disagree_scan.py`, `evidence/disagree-scan.json`). For India and DEL, `witness why --predicate disagree` shrinks
57,645 relationships to 5 in 139 trials, and `witness check` confirms "5 of 5 end the disagreement"
(`witnesses/direction-bug.*`, `evidence/direction-bug-run.txt`). The five include the flight the agent's query read backwards,
`(VNS)-[:HAS_ROUTE]->(AGR)`, as if Agra flew to VNS, so VNS counted as an extra hub on Agra's way to DEL.

**The third predicate, `differs`: a smaller repro of a wrong answer.** Give Witness the answer you expected (here, the
reference query's 12 rows for India and DEL, `evidence/wrong-answer-expected.json`) and the query that gets it wrong (the
same agent query returns 13: the 12 plus AGR). `--predicate differs` keeps that same wrong answer while it deletes:
57,645 relationships → 92 (45 nodes) in 2,099 trials, "92 of 92 change the answer", cross-checked on the Relate CLI
(`witnesses/wrong-answer.*`, `evidence/wrong-answer-run.txt`). The repro is larger than the disagreement witness because it
must reproduce all 13 wrong rows, not only the one that disagrees.

### How it uses Relate

- **Mode:** single file (`.rl`). Reductions run on a file-backed scratch copy of the source in a temp dir; the committed
  source is copied byte-for-byte, never opened for writing, and its SHA-256 is checked unchanged after every run.
- **Why this mode:** the unit of evidence is a file. One `.rl` per witness can be committed, handed over and re-run by a
  reviewer with `relate` alone, with no server. A directory store is many files; `:memory:` disappears when the process ends
  and cannot be inspected.
- **What the graph models:** the air-routes network (Kelvin Lawrence): 3,504 airports, 237 countries and 7 continents (3,748 nodes), and
  57,645 relationships: `(:Airport {iata})-[:HAS_ROUTE]->(:Airport)` for a scheduled route, `(:Airport)-[:IN_COUNTRY]->(:Country {code})`
  and `(:Airport)-[:ON_CONTINENT]->(:Continent)`. The relationships that matter are the ones that carry a query's answer.
- **Where the data lives:** `data/air-routes.rl` (source), `witnesses/two-hub.rl` (the committed witness), `witness.rl` (the
  ledger of reductions), `fixtures/` (fixture-mode stores).

Relate capabilities used:

1. explicit transactions (`begin_transaction` / `rollback_transaction` / `commit_transaction`), the reducer's inner loop (`store.py`, `ledger.py`)
2. `QueryResult.query_type` to refuse non-read queries (`guard.py`)
3. `EXPLAIN` plans to drop labels and types a query cannot reach in one verified step (`reduce.py`)
4. `read_only=True` opens, so the rerun, ledger-reader and fixture-test paths cannot write (`cli.py`, `ledger.py`, `fixture.py`)
5. single-file `.rl` stores as the witness, source and ledger format (`export.py`, `ledger.py`)
6. `relate pull` for fixture mode: one pull from Neo4j, then shrink; never pushed back (`fixture.py`)
7. `relate query --mode json` on the CLI as the independent re-check of every probe (`check.py`)
8. MCP: Witness's own tools `why` and `check` (`mcp_server.py`) run beside Relate's `relate serve --mcp`; the pairing is exercised in `scripts/mcp_transcript.py` and `evidence/mcp-transcript.md`, and with a real model in `evidence/mcp-agent-session.md`

### How the reduction works

**How 371 trials remove 57,623 relationships.** Trial 1 checks that the empty graph changes the answer. The `EXPLAIN` plan shows `:ON_CONTINENT`
cannot reach the answer, so trial 2 drops its 3,504 relationships and the 7 `:Continent` nodes at once (3,748 → 3,741 nodes). Phase A runs ddmin (delta debugging) over nodes: one `DETACH DELETE` takes a node with
all its relationships, and 69 of 253 trials keep the answer (3,729 nodes go, 3,741 → 12; 54,141 → 50 relationships). Phase B runs ddmin over
the 50 remaining relationships (16 of 116 trials keep it; 50 → 22). 86 deletions applied, 285 rolled back
(`witnesses/two-hub.trace.json`).

**Absences.** The headline's `NOT EXISTS` (no direct flight to MEX) is an absence, and no subgraph can draw one. Every answer
row already required that absence in the full graph, the manifest records the full graph's answer (`baseline`), and the witness
reproduces it. `witness demo` also prints the full graph's counts per airport (the ABSENT block); `witness why` on other
queries reports the full graph's answer but not those per-clause counts.

## 🏗️ Architecture & Tech Stack

<p align="center"><img src="docs/architecture.svg" alt="Architecture: entry points (CLI, MCP) feed a guard; the reducer copies the read-only source into a scratch store and runs delete, query, keep-or-rollback trials; survivors become a witness .rl with a manifest; witness check re-proves each relationship on a fresh copy and on the relate CLI." width="100%"></p>

| Layer | Choice |
|---|---|
| Engine | Relate 1.0.1 (`relate-db`, embedded, single file) |
| Reducer, checker, CLI, MCP | Python 3.11+ (developed on 3.12), `uv` |
| Source data | air-routes by Kelvin Lawrence (Apache-2.0), reshaped for Relate; see `NOTICE`, `data/SOURCE.md` |
| Landing | static `site/` on Vercel, built from the committed witness by `scripts/build_site.py` |

## 🚀 Getting Started (setup and run)

### Prerequisites

[`uv`](https://docs.astral.sh/uv/) and Python 3.11 or newer. The optional CLI cross-check needs the `relate` CLI (signed installer at relatedb.ai).

### Installation

```bash
git clone https://github.com/edycutjong/witness && cd witness
uv sync              # optional: install the locked dependencies (uv run does this on first use)
uv run witness demo
```

`demo` copies the committed source graph (`data/air-routes.rl`, never modified), asks the headline question
(`queries/two-hub.cypher`), reduces the answer to a deletion-minimal witness, re-proves it with `witness check`, and writes
`out/two-hub.{rl,cypher,manifest.json,html,trace.json}` plus a ledger row in `out/ledger.rl`. Nothing it runs changes a
committed file. The committed result of the same command is in `witnesses/two-hub.*`, `answers/two-hub.json` and `witness.rl`.

Then re-run the witness yourself with plain `relate`:

```bash
relate query --database witnesses/two-hub.rl --read-only --param country=MX --param dest=MEX < queries/two-hub.cypher
```

### Commands

| Command | What it does |
|---|---|
| `witness demo` | the whole path on the committed graph |
| `witness why -f Q.cypher [--param k=v] [--predicate keep\|differs\|disagree]` | reduce any read-only query's answer |
| `witness check W.rl` | re-prove a witness from its manifest: "N of N change the answer" (exit 0/1) |
| `witness rerun W.rl -f Q.cypher [--param k=v] [--print-cli]` | re-run the query on a witness, read-only, no CLI needed |
| `witness export <ledger-id\|out-dir\|W.rl> --to DIR` | copy a reduction's files |
| `witness review [ID] [--accept\|--dispute REASON]` | list unreviewed reductions, or record a verdict |
| `witness mcp [--allow DIR]` | stdio MCP server with tools `why` and `check`, beside Relate's own `relate serve --mcp` (needs the `mcp` extra: `uv run --extra mcp witness mcp`); see [Use it from an agent](#use-it-from-an-agent-mcp) |
| `witness fixture --from neo4j.env --pull SLICE.cypher --test Q.cypher --expect ROWS.json` | `relate pull` a slice from Neo4j once, shrink it to a deletion-minimal fixture (no single relationship can go without changing the test's answer), write a pytest file; never pushes back (`fixtures/mex-foreign.*`: 1,272 relationships pulled, 126 kept, 126 of 126 change the answer) |

Exit codes: 0 verified · 1 NOT verified · 2 refused (outside the supported read-only subset: no writes, procedures, `LOAD CSV`, clocks, randomness, store ids or
storage-order dependence, the last one heuristic) · 3 trial cap ·
4 aborted by the demo watchdog.

Variants: with `--predicate disagree` "deletion-minimal" reads "without ending the disagreement", and with `differs --loose` "without ending the mismatch".

"The same answer" is exact about types (`1`, `1.0` and `true` differ) and compares rows as a bag (row order is not part of
the answer, even under a final `ORDER BY`; only an `ORDER BY` with `SKIP`/`LIMIT` uses the order, and Witness applies that
cut itself), lists as bags unless `--strict-lists` (the headline demo uses it), floats to 12 significant digits
(`--float-digits`). Each manifest records
these settings under `comparison`. The proof is `witness check`: one fresh copy of W per probe, nothing shared with the
reduction. The node and relationship counts checked after every rollback during the reduction are a tripwire for rollback
residue, not the proof.

### Use it from an agent (MCP)

`witness mcp` is a stdio MCP server with two tools; run it beside Relate's own MCP server. A client config (use your clone's path):

```json
{"mcpServers": {
  "relate":  {"command": "relate", "args": ["serve", "--database", "/path/to/witness/data/air-routes.rl", "--read-only", "--mcp", "stdio"]},
  "witness": {"command": "uv", "args": ["run", "--directory", "/path/to/witness", "--extra", "mcp", "witness", "mcp"]}
}}
```

- `why(statement, parameters?, store?, predicate?, expected?, other_statement?, answer?)` reduces the answer and returns
  `verified`, the `check` line ("N of N change the answer"), the exhibits, the witness files and `evidence_markdown` (at most
  25 lines) to paste into the reply. `parameters` is an object; `store` defaults to `data/air-routes.rl`; `predicate` is
  `keep` (default), `differs` (with `expected`: the expected rows) or `disagree` (with `other_statement`: the second query).
  Pass the rows you showed as `answer` (objects keyed by column): if they differ from the store's answer, nothing is attached.
  Stores must sit in `data/` or `witnesses/` by default; `--allow DIR` (repeatable) replaces that list, so pass
  `--allow data --allow witnesses` too if you still want them (`--allow` paths are relative to where `witness mcp` starts).
- `check(witness_path, statement?, parameters?)` re-proves a witness from its `.rl` and manifest, under the comparison
  settings the manifest records (so the committed `--strict-lists` witnesses are re-proved strictly). With `statement`, the
  agent's own query is compared as `keep` against the manifest's baseline answer.
- `why` compares answers with the CLI's defaults: rows and lists as bags, floats to 12 significant digits, `differs` in its
  strict form. `--strict-lists` and `--loose` are CLI-only. Both tools cross-check on the Relate CLI unless `witness mcp`
  starts with `--no-cli`; that is a server flag, not a tool argument.
- Replies are bounded so a client can read them: at most 50 exhibits, 50 failing probes and 50 answer rows (whole rows,
  20,000 characters at most, `rows_truncated` when some are left out), each with its total. `probes_total` says how many
  necessity probes ran; a probe whose trial gave no verdict is listed under `inconclusive_probes`, never as
  `not_necessary`. The manifest beside the witness keeps everything.

Abridged call and reply (`…` marks elided fields; `statement` carries the query text; full replies in
`evidence/mcp-transcript.md`):

```text
why {"statement": "<queries/two-hub.cypher>", "parameters": {"country": "MX", "dest": "MEX"},
     "answer": [{"airport": "PBC", "hub_countries": ["MX", "US"]}, …]}
→ {"verified": true, "witness": {"relationships": 22, "nodes": 12, …},
   "check": {"check_text": "22 of 22 change the answer (…)", "not_necessary": [], …},
   "exhibits": [{"n": 1, "start": "ACA", "type": "HAS_ROUTE", "end": "MEX"}, …], "exhibits_total": 22,
   "files": {"rl": "out/mcp-…/witness.rl", …},
   "evidence_markdown": "**Answer** (4 rows): …\n**Evidence:** 22 relationships (of 57,645) reproduce it; 22 of 22 change the answer — verified deletion-minimal. …"}
```

Two recorded sessions: `evidence/mcp-transcript.md` (a scripted client: an answer, a refused write, a mismatched answer) and
`evidence/mcp-agent-session.md` (a real model, claude-sonnet-5-5 in Claude Code, writing its own Cypher and attaching the
witness for a different answer from the headline's: its rows also report hub counts, so all 68 relationships the answer rows
bind are needed, 68 of 68).

### Measured against Neo4j

The same rollback-trial loop (delete one relationship, run the headline query, roll back, check counts) ran on Relate in-process
(a file-backed scratch copy) and on Neo4j 2026.10.2 in Docker over Bolt: median of 3 runs of 1,000 trials, 366.8 vs 90.2
trials/s on one machine, with identical answers per trial: 1,000 sampled relationships run 3 times (2 of them change the answer), plus all 68
answer-relevant relationships (20 change it). The
throughput includes each side's count check (two extra Bolt queries per trial on Neo4j); per-trial latency from begin to
rollback, which excludes it on both sides, is p50 2.54 vs 6.48 ms (median of the 3 runs). The gap mostly reflects an embedded engine versus a Dockerised server with a network round trip per statement; it says nothing about Neo4j's query engine. Method, caveats and raw rows:
`evidence/neo4j-compare-2026-11-24.md`, `bench/neo4j_compare.py`.

## 🧪 Testing & CI

```bash
make ci                          # ruff, mypy, pytest with the 100% coverage gate, pip-audit, gitleaks
uv run pytest --cov=witness      # 517 pass against real Relate (2 more need a local Neo4j), 100% line + branch coverage
```

Reproduce every number in this README: [DEMO.md](DEMO.md). Raw evidence and the machine/version of each run:
`evidence/` (this suite's run: `evidence/pytest-2026-11-27.txt`; the last full local CI run: `evidence/ci-local-2026-11-27.txt`). The tests use real Relate, not mocks of the graph store. The graph store, the rollback transactions and the queries are never mocked. `relate pull` is stood in for in the fixture-mode tests (it needs a running Neo4j server; the Neo4j side is exercised by `bench/neo4j_compare.py`), and a few tests substitute timers, process calls, a failing CLI, a database wrapper that injects engine faults, or one reducer phase to reach a rare branch.

GitHub Actions (`.github/workflows/ci.yml`) runs six stages: **Quality** (ruff, mypy, tests with the coverage gate; Python 3.11
and 3.12 on `main`) and **Security** (gitleaks over the full history, pip-audit) in parallel, then **Build** (wheel, sdist,
the site checked against the committed evidence), **E2E** (the built wheel: `witness demo`, the plain Relate CLI re-running the
committed witness, the site and `/judge/` with no credentials), **Performance** (a throughput floor) and a **Deploy Gate**.
CodeQL and secret scanning run on their own; releases are cut from Angular-style commit messages
(`.github/workflows/release.yml`); Dependabot proposes grouped minor and patch updates monthly and never a major.
For judges: [JUDGE.md](JUDGE.md), also served at <https://witness-wheat.vercel.app/judge/>.

## 📽️ Demo Materials

- Demo video (1:55): https://youtu.be/GYbci7TseJw
- Landing page: https://witness-wheat.vercel.app (`site/`)
- Reproduce steps: [DEMO.md](DEMO.md)

## 🧰 Tools and AI use

- **Product capabilities:** Relate 1.0.1 (embedded engine, `relate` CLI, `relate serve --mcp`).
- **Third-party tools:** `uv`, pytest, Neo4j 2026.10.2 in Docker (comparison and fixture source only), Vercel (landing hosting).
- **AI use:** built with Claude Code as the coding agent, under the author's direction. The author is responsible for the result.
  The demo video's voiceover is an AI voice (ElevenLabs) reading a script drafted by Claude Code under the author's direction; its music and sound are synthesized in code.
- **Built during the contest period:** first commit 2026-11-15 (`git log --reverse`). No code from before the contest.
- **Reused material:** the air-routes dataset by Kelvin Lawrence (Apache-2.0, commit `efd3b1a`), modified as stated in `NOTICE`.

## 📄 License

Apache-2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
