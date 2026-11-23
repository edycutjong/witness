"""Sponsor depth 1 + 3: Relate transactions are the inner loop; counts restored after every rollback; the source
store is only ever copied, so its SHA-256 is unchanged after a full reduction."""

from pathlib import Path

from witness.reduce import Reducer
from witness.store import Scratch, sha256_file

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "data" / "air-routes.rl"
PARAMS = {"country": "MX", "dest": "MEX"}


def test_counts_after_every_rollback_on_the_full_graph(tmp_path):
    q = (ROOT / "queries" / "two-hub.cypher").read_text()
    sc = Scratch.open_copy(SRC, tmp_path)
    try:
        base = sc.answer(q, PARAMS, strict_lists=True)
        counts = sc.counts()
        rels = sorted(sc.rel_keys, key=sc.rel_keys.get)[:200]
        for r in rels:
            t = sc.trial(q, PARAMS, [r], (), check_counts=counts)  # raises IntegrityError on any residue
            assert t.error is None and t.deleted_rels == 1
        assert sc.counts() == counts
        assert sc.answer(q, PARAMS, strict_lists=True) == base
    finally:
        sc.close()


def test_source_unchanged_after_a_full_reduction(tmp_path):
    before = sha256_file(SRC)
    q = (ROOT / "queries" / "two-hub.cypher").read_text()
    sc = Scratch.open_copy(SRC, tmp_path)
    out = Reducer(sc, q, PARAMS, strict_lists=True, check_every=1).run()
    sc.close()
    assert out["final_counts"] == (12, 22)
    assert sha256_file(SRC) == before


def test_plan_chunk_drops_unreachable_types_and_keeps_the_answer(tmp_path):
    """Sponsor depth 2: EXPLAIN + relate.plan/v1 -> trial 1 drops ON_CONTINENT; the pruned graph keeps the answer."""
    q = (ROOT / "queries" / "two-hub.cypher").read_text()
    sc = Scratch.open_copy(SRC, tmp_path)
    try:
        red = Reducer(sc, q, PARAMS, strict_lists=True)
        info = red.plan_chunk()
        assert info["dropped_types"] == ["ON_CONTINENT"] and info["dropped_rels"] == 3504
        assert red.stats.log[0]["phase"] == "plan" and red.stats.log[0]["holds"] is True
        assert sc.answer(q, PARAMS, strict_lists=True) == red.baseline
    finally:
        sc.close()
