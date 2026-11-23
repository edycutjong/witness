// two-hub.cypher in Neo4j's dialect: identical semantics, but Neo4j has no coll.sort(), so the hub countries are
// ordered by an ORDER BY before collect(). Used only by bench/neo4j_compare.py (W5).
MATCH (a:Airport)-[:IN_COUNTRY]->(:Country {code: $country})
WHERE a.iata <> $dest
  AND NOT EXISTS { MATCH (a)-[:HAS_ROUTE]->(:Airport {iata: $dest}) }
MATCH (a)-[:HAS_ROUTE]->(hub:Airport)-[:HAS_ROUTE]->(:Airport {iata: $dest})
OPTIONAL MATCH (hub)-[:IN_COUNTRY]->(hc:Country)
WITH a, hub, hc ORDER BY hc.code
WITH a, count(DISTINCT hub) AS hubs, collect(DISTINCT hc.code) AS hub_countries
WHERE hubs >= 2
RETURN a.iata AS airport, hub_countries
ORDER BY airport
