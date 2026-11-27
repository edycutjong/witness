(function () {
  "use strict";
  var D = JSON.parse(document.getElementById("wdata").textContent);
  var RM = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var $ = function (s, r) { return (r || document).querySelector(s); };
  var $$ = function (s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); };
  var fmt = function (n) { return n.toLocaleString("en-US"); };
  document.documentElement.classList.add("js");

  // version chip: baked text stays if the releases API is unreachable (private repo → 404)
  var v = document.getElementById("ver");
  if (v && v.hasAttribute("data-live") && window.fetch) {
    fetch("https://api.github.com/repos/edycutjong/witness/releases/latest", { headers: { Accept: "application/vnd.github+json" } })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (j) { if (j && j.tag_name) { $$('a[href$="/releases/latest"].chip').forEach(function (c) { c.textContent = j.tag_name; }); } })
      .catch(function () {});
  }

  // copy buttons
  $$(".copy").forEach(function (b) {
    b.addEventListener("click", function () {
      var t = b.getAttribute("data-copy");
      // say "copied" only when the text reached the clipboard; otherwise say so (no silent false success)
      var show = function (ok) { b.textContent = ok ? "copied" : "copy failed: select the text"; b.classList.toggle("done", ok); setTimeout(function () { b.textContent = "copy"; b.classList.remove("done"); }, ok ? 1600 : 3200); };
      var legacy = function () {
        var ta = document.createElement("textarea"), ok = false;
        ta.value = t; ta.setAttribute("readonly", ""); ta.style.position = "fixed"; ta.style.opacity = "0";
        document.body.appendChild(ta); ta.select();
        try { ok = document.execCommand("copy"); } catch (e) { ok = false; }
        document.body.removeChild(ta); show(ok);
      };
      if (navigator.clipboard && window.isSecureContext) navigator.clipboard.writeText(t).then(function () { show(true); }, legacy); else legacy();
    });
  });

  // ── geometry shared with the generator (scripts/site_parts.py) ──
  var bow = function (p, q, b) { return [(p[0] + q[0]) / 2 - (q[1] - p[1]) * b, (p[1] + q[1]) / 2 + (q[0] - p[0]) * b]; };
  var qd = function (p, q, b) { var c = bow(p, q, b); return "M" + p[0].toFixed(1) + " " + p[1].toFixed(1) + "Q" + c[0].toFixed(1) + " " + c[1].toFixed(1) + " " + q[0].toFixed(1) + " " + q[1].toFixed(1); };
  var lerp = function (a, b, t) { return [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t]; };
  var ease = function (t) { return t < .5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2; };

  // ── hero: replay the reduction from the trace ──
  var file = document.getElementById("replay");
  var hero = file && $(".inst", file);
  var rels = document.getElementById("c-rels"), trial = document.getElementById("c-trial");
  var note = document.getElementById("note"), slam = document.getElementById("nofn");
  var tapeWrap = file && $(".tape", file);
  var timers = [], raf = 0, gen = 0; // gen: a settle() or a new play() retires every loop still scheduled
  var later = function (ms, f) { timers.push(setTimeout(f, ms)); };
  var MS = D.ms; // [trial, relationships, label]
  var N = MS[MS.length - 1][0];

  function place(t) { // t: 0 = geographic, 1 = schematic
    $$(".nd", hero).forEach(function (g) {
      var c = g.getAttribute("data-c"), p = lerp(D.geo[c], D.sch[c], t);
      g.setAttribute("transform", "translate(" + p[0].toFixed(1) + " " + p[1].toFixed(1) + ")");
    });
    $$(".ed", hero).forEach(function (e) {
      var s = e.getAttribute("data-s"), d = e.getAttribute("data-e");
      e.setAttribute("d", qd(lerp(D.geo[s], D.sch[s], t), lerp(D.geo[d], D.sch[d], t), 0.06 + 0.1 * (1 - t)));
    });
  }
  function setTrial(n) {
    trial.textContent = fmt(n);
    var r = MS[0][1];
    if (D.left && n > 0) r = D.left[n - 1]; // relationships left after trial n, measured (evidence/trial-counters)
    else for (var i = 0; i < MS.length; i++) if (n >= MS[i][0]) r = MS[i][1];
    rels.textContent = fmt(r);
    rels.classList.toggle("kept", n >= N);
    if (tapeWrap) tapeWrap.style.clipPath = "inset(0 " + (100 - 100 * n / N).toFixed(2) + "% 0 0)";
  }
  function settle() {
    gen++; timers.forEach(clearTimeout); timers = []; cancelAnimationFrame(raf);
    file.classList.remove("armed");
    $$(".wave", hero).forEach(function (w) { w.classList.add("gone"); });
    place(1); setTrial(N);
    if (tapeWrap) tapeWrap.style.clipPath = "";
    note.classList.remove("on");
  }
  function play() {
    settle();
    if (RM) return; // reduced motion: the settled exhibit is the replay's end state, shown at once
    var my = gen;
    $$(".wave", hero).forEach(function (w) { w.classList.remove("gone"); });
    $$(".lb, .tg, .ed", hero).forEach(function (x) { x.classList.remove("on", "lit"); });
    slam.classList.remove("on");
    file.classList.add("armed");
    place(0); setTrial(0);
    // trial 1–2: the empty-graph sanity trial, then the EXPLAIN plan step
    later(450, function () { setTrial(MS[1][0]); note.classList.add("on"); });
    // trials 3..end of the node pass: the map thins, far from MEX first
    var a0 = MS[1][0], a1 = MS[2][0], t0 = 1000, t1 = 3000;
    later(t0, function () { note.classList.remove("on"); });
    [0, 1, 2, 3].forEach(function (i) { later(t0 + i * 450, function () { var w = $('.wave[data-w="' + i + '"]', hero); if (w) w.classList.add("gone"); }); });
    var start = 0;
    function stepA(ts) {
      if (my !== gen) return;
      if (!start) start = ts;
      var f = Math.min(1, (ts - start) / (t1 - t0));
      setTrial(Math.round(a0 + 1 + (a1 - a0 - 1) * f));
      if (f < 1) raf = requestAnimationFrame(stepA);
    }
    later(t0, function () { start = 0; raf = requestAnimationFrame(stepA); });
    // trials after the node pass: the 13 routes light, one by one
    var b1 = N, t2 = t1 + 900;
    later(t1, function () {
      var s2 = 0;
      (function stepB(ts) { if (my !== gen) return; if (!s2) s2 = ts; var f = Math.min(1, (ts - s2) / (t2 - t1)); setTrial(Math.round(a1 + (b1 - a1) * f)); if (f < 1) raf = requestAnimationFrame(stepB); })(performance.now());
      $$(".ed", hero).forEach(function (e, i) { later(i * 55, function () { e.classList.add("lit"); }); });
    });
    // move into the exhibit layout, label, tag, stamp
    later(t2 + 100, function () {
      var s3 = 0, dur = 900;
      (function morph(ts) { if (my !== gen) return; if (!s3) s3 = ts; var f = Math.min(1, (ts - s3) / dur); place(ease(f)); if (f < 1) raf = requestAnimationFrame(morph); })(performance.now());
    });
    later(t2 + 800, function () { $$(".lb", hero).forEach(function (l) { l.classList.add("on"); }); });
    $$(".tg", hero).forEach(function (g, i) { later(t2 + 1050 + i * 60, function () { g.classList.add("on"); }); });
    later(t2 + 1950, function () { slam.classList.add("on"); });
    later(t2 + 2700, function () { file.classList.remove("armed"); $$(".lb, .tg, .ed", hero).forEach(function (x) { x.classList.remove("on", "lit"); }); slam.classList.remove("on"); });
  }
  if (file && hero) {
    document.getElementById("play").addEventListener("click", play);
    if (!RM) {
      if ("IntersectionObserver" in window) {
        var io = new IntersectionObserver(function (es) { if (es[0].isIntersecting && es[0].intersectionRatio > 0.35) { io.disconnect(); play(); } }, { threshold: [0, 0.35, 0.6] });
        io.observe(file);
      } else play();
    }
    // a hero tag opens the same exhibit below
    $$(".tg", hero).forEach(function (g) {
      g.addEventListener("click", function () { pull(+g.getAttribute("data-n")); document.getElementById("exhibit").scrollIntoView({ behavior: RM ? "auto" : "smooth" }); });
    });
  }

  // ── Relate in the tab: a pinned @relate/relate-wasm release per module worker (site/relate/worker.js), running the
  // steps in site/relate/live.js. A request that runs too long ends its worker (the browser build has no statement
  // timeout); an engine that cannot start leaves the recorded run in place. ──
  var LV = D.live;
  var esc = function (s) { return String(s).replace(/[&<>"]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]; }); };
  var CAN = !!(window.Worker && typeof WebAssembly === "object" && window.Promise);
  function Engine(v) { this.v = v; this.w = null; this.seq = 0; this.wait = {}; this.boot = null; this.info = null; this.dead = null; }
  Engine.prototype.start = function () {
    var self = this;
    if (self.dead) return Promise.reject(new Error(self.dead));
    if (self.boot) return self.boot;
    self.boot = new Promise(function (res, rej) {
      if (!CAN) { rej(new Error("this browser has no WebAssembly workers")); return; }
      try { self.w = new Worker(LV.worker, { type: "module" }); } catch (e) { rej(e); return; }
      self.w.onmessage = function (ev) {
        var m = ev.data || {}, p = self.wait[m.id];
        if (!p) return;
        delete self.wait[m.id]; clearTimeout(p.t);
        if (m.ok) p.res(m.value); else { p.rej(new Error(m.error)); if (m.trap) self.stop("the engine stopped (a WebAssembly trap); it restarts on the next run"); }
      };
      self.w.onerror = function (e) { if (e && e.preventDefault) e.preventDefault(); self.stop((e && e.message) || "the engine worker did not load"); };
      self.call("boot", [self.v], 30000).then(function (i) { self.info = i; res(i); }, rej);
    });
    var b = self.boot;
    b.catch(function (e) {
      var why = String((e && e.message) || e);
      if (self.boot === b) self.stop(why); // end the worker; the next start() is a fresh one
      self.fails = (self.fails || 0) + 1;
      if (!CAN || self.fails >= 2) self.dead = why; // one retry, then the recorded run for good
    });
    return b;
  };
  Engine.prototype.call = function (op, args, ms) {
    var self = this, id = ++self.seq;
    return new Promise(function (res, rej) {
      if (!self.w) { rej(new Error("the engine is not running")); return; }
      self.wait[id] = { res: res, rej: rej, t: setTimeout(function () { self.stop("stopped after " + ms / 1000 + " s"); }, ms) };
      self.w.postMessage({ id: id, op: op, args: args });
    });
  };
  Engine.prototype.stop = function (why) {
    var was = !!this.info;
    if (this.w) this.w.terminate();
    this.w = null; this.boot = null; this.info = null;
    var w = this.wait; this.wait = {};
    Object.keys(w).forEach(function (k) { clearTimeout(w[k].t); w[k].rej(new Error(why)); });
    if (was && this.onstop) this.onstop(why);
  };
  Engine.prototype.run = function (op, args, ms) { var self = this; return self.start().then(function () { return self.call(op, args, ms); }); };
  var engines = {};
  var eng = function (v) { return engines[v] || (engines[v] = new Engine(v)); };
  var A = eng(LV.pin);
  var st = document.getElementById("eng"), stK = document.getElementById("eng-k"), stT = document.getElementById("eng-t"), stM = document.getElementById("eng-m");
  var lastMs = null;
  function status(state, k, t) { if (st) { st.setAttribute("data-state", state); stK.innerHTML = k; stT.innerHTML = t; meter(); } }
  function meter() {
    if (!stM) return;
    var lv = Object.keys(live).length, ls = Object.keys(liveSame).length;
    stM.innerHTML = lastMs === null || st.getAttribute("data-state") !== "live" ? "" : "last pull <b>" + lastMs.toFixed(1) + " ms</b> · " + ls + " of " + lv + " live pulls = the recording";
  }
  var CLONE = "On a clone, <code>relate query --database witnesses/two-hub.rl --read-only</code> runs the same queries.";
  A.onstop = function (why) { status("off", "Engine stopped", esc(why) + ". Relate restarts on the next pull or query."); };
  function warm() {
    if (A.dead || A.boot) return A.start();
    status("load", "Loading", "Relate " + esc(LV.pin) + " is loading into this tab…");
    var p = A.start();
    p.then(function (i) {
      status("live", "Live · Relate " + esc(i.reported) + " in this tab", "Compiled to WebAssembly and served from this site; no server. Started in " + fmt(i.boot_ms) + " ms; the version is the engine's own report.");
      var rb = document.getElementById("ask-run"); if (rb && rb.getAttribute("data-busy") !== "1") rb.disabled = false;
    }, function (e) {
      status("down", "Recorded run", "The engine did not start in this browser (" + esc(e.message) + ")" + (A.dead ? ", so each pull replays the recorded run." : "; the next pull tries once more."));
      var rb = document.getElementById("ask-run"), rm = document.getElementById("ask-meta");
      if (rb && A.dead) { rb.disabled = true; rm.innerHTML = '<span class="pk rec">Not run</span> The engine did not start in this browser (' + esc(e.message) + "). " + CLONE; }
    });
    return p;
  }
  // why a request to an engine did not come back, in words; a statement's own error comes back as r.error instead
  function why(e, E) {
    var m = String((e && e.message) || e);
    if (/^stopped after/.test(m)) return ["Stopped", "S" + esc(m.slice(1)) + ". Relate's browser build has no statement timeout, so the page ended its worker; the engine restarts on the next run."];
    if (/WebAssembly trap/.test(m)) return ["Crashed", "The statement crashed the engine (a WebAssembly trap). A fresh engine starts on the next run."];
    if (/not running/.test(m)) return ["Not run", "The engine was restarting. Run it again."];
    if (E.dead || !E.info) return ["Not run", "The engine did not start in this browser (" + esc(m) + "). " + CLONE];
    return ["Relate says", esc(m)];
  }
  var same = function (a, b) { return JSON.stringify(a) === JSON.stringify(b); };
  var names = function (rows) { return rows.length ? rows.map(function (r) { return esc(r.airport); }).join(", ") : "no rows"; };

  // ── exhibit A: pull a tag ──
  var ex = $("#exhibit .inst"), rows = document.getElementById("ex-rows"), mark = document.getElementById("ex-mark");
  var proof = document.getElementById("ex-proof"), exn = document.getElementById("ex-n"), tally = document.getElementById("tally");
  var regStamp = document.getElementById("reg-stamp"), par = document.getElementById("ex-par"), sayEl = document.getElementById("ex-say");
  var say = function (t) { if (sayEl) sayEl.textContent = t; };
  function showPar(kind) {
    if (!par) return;
    par.hidden = false;
    par.className = "stamp small par " + kind;
    par.textContent = kind === "same" ? "Live = recorded" : kind === "diff" ? "Live ≠ recorded" : "Recorded";
    par.classList.remove("flip"); void par.offsetWidth; par.classList.add("flip");
  }
  var byN = {}; D.tags.forEach(function (t) { byN[t.n] = t; });
  var cur = 0, proven = {}, live = {}, liveSame = {}, pg = 0;
  function renderRows(t) {
    var after = {}; if (t) t.rows.forEach(function (r) { after[r.airport] = r.hub_countries; }); // t: a tag, or a live result
    rows.innerHTML = D.base.map(function (r) {
      var a = esc(r.airport);
      if (!t) return "<tr><td>" + a + "</td><td>[" + esc(r.hub_countries.join(", ")) + "]</td></tr>";
      if (!after[r.airport]) return '<tr class="out"><td>' + a + "</td><td>[" + esc(r.hub_countries.join(", ")) + "]</td></tr>";
      var cs = r.hub_countries.map(function (c) { return after[r.airport].indexOf(c) < 0 ? "<s>" + esc(c) + "</s>" : esc(c); });
      return "<tr><td>" + a + "</td><td>[" + cs.join(", ") + "]</td></tr>";
    }).join("");
  }
  function clearPulled() {
    $$(".pulled", ex).forEach(function (x) { x.classList.remove("pulled"); });
    $$(".out", ex).forEach(function (x) { x.classList.remove("out"); });
    $$(".pull").forEach(function (b) { b.setAttribute("aria-pressed", "false"); });
  }
  function pull(n, keep) {
    var t = byN[n]; if (!t) return;
    var my = ++pg;
    clearPulled();
    if (par) par.hidden = true;
    if (cur === n && !keep) { cur = 0; renderRows(null); exn.textContent = "none"; mark.textContent = "Unchanged"; proof.innerHTML = "Exhibit " + n + " put back: the answer is the four rows again."; say("Exhibit " + n + " put back."); askOn(); return; }
    cur = n; askOn();
    var m = t.rel.match(/\((\w+)\)-\[:(\w+)\]->\((\w+)\)/);
    if (m && m[2] === "HAS_ROUTE") { var e = $('.ed[data-n="' + n + '"]', ex), g = $('.tg[data-n="' + n + '"]', ex); if (e) e.classList.add("pulled"); if (g) g.classList.add("pulled"); }
    else { var cc = $('.cc[data-n="' + n + '"]', ex); if (cc) cc.classList.add("pulled"); }
    t.drops.forEach(function (a) { var nd = $('.nd[data-c="' + a + '"]', ex); if (nd) nd.classList.add("out"); });
    renderRows(t);
    exn.textContent = String(n);
    mark.textContent = "Changed"; mark.classList.remove("flip"); void mark.offsetWidth; mark.classList.add("flip");
    var recorded = "Exhibit " + n + " pulled: <b>" + esc(t.rel) + "</b>. " + D.base.length + " rows → " + t.rows.length + " · " + esc(t.fx) + ". ";
    var b = $('.pull[data-n="' + n + '"]'); if (b) { b.setAttribute("aria-pressed", "true"); b.classList.add("done"); }
    if (A.dead) { proof.innerHTML = '<span class="pk rec">Recorded</span> ' + recorded + "Relate transaction, rolled back, " + t.ms.toFixed(2) + " ms."; showPar("rec"); tick(n); return; }
    proof.innerHTML = '<span class="pk run">Running</span> ' + recorded + "Relate " + esc(LV.pin) + " in this tab is rebuilding the witness without it…";
    warm().then(function () { return A.call("pull", [LV.script, LV.query, LV.params, t.rel], 5000); }).then(function (r) {
      var ok = same(r.rows, t.rows);
      live[n] = 1; if (ok) liveSame[n] = 1; lastMs = r.ms;
      if (!same(r.rows, D.base)) proven[n] = 1; // counted from what the engine returned
      if (my !== pg) { tick(); return; }
      if (!ok) { // never paper over a difference: show what the engine returned
        renderRows({ rows: r.rows });
        $$(".out", ex).forEach(function (x) { x.classList.remove("out"); });
        D.base.forEach(function (row) { if (!r.rows.some(function (q) { return q.airport === row.airport; })) { var nd = $('.nd[data-c="' + row.airport + '"]', ex); if (nd) nd.classList.add("out"); } });
      }
      proof.innerHTML = '<span class="pk live">Live</span> Exhibit ' + n + " pulled: <b>" + esc(t.rel) + "</b>. Relate " + esc(A.info ? A.info.reported : LV.pin) + " rebuilt the witness without it and re-ran the query in " + r.ms.toFixed(1) + " ms: " + D.base.length + " rows → " + r.rows.length + (ok ? " · " + esc(t.fx) + ". <b>Same rows as the recorded run.</b>" : '. <b class="bad">Not the recorded run</b> (' + t.rows.length + " rows there).");
      showPar(ok ? "same" : "diff");
      if (!(allT && allT.length)) say("Exhibit " + n + " pulled, live: " + D.base.length + " rows to " + r.rows.length + (ok ? ", same as the recording." : ", not the recording."));
      tick();
    }, function (e) {
      tick(n); // the recorded run says this deletion changes the answer
      if (my !== pg) return;
      proof.innerHTML = '<span class="pk rec">Recorded</span> ' + recorded + "Relate transaction, rolled back, " + t.ms.toFixed(2) + " ms. (Live run unavailable: " + why(e, A)[1] + ")";
      showPar("rec");
    });
  }
  function tick(n) {
    if (n) proven[n] = 1;
    var k = Object.keys(proven).length, lv = Object.keys(live).length, ls = Object.keys(liveSame).length;
    tally.innerHTML = "<b>" + k + "</b> of " + D.tags.length + " change the answer" + (lv ? '<span class="tl"> · ' + lv + " live in this tab, " + ls + " of " + lv + " same as the recorded run</span>" : "");
    if (k === D.tags.length) { regStamp.classList.add("on"); }
    meter();
  }
  if (ex && CAN) {
    // start the engine once a visitor is near the exhibit AND has scrolled, tapped or typed: a page load alone (or a
    // crawler resizing the viewport) never fetches it; a pull or the query box starts it at once
    var near = false, acted = false, go = function () { if (near && acted) warm().catch(function () {}); };
    ["scroll", "wheel", "pointerdown", "keydown", "touchstart"].forEach(function (k) { window.addEventListener(k, function () { acted = true; go(); }, { once: true, passive: true }); });
    if ("IntersectionObserver" in window) {
      var wio = new IntersectionObserver(function (es) { if (es[0].isIntersecting) { wio.disconnect(); near = true; go(); } }, { rootMargin: "600px 0px" });
      wio.observe(document.getElementById("exhibit"));
    } else near = true;
  } else if (ex) { status("down", "Recorded run", "This browser has no WebAssembly workers, so each pull replays the recorded run."); A.dead = "no WebAssembly workers"; }
  if (ex) {
    tally.innerHTML = "<b>0</b> of " + D.tags.length + " pulled so far";
    $$(".pull").forEach(function (b) { b.addEventListener("click", function () { stopAll(); pull(+b.getAttribute("data-n")); }); });
    $$(".tg", ex).forEach(function (g) {
      var n = +g.getAttribute("data-n");
      g.setAttribute("tabindex", "0"); g.setAttribute("role", "button");
      g.setAttribute("aria-label", "Pull exhibit " + n + ", " + byN[n].rel);
      g.addEventListener("click", function () { stopAll(); pull(n); });
      g.addEventListener("keydown", function (e) { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); stopAll(); pull(n); } });
    });
    var allT = [], btn = document.getElementById("pull-all");
    var stopAll = function () { allT.forEach(clearTimeout); allT = []; btn.textContent = "Pull all " + D.tags.length + ", one at a time"; };
    btn.addEventListener("click", function () {
      if (allT.length) { stopAll(); return; }
      btn.textContent = "Stop";
      D.tags.forEach(function (t, i) { allT.push(setTimeout(function () { var last = i === D.tags.length - 1; if (last) allT = []; pull(t.n, true); if (last) { btn.textContent = "Pull all " + D.tags.length + " again"; setTimeout(function () { say(tally.textContent); }, 1500); } }, RM ? i * 40 : i * 520)); });
    });
  }

  // ── the query box: the visitor's own Cypher on a fresh copy of the witness (minus the pulled tag) ──
  var askQ = document.getElementById("ask-q"), askP = document.getElementById("ask-p"), askRun = document.getElementById("ask-run");
  var askMeta = document.getElementById("ask-meta"), askTbl = document.getElementById("ask-tbl"), askTry = document.getElementById("ask-try");
  function short(v) {
    if (v === null || v === undefined) return "null";
    if (Array.isArray(v)) return "[" + v.map(short).join(", ") + "]";
    if (typeof v === "object") {
      if (v.kind === "node") { var p = v.properties || {}, k = p.iata !== undefined ? "iata" : p.code !== undefined ? "code" : Object.keys(p)[0]; return "(:" + v.labels.join(":") + (k ? " {" + k + ": " + JSON.stringify(p[k]) + "}" : "") + ")"; }
      if (v.kind === "relationship") return "[:" + v.type + "]";
      return JSON.stringify(v);
    }
    return typeof v === "string" ? v : JSON.stringify(v);
  }
  function planLines(op, depth, out) {
    out.push(new Array(depth + 1).join("  ") + (depth ? "└ " : "") + op.operator + (op.details ? "  " + op.details : ""));
    (op.children || []).forEach(function (c) { planLines(c, depth + 1, out); });
    return out;
  }
  function askOn() {
    var el = document.getElementById("ask-on"), bk = document.getElementById("ask-back"); if (!el) return;
    var t = cur && byN[cur];
    el.innerHTML = t ? "Runs on: the witness with exhibit " + t.n + " pulled (<code>" + esc(t.rel) + "</code> deleted), " + (D.tags.length - 1) + " relationships." : "Runs on: the witness, " + D.tags.length + " relationships.";
    if (bk) { var had = document.activeElement === bk; bk.hidden = !t; if (had && !t && askRun) askRun.focus(); }
    if (askTbl && askTbl.innerHTML && !askTbl.classList.contains("stale")) {
      askTbl.classList.add("stale");
      askMeta.insertAdjacentHTML("afterbegin", '<b class="stl">The graph above changed since this result: run it again.</b> ');
    }
  }
  function ask() {
    if (!askRun || askRun.disabled) return;
    var on = cur && byN[cur] ? byN[cur] : null, where = on ? "the witness with exhibit " + on.n + " pulled" : "the witness";
    askRun.disabled = true; askRun.setAttribute("data-busy", "1");
    askMeta.textContent = "Relate " + LV.pin + " is running it in this tab on a fresh copy of " + where + "…";
    warm().then(function () { return A.call("ask", [LV.script, askQ.value, askP.value, on ? on.rel : null], 4000); }).then(function (r) {
      var on2 = esc(where) + " (" + r.relationships + " relationships)";
      if (r.refused) {
        askTbl.innerHTML = "";
        askMeta.innerHTML = '<span class="pk rec">Refused</span> This box reads; it does not write. Relate ran the statement on a throwaway copy and reported ' + Object.keys(r.writes).map(function (k) { return esc(k) + " " + r.writes[k]; }).join(", ") + ". The page dropped that copy; the witness is rebuilt before every run.";
      } else if (r.error) {
        askTbl.innerHTML = "";
        askMeta.innerHTML = '<span class="pk rec">Relate says</span> ' + esc(r.error);
      } else if (r.plan) {
        askTbl.innerHTML = '<pre class="plan">' + esc(planLines(r.plan.root, 0, []).join("\n")) + "</pre>";
        askMeta.innerHTML = '<span class="pk live">Live</span> The plan Relate would run on ' + on2 + " (<code>" + esc(r.plan.schema) + "</code>), " + r.ms.toFixed(1) + " ms. Witness reads these plans to drop relationship types a query cannot reach.";
      } else {
        var cols = r.columns;
        askTbl.innerHTML = cols.length ? "<table class=\"ans-t\"><thead><tr>" + cols.map(function (c) { return '<th scope="col">' + esc(c) + "</th>"; }).join("") + "</tr></thead><tbody>" +
          r.rows.map(function (row) { return "<tr>" + cols.map(function (c) { return "<td>" + esc(short(row[c])) + "</td>"; }).join("") + "</tr>"; }).join("") + "</tbody></table>" : "";
        askMeta.innerHTML = '<span class="pk live">Live</span> ' + fmt(r.total) + (r.total === 1 ? " row" : " rows") + " from " + on2 + " in " + r.ms.toFixed(1) + " ms" + (r.total > r.rows.length ? ", the first " + r.rows.length + " shown" : "") + ".";
      }
    }, function (e) {
      askTbl.innerHTML = "";
      var w = why(e, A);
      askMeta.innerHTML = '<span class="pk rec">' + w[0] + "</span> " + w[1];
    }).then(function () {
      askRun.removeAttribute("data-busy"); askRun.disabled = !!A.dead; askTbl.classList.remove("stale");
      var o = askTbl.parentNode, rr = o.getBoundingClientRect(); // on a phone the result sits below the button: bring it into view
      if (rr.top > window.innerHeight - 60 || rr.bottom < 60) o.scrollIntoView({ block: "nearest", behavior: RM ? "auto" : "smooth" });
    });
  }
  if (askRun && CAN) {
    askRun.disabled = false;
    askMeta.textContent = "Pick an example or write your own, then run it.";
    LV.examples.forEach(function (x, i) {
      var b = document.createElement("button");
      b.type = "button"; b.className = "chip try"; b.textContent = x[0];
      b.addEventListener("click", function () { if (askRun.disabled) return; askQ.value = x[1]; askP.value = JSON.stringify(x[2]); ask(); });
      askTry.appendChild(b);
    });
    askRun.addEventListener("click", ask);
    var askBack = document.getElementById("ask-back");
    if (askBack) askBack.addEventListener("click", function () { if (cur) pull(cur); });
    [askQ, askP].forEach(function (f) {
      f.addEventListener("keydown", function (e) { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) { e.preventDefault(); ask(); } });
      f.addEventListener("focus", function () { warm().catch(function () {}); }, { once: true });
    });
  }

  // ── the engine case: both forms on the release the visitor picks, each release its own engine ──
  var ecWrap = document.getElementById("ec-live"), ecOut = document.getElementById("ec-out");
  if (ecWrap && CAN) {
    ecWrap.hidden = false;
    var ecBtns = $$("button[data-v]", ecWrap);
    ecBtns.forEach(function (b) {
      b.addEventListener("click", function () {
        var v = b.getAttribute("data-v"), E = eng(v), rec = LV.ec.recorded[v];
        ecBtns.forEach(function (x) { x.classList.toggle("on", x === b); });
        $$(".rel-tape tr[data-v]").forEach(function (tr) { tr.classList.remove("live"); });
        ecOut.innerHTML = E.info ? "Running both forms on Relate " + esc(v) + "…" : "Loading Relate " + esc(v) + " into this tab…";
        E.run("pair", [LV.ec.script, LV.ec.forms, LV.ec.params], 5000).then(function (r) {
          var ok = !!rec && same(r.exists, rec.exists) && same(r.count, rec.count) && r.agree === rec.agree;
          if (!b.classList.contains("on")) return;
          ecOut.innerHTML = '<span class="pk live">Live</span> Relate <b>' + esc(E.info.reported) + "</b> (as the engine reports itself), in this tab: <code>COUNT</code> form → " + names(r.count) + " · <code>EXISTS</code> form → " + names(r.exists) + " · <b class=\"" + (r.agree ? "" : "bad") + "\">" + (r.agree ? "they agree" : "they disagree") + "</b>. " + (ok ? "Same as the recorded row." : "<b class=\"bad\">Not the recorded row.</b>");
          var tr = $('.rel-tape tr[data-v="' + v + '"]'); if (tr && ok) tr.classList.add("live");
        }, function (e) {
          if (!b.classList.contains("on")) return;
          var w = why(e, E);
          ecOut.innerHTML = '<span class="pk rec">' + w[0] + "</span> Relate " + esc(v) + ": " + w[1].replace(" " + CLONE, "") + " The table holds the recorded run.";
        });
      });
    });
  }

  // ── terminal: type the recorded run out, line by line, the first time it is seen ──
  var term = document.getElementById("term");
  var tt = []; // the typing timers, so a second click restarts instead of stacking runs
  function typeOut() {
    tt.forEach(clearTimeout); tt = [];
    var ls = $$(".ln", term);
    if (RM) { ls.forEach(function (l) { l.classList.add("on"); }); term.classList.remove("typing"); return; }
    term.classList.add("typing"); ls.forEach(function (l) { l.classList.remove("on"); });
    var pre = $("pre", term); pre.scrollTop = 0;
    ls.forEach(function (l, i) { tt.push(setTimeout(function () { l.classList.add("on"); if (i === ls.length - 1) term.classList.remove("typing"); }, i * 38)); });
  }
  if (term) {
    document.getElementById("t-play").addEventListener("click", typeOut);
    if (!RM && "IntersectionObserver" in window) {
      var tio = new IntersectionObserver(function (es) { if (es[0].isIntersecting) { tio.disconnect(); typeOut(); } }, { threshold: 0.3 });
      tio.observe(term);
    }
  }

  // ── receipts: count up from zero, once (the markup already holds the final value) ──
  var cnt = $$("[data-count]");
  if (cnt.length && !RM && "IntersectionObserver" in window) {
    var cio = new IntersectionObserver(function (es) {
      es.forEach(function (e) {
        if (!e.isIntersecting) return; cio.unobserve(e.target);
        var el = e.target, to = parseFloat(el.getAttribute("data-count")), dec = (el.getAttribute("data-count").split(".")[1] || "").length, s = 0;
        (function up(ts) { if (!s) s = ts; var f = Math.min(1, (ts - s) / 1100); var x = to * (1 - Math.pow(1 - f, 3)); el.textContent = dec ? x.toFixed(dec) : fmt(Math.round(x)); if (f < 1) requestAnimationFrame(up); })(performance.now());
      });
    }, { threshold: 0.6 });
    cnt.forEach(function (c) { cio.observe(c); });
  }
})();
