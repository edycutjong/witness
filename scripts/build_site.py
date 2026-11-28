"""Build site/ (the static landing on Vercel) from the committed files. Every number on the page is read from them.

uv run python scripts/build_site.py        -> site/index.html + site/exhibit/two-hub.html + site/icon.svg + site/og-image.png
"""

from __future__ import annotations

import hashlib
import html
import json
import re
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
REPO = "https://github.com/edycutjong/witness"
# Absolute base for og:image, canonical and the QR code (custom domain).
SITE_URL = "https://witness.edycu.dev"
# Set True when the repository is public (the public flip at submission), then rebuild and redeploy.
REPO_PUBLIC = True
VERSION = re.search(r'^version = "([^"]+)"', (ROOT / "pyproject.toml").read_text(), re.M).group(1)
RELEASES = f"{REPO}/releases/latest"
RELEASES_API = "https://api.github.com/repos/" + REPO.split("github.com/")[1] + "/releases/latest"
pytest_log = sorted((ROOT / "evidence").glob("pytest-*.txt"))[-1]
TESTS = int(re.search(r"(\d+) passed", pytest_log.read_text()).group(1))

man = json.loads((ROOT / "witnesses" / "two-hub.manifest.json").read_text())
cmp_path = sorted((ROOT / "evidence").glob("neo4j-compare-*.json"))[-1]
cmp = json.loads(cmp_path.read_text())
# full-graph necessity of the 68 bound relationships (judge review r5/r6): how many change the answer there, how many of those
# are in the witness; the rest are flights of airports outside the witness, whose deletion adds that airport
fgn = json.loads((ROOT / "evidence" / "full-graph-necessity.json").read_text())
assert (
    fgn["bound"] == cmp["targeted_agreement"]["rels"]
    and fgn["change_the_answer"] == cmp["targeted_agreement"]["relate_changed"]
)
FGN_IN = fgn["change_and_in_witness"]
FGN_OUT = fgn["change_the_answer"] - FGN_IN
exhibit = (ROOT / "witnesses" / "two-hub.html").read_text()

src_rels, src_nodes = man["source"]["relationships"], man["source"]["nodes"]
w_rels, w_nodes = man["witness"]["relationships"], man["witness"]["nodes"]
trials, secs = man["run"]["trials"], man["run"]["seconds"]
# the other recorded runs' wall clock, named beside the committed one (judge review r8: three unlabelled seconds)
_red = re.compile(r"reduced in ([0-9.]+) s · (\d+) trials")
_lm = _red.search((ROOT / "evidence" / "demo-2026-11-24.txt").read_text())
_vm = _red.search((ROOT / "evidence" / "video-demo-run-2026-11-27.txt").read_text())
assert _lm and _vm and int(_lm.group(2)) == int(_vm.group(2)) == trials
LANDING_S, VIDEO_S = _lm.group(1), _vm.group(1)
check = man["check"]["check_text"].split(" (")[0]
rows = man["baseline"]["rows"]
relate_tps = cmp["median_trials_per_s"]["relate_in_process"]
neo_tps = cmp["median_trials_per_s"]["neo4j_docker"]
ratio = cmp["ratio_trials_per_s"]

fmt = lambda n: f"{n:,}"  # noqa: E731
# the claim as /judge's hero prints it (the numbers stand above it there), and with this run's numbers for JUDGE.md
CLAIM_HERO = "When an agent answers from a graph, Witness hands back a small graph that reproduces the answer, and proves that deleting any one of its relationships changes the answer."
CLAIM = CLAIM_HERO.replace("the answer,", f"the answer (here, {fmt(src_rels)} relationships → {w_rels}),", 1)
assert CLAIM != CLAIM_HERO


sys.path.insert(0, str(Path(__file__).resolve().parent))
import site_parts as sp  # noqa: E402

PARTS = Path(__file__).resolve().parent / "site"
import vendor_relate_wasm as vrw  # noqa: E402

# ── Relate in the tab: the self-hosted @relate/relate-wasm engines (scripts/vendor_relate_wasm.py) run the witness in a
# module worker (scripts/site/worker.js) through the same steps the Node parity check runs (scripts/site/live.js) ─────
_vbad = vrw.check()
assert not _vbad, _vbad
ENGINES = json.loads((SITE / "relate" / "engines.json").read_text())
WASM = json.loads((ROOT / "evidence" / "wasm-parity.json").read_text())
LIVE_PIN = man["versions"]["relate_db"]
LIVE_FIX = [v for v in ENGINES if v != LIVE_PIN]
assert WASM["ok"] and WASM["engine"]["version"] == WASM["engine"]["reported"] == LIVE_PIN, WASM["engine"]
assert WASM["pulls"]["same_rows"] == WASM["pulls"]["of"] == WASM["pulls"]["changed"] == sp.pulls["of"], WASM["pulls"]
assert WASM["baseline_same"] and WASM["write_refused"] and all(e["same_as_recorded"] for e in WASM["engine_case"])
assert LIVE_PIN in ENGINES and len(LIVE_FIX) == 1, sorted(ENGINES)
# the page itself in a browser (scripts/browser_live.mjs, headless Chrome): every pull live and the same as the recording
BL = json.loads((ROOT / "evidence" / "browser-live.json").read_text())
BEFORE_BROWSER_RUN = "--before-browser-run" in sys.argv[1:]
assert BL["ok"] and BL["pulls"]["live"] == BL["pulls"]["same_rows"] == BL["pulls"]["of"] == sp.pulls["of"], BL["pulls"]
assert BL["write"]["refused"] and BL["stop"]["stopped"] and all(e["live"] and e["same_as_recorded"] for e in BL["engine_case"])
# nothing off this site, nothing failed, nothing on the console: with no exception (the page calls no one else)
assert not BL["third_party_requests"] and not BL["console_errors"] and not BL["failed_responses"], "the browser run saw a request off the site, a failed response or a console error"
# the engine files as served are the ones engines.json lists (hashed by the browser run), and each engine's worker
# fetched only from the site it was served from (the worker reports its own requests; a page cannot see them)
assert BEFORE_BROWSER_RUN or (BL["engine_files"]["checked"] == sum(len(e["files"]) for e in ENGINES.values()) and not BL["engine_files"]["mismatches"]), BL.get("engine_files")
_origin = BL["url"].split("/", 3)[0] + "//" + BL["url"].split("/", 3)[2]
BL_FETCHED = {} if BEFORE_BROWSER_RUN else BL["engine_worker_requests"]
assert BEFORE_BROWSER_RUN or (sorted(BL_FETCHED) == sorted(ENGINES) and all(u.startswith(_origin + "/relate/") for us in BL_FETCHED.values() for u in us) and all(BL_FETCHED.values())), BL_FETCHED
# A page load alone starts no engine (at_load, below). After a first scroll or key the engine starts only when the
# exhibit is within the page's 600 px margin; the run records which case it saw, and the two must agree.
assert BEFORE_BROWSER_RUN or ((BL["acted_away"]["engine_workers"] == 0) == (BL["acted_away"]["exhibit_px_below_viewport"] > 600)), BL.get("acted_away")
assert BL["at_load"] == {"engine_workers": 0, "plate": "ready"} and BL["engine_workers_at_end"] >= 1, BL["at_load"]
# The browser run must be of the code shipped now: the live steps (live.js, worker.js) and the page's own logic
# (landing.js, inlined in index.html; index.html itself prints numbers from that run, so its hash cannot be bound).
# A change to any of the three needs a page to record against first: `build_site.py --before-browser-run` builds it
# without these three checks; serve site/, run scripts/browser_live.mjs on it, then build again without the flag. CI
# never passes the flag.
PAGE_JS = "landing.js (inlined in index.html)"
_shipped = {f"relate/{_f}": hashlib.sha256((PARTS / _f).read_bytes()).hexdigest() for _f in ("live.js", "worker.js")}
_shipped[PAGE_JS] = hashlib.sha256((PARTS / "landing.js").read_text().strip().encode("utf-8")).hexdigest()
for _f, _sha in _shipped.items():
    assert BEFORE_BROWSER_RUN or BL["served_sha256"].get(_f) == _sha, f"evidence/browser-live.json predates {_f}: build with --before-browser-run, serve site/, re-run scripts/browser_live.mjs, build again"
BL_CHROME = BL["run"]["browser"].replace("/", " ")
assert WASM["live_js_sha256"] == hashlib.sha256((PARTS / "live.js").read_bytes()).hexdigest(), "evidence/wasm-parity.json is older than scripts/site/live.js: run node scripts/wasm_parity.mjs --out evidence/wasm-parity.json"
LIVE_FIX_V = LIVE_FIX[0]
LIVE_FILES = ("live.js", "worker.js")
LIVE_KEY = hashlib.sha256(
    b"".join((PARTS / f).read_bytes() for f in LIVE_FILES) + (SITE / "relate" / "engines.json").read_bytes()
).hexdigest()[:10]
fix = json.loads((ROOT / "fixtures" / "mex-foreign.manifest.json").read_text())
assert fix["check"]["check_text"].startswith(
    f"{fix['witness']['relationships']} of {fix['witness']['relationships']} change"
)
cov = re.search(r"TOTAL .*: ([\d.]+)%", pytest_log.read_text())
assert cov and float(cov.group(1)) == 100.0, "coverage receipt is not 100%"
readme = (ROOT / "README.md").read_text()
QUOTES = [
    (
        'Deletion-minimal means: no single remaining relationship (or kept isolated node) can be removed without changing the\nanswer. It does not mean "smallest possible".',
        "README · What a witness shows, and what it does not",
    ),
    (
        "Because a query with `NOT EXISTS` or aggregation is not monotone, a witness proves its own\nanswer on its own file; it does not prove that every superset of it gives the same answer.",
        "README · What a witness shows, and what it does not",
    ),
    (
        "The gap mostly reflects an embedded engine versus a Dockerised server with a network round trip per statement; it says nothing about Neo4j's query engine.",
        "README · Measured against Neo4j",
    ),
]
_readme_flat = " ".join(readme.replace("**", "").split())
for q, _ in QUOTES:
    assert " ".join(q.split()) in _readme_flat, f"quote not verbatim in README: {q[:50]}"
FAQ = [
    (
        "Is the witness the smallest subgraph that gives the answer?",
        "No. It is deletion-minimal: no single remaining relationship can be removed without changing the answer. A smaller witness may exist.",
    ),
    (
        "What counts as changing the answer?",
        f"The answer is compared exactly: types matter, rows are a bag (order is not part of the answer), floats to {man['comparison']['float_digits']} significant digits, and this headline run compares lists strictly (<code>--strict-lists</code>). Pulling exhibit 4 keeps all four airports but drops US from two rows, and that is a change.",
    ),
    (
        "Does Witness ever write to my graph?",
        "No. The source <code>.rl</code> is copied byte for byte and never opened for writing; every reduction checks its SHA-256 unchanged afterwards. Fixture mode pulls from Neo4j once and never pushes back.",
    ),
    (
        "Is anything mocked?",
        "Not the judged path: the graph store, transactions, rollback and queries are real Relate in every test. In tests, <code>relate pull</code> (it needs a Neo4j server) is stood in, and a few tests substitute timers, process calls, a failing CLI, a database wrapper that injects engine faults, or one reducer phase to reach rare branches. The committed fixture run pulled from a real Neo4j server (<code>fixtures/mex-foreign.report.json</code>).",
    ),
    (
        "Why Relate rather than a Neo4j server?",
        f"The inner loop is one transaction per trial, in process, on a single file: {relate_tps} trials/s here against {neo_tps} over Bolt to Neo4j in Docker on the same machine. And a witness is a file you can commit, hand over and open with plain <code>relate</code>, with no server.",
    ),
    (
        "Are the pulls on this page real?",
        f"Yes, when your browser can run them. The page loads <code>@relate/relate-wasm</code> {LIVE_PIN}, the release the witness was reduced on, from this site into a worker, rebuilds the witness from its <code>.cypher</code> script, deletes the tag you pulled and re-runs the query; each answer says <b>Live</b> and whether it matches the recorded run. If the engine cannot start, the pull replays the recording and says <b>Recorded</b>. <code>scripts/wasm_parity.mjs</code> runs the same steps outside the browser: <code>evidence/wasm-parity.json</code>.",
    ),
    (
        "How does an agent use it?",
        "Over MCP. The <code>why</code> tool returns the witness of the agent's own answer and <code>check</code> re-proves it. Two recorded sessions are committed: <code>evidence/mcp-transcript.md</code> (a scripted client) and <code>evidence/mcp-agent-session.md</code> (a real model, claude-sonnet-5-5 in Claude Code, writing its own Cypher and attaching the witness).",
    ),
]


def png_size(path: Path) -> tuple[int, int]:
    b = path.read_bytes()[16:24]
    return int.from_bytes(b[:4], "big"), int.from_bytes(b[4:], "big")


def code_ticks(t: str) -> str:
    """`x` in a quoted README sentence renders as <code>x</code>."""
    return re.sub(r"`([^`]+)`", r"<code>\1</code>", t)


def fill(tpl: str, vals: dict) -> str:
    out = re.sub(r"\{\{([A-Z0-9_]+)\}\}", lambda m: str(vals[m.group(1)]), tpl)
    assert "{{" not in out, "unfilled slot"
    return out


_t4 = next(t for t in sp.pulls["tags"] if t["n"] == 4)
_us_dropped = sum(
    "US" in b["hub_countries"] and "US" not in a["hub_countries"]
    for b, a in zip(sp.pulls["baseline_rows"], _t4["rows"], strict=True)
)
assert (_t4["drops"], _t4["rows_after"], _us_dropped) == ([], 4, 2), (
    "FAQ: 'exhibit 4 keeps all four airports but drops US from two rows'"
)
assert man["comparison"]["strict_lists"] is True, "FAQ: 'this headline run compares lists strictly'"


