// Witness, live in the tab: the steps the landing runs on Relate's browser build (@relate/relate-wasm), shared by the
// page's worker (site/relate/worker.js) and the Node parity check (scripts/wasm_parity.mjs), so the check runs this
// exact file. No DOM; every function takes an open RelateDb.
//
// The browser build has no transactions ("BEGIN is a syntax error"), so where the Python reducer deletes inside a
// transaction and rolls back, the page rebuilds the witness from its CREATE script before every pull and every query.
// The witness is 22 relationships; a fresh copy each time is the browser's stand-in for the rollback.

// The two relationship types a witness tag can name, and how to delete exactly one of them by its endpoints.
const REL = /^\((\w+)\)-\[:(HAS_ROUTE|IN_COUNTRY)\]->\((\w+)\)$/;
const DELETE = {
  HAS_ROUTE: "MATCH (:Airport {iata: $s})-[r:HAS_ROUTE]->(:Airport {iata: $d}) DELETE r",
  IN_COUNTRY: "MATCH (:Airport {iata: $s})-[r:IN_COUNTRY]->(:Country {code: $d}) DELETE r",
};
// Every write counter in the envelope's stats (Relate's WebAssembly API reference, "The envelope").
export const WRITE_COUNTERS = [
  "nodes_created", "nodes_deleted", "relationships_created", "relationships_deleted", "properties_set",
  "labels_added", "labels_removed", "indexes_added", "indexes_removed", "constraints_added", "constraints_removed",
];
export const ROW_CAP = 200;

const clock = () => (globalThis.performance ? globalThis.performance.now() : Date.now());
const ms = (t) => Math.round((clock() - t) * 1000) / 1000;

export class LiveError extends Error {}

function exec(db, statement, params) {
  const env = JSON.parse(db.execute(statement, params == null ? null : JSON.stringify(params)));
  if (env.error) throw new LiveError(env.error);
  return env;
}

// The engine's own word on which release it is.
export function version(db) {
  const env = exec(db, "CALL dbms.components() YIELD name, versions WHERE name = 'Relate' RETURN versions[0] AS version");
  return env.rows.length ? env.rows[0].version : null;
}

// A fresh in-memory store holding only the script's graph.
export function load(db, script) {
  db.reset();
  const t = clock();
  const envs = db.executeScript(script, null).map((e) => JSON.parse(e));
  const bad = envs.find((e) => e.error);
  if (bad) throw new LiveError("the witness script failed: " + bad.error);
  const created = envs.reduce((a, e) => ({ nodes: a.nodes + (e.stats.nodes_created || 0), rels: a.rels + (e.stats.relationships_created || 0) }), { nodes: 0, rels: 0 });
  return { ms: ms(t), nodes: created.nodes, relationships: created.rels };
}

// Delete exactly one tagged relationship from the store; a tag that matches none or several is an error.
function cut(db, rel) {
  const m = REL.exec(rel);
  if (!m) throw new LiveError("not a witness tag: " + rel);
  const env = exec(db, DELETE[m[2]], { s: m[1], d: m[3] });
  if (env.stats.relationships_deleted !== 1) throw new LiveError(rel + " deleted " + env.stats.relationships_deleted + " relationships, not 1");
}

// Pull one tag: rebuild the witness, delete that relationship, re-run the query.
export function pull(db, script, query, params, rel) {
  const built = load(db, script);
  const t = clock();
  cut(db, rel);
  const env = exec(db, query, params);
  return { rows: env.rows, ms: ms(t), build_ms: built.ms, relationships: built.relationships - 1 };
}

// Run any statement on a fresh copy of the witness (minus one pulled tag, if given). paramsText is the visitor's
// JSON as typed; Relate parses it and answers "invalid params JSON" itself when it does not parse. A statement that
// writes is refused: it ran on a throwaway copy, which is dropped before anything is shown. The page tells a write
// from a read by the envelope's stats (both pinned releases send them with every reply, an error included); a reply
// without stats is refused too, since nothing then says it only read.
export function ask(db, script, statement, paramsText, rel) {
  const built = load(db, script);
  if (rel) cut(db, rel);
  const t = clock();
  const env = JSON.parse(db.execute(statement, paramsText && paramsText.trim() ? paramsText : null));
  const took = ms(t);
  const writes = {};
  WRITE_COUNTERS.forEach((k) => { if (env.stats && env.stats[k] > 0) writes[k] = env.stats[k]; });
  if (!env.stats || Object.keys(writes).length) {
    db.reset();
    return { refused: true, untold: !env.stats, writes, ms: took, relationships: built.relationships - (rel ? 1 : 0) };
  }
  const rows = env.rows || [];
  return {
    error: env.error || null,
    columns: env.columns || [],
    rows: rows.slice(0, ROW_CAP),
    total: rows.length,
    plan: env.plan || null,
    ms: took,
    relationships: built.relationships - (rel ? 1 : 0),
  };
}

// The engine case: both forms of one condition on one graph, and whether they agree.
export function pair(db, script, forms, params) {
  load(db, script);
  const out = {};
  Object.keys(forms).forEach((k) => { out[k] = exec(db, forms[k], params).rows; });
  const keys = Object.keys(out);
  out.agree = keys.every((k) => JSON.stringify(out[k]) === JSON.stringify(out[keys[0]]));
  return out;
}
