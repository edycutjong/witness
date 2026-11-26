# For judges

**The claim.** When an agent answers from a graph, Witness hands back a small graph that reproduces the answer (57,645 relationships → 22), and proves that deleting any one of its relationships changes the answer.

Witness is built on Relate, the embedded graph database, for the Relate by Neo4j hackathon.

## The 30-second path

1. [Open the landing page](https://witness-wheat.vercel.app/): the agent's answer, the 22 relationships that reproduce it, and the check line; nothing to install.
2. [Open the exhibit page](https://witness-wheat.vercel.app/exhibit/two-hub.html): the register of kept relationships, each tagged as one whose deletion changes the answer.
3. Optional, one command: `git clone https://github.com/edycutjong/witness && cd witness && uv run witness demo` (needs uv; the repository opens at submission).

## The receipts

| Number | What it is |
|---|---|
| **57,645 → 22** | relationships in the air-routes graph vs in the witness (3,748 nodes → 12 nodes in the witness graph; `witnesses/two-hub.manifest.json`) |
| **22 of 22** | deleting any one of them from the witness changes the answer; checked on relate-db and on the Relate CLI (`22 of 22 change the answer`) |
| **68 → 22** | the answer rows bind 68 relationships (`queries/two-hub-bindings.cypher`); deleted from the full graph, only 20 of them change the answer, because other routes back the rest up. The witness keeps 22, each needed (`evidence/neo4j-compare-2026-11-24.md`, targeted pass) |
| **57,645 → 5** | a second case: a plausible agent mistake written for this case (the first flight matched in either direction) and the headline query disagree on IN/DEL; `5 of 5 end the disagreement` (`witnesses/direction-bug.manifest.json`) |
| **371 trials · 1.095 s** | delete, re-run, roll back; 86 deletions kept the answer and were applied (`witnesses/two-hub.manifest.json`) |
| **366.8 vs 90.2** | trials per second, Relate in-process vs Neo4j 2026.10.2 in Docker, median of 3 runs on one machine (`evidence/neo4j-compare-2026-11-24.md`) |
| **505 tests pass · 100% coverage** | real Relate; the graph store, rollback and queries are never mocked. `relate pull` (needs a Neo4j server) is stood in, and a few tests substitute timers, process calls or a failing CLI to force rare branches (`evidence/pytest-2026-11-26.txt`, `pytest --cov=witness`, gate in `pyproject.toml`) |
| **byte-identical** | the same query and seed give a byte-identical rebuild script (`.cypher`) on 2 runs (`evidence/determinism.json`) |

## Reproduce it

```bash
git clone https://github.com/edycutjong/witness && cd witness
uv run witness demo
```

The repository opens at submission; until then use the live pages above.

The whole suite against real Relate (CI and deterministic replay, not the product path): `uv run pytest --cov=witness`

## Honest limitations

- Deletion-minimal, not smallest: no single remaining relationship can be removed without changing the answer; a smaller witness may exist.
- Read-only, deterministic Cypher only. Witness refuses writes, procedures, clocks and randomness (exit 2) rather than guess.
- One graph (a public air-routes dataset, Apache-2.0): the headline query and one disagreement case. The Neo4j comparison is one machine, one query, one graph; it measures this setup (Docker VM, Bolt round trip), not a limit of Neo4j.

## Links

- Repository: https://github.com/edycutjong/witness (the repository opens at submission)
- Live site: https://witness-wheat.vercel.app/
- Exhibit page: https://witness-wheat.vercel.app/exhibit/two-hub.html
- Relate: https://relatedb.ai