def cases_vals() -> dict:
    """Exhibits B and C on the landing (judge review r6): the disagree and differs receipts, every number read from the
    committed manifests and the scan."""
    db = json.loads((ROOT / "witnesses" / "direction-bug.manifest.json").read_text())
    wa = json.loads((ROOT / "witnesses" / "wrong-answer.manifest.json").read_text())
    scan = json.loads((ROOT / "evidence" / "disagree-scan.json").read_text())
    assert (
        db["verified"]
        and db["predicate"]["kind"] == "disagree"
        and wa["verified"]
        and wa["predicate"]["kind"] == "differs"
    )
    assert db["source"]["relationships"] == wa["source"]["relationships"] == src_rels
    wa_rows = {r["airport"] for r in wa["baseline"]["rows"]}
    exp_rows = {r["airport"] for r in wa["predicate"]["expected_rows"]}
    extra = sorted(wa_rows - exp_rows)
    assert extra == ["AGR"] and exp_rows <= wa_rows, extra
    # the scan and the disagree receipt are about the same two queries and the same pair (arch review r7)
    q = {(ROOT / p).read_text().strip() for p in scan["queries"]}
    assert q == {db["statement"].strip(), db["predicate"]["other_statement"].strip()}, "scan queries != receipt queries"
    pair = (db["params"]["country"], db["params"]["dest"])
    assert pair in {(d["country"], d["dest"]) for d in scan["differ"]}, pair
    ec = json.loads((ROOT / "witnesses" / "exists-count.manifest.json").read_text())
    vers = [json.loads(ln) for ln in (ROOT / "evidence" / "relate-versions.jsonl").read_text().splitlines()]
    dis = [v["relate_db"] for v in vers if not v["the_two_forms_agree"]]
    agr = [v["relate_db"] for v in vers if v["the_two_forms_agree"]]
    ex = [x["element"] for x in ec["check"]["probes"]]
    assert ec["verified"] and ec["predicate"]["kind"] == "disagree" and ec["source"]["relationships"] == src_rels
    assert len(ex) == ec["witness"]["relationships"] == 2 and len(agr) == 1 and dis[0] == ec["versions"]["relate_db"]
    assert ec["params"] == {"country": "MX"}, "the landing says 'Mexican airports'"
    return {
        "EC_ENGINE": ec["versions"]["relate_db"],
        "EC_FIXED": agr[0],
        "EC_RELS": ec["witness"]["relationships"],
        "EC_ROWS": len(ec["baseline"]["rows"]),
        "EC_TRIALS": ec["run"]["trials"],
        "EC_CHECK": ec["check"]["check_text"].split(" (")[0],
        "EC_VERSIONS": "\n            ".join(
            f'<tr class="{"agr" if v["the_two_forms_agree"] else "dis"}" data-v="{html.escape(v["relate_db"])}"><td>{html.escape(v["relate_db"])}</td>'
            f"<td>{html.escape(', '.join(r['airport'] for r in v['count-two-match']) or 'no rows')}</td>"
            f"<td>{html.escape(', '.join(r['airport'] for r in v['exists-two-match']) or 'no rows')}</td>"
            f"<td>{'agree' if v['the_two_forms_agree'] else 'disagree'}</td></tr>"
            for v in vers
        ),
        "EC_EX1": html.escape(sorted(ex)[0]),
        "EC_EX2": html.escape(sorted(ex)[1]),
        "C_SRC": fmt(src_rels),
        "DB_RELS": db["witness"]["relationships"],
        "DB_TRIALS": fmt(db["run"]["trials"]),
        "DB_CHECK": db["check"]["check_text"].split(" (")[0],
        "SCAN_DIFFER": scan["pairs_differ"],
        "SCAN_PAIRS": scan["pairs_scanned"],
        "WA_RELS": wa["witness"]["relationships"],
        "WA_TRIALS": fmt(wa["run"]["trials"]),
        "WA_CHECK": wa["check"]["check_text"].split(" (")[0],
        "WA_ROWS": len(wa_rows),
        "WA_EXP": len(exp_rows),
    }


DESC = f"When an agent answers from a graph, Witness hands back {w_rels} of its {fmt(src_rels)} relationships that reproduce the answer on their own, and proves each of them is needed."
DESC_OG = f"{fmt(src_rels)} relationships → {w_rels} that reproduce an agent's answer on their own. Take any one of the {w_rels} away and it changes."
assert 50 <= len(DESC) <= 160 and len(DESC_OG) <= 125, (len(DESC), len(DESC_OG))


# the headline question as the query file states it, with the run's parameters filled in
QUESTION = (
    man["statement"]
    .splitlines()[0]
    .lstrip("/ ")
    .replace("$country", man["params"]["country"])
    .replace("$dest", man["params"]["dest"])
)


_EC_MAN = json.loads((ROOT / "witnesses" / "exists-count.manifest.json").read_text())
_EC_REC = {v["relate_db"]: v for v in (json.loads(ln) for ln in (ROOT / "evidence" / "relate-versions.jsonl").read_text().splitlines())}
_Q = (ROOT / sp.pulls["query"]).read_text()
_HUBS_Q = (
    "MATCH (a:Airport)-[:IN_COUNTRY]->(:Country {code: $country})\n"
    "MATCH (a)-[:HAS_ROUTE]->(hub:Airport)-[:HAS_ROUTE]->(:Airport {iata: $dest})\n"
    "RETURN a.iata AS airport, coll.sort(collect(DISTINCT hub.iata)) AS hubs\n"
    "ORDER BY airport"
)
_ALL_Q = (
    "MATCH (a)-[r]->(b)\n"
    "RETURN coalesce(a.iata, a.code) AS from, type(r) AS type, coalesce(b.iata, b.code) AS to\n"
    "ORDER BY type, from, to"
)
LIVE = {
    "worker": f"/relate/worker.js?v={LIVE_KEY}",
    "pin": LIVE_PIN,
    "fix": LIVE_FIX_V,
    "script": (ROOT / "witnesses" / "two-hub.cypher").read_text(),
    "query": _Q,
    "params": sp.pulls["params"],
    "examples": [
        ["The question", _Q.split("\n", 1)[1].rstrip("\n"), sp.pulls["params"]],
        ["Two hubs each", _HUBS_Q, sp.pulls["params"]],
        ["Every relationship", _ALL_Q, {}],
        ["EXPLAIN it", "EXPLAIN " + _Q.split("\n", 1)[1].rstrip("\n"), sp.pulls["params"]],
    ],
    "ec": {
        "script": (ROOT / "witnesses" / "exists-count.cypher").read_text(),
        "forms": {k: (ROOT / "queries" / f"{k}-two-match.cypher").read_text() for k in ("exists", "count")},
        "params": _EC_MAN["params"],
        "recorded": {
            v: {"exists": _EC_REC[v]["exists-two-match"], "count": _EC_REC[v]["count-two-match"], "agree": _EC_REC[v]["the_two_forms_agree"]}
            for v in ENGINES
        },
    },
}


def landing_page() -> str:
    shot_w, shot_h = png_size(SITE / "media" / "exhibit-page.png")
    og = hashlib.sha256((ROOT / "docs" / "assets" / "og-image-1200.png").read_bytes()).hexdigest()[:10]
    question = QUESTION
    src_cta = (
        f'<a class="btn solid" href="{REPO}"><svg viewBox="0 0 20 20" aria-hidden="true"><path d="M7 5L2 10l5 5M13 5l5 5-5 5" fill="none" stroke="currentColor" stroke-width="1.8"/></svg>Source on GitHub</a>'
        if REPO_PUBLIC
        else '<span class="src-pending"><svg viewBox="0 0 20 20" width="17" height="17" aria-hidden="true"><path d="M7 5L2 10l5 5M13 5l5 5-5 5" fill="none" stroke="currentColor" stroke-width="1.8"/></svg>Source on GitHub opens at submission</span>'
    )
    receipts = [
        (
            f'<span data-count="{src_rels}">{fmt(src_rels)}</span><span class="to">→</span><em>{w_rels}</em>',
            f"relationships in the air-routes graph, then in its witness ({fmt(src_nodes)} → {w_nodes} nodes)",
        ),
        (
            f'<em>{w_rels}</em><span class="to">of</span>{w_rels}',
            "deleting any one from the witness changes the answer, checked on relate-db and on the Relate CLI",
        ),
        (
            f'<span data-count="{cmp["targeted_agreement"]["rels"]}">{cmp["targeted_agreement"]["rels"]}</span><span class="to">→</span><em>{w_rels}</em>',
            f"relationships the answer rows bind, then the witness: deleted from the full graph, only {cmp['targeted_agreement']['relate_changed']} of the {cmp['targeted_agreement']['rels']} change the answer ({FGN_IN} of them in the witness); deleted from the witness, all {w_rels} do",
        ),
        (
            f'<span data-count="{TESTS}">{TESTS}</span><span class="to">·</span>100%',
            "tests against real Relate · line and branch coverage",
        ),
    ]
    vals = {
        "DESC": html.escape(DESC),
        "DESC_OG": html.escape(DESC_OG),
        "SITE": SITE_URL,
        "OGV": og,
        "CSS": (PARTS / "witness.css").read_text(),
        "LANDING_CSS": (PARTS / "landing.css").read_text(),
        "RELEASES": RELEASES,
        "VER_LIVE": " data-live" if REPO_PUBLIC else "",
        "VERSION": VERSION,
        "W_RELS": w_rels,
        "SRC_RELS": fmt(src_rels),
        "SOURCE_CTA": src_cta,
        "REPO": REPO,
        "CMD_NOTE": (
            "Needs uv. The committed air-routes graph is copied, never modified."
            if REPO_PUBLIC
            else "Needs uv. The repository opens at submission; until then the clone does not resolve and the recorded run below is the output."
        ),
        "ANSWER": html.escape(" ".join(r["airport"] for r in rows)),
        "HERO_SVG": sp.schematic("h", ghost=True),
        "PLAN_DROP": fmt(sp.trace["plan"]["dropped_rels"]),
        "TRIALS": trials,
        "TAPE": sp.tape_svg(),
        "APPLIED": sp.HOLDS.count("1"),
        "ROLLED": sp.HOLDS.count("0"),
        "FRAME_PAIRS": fmt(sp.FRAME_COUNTS["pairs"]),
        "RECEIPTS": "\n    ".join(f'<div class="rc"><b>{a}</b><span>{b}</span></div>' for a, b in receipts),
        "CMP_MD": cmp_path.with_suffix(".md").name,
        "PYTEST": pytest_log.name,
        "RELATE_V": man["versions"]["relate_db"],
        "PY_V": man["versions"]["python"],
        "QUESTION": html.escape(question),
        "EX_SVG": sp.schematic("x", ghost=False),
        "ANSWER_ROWS": sp.answer_rows(),
        "REGISTER": sp.register_rows(),
        "PULL_UTC": sp.pulls["run"]["utc"].replace("T", " ").rstrip("Z"),
        "SHOT_H": round(1200 * shot_h / shot_w),
        "TERM": sp.terminal_lines(),
        "DEMO_UTC": sp.DEMO_HEADER.split(" · ")[0].replace("recorded ", "").replace("T", " ").replace("Z", " UTC"),
        "DEMO_FILE": sp.demo_path.name,
        "DEMO_REDUCE": sp.DEMO_REDUCE,
        "RELATE_TPS": relate_tps,
        "NEO_TPS": neo_tps,
        "NEO_V": cmp["neo4j"]["components"][0]["v"],
        "NEO_W": round(100 * neo_tps / relate_tps, 1),
        "FIX_FROM": fmt(fix["source"]["relationships"]),
        "FIX_TO": fix["witness"]["relationships"],
        "LIMITS": "\n      ".join(
            f'<li><span class="ln-no">{i}</span><div><blockquote>{code_ticks(html.escape(" ".join(q.split())))}</blockquote><cite>{c}</cite></div></li>'
            for i, (q, c) in enumerate(QUOTES, 1)
        ),
        "FAQ": "\n      ".join(f"<details><summary>{html.escape(q)}</summary><p>{a}</p></details>" for q, a in FAQ),
        "SOURCE_FOOT": f'<a href="{REPO}">source</a>' if REPO_PUBLIC else "source opens at submission",
        "DATA": json.dumps({**sp.PAGE_DATA, "live": LIVE}, separators=(",", ":")).replace("</", "<\\/"),
        "PIN": LIVE_PIN,
        "N_ROUTES": sum(1 for t in sp.pulls["tags"] if ":HAS_ROUTE]" in t["rel"]),
        "N_CC": sum(1 for t in sp.pulls["tags"] if ":IN_COUNTRY]" in t["rel"]),
        "ASK_Q": html.escape(_Q.split("\n", 1)[1].rstrip("\n")),
        "ASK_P": html.escape(json.dumps(sp.pulls["params"]), quote=True),
        "FIX": LIVE_FIX_V,
        "WASM_SAME": WASM["pulls"]["same_rows"],
        "WASM_OF": WASM["pulls"]["of"],
        "JS": (PARTS / "landing.js").read_text(),
        **cases_vals(),
    }
    return fill((PARTS / "landing.html").read_text(), vals)


CAPS = [  # (code token as in README "Relate capabilities used", the deck's 2-3 word gloss)
    ("begin_transaction · rollback_transaction", "the inner loop", "begin_transaction"),
    ("QueryResult.query_type", "refuse writes", "query_type"),
    ("EXPLAIN", "prune unreachable types", "`EXPLAIN` plans"),
    ("read_only=True", "reruns cannot write", "read_only=True"),
    ("single-file .rl", "the evidence format", "single-file `.rl`"),
    ("relate pull", "fixture mode", "`relate pull` for fixture mode"),
    ("relate query --mode json", "re-check on the CLI", "relate query --mode json"),
    (
        "MCP · why · check",
        "Witness's own tools, beside relate serve --mcp",
        "MCP: Witness's own tools `why` and `check`",
    ),
]


def _ln(e: str, cls: str = "") -> str:
    return f'<span class="ln{(" " + cls) if cls else ""}">{e or " "}</span>'


