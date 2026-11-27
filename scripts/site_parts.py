"""Drawn parts of the landing and the deck, built only from committed files (imported by build_site.py).

- the real air-routes frame (airports + HAS_ROUTE pairs inside lon -125..-85, lat 14..45) from data/air-routes.cypher
- the witness schematic (the 10 airports of witnesses/two-hub.rl, 13 HAS_ROUTE + 9 IN_COUNTRY exhibits)
- the reduction milestones and per-trial outcomes from witnesses/two-hub.trace.json
- the pull-a-tag answers from evidence/pull-each-tag.json
Every figure is asserted against its source so the page cannot drift from the evidence.
"""

from __future__ import annotations

import html
import json
import math
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FRAME = (-125.0, -85.0, 14.0, 45.0)  # lon0, lon1, lat0, lat1
VW, VH = 640, 420  # hero / exhibit viewBox

man = json.loads((ROOT / "witnesses" / "two-hub.manifest.json").read_text())
trace = json.loads((ROOT / "witnesses" / "two-hub.trace.json").read_text())
pulls = json.loads((ROOT / "evidence" / "pull-each-tag.json").read_text())
demo_path = sorted((ROOT / "evidence").glob("demo-*.txt"))[-1]
demo = demo_path.read_text()

# ── register: the 22 exhibits in the CLI's register order, three sources must agree ─────────────────────────────────
REG = [t["rel"] for t in pulls["tags"]]
assert REG == sorted(p["element"] for p in man["check"]["probes"]), "pull-each-tag order != manifest register"
_cli = re.findall(r"^\s+(\d+)\s+(\(\w+\)-\[:\w+\]->\(\w+\))$", demo, re.M)
assert [e for _, e in _cli] == REG and [int(n) for n, _ in _cli] == list(range(1, len(REG) + 1)), (
    "demo transcript register differs"
)
assert pulls["changed"] == pulls["of"] == len(REG) == man["witness"]["relationships"], "pull-each-tag is not N of N"
assert pulls["baseline"] == sorted(r["airport"] for r in man["baseline"]["rows"]), "pull-each-tag baseline != manifest"
EDGES = [tuple(re.findall(r"\((\w+)\)", e)) + (re.search(r":(\w+)\]", e).group(1),) for e in REG]  # (start, end, type)

# ── the trace: real milestones + every trial's outcome ─────────────────────────────────────────────────────────────
ph = trace["phases"]
TR = trace["trials"]
assert len(TR) == ph["trials"] == man["run"]["trials"]
assert sum(t["holds"] for t in TR) == ph["commits"] == man["run"]["commits"], "applied deletions != commits"
_last_a = max(t["n"] for t in TR if t["phase"] == "A")
MILESTONES = [  # (trial, relationships after it, label)
    (0, ph["start_counts"][1], "the whole graph"),
    (next(t["n"] for t in TR if t["phase"] == "plan"), ph["after_plan"][1], "EXPLAIN plan drops :ON_CONTINENT"),
    (_last_a, ph["after_a"][1], "after the node pass"),
    (ph["trials"], ph["final_counts"][1], "the witness"),
]
assert ph["start_counts"][1] - ph["after_plan"][1] == trace["plan"]["dropped_rels"]
assert MILESTONES[-1][1] == man["witness"]["relationships"] and MILESTONES[0][1] == man["source"]["relationships"]
HOLDS = "".join("1" if t["holds"] else "0" for t in TR)
# Relationships left after EVERY trial, for the hero counter (arch review r7: it stepped between 4 milestones). Read
# from evidence/trial-counters-*.json (bench/trial_counters.py) and bound here to the trace and the milestones, so the
# page, the video's counter and the committed trace cannot drift apart.
_tc = json.loads(sorted((ROOT / "evidence").glob("trial-counters-*.json"))[-1].read_text())["trials"]
_k = ("n", "phase", "rels", "nodes", "holds")
assert [tuple(t[k] for k in _k) for t in _tc] == [tuple(t[k] for k in _k) for t in TR], "trial counters != trace"
LEFT = [t["rels_left"] for t in _tc]
assert all(LEFT[n - 1] == r for n, r, _ in MILESTONES if n > 0), "trial counters != milestones"

