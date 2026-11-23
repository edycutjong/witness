"""Build site/ (the static landing on Vercel) from the committed files. Every number on the page is read from them.

uv run python scripts/build_site.py        -> site/index.html + site/exhibit/two-hub.html + site/og.svg
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
grid = m.group(1)
answer_rows = ", ".join(r["airport"] for r in rows)
fmt = lambda n: f"{n:,}"  # noqa: E731

PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Witness: the {w_rels} relationships that prove your agent's answer</title>
<meta name="description" content="When an agent answers from a graph, Witness hands back a tiny graph that reproduces the answer and proves each relationship in it is needed. Built on Relate.">
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
a{{color:var(--after);text-underline-offset:3px;text-decoration-thickness:1px;transition:color .15s ease,text-decoration-thickness .15s ease}}
a:hover{{color:var(--ink);text-decoration-thickness:2px}}
a:active{{opacity:.7}}
a:focus-visible,button:focus-visible{{outline:3px solid var(--ink);outline-offset:3px;border-radius:2px}}
main{{max-width:1040px;margin:0 auto;padding:48px 24px 72px}}
.eyebrow{{font:14px/1 var(--data);letter-spacing:.14em;color:var(--muted);margin:0 0 20px}}
h1{{font:700 clamp(36px,6.4vw,64px)/1.05 var(--display);margin:0 0 18px;letter-spacing:-.01em}}
h1 em{{font-style:normal;color:var(--after)}}
h2{{font:700 14px/1 var(--data);letter-spacing:.14em;text-transform:uppercase;color:var(--muted);margin:0 0 12px}}
.lede{{font-size:21px;max-width:60ch;margin:0 0 28px}}
.stamp{{display:inline-block;margin:6px 0 28px;padding:8px 14px;border:3px solid var(--after);color:var(--after);font:700 18px/1 var(--data);letter-spacing:.08em;transform:rotate(-1.5deg)}}
.run{{display:flex;flex-wrap:wrap;gap:12px;align-items:stretch;margin:0 0 8px}}
pre{{margin:0;padding:14px 18px;background:#1F1A14;color:#F2E8D5;font:15px/1.6 var(--data);border-radius:3px;overflow-x:auto;flex:1 1 360px}}
pre b{{color:#E5484D;font-weight:400}}
button{{font:600 15px/1 var(--body);padding:0 20px;min-height:48px;background:var(--after);color:#fff;border:0;border-radius:3px;cursor:pointer;transition:background .15s ease,transform .1s ease}}
button:hover{{background:#8F1B12}}
button:active{{transform:translateY(1px) scale(.98)}}
.note{{font-size:15px;color:var(--muted);margin:0 0 44px}}
.mono,td,th,dt,dd{{font-family:var(--data);font-size:14px}}
table{{border-collapse:collapse;width:100%;margin-bottom:24px}}
th,td{{text-align:left;padding:6px 10px;border-bottom:1px solid var(--before)}}
tbody tr{{transition:background .15s ease}}tbody tr:hover{{background:rgba(180,35,24,.07)}}
.grid{{display:grid;grid-template-columns:1fr 1fr;gap:32px;margin-top:8px}}
@media (max-width:820px){{.grid{{grid-template-columns:1fr}}}}
.tag{{color:#fff;background:var(--after);font-weight:700;text-align:center;width:2.6em}}.t{{color:var(--before)}}
svg{{width:100%;height:auto;background:rgba(255,255,255,.35);border:1px solid var(--before)}}
.e{{stroke:var(--after);stroke-width:1.6}}.en{{fill:var(--after);font:700 11px monospace}}
.n{{fill:var(--paper);stroke:var(--ink);stroke-width:1.5}}.nl{{font:700 11px monospace;text-anchor:middle;fill:var(--ink)}}
.facts{{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:20px;margin:52px 0;padding:24px 0;border-top:1px solid var(--rule);border-bottom:1px solid var(--rule)}}
.facts p{{margin:0;font-size:15px;color:var(--muted)}}
.facts strong{{display:block;font:700 34px/1.1 var(--display);color:var(--ink);margin-bottom:4px}}
.links{{display:flex;flex-wrap:wrap;gap:8px 28px;margin:36px 0 0;padding:0;list-style:none}}
footer{{margin-top:56px;font-size:14px;color:var(--muted);max-width:70ch}}
@media (prefers-reduced-motion:reduce){{*{{transition:none!important;scroll-behavior:auto!important}}}}
</style>
</head>
<body>
<main>
<p class="eyebrow">WITNESS · EXHIBIT REGISTER · BUILT ON RELATE</p>
<h1><em>{w_rels}</em> of {src_rels_fmt} relationships are why.</h1>
<p class="lede">When an agent answers from a graph, Witness hands back a tiny graph that reproduces the answer, and proves each relationship in it is needed.</p>
<div class="stamp">{check_upper}</div>

<h2>Run it yourself</h2>
<div class="run">
<pre id="cmd"><b>$</b> git clone {repo} &amp;&amp; cd witness
<b>$</b> uv run witness demo</pre>
<button type="button" id="copy" aria-label="Copy the two commands">Copy commands</button>
</div>
<p class="note" id="status" role="status">The committed air-routes graph ({src_nodes_fmt} nodes, {src_rels_fmt} relationships) is copied, never modified. The result below is the committed output of the same run.</p>

<h2>The case file: airports {answer_rows} (from <span class="mono">MX</span> to <span class="mono">MEX</span>)</h2>
<div class="grid">{grid}</div>

<div class="facts">
<p><strong>{w_rels} of {w_rels}</strong>deleting any one relationship changes the answer: deletion-minimal, checked on relate-db and on the Relate CLI</p>
<p><strong>{trials} trials</strong>in {secs} s, each a rolled-back Relate transaction on the full graph</p>
<p><strong>{relate_tps} vs {neo_tps}</strong>trials per second, in-process Relate vs Neo4j in Docker, same loop, same answers ({ratio}x here)</p>
</div>

<ul class="links">
<li><a href="exhibit/two-hub.html">Open the exhibit page</a></li>
<li><a href="{repo}">Source on GitHub</a></li>
<li><a href="https://relatedb.ai">Relate</a></li>
</ul>
<footer>
<p>Deletion-minimal means no single remaining relationship can be removed without changing the answer. It does not mean smallest possible.
Numbers on this page are read from the committed files in the repository (<span class="mono">witnesses/two-hub.manifest.json</span>, <span class="mono">evidence/{cmp_name}</span>) by <span class="mono">scripts/build_site.py</span>.
A work-in-progress page: the full write-up comes later. Apache-2.0.</p>
</footer>
</main>
<script>
(function(){{
var b=document.getElementById('copy'),s=document.getElementById('status'),t=b.textContent,keep=s.textContent;
b.addEventListener('click',function(){{
var text='git clone {repo} && cd witness\\nuv run witness demo';
function ok(){{b.textContent='Copied';s.textContent='Copied the two commands.';setTimeout(function(){{b.textContent=t;s.textContent=keep}},1600)}}
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
    "a{color:var(--after);text-underline-offset:3px;transition:color .15s ease}a:hover{color:var(--ink)}"
    "a:focus-visible{outline:3px solid var(--ink);outline-offset:3px}"
    "@media (prefers-reduced-motion:reduce){a{transition:none}}"
)
served = exhibit.replace("</style>", back_css + "</style>", 1).replace(
    '<p class="mono">WITNESS · EXHIBIT REGISTER</p>',
    '<p class="mono"><a href="../">&larr; Witness</a> · EXHIBIT REGISTER</p>',
    1,
)
if served == exhibit:
    raise SystemExit("exhibit html changed shape: no style/eyebrow to patch")
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
    secs=secs,
    relate_tps=relate_tps,
    neo_tps=neo_tps,
    ratio=ratio,
    cmp_name=cmp_path.name,
)
(SITE / "index.html").write_text(page)
print(f"site/index.html {len(page):,} bytes; witness {w_rels} of {src_rels}; compare {cmp_path.name}")