def deck_page() -> str:
    og = hashlib.sha256((ROOT / "docs" / "assets" / "og-image-1200.png").read_bytes()).hexdigest()[:10]
    host = SITE_URL.split("://")[1]
    # cover terminal: lines selected from the recorded run, order kept, text never edited
    cover = []
    for ln in sp.demo.splitlines()[1:]:
        if ln.startswith(("WITNESS ", "  68 relationships", "CHECK ", "  relate CLI:", "PROVE ONE", "  CHANGED:")):
            e = html.escape(ln)
            if ln.startswith("CHECK"):
                cover.append(_ln(f'<b class="k">{e}</b>'))
            else:
                cover.append(_ln(re.sub(r"^([A-Z]{4,}(?: [A-Z]{3,})?)", r'<b class="h">\1</b>', e)))
    assert len(cover) == 6, "cover lines missing from the demo transcript"
    # the query, verbatim, with the three hard parts marked
    cy = html.escape((ROOT / "queries" / "two-hub.cypher").read_text().rstrip("\n"))
    for kw in ("NOT EXISTS", "OPTIONAL MATCH", "count(DISTINCT hub)", "collect(DISTINCT hc.code)"):
        assert kw in cy, kw
        cy = cy.replace(kw, f'<b class="hi">{kw}</b>', 1)
    cy = re.sub(r"^(//.*)$", r'<span class="cm">\1</span>', cy, count=1, flags=re.M)
    # slide 2: the real frame alone (no witness drawn)
    g = sp.schematic("g", ghost=True)
    g = g[: g.index('<g class="edges">')] + "</svg>"
    g = re.sub(
        r"<title id=\"g-t\">.*?</title>",
        f'<title id="g-t">The air-routes graph in frame: {fmt(sp.FRAME_COUNTS["pairs"])} airport pairs</title>',
        g,
    )
    # slide 5 final state: exhibit 15 pulled (the markup alone is the last step)
    fin = next(t for t in sp.pulls["tags"] if t["n"] == 15)
    pv = sp.schematic("p", ghost=False)
    for a, b in (
        (' class="ed" data-n="15"', ' class="ed pulled" data-n="15"'),
        ('class="tg" data-n="15"', 'class="tg pulled" data-n="15"'),
    ):
        assert a in pv
        pv = pv.replace(a, b, 1)
    for a in fin["drops"]:
        pv = pv.replace(f'class="nd" data-c="{a}"', f'class="nd out" data-c="{a}"', 1)
    after = {r["airport"]: r["hub_countries"] for r in fin["rows"]}
    frows = "".join(
        (
            f'<tr class="out"><td>{html.escape(r["airport"])}</td><td>[{html.escape(", ".join(r["hub_countries"]))}]</td></tr>'
            if r["airport"] not in after
            else f"<tr><td>{html.escape(r['airport'])}</td><td>[{', '.join(html.escape(c) if c in after[r['airport']] else f'<s>{html.escape(c)}</s>' for c in r['hub_countries'])}]</td></tr>"
        )
        for r in sp.pulls["baseline_rows"]
    )
    # slide 9: the MCP transcript, verbatim lines
    mcp_md = (ROOT / "evidence" / "mcp-transcript.md").read_text()
    mcp = json.loads((ROOT / "evidence" / "mcp-transcript.json").read_text())
    whys = [c for c in mcp["calls"] if c["tool"] == "why"]
    sec2 = mcp_md.split("## 2. witness `why`")[1].split("## 3.")[0]
    why_lines = [
        ln.replace("**", "")
        for ln in sec2.splitlines()
        if ln.startswith(("**Answer**", "**Evidence:**", "verified=True"))
    ]
    assert len(why_lines) == 3
    why_html = "".join(
        _ln(html.escape(x) if not x.startswith("Evidence") else f'<b class="k">{html.escape(x)}</b>') for x in why_lines
    )
    sec4 = mcp_md.split("## 4. witness `why`")[1].split("```json")[1].split("```")[0].strip("\n")
    assert "read-only queries only" in sec4
    ref_html = _ln(html.escape("// statement: " + whys[1]["arguments"]["statement"])) + "".join(
        _ln(html.escape(x)) for x in sec4.splitlines()
    )
    rec = mcp["recorded"]
    mcp_utc = datetime.strptime(rec, "%Y-%m-%dT%H:%M:%S%z").astimezone(UTC).strftime("%Y-%m-%d %H:%M UTC")
    for _code, _, cite in CAPS:
        assert cite.split(" · ")[0] in readme, f"capability not in README: {cite}"
    qr = (PARTS / "qr.svg").read_text().strip()
    assert f'aria-label="QR code: {SITE_URL}/"' in qr, "qr.svg encodes a different URL: regenerate it"
    det = json.loads((ROOT / "evidence" / "determinism.json").read_text())
    assert det["byte_identical"] is True
    p50 = cmp["median_trial_ms_p50"]
    vals = {
        "DESC": html.escape(DESC),
        "DESC_OG": html.escape(DESC_OG),
        "SITE": SITE_URL,
        "OGV": og,
        "CSS": (PARTS / "witness.css").read_text(),
        "DECK_CSS": (PARTS / "deck.css").read_text(),
        "W_RELS": w_rels,
        "SRC_RELS": fmt(src_rels),
        "SRC_NODES": fmt(src_nodes),
        "RELEASES": RELEASES,
        "VER_LIVE": " data-live" if REPO_PUBLIC else "",
        "VERSION": VERSION,
        "SITE_HOST": host,
        "COVER_TERM": "".join(cover),
        "DEMO_UTC": sp.DEMO_HEADER.split(" · ")[0].replace("recorded ", "").replace("T", " ").replace("Z", " UTC"),
        "DEMO_FILE": sp.demo_path.name,
        "MAP_SVG": g,
        "FRAME_PAIRS": fmt(sp.FRAME_COUNTS["pairs"]),
        "CYPHER": cy,
        "ANSWER_ROWS": sp.answer_rows(),
        "TRIALS": trials,
        "MS_LAST": f"Trial {sp.MILESTONES[-1][0]}: {sp.MILESTONES[-1][2]}, every relationship needed.",
        "RED_SVG": sp.schematic("d", ghost=True),
        "TAPE": sp.tape_svg(),
        "APPLIED": sp.HOLDS.count("1"),
        "ROLLED": sp.HOLDS.count("0"),
        "PLAN_DROP": fmt(sp.trace["plan"]["dropped_rels"]),
        "A_END": sp.MILESTONES[2][0],
        "A_RELS": sp.MILESTONES[2][1],
        "PULL_SVG": pv,
        "FINAL_PULL": 15,
        "FINAL_ROWS": frows,
        "FINAL_FX": html.escape(f"Exhibit 15 pulled: {fin['rel']} · {sp.EFFECTS[15]}."),
        "CAPS_LEAD": (
            f'<span class="no">1</span><code>{html.escape(CAPS[0][0])}</code>'
            f"<span>{CAPS[0][1]}: {trials} trials in the headline run</span>"
        ),
        "CAPS": "".join(
            f'<li class="{"big" if i <= 4 else "sm"}"><span class="no">{i}</span><code>{html.escape(c)}</code><span>{d}</span></li>'
            for i, (c, d, _) in enumerate(CAPS[1:], 2)
        ),
        "DET_RUNS": len(det["runs"]) if isinstance(det["runs"], list) else det["runs"],
        "TESTS": TESTS,
        "PYTEST": pytest_log.name,
        "RELATE_TPS": relate_tps,
        "NEO_TPS": neo_tps,
        "NEO_V": cmp["neo4j"]["components"][0]["v"],
        "NEO_W": round(100 * neo_tps / relate_tps, 1),
        "CMP_RUNS": len(cmp["runs"]),
        "P50_R": f"{p50['relate_in_process']:.2f}",
        "P50_N": f"{p50['neo4j_docker']:.2f}",
        "P50_RW": round(100 * p50["relate_in_process"] / p50["neo4j_docker"], 1),
        "CMP_MD": cmp_path.with_suffix(".md").name,
        "WHY_S": whys[0]["seconds"],
        "MCP_WHY": why_html,
        "REFUSE_S": whys[1]["seconds"],
        "MCP_REFUSE": ref_html,
        "MCP_DATE": mcp_utc,
        "COVER_SVG": sp.schematic("c", ghost=False),
        "REPO": REPO,
        "RUN_NOTE": (
            "Needs uv. The committed graph is copied, never modified."
            if REPO_PUBLIC
            else "Needs uv. The repository opens at submission; until then the clone does not resolve."
        ),
        "QR": qr,
        "DATA": sp.page_json(),
        "JS": (PARTS / "deck.js").read_text(),
    }
    out = fill((PARTS / "deck.html").read_text(), vals)
    n = [0]

    def foot(m):
        n[0] += 1
        return f'<div class="pfoot"><span><b>Witness</b> · v{VERSION} · {host}</span><span>{n[0]} / 10</span></div>\n</section>'

    out = re.sub(r"</section>", foot, out)
    assert n[0] == 10, "deck must have 10 slides"
    return out


SITE.mkdir(exist_ok=True)
(SITE / "exhibit").mkdir(exist_ok=True)
# the served copy gets a way back home; the committed witnesses/two-hub.html stays byte-identical to what `witness` wrote
back_css = (
    "a{color:var(--ink);text-underline-offset:3px;transition:color .15s ease,text-decoration-thickness .15s ease}"
    "a:hover{color:#6F6555;text-decoration-thickness:3px}.t,dt{color:#6F6555}"
    'h2{font:600 13px/1.4 "Source Sans 3",system-ui,sans-serif;letter-spacing:.14em;text-transform:uppercase;color:#6F6555}'
    '.nav{font:600 13px/1.4 "Source Sans 3",system-ui,sans-serif;letter-spacing:.14em;text-transform:uppercase;color:#6F6555}'
    "@media (max-width:600px){.en,.nl{font-size:19px}}"
    "a:focus-visible{outline:3px solid var(--ink);outline-offset:3px}"
    "@media (prefers-reduced-motion:reduce){a{transition:none}}"
)
fonts = (
    '<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
    '<link href="https://fonts.googleapis.com/css2?family=Fragment+Mono&family=Old+Standard+TT:wght@400;700&family=Source+Sans+3:wght@400;600&display=swap" rel="stylesheet">'
)
served = (
    exhibit.replace("</style>", back_css + "</style>", 1)
    .replace("<style>", fonts + "<style>", 1)
    .replace(
        '<p class="mono">WITNESS · EXHIBIT REGISTER</p>',
        '<p class="nav"><a href="../">&larr; Witness</a> · EXHIBIT REGISTER</p>',
        1,
    )
    .replace(
        '<div class="grid">',
        '<p class="q">Deletion-minimal: no single remaining relationship can be removed without changing the answer. It does not mean smallest possible.</p>\n<div class="grid">',
        1,
    )
)
if served == exhibit:
    raise SystemExit("exhibit html changed shape: no style/eyebrow to patch")
served = served.replace(
    "airports of $country have no direct flight to $dest",
    "airports of {country} have no direct flight to {dest}".format(**man["params"]),
    1,
)
(SITE / "exhibit" / "two-hub.html").write_text(served)
for _f in LIVE_FILES:
    shutil.copyfile(PARTS / _f, SITE / "relate" / _f)
page = landing_page()
(SITE / "index.html").write_text(page)
(SITE / "deck").mkdir(exist_ok=True)
(SITE / "deck" / "index.html").write_text(deck_page())
# favicon + social card: the judge-facing media from docs/assets (synced from the asset pipeline)
shutil.copyfile(ROOT / "docs" / "assets" / "icon.svg", SITE / "icon.svg")
# the social card at its exact 1x size (1200x630, under 1 MB); docs/assets/og-image.png is the @2x master
shutil.copyfile(ROOT / "docs" / "assets" / "og-image-1200.png", SITE / "og-image.png")

# ── /judge and JUDGE.md: one reader, one page, every number read from the committed files ───────────────────────────
# Both are written from the same lists below. A backticked path that exists in the repository becomes a link to that
# file (GitHub on the page, a relative link in JUDGE.md), so a receipt cannot name a file that is not there.
COMMITS = man["run"]["commits"]
TA = cmp["targeted_agreement"]
_db = json.loads((ROOT / "witnesses" / "direction-bug.manifest.json").read_text())
DB_RELS, DB_CHECK = _db["witness"]["relationships"], _db["check"]["check_text"].split(" (")[0]
assert _db["verified"] and DB_CHECK.endswith("end the disagreement")
_wa = json.loads((ROOT / "witnesses" / "wrong-answer.manifest.json").read_text())
WA_RELS, WA_CHECK = _wa["witness"]["relationships"], _wa["check"]["check_text"].split(" (")[0]
WA_ROWS, WA_EXP = len(_wa["baseline"]["rows"]), len(_wa["predicate"]["expected_rows"])
assert _wa["verified"] and _wa["predicate"]["kind"] == "differs" and WA_CHECK.endswith("change the answer")
det = json.loads((ROOT / "evidence" / "determinism.json").read_text())
assert det["byte_identical"] is True and man["verified"] and man["check"]["cli_used"]
# an observed engine disagreement (Relate 1.0.1; the v1.3.0 release notes list the fix), shrunk, and the releases it separates
_ec = json.loads((ROOT / "witnesses" / "exists-count.manifest.json").read_text())
EC_RELS, EC_CHECK = _ec["witness"]["relationships"], _ec["check"]["check_text"].split(" (")[0]
EC_ROWS, EC_TRIALS = len(_ec["baseline"]["rows"]), _ec["run"]["trials"]
assert _ec["verified"] and _ec["predicate"]["kind"] == "disagree" and EC_CHECK.endswith("end the disagreement")
assert _ec["source"]["relationships"] == src_rels and _ec["versions"]["relate_db"] == man["versions"]["relate_db"]
assert _ec["params"] == {"country": man["params"]["country"]}, "the engine case is no longer about the headline's country"
EC_EXHIBITS = [x["element"] for x in _ec["check"]["probes"]]
_vers = [json.loads(ln) for ln in (ROOT / "evidence" / "relate-versions.jsonl").read_text().splitlines()]
VER_DISAGREE = [v["relate_db"] for v in _vers if not v["the_two_forms_agree"]]
VER_AGREE = [v["relate_db"] for v in _vers if v["the_two_forms_agree"]]
assert VER_DISAGREE[0] == man["versions"]["relate_db"] and VER_AGREE == ["1.3.0"], (VER_DISAGREE, VER_AGREE)
assert all(v["relationships"] == EC_RELS and v["count-two-match"] and not (v["exists-two-match"] and v["relate_db"] in VER_DISAGREE) for v in _vers)
_and = lambda xs: ", ".join(xs[:-1]) + " and " + xs[-1] if len(xs) > 1 else xs[0]  # noqa: E731
# Relate's release notes as regression fixtures (--other-engine against the release that fixed each one)
_rn = json.loads((ROOT / "evidence" / "release-notes-fixes.json").read_text())
RN_ENTRIES = _rn["entries"]
assert RN_ENTRIES == len(_rn["fixes"]), "the number of release-note entries is a count of the list, not a typed number"
RN_CHANGE = sum(1 for f in _rn["fixes"] if f["status"].startswith("reproduced"))
RN_SHRUNK = sum(1 for f in _rn["fixes"] if f["status"].startswith("reproduced, shrunk"))
_rg = [json.loads(p.read_text()) for p in sorted((ROOT / "witnesses" / "regress").glob("*.manifest.json"))]
assert _rg and all(m["verified"] and m["predicate"].get("other_engine_spec") for m in _rg)
assert all(m["source"]["relationships"] == src_rels for m in _rg)
RG_N = len(_rg)
RG_SIZES = sorted((m["witness"]["relationships"], m["witness"]["isolated_nodes"]) for m in _rg)
RG_MAX_RELS = max(r for r, _ in RG_SIZES)
# the fixes marked "reproduced, shrunk" name exactly the committed regression witnesses (one fix can have two)
_named = [w for f in _rn["fixes"] if f["status"].startswith("reproduced, shrunk") for w in ([f["witness"]] if isinstance(f["witness"], str) else f["witness"])]
assert sorted(w for w in _named if w.startswith("witnesses/regress/")) == sorted(f"witnesses/regress/{m['name']}.rl" for m in _rg), _named
assert all(n in (1, 2) for r, n in RG_SIZES if r == 0), RG_SIZES  # "one or two nodes are all they need"
_rv = [json.loads(ln) for ln in (ROOT / "evidence" / "regression-releases.jsonl").read_text().splitlines()]
RV_RELEASES = sorted({r["relate_db"] for r in _rv}, key=lambda v: tuple(map(int, v.split("."))))
for _m in _rg:  # each witness changes its answer exactly once, at the release it was reduced against
    _fix = _m["predicate"]["other_engine_spec"].split("==")[1]
    _digs = [next(r["digest"] for r in _rv if r["witness"].endswith("/" + _m["name"]) and r["relate_db"] == v) for v in RV_RELEASES]
    _flips = [RV_RELEASES[i] for i in range(1, len(_digs)) if _digs[i] != _digs[i - 1]]
    assert _flips == [_fix], (_m["name"], _flips, _fix)
    # "the release the notes name": the release this witness was reduced against is the one its fix entry carries
    _w = f"witnesses/regress/{_m['name']}.rl"
    _noted = [f["release"] for f in _rn["fixes"] if f["status"].startswith("reproduced, shrunk") and _w in ([f["witness"]] if isinstance(f["witness"], str) else f["witness"])]
    assert _noted == ["v" + _fix], (_m["name"], _noted, _fix)
    # the table is of the committed witness script, and every release built the same graph from it: where the answer
    # changes it is the query that answered differently, not CREATE that stored something else
    _rows = [r for r in _rv if r["witness"].endswith("/" + _m["name"])]
    assert {r["cypher_sha256"] for r in _rows} == {hashlib.sha256((ROOT / "witnesses" / "regress" / f"{_m['name']}.cypher").read_bytes()).hexdigest()}, _m["name"]
    assert len({r["graph_sha256"] for r in _rows}) == 1 and len(_rows) == len(RV_RELEASES), _m["name"]
