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

Exit codes: 0 verified · 1 NOT verified · 2 refused (outside the supported read-only, deterministic subset) · 3 trial cap ·
4 aborted by the demo watchdog.

Deletion-minimal means: no single remaining relationship can be removed without changing the answer. It does not mean
"smallest possible".

With the Relate CLI installed, the same check runs on the CLI too, and you can re-run the witness yourself:

```bash
relate query --database witnesses/two-hub.rl --read-only --param country=MX --param dest=MEX < queries/two-hub.cypher
```
