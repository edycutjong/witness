// The same property projected with and without parentheses. Relate v1.2.0: a parenthesized projection item is classified like its plain form (#518).
MATCH (a:Airport {iata: 'MZT'})
RETURN (a.runways), a.runways
