// EXISTS over a two-stage NEXT chain whose second stage matches nothing. Relate v1.3.0: EXISTS decides on the whole stage chain (#729).
CYPHER 25 RETURN EXISTS { RETURN 1 AS k NEXT MATCH (y:Airport) WHERE y.iata = 'ZZZ' RETURN y } AS e
