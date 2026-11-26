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
# Absolute base for og:image. Switch to https://witness.edycu.dev once its DNS record resolves (HUMAN-TODO #3).
SITE_URL = "https://witness-wheat.vercel.app"
# Set True when the repository is public (HUMAN-TODO: the flip at submission), then rebuild and redeploy.
REPO_PUBLIC = False
VERSION = re.search(r'^version = "([^"]+)"', (ROOT / "pyproject.toml").read_text(), re.M).group(1)
RELEASES = f"{REPO}/releases/latest"
RELEASES_API = "https://api.github.com/repos/" + REPO.split("github.com/")[1] + "/releases/latest"
pytest_log = sorted((ROOT / "evidence").glob("pytest-*.txt"))[-1]
TESTS = int(re.search(r"(\d+) passed", pytest_log.read_text()).group(1))

man = json.loads((ROOT / "witnesses" / "two-hub.manifest.json").read_text())
cmp_path = sorted((ROOT / "evidence").glob("neo4j-compare-*.json"))[-1]
cmp = json.loads(cmp_path.read_text())
# full-graph necessity of the 68 bound relationships (a2a judge r5/r6): how many change the answer there, how many of those
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
check = man["check"]["check_text"].split(" (")[0]
rows = man["baseline"]["rows"]
relate_tps = cmp["median_trials_per_s"]["relate_in_process"]
neo_tps = cmp["median_trials_per_s"]["neo4j_docker"]
ratio = cmp["ratio_trials_per_s"]

fmt = lambda n: f"{n:,}"  # noqa: E731
CLAIM = (
    f"When an agent answers from a graph, Witness hands back a small graph that reproduces the answer "
    f"({fmt(src_rels)} relationships → {w_rels}), and proves that deleting any one of its relationships changes the answer."
)


sys.path.insert(0, str(Path(__file__).resolve().parent))
import site_parts as sp  # noqa: E402

