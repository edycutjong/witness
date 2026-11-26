# `witness mcp` — agent-style transcript

scripted MCP client (no model in the loop) against Relate's own MCP server and `witness mcp`, stdio. macOS-27.2.1-arm64-arm-64bit arm64, Python 3.12.13; Relate v1.0.1.

Tools: Relate `get_schema, read_cypher` · Witness `check, why`

## 1. relate `read_cypher` (0.005 s)

```json
{
  "columns": [
    "airport",
    "hub_countries"
  ],
  "rows": [
    {
      "airport": "PBC",
      "hub_countries": [
        "MX",
        "US"
      ]
    },
    {
      "airport": "QRO",
      "hub_countries": [
        "MX",
        "US"
      ]
    },
    {
      "airport": "TLC",
      "hub_countries": [
        "MX",
        "US"
      ]
    },
    {
      "airport": "UPN",
      "hub_countries": [
        "MX",
        "US"
      ]
    }
  ]
}
```

## 2. witness `why` (5.605 s)

**Answer** (4 rows): PBC, ['MX', 'US']; QRO, ['MX', 'US']; TLC, ['MX', 'US']; UPN, ['MX', 'US']
**Evidence:** 22 relationships (of 57,645) reproduce it; 22 of 22 change the answer — verified deletion-minimal.
```
 1 (ACA)-[:HAS_ROUTE]->(MEX)    2 (ACA)-[:IN_COUNTRY]->(MX)
 3 (DFW)-[:HAS_ROUTE]->(MEX)    4 (DFW)-[:IN_COUNTRY]->(US)
 5 (LAS)-[:HAS_ROUTE]->(MEX)    6 (LAS)-[:IN_COUNTRY]->(US)
 7 (LAX)-[:HAS_ROUTE]->(MEX)    8 (LAX)-[:IN_COUNTRY]->(US)
 9 (PBC)-[:HAS_ROUTE]->(DFW)   10 (PBC)-[:HAS_ROUTE]->(TIJ)
11 (PBC)-[:IN_COUNTRY]->(MX)   12 (QRO)-[:HAS_ROUTE]->(DFW)
13 (QRO)-[:HAS_ROUTE]->(TIJ)   14 (QRO)-[:IN_COUNTRY]->(MX)
15 (TIJ)-[:HAS_ROUTE]->(MEX)   16 (TIJ)-[:IN_COUNTRY]->(MX)
17 (TLC)-[:HAS_ROUTE]->(ACA)   18 (TLC)-[:HAS_ROUTE]->(LAS)
19 (TLC)-[:IN_COUNTRY]->(MX)   20 (UPN)-[:HAS_ROUTE]->(LAX)
21 (UPN)-[:HAS_ROUTE]->(TIJ)   22 (UPN)-[:IN_COUNTRY]->(MX)
```
Re-run with plain `relate`: `<out>/mcp-1795721777-1/witness.rl` (+ `.cypher`). Relate 1.0.1.

verified=True · trials=371 · reduction 1.359 s · ledger r-20261126-193623-ae64b5f6

## 3. witness `check` (0.28 s)

```json
{
  "check_text": "22 of 22 change the answer (22 of 22 relationships, 0 of 0 isolated nodes)",
  "cli": "CLI cross-check skipped: relate not on PATH (install: curl -sSfL https://relatedb.ai/install.sh | bash)",
  "inconclusive": 0,
  "sufficient": true,
  "verified": true
}
```

## 4. witness `why` (0.951 s)

```json
{
  "error": {
    "kind": "query",
    "message": "write keyword DETACH (read-only queries only)"
  },
  "verified": false
}
```

## 5. witness `why` (2.994 s)

```json
{
  "error": {
    "kind": "answer",
    "message": "the answer you gave differs from this store's answer to this query; nothing attached"
  },
  "verified": false
}
```

