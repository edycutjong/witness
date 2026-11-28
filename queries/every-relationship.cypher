MATCH (a)-[r]->(b)
RETURN coalesce(a.iata, a.code) AS from, type(r) AS type, coalesce(b.iata, b.code) AS to
ORDER BY type, from, to