PARTS = Path(__file__).resolve().parent / "site"
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
        "README · The Solution",
    ),
    (
        "Because a query with `NOT EXISTS` or aggregation is not monotone, a witness proves its own\nanswer on its own file; it does not prove that every superset of it gives the same answer.",
        "README · The Solution",
    ),
    (
        "The gap mostly reflects an embedded engine versus a Dockerised server with a network round trip per statement; it says nothing about Neo4j's query engine.",
        "README · Measured against Neo4j",
    ),
]
for q, _ in QUOTES:
    assert q in readme.replace("**", ""), f"quote not verbatim in README: {q[:50]}"
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
    """Exhibits B and C on the landing (a2a judge r6): the disagree and differs receipts, every number read from the
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
    # the scan and the disagree receipt are about the same two queries and the same pair (a2a arch r7)
    q = {(ROOT / p).read_text().strip() for p in scan["queries"]}
    assert q == {db["statement"].strip(), db["predicate"]["other_statement"].strip()}, "scan queries != receipt queries"
    pair = (db["params"]["country"], db["params"]["dest"])
    assert pair in {(d["country"], d["dest"]) for d in scan["differ"]}, pair
    return {
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


DESC = f"When an agent answers from a graph, Witness hands back {w_rels} of its {fmt(src_rels)} relationships that reproduce the answer, and proves deleting any one of them changes it."
DESC_OG = f"{fmt(src_rels)} relationships → {w_rels} that reproduce an agent's answer. Delete any one of the {w_rels} and it changes."
assert 50 <= len(DESC) <= 160 and len(DESC_OG) <= 125, (len(DESC), len(DESC_OG))


def landing_page() -> str:
    shot_w, shot_h = png_size(SITE / "media" / "exhibit-page.png")
    og = hashlib.sha256((ROOT / "docs" / "assets" / "og-image-1200.png").read_bytes()).hexdigest()[:10]
    question = (
        man["statement"]
        .splitlines()[0]
        .lstrip("/ ")
        .replace("$country", man["params"]["country"])
        .replace("$dest", man["params"]["dest"])
    )
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
        "DATA": sp.page_json(),
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
    ("relate query --mode json", "independent re-check", "relate query --mode json"),
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
page = landing_page()
(SITE / "index.html").write_text(page)
(SITE / "deck").mkdir(exist_ok=True)
(SITE / "deck" / "index.html").write_text(deck_page())
# favicon + social card: the judge-facing media from docs/assets (synced from the asset pipeline)
shutil.copyfile(ROOT / "docs" / "assets" / "icon.svg", SITE / "icon.svg")
# the social card at its exact 1x size (1200x630, under 1 MB); docs/assets/og-image.png is the @2x master
shutil.copyfile(ROOT / "docs" / "assets" / "og-image-1200.png", SITE / "og-image.png")

# ── /judge and JUDGE.md: one reader, one page, every number read from the committed files ───────────────────────────
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
LIVE = SITE_URL + "/"
EXHIBIT = SITE_URL + "/exhibit/two-hub.html"
OPENS = "" if REPO_PUBLIC else " (the repository opens at submission)"
OPENS_LINE = "" if REPO_PUBLIC else "The repository opens at submission; until then use the live pages above."
PATH30 = [
    (
        "Open the landing page",
        LIVE,
        f"the agent's answer, the {w_rels} relationships that reproduce it, and the check line; nothing to install",
    ),
    (
        "Open the exhibit page",
        EXHIBIT,
        "the register of kept relationships, each tagged as one whose deletion changes the answer",
    ),
    (
        "Optional, one command",
        None,
        "`git clone "
        + REPO
        + " && cd witness && uv run witness demo` (needs uv"
        + OPENS.replace(" (", "; ").rstrip(")")
        + ")",
    ),
]
RECEIPTS = [
    (
        f"{fmt(src_rels)} → {w_rels}",
        f"relationships in the air-routes graph vs in the witness ({fmt(src_nodes)} nodes → {w_nodes} nodes in the witness graph; `witnesses/two-hub.manifest.json`)",
    ),
    (
        f"{w_rels} of {w_rels}",
        f"deleting any one of them from the witness changes the answer; checked on relate-db and on the Relate CLI (`{check}`)",
    ),
    (
        f"{TA['rels']} → {w_rels}",
        f"the answer rows bind {TA['rels']} relationships (`queries/two-hub-bindings.cypher`); deleted from the full graph, only {TA['relate_changed']} of them change the answer, because other routes back the rest up (`evidence/{cmp_path.with_suffix('.md').name}`, targeted pass). {FGN_IN} of those {TA['relate_changed']} are in the witness; the other {FGN_OUT} are flights of Mexican airports outside it, whose deletion adds that airport to the answer (`evidence/full-graph-necessity.json`). The witness keeps {w_rels}, each needed in the witness (`witnesses/two-hub.manifest.json`)",
    ),
    (
        f"{fmt(src_rels)} → {DB_RELS}",
        f"a second case: a plausible agent mistake written for this case (the first flight matched in either direction) and the headline query disagree on {_db['params']['country']}/{_db['params']['dest']}; `{DB_CHECK}` (`witnesses/direction-bug.manifest.json`)",
    ),
    (
        f"{fmt(src_rels)} → {WA_RELS}",
        f"a third: `differs`, a smaller repro of a wrong answer; the same mistaken query returns {WA_ROWS} rows where the expected answer has {WA_EXP}, and the repro keeps that wrong answer; `{WA_CHECK}` (`witnesses/wrong-answer.manifest.json`)",
    ),
    (
        f"{trials} trials · {secs} s",
        f"delete, re-run, roll back; {COMMITS} deletions kept the answer and were applied (`witnesses/two-hub.manifest.json`)",
    ),
    (
        f"{relate_tps} vs {neo_tps}",
        f"trials per second, Relate in-process vs Neo4j {cmp['neo4j']['components'][0]['v']} in Docker, median of 3 runs on one machine (`evidence/{cmp_path.with_suffix('.md').name}`)",
    ),
    (
        f"{TESTS} tests pass · 100% coverage",
        f"real Relate; the graph store, rollback and queries are never mocked. `relate pull` (needs a Neo4j server) is stood in, and a few tests substitute timers, process calls, a failing CLI, a database wrapper that injects engine faults, or one reducer phase to reach rare branches (`evidence/{pytest_log.name}`, `pytest --cov=witness`, gate in `pyproject.toml`)",
    ),
    (
        "byte-identical",
        f"the same query and seed give a byte-identical rebuild script (`.cypher`) on {len(det['runs'])} runs (`evidence/determinism.json`)",
    ),
]
REPRO = [
    "git clone " + REPO + " && cd witness",
    "uv run witness demo",
]
REPLAY = "The whole suite against real Relate (CI and deterministic replay, not the product path): `uv run pytest --cov=witness`"
LIMITS = [
    "Deletion-minimal, not smallest: no single remaining relationship can be removed without changing the answer; a smaller witness may exist.",
    "Read-only, deterministic Cypher only. Witness refuses writes, procedures, clocks and randomness (exit 2) rather than guess.",
    "One graph (a public air-routes dataset, Apache-2.0): the headline query, one disagreement case and one wrong-answer repro. The Neo4j comparison is one machine, one query, one graph; it measures this setup (Docker VM, Bolt round trip), not a limit of Neo4j.",
]
LINKS = [
    ("Repository", REPO + OPENS),
    ("Live site", LIVE),
    ("Exhibit page", EXHIBIT),
    ("Relate", "https://relatedb.ai"),
]

md = [
    "# For judges",
    "",
    f"**The claim.** {CLAIM}",
    "",
    "Witness is built on Relate, the embedded graph database, for the Relate by Neo4j hackathon.",
    "",
    "## The 30-second path",
    "",
]
for i, (t, u, d) in enumerate(PATH30, 1):
    md.append(f"{i}. {f'[{t}]({u})' if u else t}: {d}.")
md += ["", "## The receipts", "", "| Number | What it is |", "|---|---|"]
md += [f"| **{a}** | {b} |" for a, b in RECEIPTS]
md += [
    "",
    "## Reproduce it",
    "",
    "```bash",
    *REPRO,
    "```",
    "",
    *([OPENS_LINE, ""] if OPENS_LINE else []),
    f"{REPLAY}",
    "",
    "## Honest limitations",
    "",
]
md += [f"- {x}" for x in LIMITS]
md += ["", "## Links", ""] + [f"- {a}: {b}" for a, b in LINKS] + [""]
(ROOT / "JUDGE.md").write_text("\n".join(md))


def inline(t):
    return re.sub(r"`([^`]+)`", r"<code>\1</code>", html.escape(t, quote=False))


JUDGE_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>For judges · Witness</title>
<meta name="description" content="{claim_attr}">
<link rel="icon" href="/icon.svg" type="image/svg+xml">
<link href="https://fonts.googleapis.com/css2?family=Fragment+Mono&family=Old+Standard+TT:wght@400;700&family=Source+Sans+3:wght@400;600&display=swap" rel="stylesheet">
<style>
:root{{--paper:#F2E8D5;--ink:#1F1A14;--muted:#6F6555;--after:#B42318;--rule:#D9CBAE}}
body{{margin:0;background:var(--paper);color:var(--ink);font:18px/1.55 "Source Sans 3",Arial,sans-serif;overflow-wrap:anywhere}}html{{overflow-x:clip}}
main{{max-width:760px;margin:0 auto;padding:40px 20px 72px}}
h1{{font:700 34px/1.15 "Old Standard TT",Georgia,serif;margin:.2em 0 .5em}}
h2{{font:600 13px/1.4 "Source Sans 3",sans-serif;letter-spacing:.14em;text-transform:uppercase;color:var(--muted);margin:40px 0 10px}}
a{{color:var(--ink);text-underline-offset:3px}}a:hover{{color:var(--after)}}a:focus-visible{{outline:3px solid var(--ink);outline-offset:3px}}
code,pre{{font-family:"Fragment Mono",Menlo,monospace;font-size:.88em}}pre{{background:rgba(31,26,20,.07);padding:14px;overflow-x:auto}}
table{{border-collapse:collapse;width:100%}}td{{border-top:1px solid var(--rule);padding:10px 8px 10px 0;vertical-align:top}}td:first-child{{font:400 17px "Fragment Mono",monospace;white-space:nowrap;padding-right:18px}}
.claim{{font-size:21px}}@media (max-width:600px){{td:first-child{{white-space:normal}}}}
</style></head><body><main>
<p><a href="/">&larr; Witness</a></p>
<h1>For judges</h1>
<p class="claim" id="claim">{claim}</p>
<p>Witness is built on Relate, the embedded graph database, for the Relate by Neo4j hackathon.</p>
<h2>The 30-second path</h2><ol>{path}</ol>
<h2>The receipts</h2><table>{receipts}</table>
<h2>Reproduce it</h2><pre>{repro}</pre>{opens_line}<p>{replay}</p>
<h2>Honest limitations</h2><ul>{limits}</ul>
<h2>Links</h2><ul>{links}</ul>
</main></body></html>
"""


def _link(u):
    return f'<a href="{u.split(" ")[0]}">{html.escape(u)}</a>' if u.startswith("http") else html.escape(u)


(SITE / "judge").mkdir(exist_ok=True)
(SITE / "judge" / "index.html").write_text(
    JUDGE_PAGE.format(
        claim=html.escape(CLAIM, quote=False),
        claim_attr=html.escape(CLAIM),
        path="".join(
            "<li>" + (f'<a href="{u}">{html.escape(t)}</a>' if u else html.escape(t)) + f": {inline(d)}.</li>"
            for t, u, d in PATH30
        ),
        receipts="".join(f"<tr><td>{html.escape(a)}</td><td>{inline(b)}</td></tr>" for a, b in RECEIPTS),
        repro=html.escape("\n".join(REPRO)),
        replay=inline(REPLAY),
        opens_line=f"<p>{OPENS_LINE}</p>" if OPENS_LINE else "",
        limits="".join(f"<li>{inline(x)}</li>" for x in LIMITS),
        links="".join(f"<li>{html.escape(a)}: {_link(b)}</li>" for a, b in LINKS),
    )
)
print(f"site/index.html {len(page):,} bytes; witness {w_rels} of {src_rels}; compare {cmp_path.name}")
