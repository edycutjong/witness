# Witness

When an agent answers from a graph, Witness hands back a tiny graph that reproduces the answer, and proves each relationship in it is needed.

Built on [Relate](https://relatedb.ai). License: Apache-2.0. Work in progress: this README is the quick start; the full
write-up comes later.

## Quick start

```bash
git clone https://github.com/edycutjong/witness && cd witness
uv run witness demo
```

`demo` copies the committed source graph (`data/air-routes.rl`, never modified), asks the headline question
(`queries/two-hub.cypher`), reduces the answer to a deletion-minimal witness with Relate transactions as the inner loop,
re-proves it with `witness check`, and writes `out/two-hub.{rl,cypher,manifest.json,html,trace.json}` plus a ledger row in
`out/ledger.rl`. Nothing it runs changes a committed file.

The committed result of the same run is in `witnesses/two-hub.*`, `answers/two-hub.json` and the ledger `witness.rl`.

## Commands

| Command | What it does |
|---|---|
| `witness demo` | the whole path on the committed graph |
| `witness why -f Q.cypher [--param k=v] [--predicate keep\|differs\|disagree]` | reduce any read-only query's answer |
| `witness check W.rl` | re-prove a witness from its manifest: "N of N change the answer" (exit 0/1) |
| `witness rerun W.rl -f Q.cypher [--param k=v] [--print-cli]` | re-run the query on a witness, read-only, no CLI needed |
| `witness export <ledger-id\|out-dir\|W.rl> --to DIR` | copy a reduction's files |
| `witness review [ID] [--accept\|--dispute REASON]` | list unreviewed reductions, or record a verdict |
| `witness mcp [--allow DIR]` | stdio MCP server with tools `why` and `check`, beside Relate's own `relate serve --mcp`; transcript: `evidence/mcp-transcript.md` |
| `witness fixture --from neo4j.env --pull SLICE.cypher --test Q.cypher --expect ROWS.json` | `relate pull` a slice from Neo4j once, shrink it to a deletion-minimal fixture (no single relationship can go without changing the test's answer), write a pytest file; never pushes back (`fixtures/mex-foreign.*`: 1,272 relationships pulled, 126 kept, 126 of 126 change the answer) |

Exit codes: 0 verified · 1 NOT verified · 2 refused (outside the supported read-only subset: no writes, procedures, `LOAD CSV`, clocks, randomness, store ids or
storage-order dependence) · 3 trial cap ·
4 aborted by the demo watchdog.

Deletion-minimal means: no single remaining relationship (or kept isolated node) can be removed without changing the
answer. It does not mean "smallest possible". With `--predicate disagree` the same sentence reads "without ending the
disagreement" (one query's answer may stay put), and with `differs --loose` "without ending the mismatch".

"The same answer" is exact about types (`1`, `1.0` and `true` differ) and compares rows as a bag (row order is not part of
the answer, even under a final `ORDER BY`; only an `ORDER BY` with `SKIP`/`LIMIT` uses the order, and Witness applies that
cut itself), lists as bags unless `--strict-lists` (the headline demo uses it), floats to 12 significant digits
(`--float-digits`). Each manifest records
these settings under `comparison`. The proof is `witness check`: one fresh copy of W per probe, nothing shared with the
reduction. The node and relationship counts checked after every rollback during the reduction are a tripwire for rollback
residue, not the proof.

With the Relate CLI installed, the same check runs on the CLI too, and you can re-run the witness yourself:

```bash
relate query --database witnesses/two-hub.rl --read-only --param country=MX --param dest=MEX < queries/two-hub.cypher
```

## Measured against Neo4j

The same rollback-trial loop (delete one relationship, run the headline query, roll back, check counts) ran on Relate in-process
(a file-backed scratch copy) and on Neo4j 2026.10.2 in Docker over Bolt: median of 3 runs of 1,000 trials, 366.8 vs 90.2
trials/s on one machine, with identical answers per trial: 1,000 sampled relationships run 3 times (2 of them change the answer), plus all 68
answer-relevant relationships (20 change it). The
throughput includes each side's count check (two extra Bolt queries per trial on Neo4j); per-trial latency from begin to
rollback, which excludes it on both sides, is p50 2.54 vs 6.48 ms (median of the 3 runs). Method, caveats and raw rows:
`evidence/neo4j-compare-2026-11-24.md`, `bench/neo4j_compare.py`.

## Landing page

`site/` is the static landing (deployed on Vercel at https://witness-wheat.vercel.app). `scripts/build_site.py` builds it from the committed witness and evidence files.
