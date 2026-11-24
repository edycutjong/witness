# For judges

**The claim.** When an agent answers from a graph, Witness hands back the graph that reproduces the answer (57,645 relationships → 22) and proves each relationship in it is needed.

## The 30-second path

1. [Open the landing page](https://witness-wheat.vercel.app/): the agent's answer, the 22 relationships it rests on, and the check line; nothing to install.
2. [Open the exhibit page](https://witness-wheat.vercel.app/exhibit/two-hub.html): the register of kept relationships, each tagged as one whose deletion changes the answer.
3. Optional, one command: `git clone https://github.com/edycutjong/witness && cd witness && uv run witness demo` (needs uv; the repository opens at submission).

## The receipts

| Number | What it is |
|---|---|
| **57,645 → 22** | relationships in the air-routes graph vs in the witness (3,748 nodes → 12 nodes in the witness graph; `witnesses/two-hub.manifest.json`) |
| **22 of 22** | deleting any one relationship changes the answer; checked on relate-db and on the Relate CLI (`22 of 22 change the answer`) |
| **371 trials · 1.095 s** | delete, re-run, roll back; 86 deletions kept the answer and were applied (`witnesses/two-hub.manifest.json`) |
| **366.8 vs 90.2** | trials per second, Relate in-process vs Neo4j 2026.10.2 in Docker, median of 3 runs on one machine (`evidence/neo4j-compare-2026-11-24.md`) |
| **499 tests · 100% coverage** | real Relate, no mocks of the graph store (`evidence/pytest-2026-11-24.txt`, `pytest --cov=witness --cov-fail-under=100`) |
| **byte-identical** | the same query and seed give the same witness on 2 runs (`evidence/determinism.json`) |

## Reproduce it

```bash
git clone https://github.com/edycutjong/witness && cd witness
uv run witness demo
```

`uv run pytest  # CI / deterministic replay of the whole suite against real Relate; not the product path`

## Honest limitations

- Deletion-minimal, not smallest: no single remaining relationship can be removed without changing the answer; a smaller witness may exist.
- Read-only, deterministic Cypher only. Witness refuses writes, procedures, clocks and randomness (exit 2) rather than guess.
- One headline graph (a public air-routes dataset, Apache-2.0) and one headline query. The Neo4j comparison is one machine, one query, one graph; it measures this setup (Docker VM, Bolt round trip), not a limit of Neo4j.

## Links

- Repository: https://github.com/edycutjong/witness (opens at submission)
- Live site: https://witness-wheat.vercel.app/
- Exhibit page: https://witness-wheat.vercel.app/exhibit/two-hub.html
- Relate: https://relatedb.ai