# the differential run (agent-written queries on relate-db 1.0.1, relate-db 1.3.0 and Neo4j; bench/differential.py).
# What an engine gave is an answer, an error, a timeout, a crash or something uncomparable; two engines are compared
# only where both answered. Every word the receipt prints about the split is read from the rows below.
_df = json.loads((ROOT / "evidence" / "differential.json").read_text())
assert _df["schema"] == "witness.differential/v2"
assert (_df["engines"]["relate_1_0_1"], _df["engines"]["relate_1_3_0"]) == ("1.0.1", "1.3.0"), _df["engines"]
assert _df["queries_sha256"] == hashlib.sha256((ROOT / "queries" / "differential.jsonl").read_bytes()).hexdigest(), "evidence/differential.json is of other queries: re-run bench/differential.py"
DF_Q = _df["queries"]
_dfa = [json.loads(ln) for ln in (ROOT / "evidence" / "differential-answers.jsonl").read_text().splitlines()]
assert len(_dfa) == DF_Q == len({r["id"] for r in _dfa})
DF_TIMEOUT_S = f"{_df['timeout_s']:g}"


def _df_tally(pair: str, allowed: set) -> dict:
    """One pair's tally, recounted from the rows; a kind the receipt has no words for stops the build."""
    t = _df["tally"][pair]
    counted: dict = {}
    for r in _dfa:
        counted[r[pair]] = counted.get(r[pair], 0) + 1
    assert t == counted and sum(t.values()) == DF_Q and set(t) <= allowed, (pair, t, counted)
    return t


def _df_order(pair: str) -> int:
    """ORDER BY queries whose rows agree on this pair: all of them must also agree on the order of the rows."""
    o = _df["order"].get(pair, {})
    assert set(o) <= {"same order"} and sum(o.values()) == sum(1 for r in _dfa if r.get(pair + "_order")), (pair, o)
    return o.get("same order", 0)


DF_T = _df_tally("relate_1_0_1_vs_1_3_0", {"same", "differ", "error/error", "timeout/timeout", "timeout/answer"})
DF_SAME, DF_DIFF = DF_T["same"], DF_T.get("differ", 0)
DF_BOTH_REFUSED, DF_BOTH_TIMEOUT, DF_ONLY_130 = DF_T.get("error/error", 0), DF_T.get("timeout/timeout", 0), DF_T.get("timeout/answer", 0)
DF_ORDERED = _df_order("relate_1_0_1_vs_1_3_0")
DF_RED = [r for r in _df.get("reductions", []) if r["engine"] == "relate-db==1.3.0"]
assert len(DF_RED) == DF_DIFF == 1 and DF_RED[0].get("verified") and (DF_RED[0]["relationships"], DF_RED[0]["nodes"]) == (0, 1), DF_RED
# "differs in value type (a float on 1.0.1, an integer on 1.3.0)": the same numbers, another type, read from the two answers
_dd = next(r for r in _dfa if r["relate_1_0_1_vs_1_3_0"] == "differ")
_h101, _h130 = _dd["relate_1_0_1"]["head"][0], _dd["relate_1_3_0"]["head"][0]
_changed = [c for c in _h101 if type(_h101[c]) is not type(_h130[c])]
assert _changed and all(_h101[c] == _h130[c] and isinstance(_h101[c], float) and isinstance(_h130[c], int) for c in _changed), (_h101, _h130)
DF_NEO = bool(isinstance(_df["engines"]["neo4j"], dict) and _df["engines"]["neo4j"].get("version"))
DF_NEO_TEXT = " The Neo4j leg is not in the committed run."
DF_ENGINES = "Relate 1.0.1 against 1.3.0; the Neo4j leg was not run"
if DF_NEO:
    _neo = _df["engines"]["neo4j"]
    _pairs = {"same", "differ", "error/error", "timeout/timeout", "answer/timeout"}
    NT = _df_tally("relate_1_0_1_vs_neo4j", _pairs)
    NT3 = _df_tally("relate_1_3_0_vs_neo4j", _pairs)
    assert _df_order("relate_1_0_1_vs_neo4j") == _df_order("relate_1_3_0_vs_neo4j") == DF_ORDERED, "'on every pair of engines'"
    NEO_RED = [r for r in _df["reductions"] if r["engine"] == "neo4j"]
    NEO_SHRUNK, NEO_NOTHING = [r for r in NEO_RED if r.get("verified")], [r for r in NEO_RED if "empty graph" in r.get("refused", "")]
    assert len(NEO_RED) == NT.get("differ", 0) == len(NEO_SHRUNK) + len(NEO_NOTHING) and len(NEO_SHRUNK) == len(NEO_NOTHING) == 1, NEO_RED
    # the shrunk one is the same query the two releases differ on, and there Neo4j answers as 1.3.0 does
    assert NEO_SHRUNK[0]["id"] == _dd["id"] and _dd["relate_1_3_0_vs_neo4j"] == "same" and NEO_SHRUNK[0]["relate_1_3_0_on_witness"] == "differs from 1.0.1"
    assert (NEO_SHRUNK[0]["relationships"], NEO_SHRUNK[0]["nodes"]) == (0, 1)
    # the other is how toString prints a float: both Relate releases one way, Neo4j the other, on no data at all
    _dt = next(r for r in _dfa if r["id"] == NEO_NOTHING[0]["id"])
    _tr, _tn = _dt["relate_1_3_0"]["head"][0], _dt["neo4j"]["head"][0]
    _tcols = [c for c in _tr if _tr[c] != _tn[c]]
    assert _dt["relate_1_0_1_vs_1_3_0"] == "same" and _dt["relate_1_3_0_vs_neo4j"] == "differ" and _tcols and all(isinstance(_tr[c], str) and "E" in _tn[c] and "E" not in _tr[c] for c in _tcols), (_tr, _tn)
    DF_TOSTRING = " and ".join(f"`{_tr[c]}` on Relate is `{_tn[c]}` on Neo4j" for c in _tcols)
    DF_ENGINES = f"Relate 1.0.1, Relate 1.3.0 and {_neo['version']}"
    NEO_ONLY_RELATE, NEO_NEITHER = NT.get("answer/timeout", 0), NT.get("timeout/timeout", 0)
    assert all(r["feature"] == "shortest" for r in _dfa if "timeout" in r["relate_1_0_1_vs_neo4j"]), "'shortest-path queries'"
    DF_NEO_TEXT = (
        f" Against {_neo['version']} ({_neo['default_language'].title()}, in a Docker container with a {_neo['settings']['server.memory.heap.max_size']} heap and {_neo['settings']['dbms.memory.transaction.total.max']} of transaction memory, the graph loaded without the store's constraints and indexes, one run): "
        f"{NT['same']} agree with 1.0.1, {NT.get('error/error', 0)} end in an error on both, {NT.get('differ', 0)} differ, and {NEO_ONLY_RELATE + NEO_NEITHER} shortest-path queries are not compared "
        f"because Neo4j did not finish them within the run's {DF_TIMEOUT_S} s ({NEO_NEITHER} of those 1.0.1 did not finish either; why was not investigated, so read it as a limit of this setup, not of Neo4j). One difference is the same value type: there Neo4j answers as 1.3.0 does, and it "
        f"shrinks to {NEO_SHRUNK[0]['nodes']} node against Neo4j too. The other is how `toString` prints a float ({DF_TOSTRING}), the same on both Relate releases; it holds on an empty graph, so there is nothing to shrink. "
        f"Wherever a query with `ORDER BY` gives the same rows on two engines, it gives them in the same order ({DF_ORDERED} of {DF_ORDERED} on every pair of engines)."
    )
# a slowdown still present on 1.3.0, measured on small graphs (ANY SHORTEST + an inline relationship predicate)
_as = [json.loads(ln) for ln in (ROOT / "evidence" / "any-shortest-inline.jsonl").read_text().splitlines()]
_as13 = [r for r in _as if r["relate_db"] == "1.3.0"]
AS_LAST_OK = max((r for r in _as13 if r["form"] == "inline" and "ms" in r), key=lambda r: r["nodes"])
_as_others = sorted({r["relate_db"] for r in _as} - {"1.3.0"})
AS_OTHER = _and(_as_others)
AS_HANG = min((r for r in _as13 if r["form"] == "inline" and "ms" not in r), key=lambda r: r["nodes"])
AS_WATCHDOG = re.fullmatch(r"no answer within ([\d.]+) s \(killed\)", AS_HANG["result"]).group(1)  # type: ignore[union-attr]
assert all("ms" in r and r["ms"] < 1 for r in _as if r["form"] == "plain"), "'without the predicate, under 1 ms'"
for _v in _as_others:  # "The same on": no answer at the same size and an answer at every smaller one, on each release
    _in = [r for r in _as if r["relate_db"] == _v and r["form"] == "inline"]
    assert {r["nodes"] for r in _in if "ms" not in r} == {r["nodes"] for r in _as13 if r["form"] == "inline" and "ms" not in r}, _v
    assert all(r.get("result") == AS_HANG["result"] for r in _in if "ms" not in r), _v
# every relationship of the full graph deleted alone: supports (drop or alter a row) and guards (add one)
sens = json.loads((ROOT / "evidence" / "full-graph-sensitivity.json").read_text())
assert sens["relationships_tried"] == src_rels and sens["supports"] + sens["guards"] == sens["change_the_answer"]
assert sens["bound_by_the_answer_rows"] == fgn["bound"] and sens["change_and_bound"] == fgn["change_the_answer"]
assert sens["change_and_in_witness"] == FGN_IN and sens["supports"] == sens["supports_in_witness"]
assert all(c["type"] == "HAS_ROUTE" and len(c["added"]) == 1 for c in sens["changing"] if c["kind"] == "guard")
# the committed witnesses re-proved on a second engine
neo = json.loads((ROOT / "evidence" / "neo4j-recheck.json").read_text())
assert neo["all_agree"] and [w["witness"] for w in neo["witnesses"]] == [
    f"witnesses/{n}.cypher" for n in ("two-hub", "direction-bug", "wrong-answer")
]
NEO_RE = [w["necessary_on_neo4j"] for w in neo["witnesses"]]
assert NEO_RE == [w["probes"] for w in neo["witnesses"]] == [w["agree_with_relate"] for w in neo["witnesses"]]
NEO_RE_V = neo["neo4j"][0]["v"]
# the stores as files: sizes are read from the files themselves and must match the recorded ones
sbytes = json.loads((ROOT / "evidence" / "store-bytes.json").read_text())
BYTES = {x["path"]: x["bytes"] for x in sbytes["stores"]}
assert all((ROOT / q).stat().st_size == n for q, n in BYTES.items()), "evidence/store-bytes.json is stale"
assert sbytes["rerun"]["cypher_byte_identical"] and sbytes["rerun"]["rl_same_graph"] and not sbytes["rerun"]["rl_byte_identical"]
assert sbytes["headline_script"]["sha256"] == det["runs"][0]["cypher_sha256"]
# other query shapes (tests/test_examples.py re-runs the three that shrink)
oq = json.loads((ROOT / "evidence" / "other-queries.json").read_text())
OQ = oq["examples"]
assert [Path(e["query"]).stem for e in OQ] == ["fewest-flights", "longest-nonstop", "domestic-only"]
assert all(e["verified"] and (ROOT / e["query"]).is_file() for e in OQ)
OQ_CAP = oq["count_with_the_default_cap"]
assert OQ_CAP["exit_code"] == 3 and OQ_CAP["run"]["trials"] == 20000
assert check == f"{w_rels} of {w_rels} change the answer"
LIVE = SITE_URL + "/"
EXHIBIT = SITE_URL + "/exhibit/two-hub.html"
DECK = SITE_URL + "/deck/"
VIDEO = "https://youtu.be/GYbci7TseJw"
assert VIDEO in readme, "the README names a different demo video"
_vlen = re.search(r"Demo video \((\d+:\d\d)\)", readme)
VIDEO_LEN = f" ({_vlen.group(1)})" if _vlen else ""  # the README's own figure, or none
LISTING = "https://relate.devpost.com/"
assert LISTING in readme
OPENS = "" if REPO_PUBLIC else " (the repository opens at submission)"
OPENS_LINE = "" if REPO_PUBLIC else "The repository opens at submission; until then use the live pages above."

