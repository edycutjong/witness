// Regions counted after a DISTINCT that drops n, with an EXISTS that names n again. Relate v1.3.0: a subquery reusing a name the DISTINCT dropped binds fresh (#734).
MATCH (n:Airport)
WITH DISTINCT n.region AS g
WHERE EXISTS { MATCH (n) WHERE n.runways > 4 }
RETURN count(g) AS c
