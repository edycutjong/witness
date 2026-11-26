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

  // ── exhibit A: pull a tag ──
  var ex = $("#exhibit .inst"), rows = document.getElementById("ex-rows"), mark = document.getElementById("ex-mark");
  var proof = document.getElementById("ex-proof"), exn = document.getElementById("ex-n"), tally = document.getElementById("tally");
  var regStamp = document.getElementById("reg-stamp");
  var byN = {}; D.tags.forEach(function (t) { byN[t.n] = t; });
  var cur = 0, proven = {};
  var esc = function (s) { return String(s).replace(/[&<>]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]; }); };
  function renderRows(t) {
    var after = {}; if (t) t.rows.forEach(function (r) { after[r.airport] = r.hub_countries; });
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
  function pull(n) {
    var t = byN[n]; if (!t) return;
    clearPulled();
    if (cur === n) { cur = 0; renderRows(null); exn.textContent = "none"; mark.textContent = "Unchanged"; proof.innerHTML = "Exhibit " + n + " put back: the answer is the four rows again."; return; }
    cur = n;
    var m = t.rel.match(/\((\w+)\)-\[:(\w+)\]->\((\w+)\)/);
    if (m && m[2] === "HAS_ROUTE") { var e = $('.ed[data-n="' + n + '"]', ex), g = $('.tg[data-n="' + n + '"]', ex); if (e) e.classList.add("pulled"); if (g) g.classList.add("pulled"); }
    else { var cc = $('.cc[data-n="' + n + '"]', ex); if (cc) cc.classList.add("pulled"); }
    t.drops.forEach(function (a) { var nd = $('.nd[data-c="' + a + '"]', ex); if (nd) nd.classList.add("out"); });
    renderRows(t);
    exn.textContent = String(n);
    mark.textContent = "Changed"; mark.classList.remove("flip"); void mark.offsetWidth; mark.classList.add("flip");
    proof.innerHTML = "Exhibit " + n + " pulled: <b>" + esc(t.rel) + "</b>. " + D.base.length + " rows → " + t.rows.length + " · " + esc(t.fx) + ". Relate transaction, rolled back, " + t.ms.toFixed(2) + " ms.";
    var b = $('.pull[data-n="' + n + '"]'); if (b) { b.setAttribute("aria-pressed", "true"); b.classList.add("done"); }
    proven[n] = 1;
    var k = Object.keys(proven).length;
    tally.innerHTML = "<b>" + k + "</b> of " + D.tags.length + " change the answer";
    if (k === D.tags.length) { regStamp.classList.add("on"); }
  }
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
      D.tags.forEach(function (t, i) { allT.push(setTimeout(function () { pull(t.n); if (i === D.tags.length - 1) { allT = []; btn.textContent = "Pull all " + D.tags.length + " again"; } }, RM ? i * 40 : i * 520)); });
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
