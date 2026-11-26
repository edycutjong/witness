# `witness mcp` with a model in the loop: one recorded agent session

A real model, not a scripted client: **claude-sonnet-5-5** in Claude Code 2.1.325 headless (`claude -p`), recorded 2026-11-26 on Darwin arm64 with Relate v1.0.1 (relate-db 1.0.1). The model was given two MCP servers, Relate's own `relate serve --mcp` on `data/air-routes.rl` (read-only) and `witness mcp`, with shell, file, web and the Task/Agent tools disallowed and the four named MCP tools pre-approved; Claude Code's other built-in tools (scheduling, skills, worktree, workflow, messaging and MCP-resource tools, and the `ToolSearch` loader) stayed in its list, and the model used only `ToolSearch` and the MCP tools (the full tool list is in the init event, line 1 of the `.jsonl`). It chose its own Cypher; nothing below is edited except local paths (shown as `<repo>` and `<out>`). Raw event stream: `evidence/mcp-agent-session.jsonl`.

Why the witness here is 68, not the headline's 22: the model's answer also reports each airport's hub count, so every hub is now part of the answer and all 68 relationships the answer rows bind are needed (the same 68 that `queries/two-hub-bindings.cypher` returns: the session's full manifest, `evidence/mcp-agent-session-witness.manifest.json`, lists all 68 probes, and the two sets are identical). Report only the hub countries, as `queries/two-hub.cypher` does, and 22 suffice. The evidence follows what the agent claimed.

## Command

```bash
cd "$(mktemp -d)"   # an empty directory: no project files or instructions
claude -p "$(cat prompt.txt)" --model sonnet --mcp-config mcp.json --strict-mcp-config --setting-sources local \
  --allowedTools mcp__relate__read_cypher mcp__relate__get_schema mcp__witness__why mcp__witness__check \
  --disallowedTools Bash Edit Write Read Glob Grep WebFetch WebSearch Task Agent NotebookEdit \
  --output-format stream-json --verbose --no-session-persistence < /dev/null
```

`mcp.json`:

```json
{"mcpServers": {
  "relate": {"command": "~/.local/bin/relate", "args": ["serve", "--database", "<repo>/data/air-routes.rl", "--read-only", "--mcp", "stdio"], "env": {"DO_NOT_TRACK": "1"}},
  "witness": {"command": "~/.local/bin/uv", "args": ["run", "--directory", "<repo>", "--extra", "mcp", "witness", "mcp", "--out", "<out>"], "env": {"DO_NOT_TRACK": "1"}}
}}
```

## Prompt (verbatim)

> You have two MCP servers: `relate` (a Relate graph database holding the air-routes graph: Airport, Country and Continent nodes; HAS_ROUTE, IN_COUNTRY and ON_CONTINENT relationships) and `witness`.
>
> Question: which airports in Mexico (country code MX) have no direct flight to MEX, yet would still reach MEX in two flights if any one hub closed? For each, list the countries of the hubs.
>
> Answer from the graph with Cypher through `relate`. Then use the `witness` tool `why` to attach evidence for your answer: pass your query, its parameters, and the rows you showed as `answer`. Put its `evidence_markdown` in your reply.

## Tool calls, in order

### 1. `ToolSearch`

```json
{
  "query": "select:mcp__relate__get_schema,mcp__relate__read_cypher,mcp__witness__why",
  "max_results": 5
}
```

Result (193 characters):

```
{"type": "tool_reference", "tool_name": "mcp__relate__get_schema"}{"type": "tool_reference", "tool_name": "mcp__relate__read_cypher"}{"type": "tool_reference", "tool_name": "mcp__witness__why"}
```

### 2. `mcp__relate__get_schema`

```json
{
  "sample_size": 100
}
```

Result (771 characters):

```
{"Airport":{"count":3504,"properties":{"altitude":{"type":"Integer"},"city":{"type":"String"},"descr":{"type":"String"},"iata":{"type":"String"},"icao":{"type":"String"},"id":{"type":"Integer"},"lat":{"type":"Float"},"lon":{"type":"Float"},"longest":{"type":"Integer"},"region":{"type":"String"},"runways":{"type":"Integer"}},"relationships":{"HAS_ROUTE":{"direction":"out","labels":["Airport"],"properties":{"dist":{"type":"Integer"}}},"IN_COUNTRY":{"direction":"out","labels":["Country"]},"ON_CONTINENT":{"direction":"out","labels":["Continent"]}},"type":"node"},"Continent":{"count":7,"properties":{"code":{"type":"String"},"name":{"type":"String"}},"type":"node"},"Country":{"count":237,"properties":{"code":{"type":"String"},"name":{"type":"String"}},"type":"node"}}
```

### 3. `mcp__relate__read_cypher`

