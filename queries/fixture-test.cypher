// A test's assertion: which foreign countries does MEX fly to directly? (aggregation over a collected list)
MATCH (:Airport {iata: 'MEX'})-[:HAS_ROUTE]->(b:Airport)-[:IN_COUNTRY]->(c:Country)
WHERE c.code <> 'MX'
RETURN count(DISTINCT b) AS foreign_airports, coll.sort(collect(DISTINCT c.code)) AS countries
