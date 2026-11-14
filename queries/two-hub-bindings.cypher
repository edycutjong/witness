// B: every relationship the answer rows of queries/two-hub.cypher match (same patterns, returning the relationships).
MATCH (a:Airport)-[ic:IN_COUNTRY]->(:Country {code: $country})
WHERE a.iata <> $dest
  AND NOT EXISTS { MATCH (a)-[:HAS_ROUTE]->(:Airport {iata: $dest}) }
MATCH (a)-[r1:HAS_ROUTE]->(hub:Airport)-[r2:HAS_ROUTE]->(:Airport {iata: $dest})
OPTIONAL MATCH (hub)-[hic:IN_COUNTRY]->(:Country)
WITH a, ic, collect(DISTINCT hub) AS hubs, collect(r1) + collect(r2) + collect(hic) AS rels
WHERE size(hubs) >= 2
UNWIND rels + [ic] AS r
RETURN DISTINCT r
