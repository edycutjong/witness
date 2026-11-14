"""Canonical keys for graph elements and canonical forms for query answers.

Answers are compared as a bag of rows. Graph elements inside rows compare by canonical key (labels/type plus
properties, and endpoint keys for relationships), never by store id. Floats are rounded to 12 significant
digits. Lists compare as bags unless ``strict_lists`` is set.
"""

from __future__ import annotations

import json
from typing import Any


def _round_float(x: float, digits: int) -> float:
    if x != x or x in (float("inf"), float("-inf")):
        return x
    return float(f"{x:.{digits}g}")


def _plain(v: Any, digits: int) -> Any:
    """JSON-safe copy of a property value with floats rounded."""
    if isinstance(v, bool) or v is None or isinstance(v, (int, str)):
        return v
    if isinstance(v, float):
        return _round_float(v, digits)
    if isinstance(v, (list, tuple)):
        return [_plain(x, digits) for x in v]
    if isinstance(v, dict):
        return {str(k): _plain(v[k], digits) for k in sorted(v)}
    return {"__repr__": repr(v)}


def node_key(labels: list[str], props: dict, digits: int = 12) -> str:
    return json.dumps(["N", sorted(labels), _plain(props, digits)], sort_keys=True, separators=(",", ":"))


def rel_key(rtype: str, start_key: str, end_key: str, props: dict, digits: int = 12) -> str:
    return json.dumps(["R", rtype, start_key, end_key, _plain(props, digits)], sort_keys=True, separators=(",", ":"))


def _is_node(v: Any) -> bool:
    return hasattr(v, "labels") and hasattr(v, "properties") and not hasattr(v, "start_node")


def _is_rel(v: Any) -> bool:
    return hasattr(v, "start_node") and hasattr(v, "properties") and hasattr(v, "type")


def canon_value(v: Any, *, strict_lists: bool = False, digits: int = 12, keyer=None) -> Any:
    """A hashable, order-normalised form of one value from a result row."""
    if v is None or isinstance(v, (bool, int, str)):
        return v
    if isinstance(v, float):
        return _round_float(v, digits)
    if _is_node(v):
        return ("node", node_key(list(v.labels), dict(v.properties), digits))
    if _is_rel(v):
        if keyer is None:
            raise ValueError("relationship values need a keyer that resolves endpoint keys")
        return ("rel", keyer(v))
    if hasattr(v, "nodes") and hasattr(v, "relationships"):  # Path
        return (
            "path",
            tuple(canon_value(n, strict_lists=True, digits=digits, keyer=keyer) for n in v.nodes),
            tuple(canon_value(r, strict_lists=True, digits=digits, keyer=keyer) for r in v.relationships),
        )
    if isinstance(v, (list, tuple)):
        items = [canon_value(x, strict_lists=strict_lists, digits=digits, keyer=keyer) for x in v]
        if strict_lists:
            return ("list", tuple(items))
        return ("bag", tuple(sorted(items, key=repr)))
    if isinstance(v, dict):
        return (
            "map",
            tuple(
                (str(k), canon_value(v[k], strict_lists=strict_lists, digits=digits, keyer=keyer)) for k in sorted(v)
            ),
        )
    return ("other", repr(v))


def canon_rows(
    rows: list[dict], columns: list[str] | None = None, *, strict_lists: bool = False, digits: int = 12, keyer=None
) -> tuple:
    """Rows as a sorted bag; each row is a tuple of (column, canonical value)."""
    out = []
    for row in rows:
        cols = columns if columns is not None else list(row.keys())
        out.append(tuple((c, canon_value(row[c], strict_lists=strict_lists, digits=digits, keyer=keyer)) for c in cols))
    return tuple(sorted(out, key=repr))


def digest(canon: tuple) -> str:
    import hashlib

    return hashlib.sha256(repr(canon).encode("utf-8")).hexdigest()[:16]
