import hashlib

import pytest

from witness.store import CollisionError, Scratch, StaleIdMap

Q = "MATCH (a:P {name: 'A'})-[:R]->(h)-[:R]->(:P {name: 'D'}) RETURN count(DISTINCT h) AS hubs"


def test_rollback_restores_counts_and_answer(tiny_rl):
    before = hashlib.sha256(tiny_rl.read_bytes()).hexdigest()
    sc = Scratch.open_copy(tiny_rl)
    counts = sc.counts()
    base = sc.run(Q).data
    rid = next(r for r, t in sc.rel_type.items() if t == "R")
    t = sc.trial(Q, {}, [rid], (), check_counts=counts)
    assert t.error is None and t.deleted_rels == 1
    assert sc.counts() == counts
    assert sc.run(Q).data == base
    sc.close()
    assert hashlib.sha256(tiny_rl.read_bytes()).hexdigest() == before  # source never written


def test_read_your_writes_inside_the_transaction(tiny_rl):
    sc = Scratch.open_copy(tiny_rl)
    ab = next(
        r for r, (s, e) in sc.rel_ends.items() if sc.node_props[s]["name"] == "A" and sc.node_props[e]["name"] == "B"
    )
    t = sc.trial(Q, {}, [ab], ())
    assert t.rows == [{"hubs": 1}]
    assert sc.run(Q).data == [{"hubs": 2}]
    sc.close()


def test_stale_id_map_aborts(tiny_rl):
    sc = Scratch.open_copy(tiny_rl)
    rid = next(iter(sc.rel_keys))
    sc.commit_delete([rid], ())
    with pytest.raises(StaleIdMap):
        sc._delete([rid], ())
    sc.db.rollback_transaction() if sc.db.transaction_active() else None
    sc.close()


def test_collisions_are_refused(tmp_path):
    import relate

    p = tmp_path / "dup.rl"
    db = relate.Database(str(p))
    db.execute("CREATE (:P {name: 'same'}), (:P {name: 'same'})")
    db.close()
    with pytest.raises(CollisionError):
        Scratch.open_copy(p)
