"""Export a witness (the scratch's remaining graph) as a byte-stable CREATE script and a single-file `.rl`."""

from __future__ import annotations

import datetime as _dt
import os
from pathlib import Path

os.environ.setdefault("DO_NOT_TRACK", "1")

import relate  # noqa: E402

from .canon import cypher_name  # noqa: E402
from .store import Scratch  # noqa: E402

# Characters str.splitlines() breaks on, plus every other control character: written as \uXXXX so a string value
# never spans two script lines (write_rl drops `//` header lines line by line; a raw "\r\n// x" inside a value was
# silently cut on rebuild, and Relate reads "\r" in a literal as a backslash and an "r").
_LINE_BREAKS = frozenset("\n\r\x0b\x0c\x1c\x1d\x1e\x85  ")


def _str_lit(v: str) -> str:
    out = []
    for ch in v:
        if ch == "\\":
            out.append("\\\\")
        elif ch == "'":
            out.append("\\'")
        elif ord(ch) < 0x20 or 0x7F <= ord(ch) <= 0x9F or ch in _LINE_BREAKS:
            out.append(f"\\u{ord(ch):04X}")
        else:
            out.append(ch)
    return "'" + "".join(out) + "'"


def _float_lit(x: float) -> str:
    if x != x:
        return "0.0/0.0"
    if x in (float("inf"), float("-inf")):
        return "1.0/0.0" if x > 0 else "-1.0/0.0"
    return repr(x)


def _lit(v) -> str:
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        return _float_lit(v)
    if isinstance(v, str):
        return _str_lit(v)
    if isinstance(v, (list, tuple)):
        return "[" + ", ".join(_lit(x) for x in v) + "]"
    if isinstance(v, dict):
        return "{" + ", ".join(f"{cypher_name(k)}: {_lit(v[k])}" for k in sorted(v)) + "}"
    # Temporal and spatial values (a `relate pull` slice from Neo4j often carries them). relate-db returns stdlib
    # date/datetime/time where they fit, and its own Temporal / Duration / Point types otherwise (nanoseconds, zones).
    if isinstance(v, _dt.datetime):
        return f"{'datetime' if v.tzinfo else 'localdatetime'}({_str_lit(v.isoformat())})"
    if isinstance(v, _dt.date):
        return f"date({_str_lit(v.isoformat())})"
    if isinstance(v, _dt.time):
        return f"{'time' if v.tzinfo else 'localtime'}({_str_lit(v.isoformat())})"
    kind = type(v).__name__
    if kind == "Temporal" and hasattr(v, "kind") and hasattr(v, "text"):
        return f"{v.kind}({_str_lit(v.text)})"
    if kind == "Duration" and hasattr(v, "months"):
        return f"duration({_str_lit(str(v))})"
    if kind == "Vector" and hasattr(v, "coordinate_type") and hasattr(v, "values"):
        vals = list(v.values)
        if not str(v.coordinate_type).isidentifier():
            raise TypeError(f"vector coordinate type {v.coordinate_type!r}")
        return f"vector({_lit(vals)}, {len(vals)}, {v.coordinate_type})"
    if kind == "Point" and hasattr(v, "srid"):
        coords = [("x", v.x), ("y", v.y)] + ([("z", v.z)] if getattr(v, "z", None) is not None else [])
        return "point({srid: " + str(int(v.srid)) + "".join(f", {k}: {_float_lit(float(c))}" for k, c in coords) + "})"
    raise TypeError(f"no Cypher literal for {type(v).__name__}")


def cypher_script(sc: Scratch, header: str = "") -> str:
    """One CREATE statement for the whole witness, elements in canonical-key order."""
    nodes = sorted(sc.node_keys, key=lambda n: sc.node_keys[n])
    var = {n: f"n{i}" for i, n in enumerate(nodes)}
    parts = []
    for n in nodes:
        labels = "".join(f":{cypher_name(lb)}" for lb in sorted(sc.node_labels[n]))
        parts.append(f"({var[n]}{labels} {_lit(sc.node_props[n])})")
    for r in sorted(sc.rel_keys, key=lambda r: sc.rel_keys[r]):
        s, e = sc.rel_ends[r]
        props = sc.rel_props[r]
        p = f" {_lit(props)}" if props else ""
        parts.append(f"({var[s]})-[:{cypher_name(sc.rel_type[r])}{p}]->({var[e]})")
    head = "".join(f"// {line}\n" for line in header.splitlines() if line)
    if not parts:
        return head
    return head + "CREATE\n  " + ",\n  ".join(parts) + ";\n"


_SCRIPT_CALLS = frozenset({"date", "datetime", "localdatetime", "time", "localtime", "duration", "point", "vector"})
_SCRIPT_CLAUSES = frozenset(
    "match optional merge set delete detach remove foreach load csv call use with unwind return union where order skip "
    "limit yield show finish filter let insert next transactions start stop alter drop grant revoke deny".split()
)


