// Which airports of $country have a flight to an airport they fly to? (the condition written with EXISTS over two MATCH clauses)
MATCH (a:Airport)-[:IN_COUNTRY]->(:Country {code: $country})
WHERE EXISTS { MATCH (a)-[:HAS_ROUTE]->(x:Airport) MATCH (x)<-[:HAS_ROUTE]-(a) }
RETURN a.iata AS airport
ORDER BY airport
