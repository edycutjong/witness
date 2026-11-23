"""Build site/ (the static landing on Vercel) from the committed files. Every number on the page is read from them.

uv run python scripts/build_site.py        -> site/index.html + site/exhibit/two-hub.html + site/icon.svg + site/og-image.png
"""

from __future__ import annotations

import html
import json
import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
REPO = "https://github.com/edycutjong/witness"
# Absolute base for og:image. Switch to https://witness.edycu.dev once its DNS record resolves (HUMAN-TODO #3).
SITE_URL = "https://witness-wheat.vercel.app"
# Set True when the repository is public (HUMAN-TODO: the flip at submission), then rebuild and redeploy.
REPO_PUBLIC = False
SOURCE_LI = f'<li><a href="{REPO}">Source on GitHub</a></li>' if REPO_PUBLIC else "<li>Source: opens at submission</li>"
PRIVATE_NOTE = (
    ""
    if REPO_PUBLIC
    else '<p class="note">The repository opens at submission; until then the clone command does not resolve and the committed output below is the run.</p>'
)

man = json.loads((ROOT / "witnesses" / "two-hub.manifest.json").read_text())
cmp_path = sorted((ROOT / "evidence").glob("neo4j-compare-*.json"))[-1]
cmp = json.loads(cmp_path.read_text())
exhibit = (ROOT / "witnesses" / "two-hub.html").read_text()

src_rels, src_nodes = man["source"]["relationships"], man["source"]["nodes"]
w_rels, w_nodes = man["witness"]["relationships"], man["witness"]["nodes"]
trials, secs = man["run"]["trials"], man["run"]["seconds"]
check = man["check"]["check_text"].split(" (")[0]
rows = man["baseline"]["rows"]
relate_tps = cmp["median_trials_per_s"]["relate_in_process"]
neo_tps = cmp["median_trials_per_s"]["neo4j_docker"]
ratio = cmp["ratio_trials_per_s"]

m = re.search(r'<div class="grid">(.*?)</div>\n<dl>', exhibit, re.S)
if not m:
    raise SystemExit("exhibit html changed shape: no grid block")
grid = m.group(1).replace("<h2>", "<h3>").replace("</h2>", "</h3>")
answer_rows = ", ".join(r["airport"] for r in rows)
fmt = lambda n: f"{n:,}"  # noqa: E731

PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Witness: the {w_rels} relationships that prove your agent's answer</title>
<meta name="description" content="When an agent answers from a graph, Witness hands back a tiny graph that reproduces the answer and proves each relationship in it is needed. Built on Relate.">
<link rel="icon" href="/icon.svg" type="image/svg+xml">
<meta property="og:type" content="website">
<meta property="og:site_name" content="Witness">
<meta property="og:title" content="Witness: the {w_rels} relationships that prove your agent's answer">
<meta property="og:description" content="{w_rels} of {src_rels_fmt} relationships reproduce the answer, and deleting any one of them changes it. Built on Relate.">
<meta property="og:image" content="{site_url}/og-image.png">
<meta property="og:image:width" content="2400">
<meta property="og:image:height" content="1260">
<meta property="og:image:alt" content="Witness: {src_rels_fmt} relationships reduced to {w_rels}; each of the {w_rels} changes the answer when deleted.">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:image" content="{site_url}/og-image.png">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Fragment+Mono&family=Old+Standard+TT:ital,wght@0,400;0,700;1,400&family=Source+Sans+3:wght@400;600&display=swap" rel="stylesheet">
<style>
:root{{--paper:#F2E8D5;--ink:#1F1A14;--muted:#6F6555;--before:#9C978E;--after:#B42318;--rule:#D9CBAE;
--display:"Old Standard TT","Libre Caslon Text",Georgia,serif;--body:"Source Sans 3","Helvetica Neue",Arial,sans-serif;
--data:"Fragment Mono","SF Mono",Menlo,monospace}}
*{{box-sizing:border-box}}
html{{scroll-behavior:smooth}}
body{{margin:0;background:var(--paper);color:var(--ink);font:17px/1.55 var(--body)}}
a{{color:var(--ink);text-underline-offset:3px;text-decoration-thickness:1px;transition:color .15s ease,text-decoration-thickness .15s ease,text-decoration-color .15s ease}}
a:hover{{color:var(--muted);text-decoration-thickness:3px}}
a:active{{opacity:.7}}
a:focus-visible,button:focus-visible{{outline:3px solid var(--ink);outline-offset:3px;border-radius:2px}}
main{{max-width:1040px;margin:0 auto;padding:48px 24px 72px}}
.eyebrow{{font:600 13px/1 var(--body);letter-spacing:.16em;text-transform:uppercase;color:var(--muted);margin:0 0 20px}}
h1{{font:700 clamp(36px,6.4vw,64px)/1.05 var(--display);margin:0 0 18px;letter-spacing:-.01em}}
h1 em{{font-style:normal;color:var(--after)}}
h2{{font:600 13px/1.4 var(--body);letter-spacing:.14em;text-transform:uppercase;color:var(--muted);margin:0 0 12px}}
.lede{{font-size:21px;max-width:60ch;margin:0 0 28px}}
.stamp{{display:inline-block;margin:6px 0 28px;padding:8px 14px;border:3px solid var(--after);color:var(--after);font:700 18px/1 var(--data);letter-spacing:.08em;transform:rotate(-1.5deg)}}
.run{{display:flex;flex-wrap:wrap;gap:12px;align-items:stretch;margin:0 0 8px}}
pre{{margin:0;padding:14px 18px;background:#1F1A14;color:#F2E8D5;font:15px/1.6 var(--data);border-radius:3px;overflow-x:auto;flex:1 1 360px}}
pre b{{color:#D9CBAE;font-weight:400}}
button{{font:600 15px/1 var(--body);padding:0 20px;min-height:48px;background:var(--ink);color:var(--paper);border:0;border-radius:3px;cursor:pointer;transition:background .15s ease,transform .1s ease}}
button:hover{{background:#4A4034}}
button:active{{transform:translateY(1px) scale(.98)}}
.note{{font-size:15px;color:var(--muted);margin:0 0 44px}}
.mono,td,th,dt,dd{{font-family:var(--data);font-size:14px}}
table{{border-collapse:collapse;width:100%;margin-bottom:24px}}
th,td{{text-align:left;padding:6px 10px;border-bottom:1px solid var(--before)}}
tbody tr{{transition:background .15s ease}}tbody tr:hover{{background:rgba(31,26,20,.07)}}
.grid{{display:grid;grid-template-columns:1fr 1fr;gap:32px;margin-top:8px}}
@media (max-width:820px){{.grid{{grid-template-columns:1fr}}}}
.tag{{color:#fff;background:var(--after);font-weight:700;text-align:center;width:2.6em}}.t{{color:var(--muted)}}
svg{{width:100%;height:auto;background:rgba(255,255,255,.35);border:1px solid var(--before)}}
.e{{stroke:var(--after);stroke-width:1.6}}.en{{fill:var(--after);font:700 11px monospace}}
.n{{fill:var(--paper);stroke:var(--ink);stroke-width:1.5}}.nl{{font:700 11px monospace;text-anchor:middle;fill:var(--ink)}}
.facts{{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:20px;margin:52px 0;padding:24px 0;border-top:1px solid var(--rule);border-bottom:1px solid var(--rule)}}
.facts p{{margin:0;font-size:15px;color:var(--muted)}}
.facts strong{{display:block;font:400 28px/1.15 var(--data);color:var(--ink);margin-bottom:4px}}
code{{font:600 .92em var(--body);background:rgba(31,26,20,.07);padding:1px 5px;border-radius:2px}}
h3{{font:600 13px/1.4 var(--body);letter-spacing:.14em;text-transform:uppercase;color:var(--muted);margin:0 0 8px}}
.links{{display:flex;flex-wrap:wrap;gap:8px 28px;margin:36px 0 0;padding:0;list-style:none}}
footer{{margin-top:56px;font-size:14px;color:var(--muted);max-width:70ch}}
@media (max-width:600px){{.en,.nl{{font-size:19px}}}}
@media (prefers-reduced-motion:reduce){{*{{transition:none!important;scroll-behavior:auto!important}}}}
</style>
</head>
<body>
<main>
<p class="eyebrow">Witness · proof for a graph-backed agent's answer · Relate + Neo4j</p>
<h1>Your agent's answer rests on <em>{w_rels}</em> of {src_rels_fmt} relationships.</h1>
<p class="lede">When an agent answers from a graph, Witness hands back a tiny graph that reproduces the answer, and proves each relationship in it is needed.</p>
<p class="lede">Built for teams shipping graph-backed agents, on Relate, the embedded graph database. The agent calls the MCP tool <code>why</code> on a read-only Cypher answer and <code>check</code> re-proves the result; <code>relate pull</code> brings a slice in from a Neo4j graph, read-only.</p>
<div class="stamp">{check_upper}</div>

<h2>Run it yourself</h2>
{private_note}
<div class="run">
<pre id="cmd" tabindex="0" aria-label="Commands"><b>$</b> git clone {repo} &amp;&amp; cd witness
<b>$</b> uv run witness demo</pre>
<button type="button" id="copy">Copy commands</button>
<span id="status" role="status" class="note" style="flex-basis:100%;margin:0"></span>
</div>
<p class="note">The committed air-routes graph ({src_nodes_fmt} nodes, {src_rels_fmt} relationships) is copied, never modified. The result below is the committed output of the same run.</p>

<h2>The case file</h2>
<p class="lede">An agent asks which Mexican airports have no direct flight to MEX but two ways out. It answers {answer_rows}. These are the relationships that answer rests on.</p>
<div class="grid">{grid}</div>

<div class="facts">
<p><strong>{w_rels} of {w_rels}</strong>deleting any one relationship changes the answer: deletion-minimal, checked on relate-db and on the Relate CLI</p>
<p><strong>{trials} trials</strong>in {secs} s on the full graph, each run in a Relate transaction and rolled back; in {commits} the answer survived, so that deletion was then applied</p>
<p><strong>{relate_tps} vs {neo_tps}</strong>trials per second, Relate in-process vs Neo4j {neo_version} Community in Docker over Bolt: the same delete-query-rollback trial on 1,000 sampled deletions, median of 3 runs, same answers ({ratio}x here; Neo4j runs a dialect of the query with an ORDER BY in place of coll.sort(), baseline rows checked identical). One machine, one query, one graph: the cost of this setup (a Docker VM, a Bolt round trip per statement, count checks), not a Neo4j limit. Method: <code>evidence/{cmp_md}</code></p>
</div>

<ul class="links">
<li><a href="exhibit/two-hub.html">Open the exhibit page</a></li>
{source_li}
<li><a href="https://relatedb.ai">Relate</a></li>
</ul>
<footer>
<p>Deletion-minimal means no single remaining relationship can be removed without changing the answer. It does not mean smallest possible.
Numbers on this page are read from the committed files in the repository (<code>witnesses/two-hub.manifest.json</code>, <code>evidence/{cmp_name}</code>) by <code>scripts/build_site.py</code>.
A work-in-progress page: the full write-up comes later. Apache-2.0.</p>
</footer>
</main>
<script>
(function(){{
var b=document.getElementById('copy'),s=document.getElementById('status'),t=b.textContent;
b.addEventListener('click',function(){{
var text='{copy_prefix}git clone {repo} && cd witness\\nuv run witness demo';
function ok(){{b.textContent='Copied';s.textContent='Copied the two commands.';setTimeout(function(){{b.textContent=t;s.textContent=''}},1600)}}
if(navigator.clipboard&&navigator.clipboard.writeText){{navigator.clipboard.writeText(text).then(ok,function(){{s.textContent='Select the commands above and copy them.'}})}}
else{{s.textContent='Select the commands above and copy them.'}}
}});
}})();
</script>
</body>
</html>
"""

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
page = PAGE.format(
    w_rels=w_rels,
    src_rels_fmt=fmt(src_rels),
    src_nodes_fmt=fmt(src_nodes),
    check_upper=html.escape(check.upper()),
    repo=REPO,
    answer_rows=html.escape(answer_rows),
    grid=grid,
    trials=trials,
    commits=man["run"]["commits"],
    neo_version=cmp["neo4j"]["components"][0]["v"],
    cmp_md=cmp_path.with_suffix(".md").name,
    private_note=PRIVATE_NOTE,
    source_li=SOURCE_LI,
    copy_prefix="" if REPO_PUBLIC else "# the repository opens at submission\\n",
    secs=secs,
    relate_tps=relate_tps,
    neo_tps=neo_tps,
    ratio=ratio,
    cmp_name=cmp_path.name,
    site_url=SITE_URL,
)
(SITE / "index.html").write_text(page)
# favicon + social card: the judge-facing media from docs/assets (synced from the asset pipeline)
for name in ("icon.svg", "og-image.png"):
    shutil.copyfile(ROOT / "docs" / "assets" / name, SITE / name)
print(f"site/index.html {len(page):,} bytes; witness {w_rels} of {src_rels}; compare {cmp_path.name}")
