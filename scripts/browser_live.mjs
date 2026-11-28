// The landing in a real browser: headless Chrome loads the page, lets Relate (WebAssembly) start in its worker, pulls
// all 22 tags, runs the query box examples, a write, a runaway query and the engine case on both releases, and records
// what the page itself showed. Complements scripts/wasm_parity.mjs, which runs the page's steps under Node.
//
//   PUPPETEER_MODULE=/path/to/node_modules/puppeteer/lib/esm/puppeteer/puppeteer.js \
//   CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
//   node scripts/browser_live.mjs https://witness.edycu.dev/ --out evidence/browser-live.json
//
// Needs Node, Chrome and puppeteer (any recent version; it is not a dependency of this repository). Exit 1 when the
// page does not run live or any pull differs from the recording.
import crypto from "node:crypto";
import fs from "node:fs";
import os from "node:os";

const url = process.argv[2] || "https://witness.edycu.dev/";
const outArg = process.argv.indexOf("--out");
const OUT = outArg > 0 ? process.argv[outArg + 1] : null;
const puppeteer = (await import(process.env.PUPPETEER_MODULE || "puppeteer")).default;
const browser = await puppeteer.launch({ headless: "new", executablePath: process.env.CHROME || undefined, args: ["--no-sandbox"] });
const page = await browser.newPage();
const consoleErrors = [], requests = [], failed = [];
page.on("console", (m) => { if (m.type() === "error") consoleErrors.push(m.text()); });
page.on("pageerror", (e) => consoleErrors.push(e.message));
page.on("request", (r) => requests.push(r.url()));
page.on("response", (r) => { if (r.status() >= 400) failed.push({ url: r.url(), status: r.status() }); });
await page.setViewport({ width: 1440, height: 1000 });
await page.goto(url, { waitUntil: "networkidle0" });
const origin = new URL(url).origin;
// at load: no engine worker exists yet and the plate says "ready" (requests a worker makes are not visible to page
// listeners, so the worker count is the control, not a request count)
const workersAtLoad = page.workers().length;
const stateAtLoad = await page.$eval("#eng", (e) => e.dataset.state);
const sha = async (path) => crypto.createHash("sha256").update(Buffer.from(await (await fetch(new URL(path, url))).arrayBuffer())).digest("hex");
const served = { "index.html": await sha("/"), "relate/live.js": await sha("/relate/live.js"), "relate/worker.js": await sha("/relate/worker.js") };
// The page's own logic (scripts/site/landing.js) is inlined in index.html. index.html also prints numbers from this very
// file, so its hash changes with every recorded run; the script's text does not, and the site build requires it to be
// the landing.js it inlines now (trimmed, as the build compares it).
const PAGE_JS = "landing.js (inlined in index.html)";
const inlined = await page.evaluate(() => { const s = Array.from(document.scripts).find((x) => !x.src && x.textContent.includes('getElementById("wdata")')); return s ? s.textContent.trim() : null; });
served[PAGE_JS] = inlined === null ? null : crypto.createHash("sha256").update(inlined, "utf8").digest("hex");
// the engines as served: every file engines.json lists, hashed here and compared with the SHA-256 it records
const enginesJson = await (await fetch(new URL("/relate/engines.json", url))).json();
const engineFiles = { checked: 0, mismatches: [] };
for (const [v, e] of Object.entries(enginesJson)) {
  for (const [rel, want] of Object.entries(e.files)) {
    engineFiles.checked += 1;
    if ((await sha(`/relate/${v}/${rel}`)) !== want) engineFiles.mismatches.push(`${v}/${rel}`);
  }
}
const text = (sel) => page.$eval(sel, (e) => e.innerText.replace(/\s+/g, " ").trim());
const until = (fn, ms = 30000) => page.waitForFunction(fn, { timeout: ms });
const click = (sel) => page.$eval(sel, (e) => e.click());

// a visitor who acts away from the exhibit (a short scroll, a key) must not start the engine either
await page.mouse.wheel({ deltaY: 120 });
await page.keyboard.press("Tab");
await new Promise((r) => setTimeout(r, 1500));
const actedAway = { exhibit_px_below_viewport: Math.round(await page.$eval("#exhibit", (e) => e.getBoundingClientRect().top - innerHeight)), engine_workers: page.workers().length, plate: await page.$eval("#eng", (e) => e.dataset.state) };
await page.evaluate(() => { document.documentElement.style.scrollBehavior = "auto"; document.getElementById("exhibit").scrollIntoView(); window.dispatchEvent(new Event("scroll")); });
await until(() => ["live", "down"].includes(document.getElementById("eng").dataset.state));
const engine = { state: await page.$eval("#eng", (e) => e.dataset.state), plate: await text("#eng") };

const pulls = [];
const n = await page.$$eval(".pull", (b) => b.length);
for (let i = 1; i <= n; i++) {
  await click(`.pull[data-n="${i}"]`);
  await until(() => !document.querySelector("#ex-proof .pk.run"), 10000);
  const proof = await text("#ex-proof");
  pulls.push({ n: i, live: /^LIVE/i.test(proof), same_rows: /Same rows as the recorded run/.test(proof), proof });
}
const tally = await text("#tally");
await click(`.pull[data-n="${n}"]`); // put the last exhibit back: the query box below runs on the whole witness
await until(() => document.getElementById("ex-n").textContent === "none");