# ── the real air-routes frame ──────────────────────────────────────────────────────────────────────────────────────
_src = (ROOT / "data" / "air-routes.cypher").read_text()
_ap = {}
for m in re.finditer(r"\{altitude: [^}]*?iata: '([A-Z0-9]+)'[^}]*?id: (\d+), lat: ([-\d.]+), lon: ([-\d.]+)", _src):
    _ap[int(m.group(2))] = (m.group(1), float(m.group(3)), float(m.group(4)))
_routes = [(int(s), int(d)) for d, s in re.findall(r"\{d: (\d+), dist: \d+, s: (\d+)\}", _src)]
assert len(_routes) > 50_000, "air-routes parse failed"
LON0, LON1, LAT0, LAT1 = FRAME
_in = lambda i: i in _ap and LON0 <= _ap[i][2] <= LON1 and LAT0 <= _ap[i][1] <= LAT1  # noqa: E731
_box = [(s, d) for s, d in _routes if _in(s) and _in(d)]
PAIRS = sorted({tuple(sorted((_ap[s][0], _ap[d][0]))) for s, d in _box})
AIRPORTS = {_ap[i][0]: (_ap[i][1], _ap[i][2]) for i in _ap if _in(i)}
FRAME_COUNTS = {"routes": len(_box), "pairs": len(PAIRS), "airports": len(AIRPORTS)}

_k = math.cos(math.radians((LAT0 + LAT1) / 2))
_s = (VH - 40) / (LAT1 - LAT0)
_X0 = 20 + ((VW - 40) - (LON1 - LON0) * _k * _s) / 2


def geo(code: str) -> tuple[float, float]:
    lat, lon = AIRPORTS[code]
    return (_X0 + (lon - LON0) * _k * _s, 20 + (LAT1 - lat) * _s)


# ── the schematic: answer airports → hubs → MEX (same 10 airports as the witness) ──────────────────────────────────
SCH = {
    "UPN": (118, 76),
    "QRO": (118, 148),
    "PBC": (118, 220),
    "TLC": (118, 292),
    "LAX": (336, 48),
    "TIJ": (336, 114),
    "DFW": (336, 180),
    "LAS": (336, 246),
    "ACA": (336, 312),
    "MEX": (540, 180),
}
COUNTRY = {}
for s, e, t in EDGES:
    if t == "IN_COUNTRY":
        COUNTRY[s] = e
ROUTES = [(i + 1, s, e) for i, (s, e, t) in enumerate(EDGES) if t == "HAS_ROUTE"]
assert set(SCH) == {s for s, _, _ in EDGES} | {e for _, e, t in EDGES if t == "HAS_ROUTE"}, "schematic != witness nodes"
assert len(ROUTES) == 13 and len(COUNTRY) == 9 and set(COUNTRY) | {"MEX"} == set(SCH)
# the schematic's <title> numbers, all derived and asserted (arch review r7: "2 countries" was the one left unchecked)
N_COUNTRIES = len(set(COUNTRY.values()))
assert (len(EDGES), len(SCH), N_COUNTRIES) == (22, 10, 2)
# MEX's own country is not in the witness (the query binds $dest by code); its label carries no country tag
TAG_T = {"MEX": 0.5}


def bow(p, q, b):
    mx, my, dx, dy = (p[0] + q[0]) / 2, (p[1] + q[1]) / 2, q[0] - p[0], q[1] - p[1]
    return (mx - dy * b, my + dx * b)


def qd(p, c, q) -> str:
    return f"M{p[0]:.1f} {p[1]:.1f}Q{c[0]:.1f} {c[1]:.1f} {q[0]:.1f} {q[1]:.1f}"


def qpt(p, c, q, t):
    return (
        (1 - t) ** 2 * p[0] + 2 * (1 - t) * t * c[0] + t * t * q[0],
        (1 - t) ** 2 * p[1] + 2 * (1 - t) * t * c[1] + t * t * q[1],
    )


SB = 0.06  # schematic bow


def tag_at(n, s, e):
    p, q = SCH[s], SCH[e]
    c = bow(p, q, SB)
    t = 0.5 if e == "MEX" else 0.36
    return qpt(p, c, q, t)


