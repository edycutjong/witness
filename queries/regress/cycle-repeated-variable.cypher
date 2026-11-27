// Three-hop cycles through LAX with the map on the first occurrence of a and a WHERE on a. Relate v1.3.0: a node variable repeated in a cycle checks every occurrence's labels and properties (#712).
MATCH (a {iata: 'LAX'})<-[:HAS_ROUTE]-(b:Airport {iata: 'MZT'})-[:HAS_ROUTE]->(c)-[:HAS_ROUTE]->(a)
WHERE a.runways > 0
RETURN count(*) AS n
