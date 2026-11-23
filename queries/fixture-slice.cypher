// The slice a test pulls from Neo4j: every Mexican airport, its routes in both directions, and the country of each neighbour.
MATCH (a:Airport)-[ic:IN_COUNTRY]->(c:Country {code: 'MX'})
OPTIONAL MATCH (a)-[r:HAS_ROUTE]-(b:Airport)
OPTIONAL MATCH (b)-[ic2:IN_COUNTRY]->(c2:Country)
RETURN a, ic, c, r, b, ic2, c2
