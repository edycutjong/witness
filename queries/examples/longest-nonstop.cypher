// Which two nonstop flights out of $from are the longest?
MATCH (:Airport {iata: $from})-[r:HAS_ROUTE]->(b:Airport)
RETURN b.iata AS airport, r.dist AS miles
ORDER BY miles DESC LIMIT 2
