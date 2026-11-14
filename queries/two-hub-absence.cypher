// Companion, run on the full graph: per answer airport, direct flights to $dest (expect 0) and hubs reaching it in two flights (expect >= 2).
UNWIND $airports AS code
MATCH (a:Airport {iata: code})
OPTIONAL MATCH (a)-[:HAS_ROUTE]->(hub:Airport)-[:HAS_ROUTE]->(:Airport {iata: $dest})
WITH a, code, count(DISTINCT hub) AS reaching_hubs
RETURN code AS airport, COUNT { (a)-[:HAS_ROUTE]->(:Airport {iata: $dest}) } AS direct_flights, reaching_hubs
ORDER BY airport
