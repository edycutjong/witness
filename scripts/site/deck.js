(function () {
  "use strict";
  var D = JSON.parse(document.getElementById("wdata").textContent);
  var $ = function (s, r) { return (r || document).querySelector(s); };
  var $$ = function (s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); };
  var fmt = function (n) { return n.toLocaleString("en-US"); };
  var RM = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var stage = document.getElementById("stage"), frames = $$(".frame"), N = frames.length;
  var count = document.getElementById("count"), notes = document.getElementById("notes");
  var cur = 0, step = {}, ov = false;

  // fit: the layout viewport, not innerWidth (mobile browsers zoom out and report a wide innerWidth)
  function fit() {
    var w = document.documentElement.clientWidth, h = document.documentElement.clientHeight;
    stage.style.setProperty("--s", Math.min(w / 1920, h / 1080).toFixed(4));
  }
  window.addEventListener("resize", fit); fit();

  // version chips: baked text stays if the releases API is unreachable (private repo → 404)
  if (document.getElementById("ver") && document.getElementById("ver").hasAttribute("data-live") && window.fetch) {
    fetch("https://api.github.com/repos/edycutjong/witness/releases/latest", { headers: { Accept: "application/vnd.github+json" } })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (j) { if (j && j.tag_name) $$('a[href$="/releases/latest"].chip').forEach(function (c) { c.textContent = j.tag_name; }); })
      .catch(function () {});
  }

  // ── slide 4: the reduction, stepped through the trace milestones ──
  var MS = D.ms, d4 = document.getElementById("d-draw"), dr = document.getElementById("d-rels"), dt = document.getElementById("d-trial");
  var dn = document.getElementById("d-note"), dtape = document.getElementById("d-tape"), raf = 0;
  var NT = MS[MS.length - 1][0];
  var bow = function (p, q, b) { return [(p[0] + q[0]) / 2 - (q[1] - p[1]) * b, (p[1] + q[1]) / 2 + (q[0] - p[0]) * b]; };
  var qd = function (p, q, b) { var c = bow(p, q, b); return "M" + p[0].toFixed(1) + " " + p[1].toFixed(1) + "Q" + c[0].toFixed(1) + " " + c[1].toFixed(1) + " " + q[0].toFixed(1) + " " + q[1].toFixed(1); };
  var lerp = function (a, b, t) { return [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t]; };
  var ease = function (t) { return t < .5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2; };
  function place(svg, t) {
    $$(".nd", svg).forEach(function (g) { var c = g.getAttribute("data-c"), p = lerp(D.geo[c], D.sch[c], t); g.setAttribute("transform", "translate(" + p[0].toFixed(1) + " " + p[1].toFixed(1) + ")"); });
    $$(".ed", svg).forEach(function (e) { var s = e.getAttribute("data-s"), d = e.getAttribute("data-e"); e.setAttribute("d", qd(lerp(D.geo[s], D.sch[s], t), lerp(D.geo[d], D.sch[d], t), 0.06 + 0.1 * (1 - t))); });
  }
  function s4(k, animate) {
    cancelAnimationFrame(raf);
    var svg = $(".inst", d4), m = MS[k];
    dr.textContent = fmt(m[1]); dt.textContent = fmt(m[0]); dr.classList.toggle("kept", k === MS.length - 1);
    dn.textContent = k === 0 ? "The whole air-routes graph, before trial 1." : k === 1 ? "Trial " + m[0] + ": " + m[2] + " · −" + fmt(MS[0][1] - m[1]) : k === 2 ? "Trial " + m[0] + ": " + m[2] + "." : "Trial " + m[0] + ": " + m[2] + ", every relationship needed.";
    dtape.style.clipPath = k === MS.length - 1 ? "" : "inset(0 " + (100 - 100 * m[0] / NT).toFixed(2) + "% 0 0)";
    if (k < MS.length - 1) { d4.classList.add("geo"); d4.classList.toggle("thin", k >= 2); place(svg, 0); return; }
    d4.classList.remove("thin");
    if (!animate || RM) { d4.classList.remove("geo"); place(svg, 1); return; }
    d4.classList.add("thin");
    var s0 = 0;
    (function morph(ts) { if (!s0) s0 = ts; var f = Math.min(1, (ts - s0) / 1100); place(svg, ease(f)); if (f > .6) d4.classList.remove("geo"); if (f < 1) raf = requestAnimationFrame(morph); else d4.classList.remove("thin"); })(performance.now());
  }

  // ── slide 5: pull a tag, stepped (9, 4, 15, then the stamp) ──
  var byN = {}; D.tags.forEach(function (t) { byN[t.n] = t; });
  var PULLS = [0, 9, 4, 15, 15], p5 = document.getElementById("p-draw");
  var pRows = document.getElementById("p-rows"), pN = document.getElementById("p-n"), pMark = document.getElementById("p-mark");
  var pFx = document.getElementById("p-fx"), pStamp = document.getElementById("p-stamp");
  var esc = function (s) { return String(s).replace(/[&<>]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]; }); };
  function rowsHtml(t) {
    var after = {}; if (t) t.rows.forEach(function (r) { after[r.airport] = r.hub_countries; });
    return D.base.map(function (r) {
      if (!t) return "<tr><td>" + r.airport + "</td><td>[" + r.hub_countries.join(", ") + "]</td></tr>";
      if (!after[r.airport]) return '<tr class="out"><td>' + r.airport + "</td><td>[" + r.hub_countries.join(", ") + "]</td></tr>";
      return "<tr><td>" + r.airport + "</td><td>[" + r.hub_countries.map(function (c) { return after[r.airport].indexOf(c) < 0 ? "<s>" + c + "</s>" : c; }).join(", ") + "]</td></tr>";
    }).join("");
  }
  function s5(k, animate) {
    var n = PULLS[k], t = byN[n];
    $$(".pulled", p5).forEach(function (x) { x.classList.remove("pulled"); });
    $$(".out", p5).forEach(function (x) { x.classList.remove("out"); });
    pRows.innerHTML = rowsHtml(t);
    pN.textContent = t ? String(n) : "none";
    pMark.textContent = t ? "Changed" : "Unchanged";
    if (animate && t) { pMark.classList.remove("flip"); void pMark.offsetWidth; pMark.classList.add("flip"); }
    if (t) {
      var m = t.rel.match(/\((\w+)\)-\[:(\w+)\]->\((\w+)\)/);
      if (m[2] === "HAS_ROUTE") { $$('[data-n="' + n + '"]', p5).forEach(function (x) { if (!x.classList.contains("cc")) x.classList.add("pulled"); }); }
      else { var cc = $('.cc[data-n="' + n + '"]', p5); if (cc) cc.classList.add("pulled"); }
      t.drops.forEach(function (a) { var nd = $('.nd[data-c="' + a + '"]', p5); if (nd) nd.classList.add("out"); });
      pFx.innerHTML = "Exhibit " + n + " pulled: " + esc(t.rel) + " · " + esc(t.fx) + ".";
    } else pFx.textContent = "Nothing pulled: the four rows on the witness alone.";
    var last = k === PULLS.length - 1;
    pStamp.classList.toggle("hide", !last);
    if (last && animate && !RM) { pStamp.classList.remove("slam"); void pStamp.offsetWidth; pStamp.classList.add("slam"); }
  }
  var STEP = { 4: s4, 5: s5 };
  var STEPS = {}; frames.forEach(function (f, i) { var s = +f.getAttribute("data-steps") || 0; if (s) STEPS[i + 1] = s; });

  function show(i, k, animate) {
    i = Math.max(0, Math.min(N - 1, i)); cur = i;
    frames.forEach(function (f, j) { f.classList.toggle("on", j === i); f.setAttribute("aria-hidden", j === i ? "false" : "true"); });
    var n = i + 1;
    if (STEPS[n]) { step[n] = k == null ? STEPS[n] : Math.max(0, Math.min(STEPS[n], k)); STEP[n](step[n], animate); }
    count.textContent = n + " / " + N;
    var a = $("aside.notes", frames[i]); notes.textContent = a ? a.textContent : "";
    if (location.hash !== "#" + n) history.replaceState(null, "", "#" + n);
  }
  function next() { var n = cur + 1; if (STEPS[n] && step[n] < STEPS[n]) { show(cur, step[n] + 1, true); return; } if (cur < N - 1) { var m = cur + 2; show(cur + 1, STEPS[m] ? 0 : null, true); } }
  function prev() { var n = cur + 1; if (STEPS[n] && step[n] > 0) { show(cur, step[n] - 1, false); return; } if (cur > 0) show(cur - 1, null, false); }
  function fromHash() { var n = parseInt((location.hash || "").slice(1), 10); return n >= 1 && n <= N ? n - 1 : 0; }

  document.addEventListener("keydown", function (e) {
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    var k = e.key;
    if (k === "ArrowRight" || k === "PageDown" || k === " ") { e.preventDefault(); if (ov) toggleOv(); else next(); }
    else if (k === "ArrowLeft" || k === "PageUp") { e.preventDefault(); if (!ov) prev(); }
    else if (k === "Home") { e.preventDefault(); show(0, null, false); }
    else if (k === "End") { e.preventDefault(); show(N - 1, null, false); }
    else if (k === "n" || k === "N") toggleNotes();
    else if (k === "o" || k === "O") toggleOv();
    else if (k === "Escape" && ov) toggleOv();
  });
  function toggleNotes() { notes.hidden = !notes.hidden; document.getElementById("ntb").setAttribute("aria-pressed", String(!notes.hidden)); }
  function toggleOv() {
    ov = !ov; document.body.classList.toggle("ov", ov); document.getElementById("ovb").setAttribute("aria-pressed", String(ov));
    if (ov) { Object.keys(STEPS).forEach(function (n) { STEP[n](STEPS[n], false); }); frames[cur].scrollIntoView({ block: "center" }); }
    else show(cur, null, false);
  }
  document.getElementById("next").addEventListener("click", next);
  document.getElementById("prev").addEventListener("click", prev);
  document.getElementById("ntb").addEventListener("click", toggleNotes);
  document.getElementById("ovb").addEventListener("click", toggleOv);
  frames.forEach(function (f, j) { f.addEventListener("click", function (e) { if (ov) { ov = true; toggleOv(); show(j, null, false); return; } if (e.target.closest("a,button")) return; var r = stage.getBoundingClientRect(); if (e.clientX - r.left < r.width * 0.3) prev(); else next(); }); });
  window.addEventListener("hashchange", function () { var i = fromHash(); if (i !== cur) show(i, null, false); });
  window.addEventListener("beforeprint", function () { Object.keys(STEPS).forEach(function (n) { STEP[n](STEPS[n], false); }); frames.forEach(function (f) { f.setAttribute("aria-hidden", "false"); }); });
  window.addEventListener("afterprint", function () { show(cur, step[cur + 1], false); });
  show(fromHash(), null, false);
})();