# more committed evidence, each figure bound to its file
_plog = pytest_log.read_text()
_skip = re.search(r"(\d+) skipped", _plog)
assert _skip
SKIPPED = int(_skip.group(1))
_ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text()
N_STAGES = len(set(re.findall(r"# ── STAGE (\d+)", _ci)))
assert N_STAGES >= 4 and "git diff --exit-code -- site JUDGE.md" in _ci and "witness demo" in _ci
_ag = json.loads((ROOT / "evidence" / "mcp-agent-session-witness.manifest.json").read_text())
AG_RELS, AG_CHECK = _ag["witness"]["relationships"], _ag["check"]["check_text"].split(" (")[0]
AG_MODEL = "claude-sonnet-5-5"
_agmd = (ROOT / "evidence" / "mcp-agent-session.md").read_text()
# the recorded session: that model, its answer reports hub counts, so every bound relationship is needed
assert _ag["verified"] and AG_MODEL in _agmd and "hub count" in _agmd and AG_RELS == TA["rels"]
_mcp = json.loads((ROOT / "evidence" / "mcp-transcript.json").read_text())
assert {"why", "check", "read_cypher"} <= {c["tool"] for c in _mcp["calls"]} and "scripted MCP client" in _mcp["what"]
_scan = json.loads((ROOT / "evidence" / "disagree-scan.json").read_text())
_cy = (ROOT / "queries" / "two-hub.cypher").read_text()
assert all(k in _cy for k in ("NOT EXISTS", "OPTIONAL MATCH", "count(DISTINCT hub)")), "the headline query changed"
_per = cmp["protocol"]["trials_per_run"]
assert all(r["answers_identical_per_trial"] == f"{_per}/{_per}" for r in cmp["runs"]) and TA["identical"] == TA["rels"]
assert sum(r["in_witness"] for r in fgn["rows"]) == w_rels, "the witness is not a subset of the bound relationships"
# the committed source store is the one every manifest names
assert hashlib.sha256((ROOT / "data" / "air-routes.rl").read_bytes()).hexdigest() == man["source"]["sha256"]
_proj = (ROOT / "pyproject.toml").read_text()
assert (
    'witness = "witness.cli:main"' in _proj
    and "relate-db==" in _proj
    and (ROOT / "src/witness/mcp_server.py").is_file()
)
_demo_md = (ROOT / "DEMO.md").read_text()
DEMO_SECTIONS = re.findall(r"^## \d+\. (.+)$", _demo_md, re.M)
assert len(DEMO_SECTIONS) == 15 and [s.split(":")[0].split(",")[0] for s in DEMO_SECTIONS] == [
    "Headline",
    "Determinism",
    "Relate vs Neo4j",
    "Fixture mode",
    "MCP tools `why` and `check`",
    "Tests",
    "Two queries disagree",
    "A smaller repro of a wrong answer (`differs`)",
    "What each deletion does",
    "An engine disagreement",
    "Other query shapes",
    "Re-proved on a second engine",
    "One query on two engines",
    "The differential run",
    "Relate in the tab",
], DEMO_SECTIONS
_e2e = re.search(r"\(([\d.]+) s end to end", sp.demo)
assert _e2e
E2E_S, DEMO_MACHINE = _e2e.group(1), sp.DEMO_HEADER.split(" · ")[1]
NEO_V = cmp["neo4j"]["components"][0]["v"]
CMP_MD = f"evidence/{cmp_path.with_suffix('.md').name}"
PYTEST = f"evidence/{pytest_log.name}"
DEMO_TXT = f"evidence/{sp.demo_path.name}"
PLAN_DROP = sp.trace["plan"]["dropped_rels"]
PLAN_TRIAL = sp.MILESTONES[1][0]
APPLIED, ROLLED = sp.HOLDS.count("1"), sp.HOLDS.count("0")
ANSWER = [r["airport"] for r in rows]
# the answer has a second column, the countries of each airport's hubs, and part of the witness exists only for it
_hub_c = sorted({c for r in rows for c in r["hub_countries"]})
assert all(sorted(r["hub_countries"]) == _hub_c for r in rows), "the rows no longer share one hub-country list"
N_ROUTES, N_COUNTRY = len(sp.ROUTES), len(sp.COUNTRY)
N_HUB_LINKS = N_COUNTRY - len(ANSWER)
assert N_ROUTES + N_COUNTRY == w_rels and N_HUB_LINKS > 0
ANSWER_NOTE = (
    f"The answer: {', '.join(ANSWER)}, each with the countries of its hubs ({', '.join(_hub_c)}). Of the {w_rels} "
    f"relationships, {N_ROUTES} are flights and {N_COUNTRY} are country links: {len(ANSWER)} place the answer's airports in "
    f"{man['params']['country']}, {N_HUB_LINKS} give the hub countries."
)
PARAMS_CLI = " ".join(f"--param {k}={v}" for k, v in man["params"].items())
RUN_CMD = ["git clone " + REPO, "cd witness", "uv run witness demo"]
ONE_CMD = " && ".join(RUN_CMD)
# shown on three lines (shell continuations), copied as one
RELATE_CMD = (
    f"relate query --database witnesses/two-hub.rl --read-only \\\n  {PARAMS_CLI} \\\n  < queries/two-hub.cypher"
)
assert RELATE_CMD.replace(" \\\n  ", " ") in readme, "the README's plain-relate command differs"

WHAT = "Witness is a Python CLI and MCP server built on Relate."
BUILT = "Every trial is a Relate transaction, and the witness is one `.rl` file you open with plain `relate`. Built for the Relate by Neo4j hackathon."
PATH30 = [
    (
        "Open the landing page",
        "Open landing",
        LIVE,
        f"the answer, the {w_rels} relationships that reproduce it, and the check line; nothing to install",
    ),
    (
        "Open the exhibit page",
        "Open exhibit",
        EXHIBIT,
        "the register of kept relationships, each tagged as one whose deletion changes the answer",
    ),
]
PATH_CMD_NOTE = "needs uv" + OPENS.replace(" (", "; ").rstrip(")")
PATH_EXPECT = f"Expect `{check}` and exit 0."

# (number as text, number as markup, what it is, what bounds it, [(the file it is recorded in, a note)])
_nb, _to, _u = '<span class="nb">{}</span>', '<span class="to">{}</span>', '<span class="u">{}</span>'
_MAN = "witnesses/two-hub.manifest.json"
RECEIPTS = [
    (
        f"{fmt(src_rels)} → {w_rels}",
        _nb.format(fmt(src_rels)) + _to.format("→") + f"<em>{w_rels}</em>",
        "Relationships in the air-routes graph, then in the witness.",
        f"{fmt(src_nodes)} nodes → {w_nodes} nodes in the witness graph. As files: {fmt(BYTES['data/air-routes.rl'])} bytes → {fmt(BYTES['witnesses/two-hub.rl'])}.",
        [(_MAN, ""), ("evidence/store-bytes.json", "the files")],
    ),
    (
        f"{w_rels} of {w_rels}",
        f"<em>{w_rels}</em>" + _to.format("of") + f"{w_rels}",
        "Deleting any one of them from the witness changes the answer.",
        f"Checked on relate-db and on the Relate CLI: `{check}`.",
        [(_MAN, ""), ("evidence/pull-each-tag.json", "what each deletion does to the answer")],
    ),
    (
        f"{BL['pulls']['same_rows']} of {BL['pulls']['of']} live",
        f"<em>{BL['pulls']['same_rows']}</em>" + _to.format("of") + f"{BL['pulls']['of']}" + _u.format("live"),
        f"The same pulls, run in a browser by Relate {LIVE_PIN} compiled to WebAssembly.",
        f"The landing's pull-a-tag runs `@relate/relate-wasm` {LIVE_PIN}, pinned and served from the site, in a module worker: it rebuilds the witness from `witnesses/two-hub.cypher`, deletes the tag and re-runs the query, where the Python run rolls back a transaction (the browser build has none). In headless {BL_CHROME} (`scripts/browser_live.mjs`) the page showed all {BL['pulls']['of']} pulls live and the same as the recording, both engine releases live with their recorded rows, a write refused and a runaway query stopped after {round(BL['stop']['ms'] / 1000)} s, with no request off the site (each engine's worker reports what it fetched), no failed response and no console error; under Node, `scripts/wasm_parity.mjs` runs the page's own steps (`site/relate/live.js`) on the same engine files and gets the recorded rows on {WASM['pulls']['same_rows']} of {WASM['pulls']['of']} pulls. A query box runs your own Cypher on the witness; a statement that writes runs on a throwaway copy and is refused.",
        [("evidence/browser-live.json", "the browser run"), ("evidence/wasm-parity.json", "under Node"), ("site/relate/engines.json", "the pinned engines")],
    ),
    (
        f"{TA['rels']} → {w_rels}",
        _nb.format(TA["rels"]) + _to.format("→") + f"<em>{w_rels}</em>",
        f"The answer rows match {TA['rels']} relationships; the witness keeps {w_rels} of them.",
        f"Deleted from the full graph one at a time, {TA['relate_changed']} of the {TA['rels']} change the answer and the other {TA['rels'] - TA['relate_changed']} do not, because other routes back them up. Deleted from the witness, each of the {w_rels} changes it.",
        [
            ("evidence/full-graph-necessity.json", ""),
            (CMP_MD, "targeted pass"),
            (_MAN, ""),
            ("queries/two-hub-bindings.cypher", "the matching query"),
        ],
    ),
    (
        f"{sens['change_the_answer']} of {fmt(src_rels)}",
        f"<em>{sens['change_the_answer']}</em>" + _to.format("of") + _nb.format(fmt(src_rels)),
        "What the answer depends on in the full graph, and what a witness leaves out.",
        f"Every relationship of the full graph was deleted alone: {sens['change_the_answer']} change the answer. {sens['supports']} are supports, whose deletion drops or alters an answer row, and all {sens['supports_in_witness']} are in the witness. {sens['guards']} are guards, each the direct flight to {man['params']['dest']} of an airport of {man['params']['country']} that is not in the answer, whose deletion adds that airport as a row. A witness holds what reproduces its rows, not what keeps other rows out.",
        [("evidence/full-graph-sensitivity.json", ""), ("bench/full_graph_sensitivity.py", "re-records it")],
    ),
    (
        f"{fmt(src_rels)} → {EC_RELS}",
        _nb.format(fmt(src_rels)) + _to.format("→") + f"<em>{EC_RELS}</em>",
        "An engine disagreement, observed and shrunk.",
        f"Relate's v{VER_AGREE[0]} release notes list a fix for `EXISTS` and `COUNT` over two `MATCH` clauses. On the pinned {man['versions']['relate_db']} the two ways of writing one condition return {EC_ROWS} and 0 airports of {_ec['params']['country']}; `{EC_CHECK}`. The {EC_RELS}-relationship script separates the releases: the two disagree on relate-db {_and(VER_DISAGREE)} and agree on {VER_AGREE[0]}.",
        [
            ("witnesses/exists-count.manifest.json", ""),
            ("evidence/exists-count-run.txt", "the run"),
            ("evidence/relate-versions.jsonl", "the releases"),
        ],
    ),
    (
        f"{RN_ENTRIES} → {RN_CHANGE} → {RN_SHRUNK}",
        _nb.format(RN_ENTRIES) + _to.format("→") + _nb.format(RN_CHANGE) + _to.format("→") + f"<em>{RN_SHRUNK}</em>",
        "Relate's own release notes, as regression fixtures.",
        f"Every read-path fix entry from v1.0.2 to v1.3.0 ({RN_ENTRIES}) was tried on air-routes against the pinned release: {RN_CHANGE} change an answer, and {RN_SHRUNK} of those fixes shrink with `--other-engine` against the release that fixed them, to {RG_N} witnesses of at most {RG_MAX_RELS} relationships ({sum(1 for r, _ in RG_SIZES if r == 0)} of them hold only one or two nodes: those answers turn on a property or a column name). Rebuilt on {_and(RV_RELEASES)}, each changes its answer exactly at the release its notes name.",
        [
            ("evidence/release-notes-fixes.json", "all the entries"),
            ("evidence/regress-runs.txt", "the runs"),
            ("evidence/regression-releases.jsonl", "the releases"),
        ],
    ),
    (
        f"{DF_Q} queries",
        f"<em>{DF_Q}</em>" + _to.format("queries"),
        "A differential run of agent-written queries.",
        f"{DF_Q} read queries written by an AI agent from the schema before any engine compared them, each run in a transaction that is rolled back. relate-db 1.0.1 against 1.3.0: {DF_SAME} agree, {DF_BOTH_REFUSED} end in an error on both, {DF_BOTH_TIMEOUT} gives no answer within {DF_TIMEOUT_S} s on either, {DF_ONLY_130} answer only on 1.3.0, {DF_DIFF} differs in value type (a float on 1.0.1, an integer on 1.3.0) and shrinks to {DF_RED[0]['nodes']} node." + DF_NEO_TEXT,
        [("evidence/differential.json", ""), ("evidence/differential-answers.jsonl", "the answers per query"), ("queries/differential.jsonl", "the queries")],
    ),
    (
        f"{AS_LAST_OK['ms']:,} ms",
        f"<em>{AS_LAST_OK['ms']:,}</em>" + _to.format("ms"),
        "A slowdown still present on Relate 1.3.0, found by that run.",
        f"`ANY SHORTEST` over `->+` with an inline relationship predicate that every relationship satisfies: {AS_LAST_OK['ms']:,} ms on {AS_LAST_OK['rels']} relationships, no answer within {AS_WATCHDOG} s on {AS_HANG['rels']}; without the predicate, under 1 ms. The same on {AS_OTHER}.",
        [("evidence/any-shortest-inline.jsonl", ""), ("bench/any_shortest_inline.py", "re-records it")],
    ),
    (
        f"{fmt(src_rels)} → {DB_RELS}",
        _nb.format(fmt(src_rels)) + _to.format("→") + f"<em>{DB_RELS}</em>",
        "A query mistake: two queries disagree.",
        f"A plausible agent mistake written for this case (the first flight matched in either direction) and the headline query disagree on {_db['params']['country']}/{_db['params']['dest']}; `{DB_CHECK}`.",
        [("witnesses/direction-bug.manifest.json", "")],
    ),
    (
        f"{fmt(src_rels)} → {WA_RELS}",
        _nb.format(fmt(src_rels)) + _to.format("→") + f"<em>{WA_RELS}</em>",
        "A wrong answer, reproduced smaller (`differs`).",
        f"The same mistaken query returns {WA_ROWS} rows where the expected answer has {WA_EXP}, and the repro holds that wrong answer fixed; `{WA_CHECK}`.",
        [("witnesses/wrong-answer.manifest.json", "")],
    ),
    (
        f"{trials} trials · {secs} s",
        f"{trials}" + _u.format("trials") + _to.format("·") + f"{secs}" + _u.format("s"),
        "Delete, re-run, roll back.",
        f"{COMMITS} deletions kept the answer and were then applied. Trials and deletions repeat exactly; wall-clock seconds do not: the landing's paste reduced in {LANDING_S} s, the video's take in {VIDEO_S} s.",
        [
            (_MAN, "this run"),
            ("evidence/demo-2026-11-24.txt", "the landing's paste"),
            ("evidence/video-demo-run-2026-11-27.txt", "the video's take"),
        ],
    ),
    (
        f"{relate_tps} vs {neo_tps}",
        f"{relate_tps}" + _to.format("vs") + f"{neo_tps}" + _u.format("trials/s"),
        f"Trials per second: Relate in-process, then Neo4j {NEO_V} in Docker.",
        f"The same loop and query on one machine, median of {len(cmp['runs'])} runs, the same answer on every trial. It measures this setup (Docker VM, Bolt round trip), not a limit of Neo4j.",
        [(CMP_MD, "")],
    ),
    (
        " · ".join(str(n) for n in NEO_RE),
        _to.format(" · ").join(f"<em>{n}</em>" for n in NEO_RE),
        f"Re-proved on a second engine: Neo4j {NEO_RE_V}.",
        f"`witness check` runs on two surfaces of Relate, which rules out a mistake in Witness, not one in the engine. Each rebuild script was loaded into an empty Neo4j and every relationship deleted alone in a rolled-back transaction: {NEO_RE[0]} of {NEO_RE[0]}, {NEO_RE[1]} of {NEO_RE[1]} and {NEO_RE[2]} of {NEO_RE[2]}, each verdict the same as Relate's.",
        [("evidence/neo4j-recheck.json", ""), ("bench/neo4j_recheck.py", "re-records it")],
    ),
    (
        f"{TESTS} tests pass · 100% coverage",
        f"{TESTS}" + _u.format("tests") + _to.format("·") + "100%" + _u.format("coverage"),
        "Tests pass against real Relate, under a 100% line and branch coverage gate.",
        f"The graph store, rollback and queries are never mocked. `relate pull` (needs a Neo4j server) is stood in, and a few tests substitute timers, process calls, a failing CLI, a database wrapper that injects engine faults, or one reducer phase to reach rare branches. {SKIPPED} more tests need a local Neo4j in Docker and skip without it.",
        [(PYTEST, "`pytest --cov=witness`"), ("pyproject.toml", "the gate")],
    ),
    (
        "byte-identical",
        "byte-identical",
        f"The same query and seed give a byte-identical rebuild script (`.cypher`) on {len(det['runs'])} runs, and CI re-derives it on Linux.",
        f"A test requires a fresh reduction to write the committed script byte for byte, under Python 3.11 and 3.12 on every push. The `.rl` written from the script is not byte-identical between runs (the same graph and size, {sbytes['rerun']['rl_bytes_that_differ']} bytes differ in the recorded pair), so the hash to pin is the script's.",
        [
            ("evidence/determinism.json", ""),
            ("evidence/store-bytes.json", "the `.rl` comparison"),
            ("tests/test_cli.py", "the test"),
        ],
    ),
]

