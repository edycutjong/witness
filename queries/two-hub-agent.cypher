// The agent's first try at queries/two-hub.cypher: the first hop is matched in either direction (a realistic mistake).
MATCH (a:Airport)-[:IN_COUNTRY]->(:Country {code: $country})
WHERE a.iata <> $dest
  AND NOT EXISTS { MATCH (a)-[:HAS_ROUTE]->(:Airport {iata: $dest}) }
MATCH (a)-[:HAS_ROUTE]-(hub:Airport)-[:HAS_ROUTE]->(:Airport {iata: $dest})
OPTIONAL MATCH (hub)-[:IN_COUNTRY]->(hc:Country)
WITH a, count(DISTINCT hub) AS hubs, coll.sort(collect(DISTINCT hc.code)) AS hub_countries
WHERE hubs >= 2
RETURN a.iata AS airport, hub_countries
ORDER BY airport
