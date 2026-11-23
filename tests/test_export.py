"""Export round-trip: a witness's CREATE script rebuilds the same graph, value for value and type for type."""

import relate

from witness.export import _lit, cypher_script, write_rl
from witness.store import Scratch

TRICKY_STRINGS = {
    "crlf_comment": "line1\r\n// not a comment x",
    "tab": "a\tb",
    "quote_backslash": "it's a \\ path",
    "unicode": "Zürich é 中",
    "nul_and_seps": "a\x00b\x85c d\x1ce",
}


def _source(tmp_path):
    src = tmp_path / "src.rl"
    db = relate.Database(str(src))
    db.execute(
        "CREATE (a:`We``ird` $s)-[:`RE``L` {since: date('2024-01-02'), w: 1.0/0.0, n: 0.0/0.0}]->"
        "(b:B {d: datetime('2024-01-02T03:04:05.123456789+07:00'), z: datetime('2024-01-02T03:04:05[Europe/Paris]'),"
        " ldt: localdatetime('2024-01-02T03:04:05.5'), t: time('03:04:05+01:00'), lt: localtime('03:04:05.000000001'),"
        " du: duration('P1Y2M3DT4H5M6.5S'), p: point({x: 1.5, y: 2.0}), g: point({latitude: 1.0, longitude: 2.0}),"
        " p3: point({x: 1.0, y: 2.0, z: 3.0}), xs: [3, 1, 2], fs: [2.5, 1.0], ss: ['b', 'a'], bs: [true, false],"
        " neg: -0.0, big: 1e300})",
        {"s": TRICKY_STRINGS},
    )
    db.close()
    return src


def test_round_trip_keeps_every_value_and_type(tmp_path):
    src = _source(tmp_path)
    sc = Scratch.open_copy(src, tmp_path)
    script = cypher_script(sc, "header line\nsecond header")
    keys = (set(sc.node_keys.values()), set(sc.rel_keys.values()))
    props = sorted(map(repr, sc.node_props.values()))
    sc.close()
    # one script line per element: no value spans a line, so the `//` header strip cannot cut a value
    assert all(not line.lstrip().startswith("//") for line in script.splitlines()[2:])
    rebuilt = tmp_path / "rebuilt.rl"
    assert write_rl(script, rebuilt) == (2, 1)
    sc2 = Scratch.open_copy(rebuilt, tmp_path)
    try:
        assert (set(sc2.node_keys.values()), set(sc2.rel_keys.values())) == keys
        assert sorted(map(repr, sc2.node_props.values())) == props
        a = next(p for p in sc2.node_props.values() if "crlf_comment" in p)
        assert a == TRICKY_STRINGS
    finally:
        sc2.close()


def test_string_literal_never_holds_a_raw_line_break():
    lit = _lit("a\r\nb c\x85d")
    assert lit.splitlines() == [lit]
    assert "\\u000D" in lit and "\\u000A" in lit