def validate_witness_script(script: str) -> None:
    """A witness `.cypher` is one CREATE of literal values (what cypher_script() writes).

    `check` rebuilds W from the `.cypher` beside a `.rl`, so a hand-edited script (LOAD CSV, CALL, MATCH, a second
    statement, a parameter, a function other than a temporal/point constructor) is refused before it runs
    (a2a arch r1)."""
    from .guard import Refused, _split_args, tokenize

    toks = tokenize(script)
    if not toks:
        return
    if toks[0].kind != "ident" or toks[0].quoted or toks[0].text != "create":
        raise Refused("a witness .cypher must be one CREATE statement", "witness")
    for k, t in enumerate(toks):
        prev = toks[k - 1].text if k else ""
        nxt = toks[k + 1].text if k + 1 < len(toks) else ""
        if t.kind == "param":
            raise Refused("a witness .cypher holds literal values only (no parameters)", "witness")
        if t.text == ";" and k != len(toks) - 1:
            raise Refused("a witness .cypher must be one CREATE statement", "witness")
        if k > 0 and t.kind == "ident" and nxt == "(":
            # Every call, wherever it sits: a map value follows ":" ({p: rand()} slipped past the label skip, a2a r2).
            # Only the constructors cypher_script() writes, un-namespaced, with literal arguments.
            if prev == "." or t.quoted or t.text not in _SCRIPT_CALLS:
                raise Refused(f"{t.name}() in a witness .cypher (only temporal/point constructors)", "witness")
            args = _split_args(toks, k + 1)
            if t.text == "vector":  # vector([numbers], dimension, COORDINATE_TYPE)
                ok = len(args) == 3 and len(args[1]) == 1 and args[1][0].kind == "num" and len(args[2]) == 1
                ok = ok and args[2][0].kind == "ident" and not args[2][0].quoted
                ok = ok and args[0][0].text == "[" and all(x.kind in ("num", "punct") for x in args[0])
            elif t.text == "point":
                a = args[0] if len(args) == 1 else []
                ok = bool(a) and a[0].text == "{" and a[-1].text == "}"
                ok = ok and all(x.kind in ("num", "punct") or x.text in ("srid", "x", "y", "z") for x in a)
            else:
                ok = len(args) == 1 and len(args[0]) == 1 and args[0][0].kind == "str"
            if not ok:
                raise Refused(f"{t.name}() in a witness .cypher takes one literal argument", "witness")
            continue
        if k == 0 or t.kind != "ident" or t.quoted or prev in (".", ":") or (nxt == ":" and prev in ("{", ",")):
            continue  # a label, type or map key
        if t.text in _SCRIPT_CLAUSES:
            raise Refused(f"{t.text.upper()} in a witness .cypher (one literal CREATE only)", "witness")


def write_rl(script: str, path: Path) -> tuple[int, int]:
    path = Path(path)
    if path.exists():
        path.unlink()
    db = relate.Database(str(path))
    body = "\n".join(line for line in script.splitlines() if not line.startswith("//")).strip().rstrip(";")
    if body:
        db.execute(body)
    counts = (db.node_count(), db.relationship_count())
    db.close()
    return counts


# ---- the witness file set: <name>.{rl,cypher,manifest.json,html,trace.json} -------------------------------------
def display_name(props: dict, fallback: str = "?") -> str:
    for k in ("iata", "code", "name", "title", "id"):
        if k in props:
            return str(props[k])
    return fallback


def exhibits(sc: Scratch) -> list[dict]:
    """The witness relationships in register order: by start name, type, end name (then key, so the order is total)."""
    out = []
    for r in sc.rel_keys:
        s, e = sc.rel_ends[r]
        out.append(
            {
                "start": display_name(sc.node_props[s]),
                "start_labels": sorted(sc.node_labels[s]),
                "type": sc.rel_type[r],
                "end": display_name(sc.node_props[e]),
                "end_labels": sorted(sc.node_labels[e]),
                "key": sc.rel_keys[r],
                "id": r,
            }
        )
    out.sort(key=lambda x: (x["start"], x["type"], x["end"], x["key"]))
    for i, x in enumerate(out, 1):
        x["n"] = i
    return out


def isolated(sc: Scratch) -> list[str]:
    touched = {x for ends in sc.rel_ends.values() for x in ends}
    return sorted(display_name(sc.node_props[n]) for n in sc.node_keys if n not in touched)