# the listing's criteria, in the listing's order: where the evidence for each one is (no scores, only places to look)
# each bullet: (a short lead, the sentence, [files])
CRIT_LEDE = f"The [listing]({LISTING})'s five criteria, each with the files and sections that answer it. Nothing below is a score; it is where the evidence is."
CRITERIA = [
    (
        "Creativity",
        [
            (
                "Rollback as the search loop.",
                f"{trials} delete, re-run, roll-back trials take {fmt(src_rels)} relationships down to {w_rels}",
                ["src/witness/reduce.py", "witnesses/two-hub.trace.json"],
            ),
            (
                "Not a path lookup.",
                "The headline question uses aggregation, `NOT EXISTS` and `OPTIONAL MATCH`, and the witness still reproduces its answer",
                ["queries/two-hub.cypher"],
            ),
            (
                "One loop, more than one thing to hold on to.",
                f"An answer ({w_rels} relationships), a disagreement between two queries ({DB_RELS}, and {EC_RELS} for the engine case), or an answer you say is wrong ({WA_RELS}; the same test as the first, applied to a wrong answer)",
                [_MAN, "witnesses/direction-bug.manifest.json", "witnesses/exists-count.manifest.json", "witnesses/wrong-answer.manifest.json"],
            ),
            (
                "What is borrowed is named.",
                "The search is delta debugging (Zeller and Hildebrandt, 2002) and the word witness is from data provenance (Buneman, Khanna and Tan, 2001). What Witness does with them: the thing shrunk is a graph store, the test is a Cypher answer found by search (so `NOT EXISTS` and aggregation are covered), each trial is a Relate transaction, and the result is a `.rl` file",
                ["README.md"],
            ),
        ],
    ),
    (
        "Relate and connected context",
        [
            (
                "Mode: single-file `.rl`.",
                f"The unit of evidence is a file a reviewer opens with plain `relate`: {fmt(BYTES['witnesses/two-hub.rl'])} bytes for the headline witness. Mode, reason and capabilities are in [How it uses Relate](#how-it-uses-relate)",
                ["evidence/store-bytes.json"],
            ),
            (
                "Which relationships matter is measured.",
                f"Each of the {w_rels} is deleted in turn and the query re-run; all {w_rels} change the answer",
                ["evidence/pull-each-tag.json"],
            ),
            (
                "Relate runs in the reader's tab.",
                f"On the landing, Relate {LIVE_PIN} compiled to WebAssembly re-runs each pull, the reader's own read queries and the engine case on two releases; in headless Chrome all {BL['pulls']['of']} pulls ran live and gave the recorded rows",
                ["evidence/browser-live.json", "evidence/wasm-parity.json"],
            ),
            (
                "The graph is persisted in the repository.",
                f"The source, {len(list((ROOT / 'witnesses').glob('*.rl')))} witnesses, a fixture and the ledger of reductions are committed `.rl` stores",
                ["data/air-routes.rl", "witnesses/two-hub.rl", "witness.rl"],
            ),
            (
                "The same verdicts on Neo4j.",
                f"The rebuild scripts load into Neo4j {NEO_RE_V}, where the same single deletions change the answer: {NEO_RE[0]} of {NEO_RE[0]}, {NEO_RE[1]} of {NEO_RE[1]}, {NEO_RE[2]} of {NEO_RE[2]}",
                ["evidence/neo4j-recheck.json"],
            ),
            (
                "Beside Relate's own MCP server.",
                "A scripted client and, separately, a real model answer through `relate serve --mcp`, then call Witness's `why` for the evidence; the scripted client also calls `check`",
                ["evidence/mcp-transcript.md", "evidence/mcp-agent-session.md"],
            ),
        ],
    ),
    (
        "Functionality and completeness",
        [
            (
                "One command, the whole path.",
                "On a fresh clone: copy, guard, order check, reduce, check, then the exhibit page and a ledger row. The commands are in [Verify it yourself](#verify-it-yourself)",
                [],
            ),
            (
                "More than the demo.",
                "`witness why` on any read-only query and any `.rl` (`--store`), `check`, `rerun`, `export`, `review`, fixture mode and an MCP server",
                ["src/witness/cli.py", "src/witness/mcp_server.py"],
            ),
            (
                "Other query shapes.",
                f"A path question (`allShortestPaths`, {fmt(src_rels)} relationships → {OQ[0]['witness']['relationships']}), a top-k with `ORDER BY` + `LIMIT` (→ {OQ[1]['witness']['relationships']}) and an `EXISTS` / `NOT EXISTS` pair (→ {OQ[2]['witness']['relationships']}), each re-run by a test; and one that does not shrink, a count over the whole graph, which stops at the trial cap and says NOT verified",
                ["evidence/other-queries.json", "tests/test_examples.py"],
            ),
            (
                "Tested against real Relate.",
                f"{TESTS} tests pass under a 100% line and branch coverage gate; CI runs {N_STAGES} stages, one of them the built wheel running `witness demo` and plain `relate` re-running the committed witness",
                [PYTEST, ".github/workflows/ci.yml"],
            ),
            (
                "It refuses what it cannot do.",
                "Writes, procedures, clocks and randomness exit 2 with a one-line reason",
                ["src/witness/guard.py", "tests/test_guard.py", "tests/test_errors.py"],
            ),
        ],
    ),
    (
        "Usefulness",
        [
            (
                "Who it is for.",
                f"The developer whose agent answers from a graph and who has to show what an answer rests on before anyone acts on it: a reviewer reads {w_rels} relationships, not {fmt(src_rels)} and not the {TA['rels']} a listing of the matched paths would show. And the developer who has to hand a wrong or surprising answer to someone else as a graph small enough to read",
                [],
            ),
            (
                "A real engine disagreement, shrunk to a repro.",
                f"On Relate {man['versions']['relate_db']} two ways of writing one condition return {EC_ROWS} and 0 rows on the air-routes graph (the v{VER_AGREE[0]} release notes list the fix). Witness hands back the {EC_RELS} relationships that still show it, and that script tells the releases apart: {_and(VER_DISAGREE)} disagree, {VER_AGREE[0]} agrees",
                ["witnesses/exists-count.manifest.json", "evidence/relate-versions.jsonl"],
            ),
            (
                "For the people who maintain the engine, and anyone moving a query between releases.",
                f"`--other-engine` shrinks what makes two engines answer one query differently. Relate's own release notes became {RG_N} regression fixtures of at most {RG_MAX_RELS} relationships, each changing its answer exactly at the release that fixed it, and a differential run of {DF_Q} agent-written queries ({DF_ENGINES}) found a slowdown still present on Relate 1.3.0",
                ["evidence/release-notes-fixes.json", "evidence/regression-releases.jsonl", "evidence/differential.json"],
            ),
            (
                "An agent attached the evidence itself.",
                f"In a recorded session a real model ({AG_MODEL} in Claude Code) wrote its own Cypher, called `why` over MCP and attached the witness of its answer: `{AG_CHECK}`. Its answer also reports hub counts, so all {AG_RELS} relationships the answer rows bind are needed",
                ["evidence/mcp-agent-session.md"],
            ),
            (
                "It shows where a wrong query goes wrong.",
                f"Two versions of the question disagree on {_scan['pairs_differ']} of {_scan['pairs_scanned']} country and busiest-airport pairs; for India and DEL, {DB_RELS} relationships keep them disagreeing, one of them the flight the mistaken query read backwards",
                ["evidence/disagree-scan.json", "witnesses/direction-bug.manifest.json"],
            ),
            (
                "A second use: test fixtures.",
                f"`relate pull` brought {fmt(fix['source']['relationships'])} relationships in from Neo4j once, and Witness kept the {fix['witness']['relationships']} the test needs. The same run, repeated against a Neo4j created from scratch, wrote the same fixture",
                ["fixtures/mex-foreign.manifest.json", "evidence/fixture-run-2026-11-27.txt"],
            ),
        ],
    ),
    (
        "Documentation and reproducibility",
        [
            (
                "The README answers the listing's question.",
                "How Witness uses Relate, which mode, and why",
                ["README.md"],
            ),
            (
                "Commands, not only claims.",
                f"`DEMO.md` gives the command or the recorded run for {len(DEMO_SECTIONS)} sets of numbers: the headline, determinism, the Neo4j comparison, fixture mode (with the commands to create the Neo4j it pulls from), the MCP tools, the tests, the query disagreement, the wrong-answer repro, what each deletion does, the engine disagreement, other query shapes, the Neo4j re-proof, the two-engine door with the changelog fixtures, the differential run, and the live pulls in the browser against the recording",
                [],
            ),
            (
                "The page cannot drift from the evidence.",
                "This page and `JUDGE.md` are written by `scripts/build_site.py` from the committed files; CI rebuilds both and fails on any difference",
                [".github/workflows/ci.yml"],
            ),
            (
                "Shown running.",
                f"The [demo video{VIDEO_LEN}]({VIDEO}) and the [pitch deck]({DECK}). What the stamp does not say is in [Honest limitations](#honest-limitations)",
                [],
            ),
        ],
    ),
]
assert len(CRITERIA) == 5
# the README section the last criterion points at
assert all(x in readme for x in ("### How it uses Relate", "**Mode:**", "**Why this mode:**"))

FACTS = [
    (
        "Mode",
        "Single file (`.rl`). Reductions run on a file-backed scratch copy in a temp dir; the committed source is copied byte for byte, never opened for writing, and its SHA-256 is checked unchanged after every run.",
    ),
    (
        "Why this mode",
        "The unit of evidence is a file. One `.rl` per witness can be committed, handed over and re-run by a reviewer with `relate` alone, with no server. A directory store is many files; `:memory:` disappears when the process ends and cannot be inspected.",
    ),
    (
        "What the graph models",
        f"The air-routes network by Kelvin Lawrence (Apache-2.0): {fmt(src_nodes)} nodes and {fmt(src_rels)} relationships, `(:Airport)-[:HAS_ROUTE]->(:Airport)`, `(:Airport)-[:IN_COUNTRY]->(:Country)` and `(:Airport)-[:ON_CONTINENT]->(:Continent)` (`data/SOURCE.md`).",
    ),
]
CMP_NOTE = f"Same loop and query, one machine, median of {len(cmp['runs'])} runs, identical answers (`{CMP_MD}`). It measures this setup (Docker VM, Bolt round trip), not a limit of Neo4j."
TAPE_CAP = f"**{APPLIED}** deletions kept the answer and were then applied (tall) · the other **{ROLLED}** changed it and stayed rolled back (short) · `witnesses/two-hub.trace.json`"
# what Witness does with each capability in CAPS, the files it lives in, and a token that must be in the first one
CAP_USE = [
    (
        f"One transaction per trial: begin, delete, re-run the query, compare, roll back. {trials} trials in the headline run; the {COMMITS} deletions that kept the answer are then committed on the scratch copy.",
        ["src/witness/store.py"],
        "rollback_transaction",
    ),
    (
        'After Witness\'s own token check, Relate has to report the query as read-only (`query_type` is `"r"`); anything else is refused with exit 2.',
        ["src/witness/guard.py"],
        "query_type",
    ),
    (
        f"Labels and types that neither the query nor its plan names go in one verified step: `:ON_CONTINENT`, {fmt(PLAN_DROP)} relationships, in trial {PLAN_TRIAL}.",
        ["src/witness/reduce.py"],
        "EXPLAIN",
    ),
    (
        "The rerun, ledger-reader and fixture-test paths open their store read-only, so they cannot write.",
        ["src/witness/cli.py", "src/witness/ledger.py", "src/witness/fixture.py"],
        "read_only=True",
    ),
    (
        "The witness, the source and the ledger are each one `.rl` file: commit it, hand it over, open it with plain `relate`.",
        ["src/witness/export.py", "src/witness/ledger.py"],
        ".rl",
    ),
    (
        f"Fixture mode: one pull from Neo4j, then shrink; nothing is pushed back. The committed run pulled {fmt(fix['source']['relationships'])} relationships and kept {fix['witness']['relationships']}.",
        ["src/witness/fixture.py", "fixtures/mex-foreign.report.json"],
        '"pull"',
    ),
    (
        f"A second surface: when the Relate CLI is installed, sufficiency and the necessity probes run again on it, outside the Python API (in the committed run, all {w_rels}). It is the same engine, so it rules out a mistake in Witness, not one in Relate; for that see the Neo4j re-proof in the receipts.",
        ["src/witness/check.py"],
        '"--mode", "json"',
    ),
    (
        "A client answers through Relate's own server, then calls Witness's `why` for the evidence of that answer; `check` re-proves a witness. Recorded twice: a scripted client that calls both, and a real model that calls `why`.",
        ["src/witness/mcp_server.py", "evidence/mcp-transcript.md", "evidence/mcp-agent-session.md"],
        "def why",
    ),
]
assert len(CAP_USE) == len(CAPS)
for (_code, _, _), (_, _files, _tok) in zip(CAPS, CAP_USE, strict=True):
    assert all((ROOT / f).is_file() for f in _files), _files
    assert _tok in (ROOT / _files[0]).read_text(), f"{_code}: {_tok!r} is not in {_files[0]}"
