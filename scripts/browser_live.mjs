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
const wasmAtLoad = requests.filter((u) => u.endsWith(".wasm")).length;
const text = (sel) => page.$eval(sel, (e) => e.innerText.replace(/\s+/g, " ").trim());
const until = (fn, ms = 30000) => page.waitForFunction(fn, { timeout: ms });
const click = (sel) => page.$eval(sel, (e) => e.click());

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
  wasm_requests_at_load: wasmAtLoad,
  engine,
  pulls: { of: pulls.length, live: pulls.filter((p) => p.live).length, same_rows: pulls.filter((p) => p.same_rows).length, tally, rows: pulls },
  ask,
  write: { refused: /^REFUSED/i.test(write.meta), meta: write.meta },
  stop: { ms: stop.ms, stopped: /^STOPPED/i.test(stop.meta), meta: stop.meta, next_run: after.meta },
  engine_case: engineCase,
  third_party_requests: requests.filter((u) => !u.startsWith(origin) && !u.startsWith("data:") && !/fonts\.(googleapis|gstatic)\.com|api\.github\.com/.test(u)),
  console_errors: consoleErrors,
  failed_responses: failed,
};
// the version chip asks api.github.com for the latest release and keeps its baked text when that fails (rate limit);
// Chrome logs that failure as a console error, which says nothing about the engine
const chipOnly = failed.length > 0 && failed.every((f) => f.url.startsWith("https://api.github.com/"));
const engineErrors = consoleErrors.filter((m) => !(chipOnly && /^Failed to load resource/.test(m)));
report.console_errors_not_from_the_version_chip = engineErrors;
report.ok = engine.state === "live" && report.pulls.live === n && report.pulls.same_rows === n && report.write.refused && report.stop.stopped &&
  /^LIVE/i.test(after.meta) && engineCase.every((e) => e.live && e.same_as_recorded) && report.third_party_requests.length === 0 && engineErrors.length === 0;
await browser.close();
if (OUT) fs.writeFileSync(OUT, JSON.stringify(report, null, 2) + "\n");
console.log(`browser: ${report.run.browser}; engine ${engine.state}; ${report.pulls.live} of ${n} pulls live, ${report.pulls.same_rows} same as the recording; ` +
  `write refused ${report.write.refused}; stopped after ${stop.ms} ms ${report.stop.stopped}; engine case ${engineCase.map((e) => `${e.version} ${e.agree ? "agree" : "disagree"}`).join(", ")}; ok ${report.ok}`);
process.exit(report.ok ? 0 : 1);