TAG_PATH = "M-17 0L-10 -10H17V10H-10Z"


def tag_svg(n: int, x: float, y: float, cls: str = "tg") -> str:
    return (
        f'<g class="{cls}" data-n="{n}" transform="translate({x:.1f} {y:.1f})">'
        f'<path d="{TAG_PATH}"/><circle cx="-9.5" cy="0" r="2"/><text x="4" y="4.6">{n}</text></g>'
    )


def schematic(prefix: str, ghost: bool) -> str:
    """The witness drawn as a register exhibit. ``ghost`` adds the real air-routes frame behind it (the hero)."""
    box = "56 16 552 392" if ghost else "56 22 552 312"  # the drawing's own extent (map frame x 112-528, labels 60-600)
    out = [
        f'<svg class="inst" viewBox="{box}" role="img" aria-labelledby="{prefix}-t">',
        f'<title id="{prefix}-t">The witness: {len(EDGES)} relationships among {len(SCH) + N_COUNTRIES} nodes '
        f"({len(SCH)} airports, {N_COUNTRIES} countries), the {len(ROUTES)} routes carry numbered exhibit tags, "
        f"the {len(COUNTRY)} country links show as country codes</title>",
    ]
    if ghost:
        # four waves, farthest from MEX first (the replay fades them in this order)
        mex = geo("MEX")
        lines = []
        for a, b in PAIRS:
            p, q = geo(a), geo(b)
            d = math.hypot((p[0] + q[0]) / 2 - mex[0], (p[1] + q[1]) / 2 - mex[1])
            c = bow(p, q, 0.12)
            lines.append((d, f"M{p[0]:.0f} {p[1]:.0f}Q{c[0]:.0f} {c[1]:.0f} {q[0]:.0f} {q[1]:.0f}"))
        lines.sort(key=lambda x: -x[0])
        n = len(lines)
        out.append('<g class="ghost" aria-hidden="true">')
        for i in range(4):
            seg = lines[i * n // 4 : (i + 1) * n // 4]
            out.append(f'<path class="wave" data-w="{i}" d="{"".join(d for _, d in seg)}"/>')
        dots = "".join(f"M{geo(c)[0]:.0f} {geo(c)[1]:.0f}h0" for c in AIRPORTS if c not in SCH)
        out.append(f'<path class="dots" d="{dots}"/></g>')
    out.append('<g class="edges">')
    for n, s, e in ROUTES:
        p, q = SCH[s], SCH[e]
        out.append(f'<path class="ed" data-n="{n}" data-s="{s}" data-e="{e}" d="{qd(p, bow(p, q, SB), q)}"/>')
    out.append('</g><g class="nodes">')
    nums = {s: i + 1 for i, (s, e, t) in enumerate(EDGES) if t == "IN_COUNTRY"}
    for c, (x, y) in SCH.items():
        left, right = x < 200, c == "MEX"
        anchor = "end" if left else "start" if right else "middle"
        lx, ly = (-14, 6) if left else (14, 6) if right else (0, -14)
        cc = COUNTRY.get(c)
        ctry = f'<tspan class="cc" data-n="{nums[c]}" dx="5">{cc}</tspan>' if cc else ""
        out.append(
            f'<g class="nd" data-c="{c}" transform="translate({x} {y})"><circle r="5"/>'
            f'<text class="lb" x="{lx}" y="{ly}" text-anchor="{anchor}">{c}{ctry}</text></g>'
        )
    out.append('</g><g class="tags">')
    for n, s, e in ROUTES:
        x, y = tag_at(n, s, e)
        out.append(tag_svg(n, x, y))
    out.append("</g></svg>")
    return "\n".join(out)


# ── pull-a-tag: what each exhibit's deletion does to the answer (static text + JSON for the page) ───────────────────
BASE = {r["airport"]: r["hub_countries"] for r in pulls["baseline_rows"]}


def effect(t: dict) -> str:
    after = {r["airport"]: r["hub_countries"] for r in t["rows"]}
    if t["drops"]:
        d = t["drops"]
        who = d[0] if len(d) == 1 else ", ".join(d[:-1]) + " and " + d[-1]
        return f"{who} drop{'s' if len(d) == 1 else ''} out"
    lost: dict[str, list[str]] = {}
    for a, cs in BASE.items():
        for c in cs:
            if c not in after.get(a, []):
                lost.setdefault(c, []).append(a)
    assert lost, f"exhibit {t['n']} changed nothing visible"
    parts = []
    for c, who in lost.items():
        w = who[0] if len(who) == 1 else ", ".join(who[:-1]) + " and " + who[-1]
        parts.append(f"{w} lose{'s' if len(who) == 1 else ''} {c}")
    return "; ".join(parts)


EFFECTS = {t["n"]: effect(t) for t in pulls["tags"]}
PAGE_DATA = {
    "base": pulls["baseline_rows"],
    "tags": [
        {"n": t["n"], "rel": t["rel"], "rows": t["rows"], "drops": t["drops"], "ms": t["ms"], "fx": EFFECTS[t["n"]]}
        for t in pulls["tags"]
    ],
    "geo": {c: [round(v, 1) for v in geo(c)] for c in SCH},
    "sch": SCH,
    "ms": [[a, b, c] for a, b, c in MILESTONES],
    "left": LEFT,
    "holds": HOLDS,
}


def page_json() -> str:
    return json.dumps(PAGE_DATA, separators=(",", ":")).replace("</", "<\\/")


def tape_svg() -> str:
    """One tick per trial: tall = the deletion kept the answer and was applied; short = it changed it, rolled back."""
    w = 2
    ticks_a = "".join(f"M{i * w + 1} 2v14" for i, h in enumerate(HOLDS) if h == "1")
    ticks_r = "".join(f"M{i * w + 1} 6v6" for i, h in enumerate(HOLDS) if h == "0")
    return (
        f'<svg class="tape" viewBox="0 0 {len(HOLDS) * w} 18" preserveAspectRatio="none" aria-hidden="true">'
        f'<path class="tr" d="{ticks_r}"/><path class="ta" d="{ticks_a}"/></svg>'
    )


def register_rows() -> str:
    rows = []
    for t in pulls["tags"]:
        n = t["n"]
        rows.append(
            f'<li data-n="{n}"><button type="button" class="pull" data-n="{n}" aria-pressed="false">'
            f'<span class="no">{n}</span><code>{html.escape(t["rel"])}</code>'
            f'<span class="fx">{html.escape(EFFECTS[n])}</span></button></li>'
        )
    return "\n".join(rows)


def _e(v) -> str:
    """Every string from evidence is escaped before it becomes HTML (arch review r7)."""
    return html.escape(str(v), quote=True)


def answer_rows() -> str:
    out = []
    for r in pulls["baseline_rows"]:
        a, cs = _e(r["airport"]), _e(", ".join(r["hub_countries"]))
        out.append(f'<tr data-a="{a}"><td>{a}</td><td>[{cs}]</td></tr>')
    return "\n".join(out)


def term_line(ln: str) -> str:
    """One line of the recorded transcript, text untouched; exhibit numbers and the check line in the kept colour."""
    e = html.escape(ln)
    m = re.match(r"^(\s+)(\d+)(\s+\(\w+\)-\[:\w+\]->\(\w+\))$", ln)
    if m:
        e = f'{m.group(1)}<b class="k">{m.group(2)}</b>{html.escape(m.group(3))}'
    elif ln.startswith("CHECK"):
        e = f'<b class="k">{e}</b>'
    elif re.match(r"^[A-Z]{3,}", ln):
        e = re.sub(r"^([A-Z][A-Z ]+?)(\s{2}|$)", r'<b class="h">\1</b>\2', e, count=1)
    return f'<span class="ln">{e or " "}</span>'


def terminal_lines(limit: int | None = None) -> str:
    """The recorded `witness demo` transcript, verbatim; exhibit numbers and the check line in the kept colour."""
    lines = demo.splitlines()[1:]  # line 0 is the recording header, shown as the card's caption
    return "".join(term_line(ln) for ln in lines[:limit])


DEMO_HEADER = demo.splitlines()[0].lstrip("# ")
DEMO_REDUCE = re.search(r"reduced in ([\d.]+) s", demo).group(1)
assert "22 of 22 change the answer" in demo and f"{man['run']['trials']} trials" in demo
