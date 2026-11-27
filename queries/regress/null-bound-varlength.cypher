// An OPTIONAL MATCH that binds x to null, then a variable-length MATCH ending at x. Relate v1.3.0: a variable bound to null matches nothing in later patterns (#734).
MATCH (a:Airport {iata: 'MZT'})
OPTIONAL MATCH (a)-[:IN_COUNTRY]->(x:Continent)
MATCH (a)-[:HAS_ROUTE*2]->(x)
RETURN count(*) AS n
