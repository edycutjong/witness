// The 30th percentile of runway counts, and its type. Relate v1.3.0: percentileDisc returns the input value exactly (#730).
MATCH (a:Airport)
RETURN percentileDisc(a.runways, 0.3) AS v, valueType(percentileDisc(a.runways, 0.3)) AS t