def _esc(s) -> str:
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def exhibit_html(
    title: str,
    question: str,
    answer_rows: list[dict],
    columns: list[str],
    ex: list[dict],
    stamp: str,
    verified: bool,
    meta: list[tuple[str, str]],
) -> str:
    """A self-contained, offline exhibit view: the answer, the numbered exhibits, and a small graph drawing."""
    import math

    names = sorted({x["start"] for x in ex} | {x["end"] for x in ex})
    pos = {}
    for i, nme in enumerate(names):
        a = 2 * math.pi * i / max(1, len(names)) - math.pi / 2
        pos[nme] = (300 + 230 * math.cos(a), 270 + 230 * math.sin(a))
    lines = []
    for x in ex:
        (x1, y1), (x2, y2) = pos[x["start"]], pos[x["end"]]
        dx, dy = x2 - x1, y2 - y1
        d = math.hypot(dx, dy) or 1
        x2b, y2b = x2 - dx / d * 22, y2 - dy / d * 22
        mx, my = (x1 + x2) / 2, (y1 + y2) / 2
        lines.append(
            f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2b:.1f}" y2="{y2b:.1f}" class="e" marker-end="url(#a)"/>'
            f'<text x="{mx:.1f}" y="{my:.1f}" class="en">{x["n"]}</text>'
        )
    circles = "".join(
        f'<circle cx="{x:.1f}" cy="{y:.1f}" r="20" class="n"/><text x="{x:.1f}" y="{y + 4:.1f}" class="nl">{_esc(n)}</text>'
        for n, (x, y) in pos.items()
    )
    head = "".join(f"<th>{_esc(c)}</th>" for c in columns)
    body = "".join("<tr>" + "".join(f"<td>{_esc(r.get(c))}</td>" for c in columns) + "</tr>" for r in answer_rows)
    rows = "".join(
        f'<tr><td class="tag">{x["n"]}</td><td>{_esc(x["start"])}</td><td class="t">{_esc(x["type"])}</td>'
        f"<td>{_esc(x['end'])}</td></tr>"
        for x in ex
    )
    meta_html = "".join(f"<dt>{_esc(k)}</dt><dd>{_esc(v)}</dd>" for k, v in meta)
    stamp_cls = "stamp" if verified else "stamp no"
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_esc(title)} — Witness</title>
<style>
:root{{--paper:#F2E8D5;--ink:#1F1A14;--before:#9C978E;--after:#B42318}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--paper);color:var(--ink);
font:16px/1.5 "Source Sans 3","Source Sans Pro",system-ui,sans-serif}}
main{{max-width:1040px;margin:0 auto;padding:40px 24px}}
h1{{font:700 34px/1.15 "Old Standard TT",Georgia,serif;margin:0 0 8px}}
.q{{font-size:19px;max-width:70ch}}.mono,td,th,dt,dd{{font-family:"Fragment Mono",ui-monospace,Menlo,monospace;font-size:14px}}
table{{border-collapse:collapse;width:100%}}th,td{{text-align:left;padding:6px 10px;border-bottom:1px solid var(--before)}}
.grid{{display:grid;grid-template-columns:1fr 1fr;gap:32px;margin-top:28px}}
@media (max-width:820px){{.grid{{grid-template-columns:1fr}}}}
.tag{{color:#fff;background:var(--after);font-weight:700;text-align:center;width:2.6em}}.t{{color:var(--before)}}
.stamp{{display:inline-block;margin:20px 0;padding:8px 14px;border:3px solid var(--after);color:var(--after);
font:700 18px/1 "Fragment Mono",monospace;letter-spacing:.08em;transform:rotate(-1.5deg)}}
.stamp.no{{border-color:var(--ink);color:var(--ink)}}
svg{{width:100%;height:auto;background:rgba(255,255,255,.35);border:1px solid var(--before)}}
.e{{stroke:var(--after);stroke-width:1.6}}.en{{fill:var(--after);font:700 11px monospace}}
.n{{fill:var(--paper);stroke:var(--ink);stroke-width:1.5}}.nl{{font:700 11px monospace;text-anchor:middle;fill:var(--ink)}}
dl{{display:grid;grid-template-columns:max-content 1fr;gap:4px 16px;margin-top:28px}}dt{{color:var(--before)}}dd{{margin:0}}
</style></head><body><main>
<p class="mono">WITNESS · EXHIBIT REGISTER</p>
<h1>{_esc(title)}</h1>
<p class="q">{_esc(question)}</p>
<div class="{stamp_cls}">{_esc(stamp)}</div>
<div class="grid">
<section><h2>The answer</h2><table><tr>{head}</tr>{body}</table>
<h2>Exhibits ({len(ex)} relationships)</h2><table><tr><th>#</th><th>from</th><th>type</th><th>to</th></tr>{rows}</table></section>
<section><h2>The witness graph</h2>
<svg viewBox="0 0 600 540" role="img" aria-label="witness graph, {len(names)} nodes, {len(ex)} relationships">
<defs><marker id="a" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
<path d="M0 0L10 5L0 10z" fill="#B42318"/></marker></defs>{"".join(lines)}{circles}</svg></section>
</div>
<dl>{meta_html}</dl>
</main></body></html>
"""