const ask = [];
for (const [i, label] of (await page.$$eval("#ask-try .chip", (c) => c.map((x) => x.textContent))).entries()) {
  await page.$$eval("#ask-try .chip", (c, k) => c[k].click(), i);
  await until(() => !document.getElementById("ask-run").disabled, 10000);
  ask.push({ example: label, meta: await text("#ask-meta"), rows: await page.$$eval("#ask-tbl tbody tr", (t) => t.length) });
}
const runQuery = async (q, ms = 30000) => {
  await page.$eval("#ask-q", (e, v) => { e.value = v; }, q);
  const t0 = Date.now();
  await click("#ask-run");
  await until(() => !document.getElementById("ask-run").disabled, ms);
  return { ms: Date.now() - t0, meta: await text("#ask-meta") };
};
const write = await runQuery("MATCH (n) DETACH DELETE n");
const stop = await runQuery("MATCH p=(a)-[*1..14]-(b) RETURN count(p) AS n");
const after = await runQuery("MATCH (n) RETURN count(n) AS nodes");

const engineCase = [];
for (const v of await page.$$eval("#ec-live button[data-v]", (b) => b.map((x) => x.dataset.v))) {
  await click(`#ec-live button[data-v="${v}"]`);
  await until(() => /^(LIVE|NOT RUN|STOPPED|CRASHED|RELATE SAYS)/i.test(document.getElementById("ec-out").innerText));
  const out = await text("#ec-out");
  engineCase.push({ version: v, live: /^LIVE/i.test(out), agree: /they agree/.test(out), same_as_recorded: /Same as the recorded row/.test(out), text: out });
}

const report = {
  schema: "witness.browser-live/v1",
  what: "the landing in headless Chrome: what the page showed for each live pull, the query box, a write, a runaway query and the engine case",
  url,
  run: { utc: new Date().toISOString().replace(/\.\d+Z$/, "Z"), browser: await browser.version(), node: process.version, machine: `${os.type()} ${os.arch()}` },
  served_sha256: served,
  at_load: { engine_workers: workersAtLoad, plate: stateAtLoad },
  engine,
  pulls: { of: pulls.length, live: pulls.filter((p) => p.live).length, same_rows: pulls.filter((p) => p.same_rows).length, tally, rows: pulls },
  ask,
  write: { refused: /^REFUSED/i.test(write.meta), meta: write.meta },
  stop: { ms: stop.ms, stopped: /^STOPPED/i.test(stop.meta), meta: stop.meta, next_run: after.meta },
  engine_case: engineCase,
  acted_away: actedAway,
  engine_files: engineFiles,
  third_party_requests: requests.filter((u) => !u.startsWith(origin) && !u.startsWith("data:")),
  console_errors: consoleErrors,
  failed_responses: failed,
};
// what each engine's worker fetched to start, as the worker itself reports it (the page's listeners above cannot see
// a worker's requests); the page keeps the list in an attribute
report.engine_worker_requests = await page.evaluate(() => Object.fromEntries(Array.from(document.documentElement.attributes)
  .filter((a) => a.name.startsWith("data-engine-fetched-")).map((a) => [a.name.slice("data-engine-fetched-".length).replace(/-/g, "."), a.value.split(" ").filter(Boolean)])));
const workerOffSite = Object.values(report.engine_worker_requests).flat().filter((u) => !u.startsWith(origin));
report.engine_workers_at_end = page.workers().length; // engine workers the page created that Chrome still lists at the end
report.ok = engine.state === "live" && report.pulls.live === n && report.pulls.same_rows === n && report.write.refused && report.stop.stopped &&
  /^LIVE/i.test(after.meta) && engineCase.every((e) => e.live && e.same_as_recorded) && report.third_party_requests.length === 0 && consoleErrors.length === 0 && failed.length === 0 &&
  workersAtLoad === 0 && stateAtLoad === "ready" && report.engine_workers_at_end >= 1 && engineFiles.mismatches.length === 0 && engineFiles.checked > 0 && served[PAGE_JS] !== null &&
  Object.keys(report.engine_worker_requests).length === engineCase.length && workerOffSite.length === 0 &&
  (actedAway.exhibit_px_below_viewport <= 600 || (actedAway.engine_workers === 0 && actedAway.plate === "ready"));
await browser.close();
if (OUT) fs.writeFileSync(OUT, JSON.stringify(report, null, 2) + "\n");
console.log(`browser: ${report.run.browser}; engine ${engine.state}; ${report.pulls.live} of ${n} pulls live, ${report.pulls.same_rows} same as the recording; ` +
  `write refused ${report.write.refused}; stopped after ${stop.ms} ms ${report.stop.stopped}; engine case ${engineCase.map((e) => `${e.version} ${e.agree ? "agree" : "disagree"}`).join(", ")}; ok ${report.ok}`);
process.exit(report.ok ? 0 : 1);
