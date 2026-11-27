// Airports of Mexico counted inside a CALL subquery with no importing clause. Relate v1.3.0: a CALL body with no scope clause imports nothing (#734).
MATCH (c:Country {code: 'MX'})
CALL { MATCH (a:Airport)-[:IN_COUNTRY]->(c) RETURN count(a) AS n }
RETURN n