```json
{
  "statement": "MATCH (a:Airport)-[:IN_COUNTRY]->(:Country {code:'MX'}), (m:Airport {iata:'MEX'})\nWHERE a <> m AND NOT (a)-[:HAS_ROUTE]->(m)\nMATCH (a)-[:HAS_ROUTE]->(h:Airport)-[:HAS_ROUTE]->(m)\nWHERE h <> a\nMATCH (h)-[:IN_COUNTRY]->(c:Country)\nWITH a, count(DISTINCT h) AS hubs, collect(DISTINCT c.code) AS hub_countries\nWHERE hubs >= 2\nRETURN a.iata AS airport, hubs, hub_countries ORDER BY airport"
}
```

Result (3,546 characters):

```
{"columnTypes":["STRING","INTEGER","LIST"],"columns":["airport","hubs","hub_countries"],"elapsed_ms":243.021542,"error":null,"execute_ms":242.92408300000002,"lex_parse_ms":0.012374999999999999,"lower_ms":0.027792,"notifications":[{"category":"PERFORMANCE","code":"Neo.ClientNotification.Statement.CartesianProduct","description":"the MATCH patterns share no join anchor","gql_status":"03N90","operator_id":4,"remedy":"Give the patterns a join anchor: reuse a node variable across them, or add a pattern that relates their endpoints; otherwise run them as separate queries.","severity":"INFORMATION","title":"Cartesian product"},{"category":"PERFORMANCE","code":"Relate.Notification.Statement.MissingIndex","description":"the equality predicate on iata filters :Airport without a range index on (:Airport {iata})","gql_status":"03C91","operator_id":4,"remedy":"CREATE INDEX relate_Airport__iata FOR (n:Airport) ON (n.iata)","severity":"INFORMATION","title":"Missing index"}],"parse_ms":0.058334000000000004,"plan":{"profiled":false,"root":{"actual":null,"children":[{"actual":null,"children":[{"actual":null,"children":[{"actual":null,"children":[{"actual":null,"children":[],"details":"(:Country)<-[:IN_COUNTRY]-(a:Airport), (m:Airport), WHERE filter","estimated_rows":null,"identifiers":[],"operator":"Expand","warnings":[{"category":"PERFORMANCE","code":"Neo.ClientNotification.Statement.CartesianProduct","description":"the MATCH patterns share no join anchor","gql_status":"03N90","remedy":"Give the patterns a join anchor: reuse a node variable across them, or add a pattern that relates their endpoints; otherwise run them as separate queries.","severity":"INFORMATION","title":"Cartesian product"},{"category":"PERFORMANCE","code":"Relate.Notification.Statement.MissingIndex","description":"th
… (3,546 characters in total; the full result is in the .jsonl)
```

### 4. `mcp__witness__why`

```json
{
  "statement": "MATCH (a:Airport)-[:IN_COUNTRY]->(:Country {code:'MX'}), (m:Airport {iata:'MEX'})\nWHERE a <> m AND NOT (a)-[:HAS_ROUTE]->(m)\nMATCH (a)-[:HAS_ROUTE]->(h:Airport)-[:HAS_ROUTE]->(m)\nWHERE h <> a\nMATCH (h)-[:IN_COUNTRY]->(c:Country)\nWITH a, count(DISTINCT h) AS hubs, collect(DISTINCT c.code) AS hub_countries\nWHERE hubs >= 2\nRETURN a.iata AS airport, hubs, hub_countries ORDER BY airport",
  "answer": [
    {
      "airport": "PBC",
      "hubs": 7,
      "hub_countries": [
        "MX",
        "US"
      ]
    },
    {
      "airport": "QRO",
      "hubs": 9,
      "hub_countries": [
        "MX",
        "US"
      ]
    },
    {
      "airport": "TLC",
      "hubs": 10,
      "hub_countries": [
        "MX",
        "US"
      ]
    },
    {
      "airport": "UPN",
      "hubs": 2,
      "hub_countries": [
        "MX",
        "US"
      ]
    }
  ]
}
```

Result (8,251 characters):

