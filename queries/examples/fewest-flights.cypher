// What is the smallest number of flights that gets you from $from to $to?
MATCH p = allShortestPaths((a:Airport {iata: $from})-[:HAS_ROUTE*]->(b:Airport {iata: $to}))
RETURN DISTINCT length(p) AS flights
