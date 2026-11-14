"""Export a witness (the scratch's remaining graph) as a byte-stable CREATE script and a single-file `.rl`."""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("DO_NOT_TRACK", "1")

import relate  # noqa: E402

from .store import Scratch  # noqa: E402


def _lit(v) -> str:
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        return repr(v)
    if isinstance(v, str):
        return "'" + v.replace("\\", "\\\\").replace("'", "\\'") + "'"
    if isinstance(v, (list, tuple)):
        return "[" + ", ".join(_lit(x) for x in v) + "]"
    if isinstance(v, dict):
        return "{" + ", ".join(f"`{k}`: {_lit(v[k])}" for k in sorted(v)) + "}"
    raise TypeError(f"no Cypher literal for {type(v).__name__}")


def cypher_script(sc: Scratch, header: str = "") -> str:
    """One CREATE statement for the whole witness, elements in canonical-key order."""
    nodes = sorted(sc.node_keys, key=lambda n: sc.node_keys[n])
    var = {n: f"n{i}" for i, n in enumerate(nodes)}
    parts = []
    for n in nodes:
        labels = "".join(f":`{lb}`" for lb in sorted(sc.node_labels[n]))
        parts.append(f"({var[n]}{labels} {_lit(sc.node_props[n])})")
    for r in sorted(sc.rel_keys, key=lambda r: sc.rel_keys[r]):
        s, e = sc.rel_ends[r]
        props = sc.rel_props[r]
        p = f" {_lit(props)}" if props else ""
        parts.append(f"({var[s]})-[:`{sc.rel_type[r]}`{p}]->({var[e]})")
    head = "".join(f"// {line}\n" for line in header.splitlines() if line)
    if not parts:
        return head
    return head + "CREATE\n  " + ",\n  ".join(parts) + ";\n"


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