assert (
    "committed on the scratch" in CAP_USE[0][0] and "commit_transaction" in (ROOT / "src/witness/store.py").read_text()
)
_fx = fix["witness"]
STORES = [  # (store, what it is, nodes, relationships): the persisted graphs a judge can open
    ("data/air-routes.rl", "the source graph, never opened for writing", src_nodes, src_rels),
    ("witnesses/two-hub.rl", "the headline witness", w_nodes, w_rels),
    (
        "witnesses/direction-bug.rl",
        "the witness of a disagreement between two queries",
        _db["witness"]["nodes"],
        DB_RELS,
    ),
    ("witnesses/wrong-answer.rl", "the smaller repro of a wrong answer", _wa["witness"]["nodes"], WA_RELS),
    (
        "witnesses/exists-count.rl",
        f"the witness of an engine disagreement (Relate {man['versions']['relate_db']})",
        _ec["witness"]["nodes"],
        EC_RELS,
    ),
    (
        "fixtures/mex-foreign.rl",
        "a test fixture: pulled from Neo4j once, then shrunk",
        _fx["nodes"],
        _fx["relationships"],
    ),
]
assert all((ROOT / s[0]).is_file() for s in STORES) and (ROOT / "witness.rl").is_file()
assert all(s[0] in BYTES for s in STORES) and "witness.rl" in BYTES
# what the committed ledger holds, read from the store itself (it is a graph too)
import relate  # noqa: E402

_led = relate.Database(str(ROOT / "witness.rl"), read_only=True)
try:
    LEDGER_REDUCTIONS = _led.execute("MATCH (r:Reduction)-[:PRODUCED]->(:Witness) RETURN count(r) AS n").data[0]["n"]
    LEDGER_REVIEWS = _led.execute("MATCH (v:Review)-[:ON]->(:Reduction) RETURN count(v) AS n").data[0]["n"]
finally:
    _led.close()
assert LEDGER_REDUCTIONS >= 1
_reviews = "no review recorded yet" if LEDGER_REVIEWS == 0 else f"{LEDGER_REVIEWS} reviewed"
STORES_ALSO = (
    f"Also committed: `witness.rl` ({fmt(BYTES['witness.rl'])} bytes), the ledger, a small graph of its own: "
    f"`(:Reduction)-[:PRODUCED]->(:Witness)`, and `(:Review)-[:ON]->(:Reduction)` when a person accepts or disputes one with "
    f"`witness review`. It holds {LEDGER_REDUCTIONS} reduction, {_reviews}."
)
# the drawing of witnesses/two-hub.rl (site_parts asserts each of these counts against the register)
WIT_CAP = (
    f"`witnesses/two-hub.rl`, drawn: {len(sp.EDGES)} relationships among {len(sp.SCH) + sp.N_COUNTRIES} nodes "
    f"({len(sp.SCH)} airports, {sp.N_COUNTRIES} countries). The {len(sp.ROUTES)} routes carry numbered exhibit tags; the "
    f"{len(sp.COUNTRY)} country links show as country codes: {len(ANSWER)} place the answer's airports in "
    f"{man['params']['country']} and {N_HUB_LINKS} give the hub countries the answer lists. Delete any one and the answer "
    f"changes: [pull a tag yourself]({LIVE}#exhibit)."
)
assert (len(sp.EDGES), len(sp.SCH) + sp.N_COUNTRIES) == (w_rels, w_nodes) and 'id="exhibit"' in page

# (what to do, the command lines, what to expect, a note)
VERIFY = [
    (
        "Run the whole path",
        RUN_CMD,
        f"`{check}`, a last line that starts `VERIFIED`, and exit 0.",
        f"Needs uv. The committed graph is copied, never modified; the output goes to `out/`. The recorded run reports {E2E_S} s end to end on an {DEMO_MACHINE} (`{DEMO_TXT}`). With a `relate` CLI other than v1.0.1 on your PATH the first lines say the CLI cross-check is skipped; the Python checks and the result are the same."
        + OPENS,
    ),
    (
        "Re-prove the committed witness",
        ["uv run witness check witnesses/two-hub.rl"],
        f"`{check}`, then `VERIFIED`, exit 0. Exit 1 would mean not verified.",
        "One fresh copy of the witness per probe; nothing is shared with the reduction.",
    ),
    (
        "Re-run it with plain Relate",
        [RELATE_CMD],
        f"the same {len(ANSWER)} airports the full graph gives: {', '.join(ANSWER)}.",
        "Needs the Relate CLI (checked with v1.0.1 and v1.3.0, `evidence/relate-1.3.0-2026-11-27.txt`). No Witness code runs: the witness is an ordinary `.rl` file.",
    ),
    (
        "Ask it something else",
        [e["command"] for e in OQ],
        _and([f"`{e['check'].split(' (')[0]}`" for e in OQ]) + ", each ending `VERIFIED`, exit 0.",
        f"Three other query shapes on the same graph: a path question ({OQ[0]['question'][0].lower() + OQ[0]['question'][1:].rstrip('?')}), a top-k with `ORDER BY` + `LIMIT` ({OQ[1]['question'][0].lower() + OQ[1]['question'][1:].rstrip('?')}) and an `EXISTS` / `NOT EXISTS` pair ({OQ[2]['question'][0].lower() + OQ[2]['question'][1:].rstrip('?')}). Or bring your own graph: `uv run witness why -f Q.cypher --store YOUR.rl`.",
    ),
    (
        "Run the tests",
        ["uv run pytest --cov=witness"],
        f"{TESTS} passed and 100% line and branch coverage; {SKIPPED} more need a Neo4j server and skip without one.",
        "CI and deterministic replay, not the product path.",
    ),
]
assert "VERIFIED" in sp.demo.splitlines()[-1]
VERIFY_MORE = "More commands, one section per set of numbers: `DEMO.md`. The files behind every figure on this page: `evidence/`, `witnesses/`."
# the sections of this page in order, with what each one holds (every count is a list's own length)
INDEX = [
    ("The receipts", "#the-receipts", f"{len(RECEIPTS)} receipts, each with its file"),
    ("How it uses Relate", "#how-it-uses-relate", f"mode, reason, {len(CAPS)} capabilities"),
    ("Verify it yourself", "#verify-it-yourself", f"{len(VERIFY)} steps, on your machine"),
    ("By criterion", "#by-criterion", f"where to look for each of the {len(CRITERIA)}"),
]
assert "MEX" not in sp.COUNTRY, "MEX now has a country link in the witness: the limitation below names it"
LIMITS = [
    "Verified is about the evidence, not the query: exit 0 says the witness is deletion-minimal for its predicate. It does not say the query asks the right question; the repro of a wrong answer is verified too.",
    f"Supports, not guards: a witness holds what reproduces the rows it has, not what keeps other rows out. In the full graph {sens['guards']} single relationships each keep another airport out of the headline answer, and {sens['guards'] - sens['guards_in_witness']} of them are not in the witness (`evidence/full-graph-sensitivity.json`).",
    "Deletion-minimal, not smallest: no single remaining relationship can be removed without changing the answer; a smaller witness may exist.",
    "Its own answer, on its own file: because a query with `NOT EXISTS` or aggregation is not monotone, a witness does not prove that every graph containing it gives the same answer. It also leaves out true facts the answer does not need: MEX has no country link in `witnesses/two-hub.rl`.",
    "Read-only Cypher only, with no clock or randomness: Witness refuses writes, procedures, clocks and randomness (exit 2) rather than guess. Dependence on storage order is caught by a heuristic (the same answer from a store built in reverse order), not proven absent.",
    f"Answers that rest on thousands of facts do not shrink: a count over the whole graph ran to the default cap of {fmt(OQ_CAP['run']['trials'])} trials ({round(OQ_CAP['run']['seconds'] / 60)} minutes here) and exited 3, NOT verified, with {fmt(OQ_CAP['witness']['relationships'])} relationships left (`evidence/other-queries.json`).",
    f"One graph (a public air-routes dataset, Apache-2.0): the headline query, three more cases and three more query shapes. The one mistaken query was written for the case; the engine disagreement is observed, and only on Relate {_and(VER_DISAGREE)}. The Neo4j comparison is one machine, one query, one graph; it measures this setup (Docker VM, Bolt round trip), not a limit of Neo4j.",
]
DECK_SLIDES = (SITE / "deck" / "index.html").read_text().count('<div class="pfoot">')  # the deck written just above
assert DECK_SLIDES == 10
LINKS = [  # (label, url, what is there)
    ("Repository", REPO + OPENS, "the source, the evidence and the commit history"),
    ("Live site", LIVE, "the landing: replay the reduction, pull a tag yourself"),
    ("Demo video", VIDEO, f"watch it run{VIDEO_LEN}"),
    ("Pitch deck", DECK, f"{DECK_SLIDES} slides, every number read from the same files"),
    ("Exhibit page", EXHIBIT, "the page Witness writes beside every witness"),
    ("README", f"{REPO}/blob/main/README.md", "how it uses Relate, and why"),
    ("DEMO.md", f"{REPO}/blob/main/DEMO.md", "the commands behind the numbers, section by section"),
    ("JUDGE.md", f"{REPO}/blob/main/JUDGE.md", "this page as Markdown, in the repository"),
    ("Relate", "https://relatedb.ai", "the embedded graph database it is built on"),
]


def repo_path(tok: str) -> bool:
    """True when a backticked token is a file or directory of this repository (never the ignored out/ or dist/)."""
    if not re.fullmatch(r"[\w./-]+", tok) or ("/" not in tok and "." not in tok.strip(".")):
        return False
    return not tok.startswith(("out/", "dist/", "/", "..")) and (ROOT / tok).exists()


def _spans(t: str) -> list[str]:
    parts = t.split("`")
    assert len(parts) % 2 == 1, f"unbalanced backticks: {t}"
    return parts


def md_inline(t: str) -> str:
    """JUDGE.md: a committed path becomes a relative link, so it opens from the repository page."""
    return "".join(p if i % 2 == 0 else f"[`{p}`]({p})" if repo_path(p) else f"`{p}`" for i, p in enumerate(_spans(t)))


def _local(u: str) -> str:
    """Pages of this site are linked relative, so the page works on any host that serves site/."""
    return (u[len(SITE_URL) :] or "/") if u.startswith(SITE_URL) else u


def chip(p: str) -> str:
    """A committed path as a link to that file on GitHub. It may wrap after a slash, never inside a name."""
    assert repo_path(p), f"not a path of this repository: {p}"
    segs = "<wbr>".join(f'<span class="sg">{html.escape(s, quote=False)}</span>' for s in re.findall(r"[^/]+/?", p))
    if not REPO_PUBLIC:
        return f"<code>{segs}</code>"
    kind = "tree" if (ROOT / p).is_dir() else "blob"
    return f'<a class="src" href="{REPO}/{kind}/main/{p.rstrip("/")}"><code>{segs}</code></a>'


