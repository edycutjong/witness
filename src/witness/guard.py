"""The query guard (W2): a supported, read-only, deterministic subset of Cypher.

Every user-supplied statement passes through ``guard()`` before it runs anywhere: the query, the ``disagree``
reference, the absence companion, and any ``check`` override. Witness's own statements (trial deletes, the export
rebuild) never do; delete counts, node/relationship counts and the source SHA-256 cover those.

Layers, all fail-closed:
1. a token stream (comments and string literals stripped, identifiers case-folded, backticks removed, namespaced
   names joined) checked for write keywords, procedure calls, clock-reading and store-dependent functions;
2. static order rules: one statement; LIMIT/SKIP only after an ORDER BY, and only in the final RETURN;
3. Relate's own ``EXPLAIN`` ``query_type``, which must be ``"r"``;
4. (``order_check``) the same answer from a second store built in reverse canonical order — a heuristic second net,
   not a proof.

The guard defines "a supported query subset". It never claims to prove a query deterministic.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

WRITE_KEYWORDS = {"create", "merge", "set", "delete", "detach", "remove", "foreach"}
REFUSED_FUNCTIONS = {
    "rand": "rand() is random",
    "randomuuid": "randomUUID() is random",
    "uuid": "uuid() is random",
    "timestamp": "timestamp() reads the clock",
    "elementid": "elementId() depends on the store, not the data",
    "id": "id() depends on the store, not the data",
    "shortestpath": "shortestPath() returns one of several tied paths (allShortestPaths() is allowed)",
}
TEMPORALS = {
    "date",
    "time",
    "localtime",
    "datetime",
    "localdatetime",
    "local_datetime",
    "local_time",
    "zoned_time",
    "zoned_datetime",
}
CLOCKS = {"realtime", "statement", "transaction"}
# Map keys that make a temporal map constructor a fixed value (anything else, e.g. only `timezone`, reads the clock:
# the P1a probe showed datetime({timezone: 'UTC'}) changes between two calls on Relate 1.0.1).
TEMPORAL_FIELDS = {
    "year",
    "month",
    "day",
    "week",
    "weekyear",
    "ordinalday",
    "quarter",
    "dayofweek",
    "dayofquarter",
    "hour",
    "minute",
    "second",
    "millisecond",
    "microsecond",
    "nanosecond",
    "epochseconds",
    "epochmillis",
    "date",
    "time",
    "datetime",
}
ORDER_INSENSITIVE_BODIES = {"exists", "count"}  # row order inside these subquery bodies cannot change the result


class Refused(ValueError):
    """The statement is outside the supported subset. ``reason`` is printed and the CLI exits 2."""

    def __init__(self, reason: str, door: str = "query"):
        super().__init__(f"refused ({door}): {reason}")
        self.reason = reason
        self.door = door


@dataclass
class Tok:
    kind: str  # ident | num | str | param | punct
    text: str  # case-folded for idents
    start: int
    end: int
    quoted: bool = False  # backtick identifier


_TOKEN = re.compile(
    r"""
    (?P<ws>\s+)
  | (?P<lc>//[^\n]*)
  | (?P<bc>/\*.*?\*/)
  | (?P<str>'(?:[^'\\]|\\.)*'|"(?:[^"\\]|\\.)*")
  | (?P<bt>`(?:[^`]|``)*`)
  | (?P<param>\$[A-Za-z_][A-Za-z0-9_]*|\$`(?:[^`]|``)*`)
  | (?P<num>\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)
  | (?P<ident>[A-Za-z_][A-Za-z0-9_]*)
  | (?P<punct><>|<=|>=|=~|->|<-|\.\.|[^\s])
    """,
    re.VERBOSE | re.DOTALL,
)


def tokenize(text: str) -> list[Tok]:
    toks: list[Tok] = []
    pos = 0
    while pos < len(text):
        m = _TOKEN.match(text, pos)
        if m is None:  # an unterminated string or comment
            raise Refused("unterminated string, identifier or comment")
        kind = m.lastgroup
        s = m.group(0)
        if kind in ("ws", "lc", "bc"):
            pass
        elif kind == "bt":
            toks.append(Tok("ident", s[1:-1].replace("``", "`").lower(), m.start(), m.end(), quoted=True))
        elif kind == "ident":
            toks.append(Tok("ident", s.lower(), m.start(), m.end()))
        else:
            toks.append(Tok(kind, s, m.start(), m.end()))
        pos = m.end()
    return toks


@dataclass
class Call:
    name: str  # joined, case-folded: "datetime.realtime"
    index: int  # token index of the "("
    args: list[list[Tok]]


def _function_calls(toks: list[Tok]) -> list[Call]:
    calls = []
    for i, t in enumerate(toks):
        if t.kind != "punct" or t.text != "(" or i == 0 or toks[i - 1].kind != "ident":
            continue
        # walk back over ident(.ident)* — a property access followed by "(" is a namespaced function name
        j = i - 1
        parts = [toks[j].text]
        while j >= 2 and toks[j - 1].text == "." and toks[j - 2].kind == "ident":
            parts.insert(0, toks[j - 2].text)
            j -= 2
        # a pattern like (a:Label)( or a node variable followed by "(" is not a call; labels follow ":"
        if j >= 1 and toks[j - 1].text == ":":
            continue
        calls.append(Call(".".join(parts), i, _split_args(toks, i)))
    return calls


def _split_args(toks: list[Tok], open_idx: int) -> list[list[Tok]]:
    depth = 0
    args: list[list[Tok]] = [[]]
    for t in toks[open_idx + 1 :]:
        if t.text in "([{":
            depth += 1
        elif t.text in ")]}":
            if depth == 0:
                break
            depth -= 1
        if depth == 0 and t.text == ",":
            args.append([])
            continue
        args[-1].append(t)
    return [a for a in args if a] if args != [[]] else []


def _literal_map_with_temporal_field(arg: list[Tok]) -> bool:
    """True for a literal map like {year: 2024, month: 1} whose values are all literals and which names a field."""
    if not arg or arg[0].text != "{" or arg[-1].text != "}":
        return False
    inner = arg[1:-1]
    keys = set()
    expect_key = True
    i = 0
    while i < len(inner):
        t = inner[i]
        if expect_key:
            if t.kind != "ident" or i + 1 >= len(inner) or inner[i + 1].text != ":":
                return False
            keys.add(t.text)
            i += 2
            expect_key = False
            continue
        # one literal value (a signed number or a string), then "," or the end
        if t.text == "-" and i + 1 < len(inner) and inner[i + 1].kind == "num":
            i += 1
        elif t.kind not in ("num", "str"):
            return False
        i += 1
        if i < len(inner):
            if inner[i].text != ",":
                return False
            i += 1
        expect_key = True
    return bool(keys & TEMPORAL_FIELDS)


def _check_temporal(call: Call) -> str | None:
    head, _, tail = call.name.rpartition(".")
    base = head if head else tail
    if head and base in TEMPORALS and tail in CLOCKS:
        return f"{call.name}() reads the clock"
    if head:
        return None  # date.truncate(...) etc.: a clock inside its arguments is caught on its own
    if tail not in TEMPORALS:
        return None
    if not call.args:
        return f"{tail}() with no argument reads the clock"
    if len(call.args) == 1:
        a = call.args[0]
        if len(a) == 1 and a[0].kind == "str":
            return None
        if _literal_map_with_temporal_field(a):
            return None
    return f"{tail}(...) needs a literal string or a literal map with a date/time field (other forms read the clock)"


@dataclass
class Cut:
    """ORDER BY + SKIP/LIMIT in the final RETURN. Witness lifts the cut, runs, then applies it itself."""

    order_cols: list[str]
    skip: int
    limit: int | None


@dataclass
class GuardedQuery:
    text: str  # the statement as given (trailing ';' removed)
    params: dict
    exec_text: str  # what actually runs: the text with SKIP/LIMIT lifted when there is a cut
    cut: Cut | None = None
    door: str = "query"
    warnings: list[str] = field(default_factory=list)
    query_type: str | None = None


def _resolve_int(tok: Tok, params: dict, what: str) -> int:
    if tok.kind == "num" and tok.text.isdigit():
        return int(tok.text)
    if tok.kind == "param":
        v = params.get(tok.text[1:].strip("`"))
        if isinstance(v, int) and not isinstance(v, bool) and v >= 0:
            return v
    raise Refused(f"{what} must be a non-negative integer literal or integer parameter")


def static_checks(text: str, params: dict | None = None, door: str = "query") -> GuardedQuery:
    """Token-stream refusals and order rules. Pure text work: no engine involved."""
    params = params or {}
    body = text.strip()
    toks = tokenize(body)
    while toks and toks[-1].text == ";":
        body = body[: toks[-1].start].rstrip()
        toks.pop()
    if not toks:
        raise Refused("empty statement", door)
    if any(t.text == ";" for t in toks):
        raise Refused("one statement only (a ';'-separated script is refused)", door)

    def prev(i):
        return toks[i - 1].text if i > 0 else ""

    def nxt(i):
        return toks[i + 1] if i + 1 < len(toks) else None

    for i, t in enumerate(toks):
        if t.kind != "ident" or t.quoted:
            continue
        if prev(i) in (".", ":"):  # property key or label/type name
            continue
        n = nxt(i)
        if n is not None and n.text == ":" and prev(i) in ("{", ","):  # map key
            continue
        if t.text in WRITE_KEYWORDS:
            raise Refused(f"write keyword {t.text.upper()} (read-only queries only)", door)
        if t.text == "load" and n is not None and n.text == "csv":
            raise Refused("LOAD CSV reads outside the graph", door)
        if t.text == "use":
            raise Refused("USE switches the graph", door)
        if t.text == "in" and n is not None and n.text == "transactions":
            raise Refused("CALL { } IN TRANSACTIONS", door)
        if t.text == "call" and n is not None and n.text not in ("{", "("):
            raise Refused("procedure calls are refused (CALL { } subqueries are allowed)", door)
        if t.text == "shortest" and prev(i) != "all":
            raise Refused("SHORTEST k / ANY SHORTEST picks among tied paths (ALL SHORTEST is allowed)", door)

    for c in _function_calls(toks):
        if c.name in REFUSED_FUNCTIONS:
            raise Refused(REFUSED_FUNCTIONS[c.name], door)
        why = _check_temporal(c)
        if why:
            raise Refused(why, door)

    return _order_rules(body, toks, params, door)


def _order_rules(body: str, toks: list[Tok], params: dict, door: str) -> GuardedQuery:
    # Walk the tokens, tracking brace bodies; a '{' right after EXISTS/COUNT opens an order-insensitive body.
    stack: list[tuple[bool, dict | None]] = []  # (inside an order-insensitive body, the clause open outside it)
    clauses: list[dict] = []  # WITH/RETURN clauses: {"kw", "insensitive", "idx": [token indexes], "depth"}
    cur = None
    for i, t in enumerate(toks):
        if t.text == "{":
            insensitive = (i > 0 and toks[i - 1].kind == "ident" and toks[i - 1].text in ORDER_INSENSITIVE_BODIES) or (
                bool(stack) and stack[-1][0]
            )
            stack.append((insensitive, cur))
            continue
        if t.text == "}":
            if stack:
                cur = stack.pop()[1]
            continue
        insensitive = bool(stack) and stack[-1][0]
        is_kw = t.kind == "ident" and not t.quoted and (i == 0 or toks[i - 1].text not in (".", ":"))
        if is_kw and t.text in ("with", "return"):
            cur = {"kw": t.text, "insensitive": insensitive, "idx": [], "depth": len(stack)}
            clauses.append(cur)
            continue
        if is_kw and t.text in ("match", "optional", "unwind", "call", "union") and cur is not None:
            if len(stack) == cur["depth"]:
                cur = None
            continue
        if cur is not None and len(stack) == cur["depth"]:
            cur["idx"].append(i)

    union = any(t.kind == "ident" and t.text == "union" and not t.quoted for t in toks)
    top = [k for k, cl in enumerate(clauses) if cl["depth"] == 0]
    last_top = top[-1] if top else -1
    cut = None
    exec_text = body
    for ci, cl in enumerate(clauses):
        words = [toks[i] for i in cl["idx"]]
        has = {w.text for w in words if w.kind == "ident" and not w.quoted}
        if not ({"limit", "skip"} & has) or cl["insensitive"]:
            continue
        ordered = any(
            w.text == "order" and k + 1 < len(words) and words[k + 1].text == "by" for k, w in enumerate(words)
        )
        if not ordered:
            raise Refused("LIMIT/SKIP without ORDER BY depends on storage order", door)
        final = cl["kw"] == "return" and ci == last_top
        if not final or union:
            raise Refused("ORDER BY + LIMIT/SKIP is supported only in the final RETURN (no UNION) in v0.1", door)
        cut = _parse_cut(body, words, params, door)
        first = next(w for w in words if w.kind == "ident" and w.text in ("skip", "limit"))
        exec_text = body[: first.start].rstrip()
    return GuardedQuery(text=body, params=params, exec_text=exec_text, cut=cut, door=door)


def _parse_cut(body: str, words: list[Tok], params: dict, door: str) -> Cut:
    k = next(k for k, w in enumerate(words) if w.text == "order" and words[k + 1].text == "by")
    cols: list[str] = []
    j = k + 2
    skip, limit = 0, None
    while j < len(words):
        w = words[j]
        if w.kind == "ident" and w.text in ("skip", "limit"):
            break
        if w.kind != "ident":
            raise Refused("ORDER BY with LIMIT/SKIP must sort by returned column names (no expressions) in v0.1", door)
        cols.append(body[w.start : w.end].strip("`"))
        j += 1
        if j < len(words) and words[j].kind == "ident" and words[j].text in ("asc", "desc", "ascending", "descending"):
            j += 1
        if j < len(words) and words[j].text == ",":
            j += 1
    while j < len(words):
        w = words[j]
        if w.text in ("skip", "offset") and j + 1 < len(words):
            skip = _resolve_int(words[j + 1], params, "SKIP")
            j += 2
        elif w.text == "limit" and j + 1 < len(words):
            limit = _resolve_int(words[j + 1], params, "LIMIT")
            j += 2
        else:
            raise Refused("unsupported tokens after ORDER BY ... SKIP/LIMIT", door)
    return Cut(order_cols=cols, skip=skip, limit=limit)


class Tie:
    """A tie straddles the SKIP/LIMIT cut: which rows fall inside depends on storage order."""

    def __init__(self, rows):
        self.rows = rows

    def __repr__(self) -> str:
        return f"Tie({self.rows!r})"


def apply_cut(rows: list[dict], columns: list[str], cut: Cut, key) -> list[dict] | Tie:
    """Apply SKIP/LIMIT to rows already sorted by the engine; a tie at either boundary returns ``Tie``."""
    missing = [c for c in cut.order_cols if c not in columns]
    if missing:
        raise Refused(f"ORDER BY with LIMIT/SKIP must sort by returned columns; not returned: {missing}")

    def sk(r):
        return tuple(key(r[c]) for c in cut.order_cols)

    lo = cut.skip
    hi = len(rows) if cut.limit is None else min(len(rows), cut.skip + cut.limit)
    for b in (lo, hi):
        if 0 < b < len(rows) and sk(rows[b - 1]) == sk(rows[b]):
            return Tie([rows[b - 1], rows[b]])
    return rows[lo:hi]


def engine_checks(gq: GuardedQuery, db) -> GuardedQuery:
    """Relate's own classification: EXPLAIN must report query_type 'r'. Relate itself refuses two statements."""
    try:
        res = db.execute("EXPLAIN " + gq.exec_text, gq.params)
    except Exception as e:  # noqa: BLE001
        raise Refused(f"Relate could not plan it: {type(e).__name__}: {e}", gq.door) from e
    qt = getattr(res, "query_type", None) or getattr(getattr(res, "summary", None), "query_type", None)
    gq.query_type = qt
    if qt != "r":
        raise Refused(f"Relate reports query_type {qt!r}; only read queries ('r') are supported", gq.door)
    return gq


def guard(text: str, params: dict | None, db, door: str = "query") -> GuardedQuery:
    """Static checks, then Relate's query_type. The order check runs separately (it needs a second store)."""
    return engine_checks(static_checks(text, params, door), db)


def strip_comments(text: str) -> str:
    """The statement without // and /* */ comments (string literals untouched), on one line, trailing ';' removed."""
    out = []
    pos = 0
    while pos < len(text):
        m = _TOKEN.match(text, pos)
        if m is None:
            out.append(text[pos:])
            break
        if m.lastgroup in ("lc", "bc"):
            out.append(" ")
        elif m.lastgroup == "ws":
            out.append(" ")
        else:
            out.append(m.group(0))
        pos = m.end()
    return re.sub(r"\s+", " ", "".join(out)).strip().rstrip(";").strip()
