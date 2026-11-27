// How many airports have no direct flight to $dest?
MATCH (a:Airport) WHERE NOT EXISTS { (a)-[:HAS_ROUTE]->(:Airport {iata: $dest}) } RETURN count(a) AS airports
