// Witness: one Relate engine, a pinned @relate/relate-wasm release served from this site (site/relate/<version>/), in
// a dedicated module worker. A long statement then blocks only this worker, and the page can end it: the browser
// build has no statement timeout, so worker.terminate() is the stop button (Relate's browser guide, "Choose the thread").
const tag = self.location.search; // the page's cache key, passed on to live.js
const live = import(new URL("./live.js" + tag, import.meta.url).href);
const OPS = ["pull", "ask", "pair", "load"];
let engine = null;

function boot(v) {
  if (!/^\d+\.\d+\.\d+$/.test(v)) throw new Error("not a release: " + v);
  engine = (async () => {
    const t = performance.now();
    const base = new URL("./" + v + "/", import.meta.url);
    const relate = await import(new URL("relate.js", base).href);
    await relate.default({ module_or_path: new URL("relate_bg.wasm", base) });
    const trap = await import(new URL("trap.js", base).href);
    const L = await live;
    const db = new relate.RelateDb();
    return { db, L, trap, reported: L.version(db), boot_ms: Math.round(performance.now() - t) };
  })();
  return engine;
}

self.onmessage = async (ev) => {
  const { id, op, args } = ev.data || {};
  let e = null;
  try {
    if (op === "boot") {
      e = await boot(args[0]);
      self.postMessage({ id, ok: true, value: { reported: e.reported, boot_ms: e.boot_ms } });
      return;
    }
    if (!engine || OPS.indexOf(op) < 0) throw new Error("unknown request: " + op);
    e = await engine;
    self.postMessage({ id, ok: true, value: e.L[op](e.db, ...args) });
  } catch (err) {
    const trap = !!(e && e.trap.isWasmTrap(err));
    self.postMessage({ id, ok: false, trap, error: String((err && err.message) || err) });
  }
};
