// Parity: the landing's live pulls, run outside the browser on the same files the page serves (site/relate/live.js and
// the self-hosted @relate/relate-wasm engines), must return the rows the Python run recorded.
//
//   node scripts/wasm_parity.mjs [--out evidence/wasm-parity.json]
//
// Checks: (1) all 22 pulls on Relate 1.0.1 against evidence/pull-each-tag.json, row for row; (2) the unpulled witness
// gives the manifest's baseline answer; (3) the engine case on 1.0.1 and on 1.3.0 against evidence/relate-versions.jsonl;
// (4) a write in the query box is refused. Exit 1 on any mismatch. Node loads the browser build with initSync and the
// engine's bytes (Relate's WebAssembly API reference); nothing here is a mock.
import crypto from "node:crypto";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const read = (p) => fs.readFileSync(path.join(ROOT, p), "utf8");
const json = (p) => JSON.parse(read(p));
const outArg = process.argv.indexOf("--out");
const OUT = outArg > 0 ? process.argv[outArg + 1] : null;
const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);

const L = await import(pathToFileURL(path.join(ROOT, "site/relate/live.js")).href);
const engines = json("site/relate/engines.json");

async function open(v) {
  const dir = path.join(ROOT, "site/relate", v);
  const relate = await import(pathToFileURL(path.join(dir, "relate.js")).href);
  relate.initSync({ module: fs.readFileSync(path.join(dir, "relate_bg.wasm")) });
  return new relate.RelateDb();
}

const pulls = json("evidence/pull-each-tag.json");
const man = json("witnesses/two-hub.manifest.json");
const script = read(pulls.witness.replace(/\.rl$/, ".cypher"));
const query = read(pulls.query);
const PIN = man.versions.relate_db;
const bad = [];

const db = await open(PIN);
const reported = L.version(db);
if (reported !== PIN) bad.push(`engine ${PIN} reports ${reported}`);

const rows = pulls.tags.map((t) => {
  const r = L.pull(db, script, query, pulls.params, t.rel);
  const ok = same(r.rows, t.rows);
  if (!ok) bad.push(`pull ${t.n} ${t.rel}: ${JSON.stringify(r.rows)} != recorded ${JSON.stringify(t.rows)}`);
  return { n: t.n, rel: t.rel, rows_after: r.rows.length, same_rows: ok, changed: !same(r.rows, man.baseline.rows), ms: r.ms };
});

const base = L.ask(db, script, query, JSON.stringify(pulls.params), null);
if (!same(base.rows, man.baseline.rows)) bad.push(`unpulled witness: ${JSON.stringify(base.rows)} != manifest baseline`);
const write = L.ask(db, script, "CREATE (:Airport {iata: 'NEW'}) RETURN 1 AS one", "", null);
if (!write.refused) bad.push("a CREATE in the query box was not refused");

const ec = json("witnesses/exists-count.manifest.json");
const ecScript = read("witnesses/exists-count.cypher");
const forms = { exists: read("queries/exists-two-match.cypher"), count: read("queries/count-two-match.cypher") };
const recorded = Object.fromEntries(read("evidence/relate-versions.jsonl").trim().split("\n").map((l) => JSON.parse(l)).map((v) => [v.relate_db, v]));
const engineCase = [];
for (const v of Object.keys(engines)) {
  const d = v === PIN ? db : await open(v);
  const got = L.pair(d, ecScript, forms, ec.params);
  const rec = recorded[v];
  const ok = !!rec && same(got.exists, rec["exists-two-match"]) && same(got.count, rec["count-two-match"]) && got.agree === rec.the_two_forms_agree;
  if (!ok) bad.push(`engine case on ${v}: ${JSON.stringify(got)} != recorded ${JSON.stringify(rec)}`);
  engineCase.push({ version: v, reported: L.version(d), exists: got.exists, count: got.count, agree: got.agree, same_as_recorded: ok });
}

const report = {
  schema: "witness.wasm-parity/v1",
  what: "the landing's live steps (site/relate/live.js) on the self-hosted @relate/relate-wasm engines, against the recorded Python run",
  run: { utc: new Date().toISOString().replace(/\.\d+Z$/, "Z"), node: process.version, machine: `${os.type()} ${os.arch()}` },
  engine: { package: engines[PIN].package, version: PIN, reported, integrity: engines[PIN].integrity },
  live_js_sha256: crypto.createHash("sha256").update(fs.readFileSync(path.join(ROOT, "site/relate/live.js"))).digest("hex"),
  pulls: { witness: pulls.witness.replace(/\.rl$/, ".cypher"), recorded: "evidence/pull-each-tag.json", of: rows.length, same_rows: rows.filter((r) => r.same_rows).length, changed: rows.filter((r) => r.changed).length, rows },
  baseline_same: same(base.rows, man.baseline.rows),
  write_refused: !!write.refused,
  engine_case: engineCase,
  ok: bad.length === 0,
};
if (OUT) fs.writeFileSync(path.resolve(OUT), JSON.stringify(report, null, 2) + "\n");
console.log(`wasm parity: ${report.pulls.same_rows} of ${report.pulls.of} pulls match the recorded rows on Relate ${reported} (${report.pulls.changed} change the answer); ` +
  `engine case ${engineCase.map((e) => `${e.reported} ${e.agree ? "agree" : "disagree"}`).join(", ")}; write refused: ${report.write_refused}`);
if (bad.length) { console.error(bad.join("\n")); process.exit(1); }