```
{
  "answer": {
    "columns": [
      "airport",
      "hubs",
      "hub_countries"
    ],
    "rows": [
      {
        "airport": "PBC",
        "hubs": 7,
        "hub_countries": [
          "MX",
          "US"
        ]
      },
      {
        "airport": "QRO",
        "hubs": 9,
        "hub_countries": [
          "MX",
          "US"
        ]
      },
      {
        "airport": "TLC",
        "hubs": 10,
        "hub_countries": [
          "MX",
          "US"
        ]
      },
      {
        "airport": "UPN",
        "hubs": 2,
        "hub_countries": [
          "MX",
          "US"
        ]
      }
    ],
    "rows_total": 4
  },
  "source_sha256": "b124cf2c6b3af3075cec11125b0355523ca2817210adfcfe1ac3aa4a650e6734",
  "source_relationships": 57645,
  "witness": {
    "relationships": 68,
    "nodes": 25,
    "deletion_minimal_verified": true
  },
  "check": {
    "check_text": "68 of 68 change the answer (68 of 68 relationships, 0 of 0 isolated nodes)",
    "verified": true,
    "sufficient": true,
    "inconclusive": 0,
    "cli": "relate CLI: sufficiency + 68 of 68 necessity probes cross-checked",
    "cli_used": true,
    "disagreements": [],
    "reasons": [],
    "not_necessary": []
  },
  "verified": true,
  "determinism_claimed": true,
  "exhibits": [
    {
      "n": 1,
      "start": "ACA",
      "type": "HAS_ROUTE",
      "end": "MEX"
    },
    {
      "n": 2,
      "start": "ACA",
      "type": "IN_COUNTRY",
      "end": "MX"
    },
    {
      "n": 3,
      "start": "ATL",
      "type": "HAS_ROUTE",
      "end": "MEX"
    },
    {
      "n": 4,
      "start": "ATL",
      "type": "IN_COUNTRY",
      "end": "US"
    },
    {
      "n": 5,
      "start": "CUN",
      "type": "HAS_ROUTE",
      "end": "MEX"
    },
    {
      "n": 6,
      
… (8,251 characters in total; the full result is in the .jsonl)
```

## The model's reply (verbatim)

Four Mexican airports have no direct flight to MEX but would still reach it in two flights if any single hub closed. I took that to mean at least two distinct intermediate hubs, so no one hub is a single point of failure.

| Airport | Distinct hubs | Hub countries |
|---|---|---|
| PBC | 7 | MX, US |
| QRO | 9 | MX, US |
| TLC | 10 | MX, US |
| UPN | 2 | MX, US |

I counted a hub only when the route direction runs airport → hub → MEX. In every case the hubs are in Mexico (MX) or the United States (US).

**Evidence:** 68 relationships (of 57,645) reproduce it; 68 of 68 change the answer — verified deletion-minimal.
```
 1 (ACA)-[:HAS_ROUTE]->(MEX)    2 (ACA)-[:IN_COUNTRY]->(MX)
 3 (ATL)-[:HAS_ROUTE]->(MEX)    4 (ATL)-[:IN_COUNTRY]->(US)
 5 (CUN)-[:HAS_ROUTE]->(MEX)    6 (CUN)-[:IN_COUNTRY]->(MX)
 7 (DFW)-[:HAS_ROUTE]->(MEX)    8 (DFW)-[:IN_COUNTRY]->(US)
 9 (DGO)-[:HAS_ROUTE]->(MEX)   10 (DGO)-[:IN_COUNTRY]->(MX)
11 (FLL)-[:HAS_ROUTE]->(MEX)   12 (FLL)-[:IN_COUNTRY]->(US)
13 (GDL)-[:HAS_ROUTE]->(MEX)   14 (GDL)-[:IN_COUNTRY]->(MX)
15 (IAH)-[:HAS_ROUTE]->(MEX)   16 (IAH)-[:IN_COUNTRY]->(US)
17 (LAS)-[:HAS_ROUTE]->(MEX)   18 (LAS)-[:IN_COUNTRY]->(US)
19 (LAX)-[:HAS_ROUTE]->(MEX)   20 (LAX)-[:IN_COUNTRY]->(US)
21 (MTY)-[:HAS_ROUTE]->(MEX)   22 (MTY)-[:IN_COUNTRY]->(MX)
23 (MZT)-[:HAS_ROUTE]->(MEX)   24 (MZT)-[:IN_COUNTRY]->(MX)
25 (PBC)-[:HAS_ROUTE]->(CUN)   26 (PBC)-[:HAS_ROUTE]->(DFW)
27 (PBC)-[:HAS_ROUTE]->(GDL)   28 (PBC)-[:HAS_ROUTE]->(IAH)
29 (PBC)-[:HAS_ROUTE]->(MTY)   30 (PBC)-[:HAS_ROUTE]->(TGZ)
31 (PBC)-[:HAS_ROUTE]->(TIJ)   32 (PBC)-[:IN_COUNTRY]->(MX)
33 (PVR)-[:HAS_ROUTE]->(MEX)   34 (PVR)-[:IN_COUNTRY]->(MX)
35 (QRO)-[:HAS_ROUTE]->(ACA)   36 (QRO)-[:HAS_ROUTE]->(ATL)
37 (QRO)-[:HAS_ROUTE]->(CUN)   38 (QRO)-[:HAS_ROUTE]->(DFW)
… +15 more lines in the file
```
Re-run with plain `relate`: `<out>/mcp-1795711857-1/witness.rl` (+ `.cypher`). Relate 1.0.1.

---

5 turns, 40.3 s wall clock. The first attempt the same evening failed (`evidence/mcp-agent-session-first-attempt.jsonl`): the `why` reply was 74,771 characters and Claude Code refused a tool result that large, so the model answered without evidence. `why` and `check` now send a bounded reply (`REPLY_ROWS` in `src/witness/mcp_server.py`; the manifest beside the witness keeps everything), and this session is the re-run.
