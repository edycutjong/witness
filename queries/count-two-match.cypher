// Which airports of $country have a flight to an airport they fly to? (the same condition written with COUNT over the same two MATCH clauses)
MATCH (a:Airport)-[:IN_COUNTRY]->(:Country {code: $country})
WHERE COUNT { MATCH (a)-[:HAS_ROUTE]->(x:Airport) MATCH (x)<-[:HAS_ROUTE]-(a) } > 0
RETURN a.iata AS airport
ORDER BY airport
