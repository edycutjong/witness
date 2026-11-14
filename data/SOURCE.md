# Data source: air-routes

**What it is.** Kelvin Lawrence's air-routes graph: real airports, the scheduled routes between them, and each airport's
country and continent. Snapshot **air-routes v0.89, generated 2022-08-29**: a dated network, not live routes.

**Where it comes from.** https://github.com/krlawrence/graph, files `sample-data/air-routes-latest-nodes.csv` and
`sample-data/air-routes-latest-edges.csv`, pinned at commit `efd3b1ae636f602577cfbccb16ecfe358a02ee36`.

| File | SHA-256 |
|---|---|
| air-routes-latest-nodes.csv | `f921d4f1dd429418a96c17c49d42b42ce6cf5d6c9772e784556a631760b53579` |
| air-routes-latest-edges.csv | `01749b2717ccca5efe11c4b1f5e25f8c59ab682014104f3fb8bdb67e23b101b5` |

**License.** Apache-2.0, as published in the source repository (`LICENSE` in krlawrence/graph). The repository states no
separate data license. Attribution is also in `NOTICE`.

**Modified.** Reshaped into a property graph for Relate by `scripts/build_source.py`; the single `version` node (it names
the dataset author) was dropped. No personal data: airports, cities, countries, continents and distances only.

**Graph model.**
```
(:Airport {id, iata, icao, city, descr, region, runways, longest, altitude, lat, lon})
(:Country {code, name})   (:Continent {code, name})
(:Airport)-[:IN_COUNTRY]->(:Country)
(:Airport)-[:ON_CONTINENT]->(:Continent)
(:Airport)-[:HAS_ROUTE {dist}]->(:Airport)
Unique: Airport.id, Country.code, Continent.code
```

**Counts** (from `source-stats.json`): 3,504 airports, 237 countries, 7 continents;
50,637 `HAS_ROUTE`, 3,504 `IN_COUNTRY`, 3,504 `ON_CONTINENT`; the store holds
**3,748 nodes and 57,645 relationships**. Unresolved edges dropped:
0. Duplicate routes collapsed: 0.

**Files.**
- `air-routes.rl`: the single-file Relate store the demo opens (11,079,680 bytes, sha256 `b124cf2c6b3af3075cec11125b0355523ca2817210adfcfe1ac3aa4a650e6734`).
- `air-routes.cypher`: the same graph as a CREATE script (sha256 `e1a37cc2e944c765318bfdc7042000bde2e49a2f48c12be2d79cbc7c4e4cb3b8`); byte-stable across rebuilds.
  The `.rl` bytes are recorded by SHA-256 and are not promised stable across builds.

Rebuild (optional; nobody needs to): `uv run python scripts/build_source.py`.

`relate info --database data/air-routes.rl --json` (1.0.1 client, Relate CLI v1.0.1):
```json
{"checkpoint_lsn":131,"codec":"parquet","commit_ts":131,"constraints":[{"enforced_label":null,"kind":"unique","label":"Airport","name":"airport_id","properties":["id"],"property_type":null,"relationship":false},{"enforced_label":null,"kind":"unique","label":"Continent","name":"continent_code","properties":["code"],"property_type":null,"relationship":false},{"enforced_label":null,"kind":"unique","label":"Country","name":"country_code","properties":["code"],"property_type":null,"relationship":false}],"format_version":5,"indexes":[{"label":"Airport","name":"airport_id","property":"id#RANGE#airport_id"},{"label":"Continent","name":"continent_code","property":"code#RANGE#continent_code"},{"label":"Country","name":"country_code","property":"code#RANGE#country_code"}],"layout":"bundle","node_count":3748,"rel_count":57645,"superblock_version":1,"total_bytes":11079680,"wal_segments":1}
```