def inline(t: str) -> str:
    """/judge: `code`, **bold**, [text](url); a committed path links to that file on GitHub."""
    out = []
    for i, p in enumerate(_spans(t)):
        e = html.escape(p, quote=False)
        if i % 2:
            out.append(chip(p) if repo_path(p) else f"<code>{e}</code>")
        else:
            e = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", lambda m: f'<a href="{_local(m.group(2))}">{m.group(1)}</a>', e)
            out.append(re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", e))
    return "".join(out)


def md_srcs(srcs: list[tuple[str, str]]) -> str:
    return ", ".join(md_inline(f"`{p}`") + (f" ({md_inline(n)})" if n else "") for p, n in srcs)


def html_srcs(srcs: list[tuple[str, str]]) -> str:
    return "".join(f"<span>{chip(p)}{f'<i>{inline(n)}</i>' if n else ''}</span>" for p, n in srcs)


md = [
    "# For judges",
    "",
    f"**The claim.** {CLAIM}",
    "",
    f"{WHAT} {BUILT}",
    "",
    "## The 30-second path",
    "",
]
md += [f"{i}. [{t}]({u}): {d}." for i, (t, _, u, d) in enumerate(PATH30, 1)]
md += [
    f"{len(PATH30) + 1}. Optional, one command: `{ONE_CMD}` ({PATH_CMD_NOTE}). {PATH_EXPECT}",
    "",
    f"Prefer to watch? [Demo video{VIDEO_LEN}]({VIDEO}) · [pitch deck]({DECK})",
    "",
    "## The receipts",
    "",
    "| Number | What it is | Recorded in |",
    "|---|---|---|",
]
md += [
    f"| **{a}** | **{md_inline(lead)}**{' ' + md_inline(rest) if rest else ''} | {md_srcs(srcs)} |"
    for a, _, lead, rest, srcs in RECEIPTS
]
md += ["", "## How it uses Relate", "", *[f"- **{k}:** {md_inline(v)}" for k, v in FACTS], ""]
md += [
    "One trial is `begin_transaction`, delete, re-run the query, compare the answer, `rollback_transaction`. "
    + md_inline(
        f"In the headline run {APPLIED} deletions kept the answer and were then applied; the other {ROLLED} changed it and stayed rolled back (`witnesses/two-hub.trace.json`). "
        f"Relate in-process ran {relate_tps} trials/s, Neo4j {NEO_V} in Docker {neo_tps}. {CMP_NOTE}"
    ),
    "",
    f"The {len(CAPS)} Relate capabilities it uses:",
    "",
    "| | Relate capability | What Witness does with it | In the source |",
    "|---|---|---|---|",
]
md += [
    f"| {i} | `{code}` | {md_inline(use)} | {', '.join(md_inline(f'`{f}`') for f in files)} |"
    for i, ((code, _, _), (use, files, _)) in enumerate(zip(CAPS, CAP_USE, strict=True), 1)
]
md += [
    "",
    "The graph is persisted. Stores committed in this repository:",
    "",
    "| Store | What it is | Nodes | Relationships | Bytes |",
    "|---|---|---|---|---|",
]
md += [f"| {md_inline(f'`{p}`')} | {what} | {fmt(n)} | {fmt(r)} | {fmt(BYTES[p])} |" for p, what, n, r in STORES]
md += ["", md_inline(STORES_ALSO), "", f"The question: {QUESTION} {ANSWER_NOTE}", ""]
md += ["## Verify it yourself", ""]
for i, (t, lines, expect, note) in enumerate(VERIFY, 1):
    md += [f"{i}. **{t}.** {md_inline(note)}", "", "   ```bash"]
    md += [*[f"   {x}".replace("\n", "\n   ") for x in lines], "   ```", "", f"   Expect {md_inline(expect)}", ""]
md += [
    *([OPENS_LINE, ""] if OPENS_LINE else []),
    md_inline(VERIFY_MORE),
    "",
    "## By criterion",
    "",
    md_inline(CRIT_LEDE),
]
for name, bullets in CRITERIA:
    md += ["", f"### {name}", ""]
    md += [
        f"- **{md_inline(lead)}** {md_inline(text)}" + (f" ({md_srcs([(f, '') for f in files])})." if files else ".")
        for lead, text, files in bullets
    ]
md += ["", "## Honest limitations", ""]
md += [f"- {md_inline(x)}" for x in LIMITS]
md += ["", "## Links", ""] + [f"- {a}: {b} · {c}" for a, b, c in LINKS] + [""]
(ROOT / "JUDGE.md").write_text("\n".join(md))

_EXT = '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M5 11l6-6M6.5 5H11v4.5" fill="none" stroke="currentColor" stroke-width="1.6"/></svg>'
_GO = '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M3 8h9M8.5 4.5L12 8l-3.5 3.5" fill="none" stroke="currentColor" stroke-width="1.6"/></svg>'


def _cmd_tokens(line: str) -> str:
    """A command line for display: flags never break at their hyphens, a long URL may break after a slash."""
    out = []
    for tok in re.split(r"( +|\n)", line):
        e = html.escape(tok, quote=False)
        if "/" in tok and len(tok) > 30:
            out.append(re.sub(r"/(?=[^/])", "/<wbr>", e))
        elif "-" in tok or "=" in tok or "/" in tok:
            out.append(f'<span class="nw">{e}</span>')
        else:
            out.append(e)
    return "".join(out)


def cmd_block(lines: list[str], what: str) -> str:
    """Each line is one command; a line may carry a shell continuation (backslash + newline) for display only."""
    code = "".join(f'<span class="cl">{_cmd_tokens(x)}</span>' for x in lines)
    one = " && ".join(re.sub(r" \\\n +", " ", x) for x in lines)
    tall = sum(1 + x.count("\n") for x in lines) > 2
    return (
        f'<div class="cmd{" tall" if tall else ""}"><code>{code}</code><button type="button" class="copy" '
        f'data-copy="{html.escape(one)}" aria-label="Copy the command: {html.escape(what)}">copy</button></div>'
    )


def judge_term() -> str:
    """Lines of the recorded `witness demo` run: whole blocks in their order, text untouched; every gap is marked."""
    lines = sp.demo.splitlines()[1:]

    def block(word: str) -> list[int]:
        i = next(k for k, ln in enumerate(lines) if ln.startswith(word))
        j = i
        while j < len(lines) and lines[j].strip():
            j += 1
        return list(range(i, j))

    keep = [*block("Witness "), *block("QUESTION"), *block("ANSWER"), *block("WITNESS"), *block("EXHIBITS")[:4]]
    keep += [*block("CHECK"), *block("PROVE ONE"), *block("VERIFIED")]
    assert keep == sorted(keep) and keep[0] == 0
    out, prev = [], -1
    for k in keep:
        skipped = [ln for ln in lines[prev + 1 : k] if ln.strip()]
        if skipped:
            out.append(f'<span class="ln cut">  ⋮ {len(skipped)} lines not shown here</span>')
        if k - prev > 1:
            out.append('<span class="ln"> </span>')
        out.append(sp.term_line(lines[k]))
        prev = k
    assert prev == len(lines) - 1, "the transcript no longer ends on the VERIFIED line"
    return "".join(out)


def judge_page() -> str:
    og = hashlib.sha256((ROOT / "docs" / "assets" / "og-image-1200.png").read_bytes()).hexdigest()[:10]
    path = [
        f'<li><span class="st-no" aria-hidden="true">{i}</span><div class="st"><h3>{html.escape(t)}</h3>'
        f'<p>{inline(d[0].upper() + d[1:])}.</p></div><a class="btn st-go{" solid" if i == 1 else ""}" href="{_local(u)}">'
        f"{html.escape(b)}{_GO}</a></li>"
        for i, (t, b, u, d) in enumerate(PATH30, 1)
    ]
    path.append(
        f'<li class="run"><span class="st-no" aria-hidden="true">{len(PATH30) + 1}</span><div class="st">'
        f"<h3>Run one command <small>optional · {html.escape(PATH_CMD_NOTE)}</small></h3>"
        f'{cmd_block(RUN_CMD, "clone the repository and run the demo")}<p class="exp">{inline(PATH_EXPECT)}</p></div></li>'
    )
    ctas = [
        (
            f'<a class="btn" href="{REPO}"><svg viewBox="0 0 20 20" aria-hidden="true"><path d="M7 5L2 10l5 5M13 5l5 5-5 5" fill="none" stroke="currentColor" stroke-width="1.8"/></svg>Source on GitHub</a>'
            if REPO_PUBLIC
            else '<span class="src-pending">Source on GitHub opens at submission</span>'
        ),
        f'<a class="btn" href="{VIDEO}"><svg viewBox="0 0 20 20" aria-hidden="true"><path d="M3 4h14v12H3z" fill="none" stroke="currentColor" stroke-width="1.6"/><path d="M8.5 7.5v5l4.5-2.5z" fill="currentColor"/></svg>Demo video{VIDEO_LEN}</a>',
        '<a class="btn" href="/deck/"><svg viewBox="0 0 20 20" aria-hidden="true"><path d="M3 4h14v10H3zM7 17h6M10 14v3" fill="none" stroke="currentColor" stroke-width="1.6"/></svg>Pitch deck</a>',
    ]
    receipts = [
        f'<tr role="row"><td role="cell" class="no">{i}</td>'
        f'<td role="cell" class="num{" word" if num == label else ""}"><span class="sr">{html.escape(label)}</span><span aria-hidden="true">{num}</span></td>'
        f'<td role="cell" class="what"><b>{inline(lead)}</b>{f"<span>{inline(rest)}</span>" if rest else ""}'
        f'<p class="rec"><span class="lbl">Recorded in</span>{html_srcs(srcs)}</p></td></tr>'
        for i, (label, num, lead, rest, srcs) in enumerate(RECEIPTS, 1)
    ]
    criteria = [
        f'<li><div><span class="crit-k">Criterion {i} of {len(CRITERIA)}</span><h3>{html.escape(name)}</h3></div><ul>'
        + "".join(
            f"<li><b>{inline(lead)}</b> {inline(text)}."
            + (f'<span class="rec">{html_srcs([(f, "") for f in files])}</span>' if files else "")
            + "</li>"
            for lead, text, files in bullets
        )
        + "</ul></li>"
        for i, (name, bullets) in enumerate(CRITERIA, 1)
    ]
    caps = [
        f'<tr role="row"><td role="cell" class="no">{i}</td><td role="cell" class="cap"><code>{html.escape(code)}</code></td>'
        f'<td role="cell" class="use">{inline(use)}</td>'
        f'<td role="cell" class="where">{" ".join(chip(f) for f in files)}</td></tr>'
        for i, ((code, _, _), (use, files, _)) in enumerate(zip(CAPS, CAP_USE, strict=True), 1)
    ]
    stores = [
        f'<tr role="row"><td role="cell" class="path">{chip(p)}</td><td role="cell" class="role">{html.escape(what[0].upper() + what[1:])} · {fmt(BYTES[p])} bytes</td>'
        f'<td role="cell" class="n" data-l="nodes">{fmt(n)}</td><td role="cell" class="n" data-l="relationships">{fmt(r)}</td></tr>'
        for p, what, n, r in STORES
    ]
    verify = [
        f'<li><span class="st-no" aria-hidden="true">{i}</span><div class="st"><h3>{html.escape(t)}</h3>'
        f'{cmd_block(lines, t.lower())}<p class="exp"><span class="lbl">Expect</span>{inline(expect)}</p>'
        f'<p class="note">{inline(note)}</p></div></li>'
        for i, (t, lines, expect, note) in enumerate(VERIFY, 1)
    ]
    limits = []
    for i, x in enumerate(LIMITS, 1):
        lead, rest = x.split(": ", 1)
        limits.append(
            f'<li><span class="ln-no" aria-hidden="true">{i}</span><div><h3>{html.escape(lead)}</h3>'
            f"<p>{inline(rest[0].upper() + rest[1:])}</p></div></li>"
        )
    tiles = [
        f'<li><a class="tile" href="{_local(u.split(" ")[0])}"><b>{html.escape(a)}{_EXT}</b>'
        f'<span class="t-note">{html.escape(c[0].upper() + c[1:])}</span><span class="t-url">{html.escape(_shown(u))}</span></a></li>'
        for a, u, c in LINKS
    ]
    vals = {
        "CLAIM_ATTR": html.escape(CLAIM),
        "DESC_OG": html.escape(DESC_OG),
        "SITE": SITE_URL,
        "OGV": og,
        "CSS": (PARTS / "witness.css").read_text(),
        "JUDGE_CSS": (PARTS / "judge.css").read_text(),
        "NAV_SRC": f'<a class="chip" href="{REPO}">source</a>' if REPO_PUBLIC else "",
        "SRC_RELS": fmt(src_rels),
        "W_RELS": w_rels,
        "CHECK": html.escape(check),
        "WHAT": html.escape(WHAT),
        "CLAIM_HERO": html.escape(CLAIM_HERO, quote=False),
        "BUILT": inline(BUILT),
        "HERO_CTAS": "\n        ".join(ctas),
        "PATH": "\n          ".join(path),
        "PATH_MORE": f'<span>Prefer to watch it run?</span><a href="{VIDEO}">Demo video{VIDEO_LEN}{_EXT}</a>'
        + (f"<span>{OPENS_LINE}</span>" if OPENS_LINE else ""),
        "INDEX": "\n          ".join(
            f'<li><a href="{u}"><b>{html.escape(t)}</b><span>{html.escape(d)}</span></a></li>' for t, u, d in INDEX
        ),
        "RECEIPTS": "\n          ".join(receipts),
        "SRC_NOTE": inline(
            f"Relate {man['versions']['relate_db']} · Python {man['versions']['python']} · every linked path is a file in the repository, and `scripts/build_site.py` writes this page from them."
        ),
        "CRIT_LEDE": inline(CRIT_LEDE),
        "CRITERIA": "\n      ".join(criteria),
        "FACTS": "\n        ".join(f"<dt>{html.escape(k)}</dt><dd>{inline(v)}</dd>" for k, v in FACTS),
        "TRIALS": trials,
        "TAPE": sp.tape_svg(),
        "TAPE_CAP": inline(TAPE_CAP),
        "RELATE_TPS": relate_tps,
        "NEO_TPS": neo_tps,
        "NEO_V": NEO_V,
        "NEO_W": round(100 * neo_tps / relate_tps, 1),
        "CMP_NOTE": inline(CMP_NOTE),
        "CAPS_H": f"{len(CAPS)} Relate capabilities, each with its place in the source",
        "CAPS": "\n          ".join(caps),
        "STORES_H": "The graph is persisted: the stores in the repository",
        "STORES": "\n              ".join(stores),
        "STORES_ALSO": inline(STORES_ALSO),
        "QUESTION": html.escape(QUESTION),
        "ANSWER": " ".join(f"<b>{html.escape(a)}</b>" for a in ANSWER)
        + f" · each with its hubs' countries: {html.escape(', '.join(_hub_c))}",
        "WIT_SVG": sp.schematic("j", ghost=False),
        "WIT_CAP": inline(WIT_CAP),
        "VERIFY": "\n        ".join(verify),
        "TERM": judge_term(),
        "DEMO_UTC": sp.DEMO_HEADER.split(" · ")[0].replace("recorded ", "").replace("T", " ").replace("Z", " UTC"),
        "DEMO_SRC": inline(f"`{DEMO_TXT}`"),
        "VERIFY_MORE": inline(VERIFY_MORE),
        "LIMITS": "\n      ".join(limits),
        "LINKS": "\n      ".join(tiles),
        "SOURCE_FOOT": f'<a href="{REPO}">source</a>' if REPO_PUBLIC else "source opens at submission",
        "JS": (PARTS / "judge.js").read_text(),
    }
    return fill((PARTS / "judge.html").read_text(), vals)


def _shown(u: str) -> str:
    """A link tile's printed address: a file of the repository reads as repository · file."""
    blob = REPO + "/blob/main/"
    return f"{REPO.split('github.com/')[1]} · {u[len(blob) :]}" if u.startswith(blob) else u.split("://")[1].rstrip("/")


(SITE / "judge").mkdir(exist_ok=True)
judge = judge_page()
(SITE / "judge" / "index.html").write_text(judge)
print(
    f"site/index.html {len(page):,} bytes; site/judge/index.html {len(judge):,} bytes; witness {w_rels} of {src_rels}; compare {cmp_path.name}"
)
