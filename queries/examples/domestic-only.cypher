// Which airports of $country have flights, but none that leave the country?
MATCH (a:Airport)-[:IN_COUNTRY]->(:Country {code: $country})
WHERE EXISTS { (a)-[:HAS_ROUTE]->(:Airport) }
  AND NOT EXISTS { MATCH (a)-[:HAS_ROUTE]->(:Airport)-[:IN_COUNTRY]->(o:Country) WHERE o.code <> $country }
RETURN a.iata AS airport
ORDER BY airport
