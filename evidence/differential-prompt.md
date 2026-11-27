# The prompt that produced queries/differential.jsonl

Given to an AI agent (Claude, a general-purpose coding subagent) on 2026-11-28, before any engine comparison. Local file
paths are replaced by placeholders; nothing else is changed. The agent validated each query on relate-db 1.0.1 (it ran,
or its error was recorded) and had no Neo4j. The committed file is the agent's output with four of its fields kept (`id`,
`feature`, `question`, `cypher`) and its timing fields dropped; no query was edited afterwards.

---

Task: write ~200 read-only Cypher queries for a differential test (the same query run on two graph engines, Relate and
Neo4j 2026.10 community; any answer difference is a finding).

Graph (air-routes, 3,748 nodes / 57,645 relationships), store file: <a byte copy of data/air-routes.rl>.
- (:Airport {id:int, iata, icao, city, descr, region, altitude:int, lat:float, lon:float, longest:int, runways:int}) 3,504 nodes
- (:Country {code, name}) 237 · (:Continent {code, name}) 7
- (:Airport)-[:HAS_ROUTE {dist:int}]->(:Airport) 50,637 · (:Airport)-[:IN_COUNTRY]->(:Country) 3,504 · (:Airport)-[:ON_CONTINENT]->(:Continent) 3,504
Some property values may be missing on some nodes; check before assuming.

Rules for every query:
1. Read-only, deterministic: no CREATE/MERGE/SET/DELETE/CALL procedures/LOAD CSV, no rand(), randomUUID(), timestamp(),
   date()/datetime() without a literal argument, no APOC, no `coll.*` functions (Relate-only), no vector/full-text SEARCH.
2. Portable: valid in both Neo4j 5/2026 Cypher and Relate (Neo4j-compatible). Prefer standard Cypher 5 / GQL features.
3. Return scalar columns only (strings, numbers, booleans, null, lists/maps of scalars), never nodes, relationships or
   paths. Alias every column.
4. Order-independent answers: either ORDER BY over a total key (break ties) or a single aggregate row. If you collect()
   into a list, make the list order-independent, otherwise the engines may legitimately differ in list order.
5. Bounded: each query must finish in under 3 s on relate-db 1.0.1 on this graph. Variable-length paths only from a
   filtered, small start set and <= 3 hops; LIMIT large result sets (with a total ORDER BY before the LIMIT).
6. No parameters: inline literals.

Coverage: deliberately spread across features where engines tend to differ. At least ~8 queries each for: OPTIONAL MATCH
(incl. chains, and a MATCH after an OPTIONAL MATCH on a possibly-null variable); EXISTS { } / NOT EXISTS { } with one and
with two MATCH clauses; COUNT { } and COLLECT { } subqueries; WHERE comparisons whose one side is a subquery; aggregation
(count/sum/avg/min/max/collect/stDev/percentileDisc/percentileCont) incl. DISTINCT inside, expression grouping keys,
aggregates over empty input; WITH chains + DISTINCT + ORDER BY on aliases and on the base variable; UNWIND (incl. empty
list, null); list comprehensions, pattern comprehensions, reduce(), any/all/none/single; CASE and null propagation;
string functions; numeric functions and integer vs float arithmetic, division by zero, integer overflow edges, toInteger /
toFloat / toString on edge values; ORDER BY with nulls and mixed types; SKIP/LIMIT; UNION vs UNION ALL; CALL { }
subqueries with importing WITH / CALL (x) { } scope syntax; shortestPath / allShortestPaths / SHORTEST k keyword form with
WHERE on the path; variable-length and quantified path patterns; cycles (a node variable repeated in a pattern) with
labels/properties on the repeated occurrence; relationship uniqueness within a pattern; undirected patterns; label
expressions (:A|B, :!A); map projections; properties()/keys(); type coercion in comparisons (1 = 1.0, '1' = 1).

Validate: run each query on relate-db 1.0.1 against the store. Keep queries that run in < 3 s; for one that errors on
Relate, keep it only if it is standard Neo4j Cypher (record the error; that is a finding too), otherwise fix it. Do not
tune queries to make engines agree; you do not have Neo4j, that comparison happens later.

Output: one JSON object per line: {"id", "feature", "question", "cypher", "relate_101_ms", "relate_101_rows",
"relate_101_error"}. Aim for 200 (at least 180).
