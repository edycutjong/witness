// Witness 0.1.0 · relate-db 1.0.1 · seed 0
// source sha256 b124cf2c6b3af3075cec11125b0355523ca2817210adfcfe1ac3aa4a650e6734
// params {"country": "IN", "dest": "DEL"}
CREATE
  (n0:`Airport` {`altitude`: 266, `city`: 'Varanasi', `descr`: 'Lal Bahadur Shastri Airport', `iata`: 'VNS', `icao`: 'VIBN', `id`: 656, `lat`: 25.4524002075, `lon`: 82.8592987061, `longest`: 7238, `region`: 'IN-UP', `runways`: 1}),
  (n1:`Airport` {`altitude`: 39, `city`: 'Mumbai', `descr`: 'Mumbai, Chhatrapati Shivaji International Airport', `iata`: 'BOM', `icao`: 'VABB', `id`: 69, `lat`: 19.0886993408, `lon`: 72.8678970337, `longest`: 11302, `region`: 'IN-MM', `runways`: 2}),
  (n2:`Airport` {`altitude`: 551, `city`: 'Agra', `descr`: 'Agra Airport', `iata`: 'AGR', `icao`: 'VIAG', `id`: 654, `lat`: 27.1557998657227, `lon`: 77.9608993530273, `longest`: 9000, `region`: 'IN-UP', `runways`: 2}),
  (n3:`Airport` {`altitude`: 777, `city`: 'New Delhi', `descr`: 'Indira Gandhi International Airport', `iata`: 'DEL', `icao`: 'VIDP', `id`: 59, `lat`: 28.566499710083, `lon`: 77.1031036376953, `longest`: 14534, `region`: 'IN-DL', `runways`: 3}),
  (n4:`Country` {`code`: 'IN', `name`: 'India'}),
  (n0)-[:`HAS_ROUTE` {`dist`: 325}]->(n2),
  (n0)-[:`HAS_ROUTE` {`dist`: 414}]->(n3),
  (n1)-[:`HAS_ROUTE` {`dist`: 707}]->(n3),
  (n2)-[:`HAS_ROUTE` {`dist`: 644}]->(n1),
  (n2)-[:`IN_COUNTRY`]->(n4);
