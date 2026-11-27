// Airports reached from MZT whose shortest paths have at least 2 hops (a clause WHERE over the path of ALL SHORTEST). Relate v1.0.2: the WHERE post-filters the selected shortest paths (#373).
MATCH p = ALL SHORTEST (a:Airport {iata: 'MZT'})-[:HAS_ROUTE*..2]-(b:Airport)
WHERE length(p) >= 2
RETURN count(DISTINCT b) AS n
