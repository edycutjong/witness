// Witness 0.1.0 · relate-db 1.0.1 · seed 0
// source sha256 b124cf2c6b3af3075cec11125b0355523ca2817210adfcfe1ac3aa4a650e6734
// params {"country": "MX"}
CREATE
  (n0:`Airport` {`altitude`: 127, `city`: 'Los Angeles', `descr`: 'Los Angeles International Airport', `iata`: 'LAX', `icao`: 'KLAX', `id`: 13, `lat`: 33.94250107, `lon`: -118.4079971, `longest`: 12091, `region`: 'US-CA', `runways`: 4}),
  (n1:`Airport` {`altitude`: 38, `city`: 'Mazatlán', `descr`: 'General Rafael Buelna International Airport', `iata`: 'MZT', `icao`: 'MMMZ', `id`: 413, `lat`: 23.1613998413, `lon`: -106.26599884, `longest`: 8858, `region`: 'MX-SIN', `runways`: 1}),
  (n2:`Country` {`code`: 'MX', `name`: 'Mexico'}),
  (n1)-[:`HAS_ROUTE` {`dist`: 1045}]->(n0),
  (n1)-[:`IN_COUNTRY`]->(n2);
