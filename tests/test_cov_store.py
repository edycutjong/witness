"""The scratch store: collisions, the relationship-key fallback, stale ids, trial errors, rollback integrity, replay."""

import hashlib

import pytest
import relate

from witness.canon import rel_key
from witness.guard import static_checks
from witness.predicates import answer_of
from witness.store import CollisionError, IntegrityError, Scratch, StaleIdMap, replay, sha256_file


def make_rl(tmp_path, script, name="g.rl"):
    path = tmp_path / name
    db = relate.Database(str(path))
    db.execute(script)
    db.close()
    return path


def test_two_identical_relationships_between_the_same_nodes_are_refused_as_indistinguishable(tmp_path):
    p = make_rl(tmp_path, "CREATE (a:P {name: 'A'}), (b:P {name: 'B'}), (a)-[:R]->(b), (a)-[:R]->(b)")
    with pytest.raises(CollisionError, match="1 content-identical relationships"):
        Scratch.open_copy(p)


def test_a_relationship_that_postdates_the_index_still_gets_its_canonical_key(tiny_rl):
    sc = Scratch.open_copy(tiny_rl)
    sc.db.execute("MATCH (a:P {name: 'B'}), (c:P {name: 'C'}) CREATE (a)-[:NEW {w: 1}]->(c)")  # not in the index
    rel = sc.run("MATCH ()-[r:NEW]->() RETURN r").data[0]["r"]
    assert rel.element_id not in sc.rel_keys
    key = sc.keyer(rel)
    b = next(k for n, k in sc.node_keys.items() if sc.node_props[n]["name"] == "B")
    c = next(k for n, k in sc.node_keys.items() if sc.node_props[n]["name"] == "C")
    assert key == rel_key("NEW", b, c, {"w": 1}) and key != rel_key("NEW", c, b, {"w": 1})
    sc.reindex()  # after a reindex the indexed key and the fallback key agree
    assert sc.rel_keys[rel.element_id] == key
    sc.close()


def test_deleting_a_node_that_is_already_gone_is_a_stale_id_map(tiny_rl):
    sc = Scratch.open_copy(tiny_rl)
    nid = next(n for n, p in sc.node_props.items() if p["name"] == "E")
    sc.commit_delete((), [nid])
    with pytest.raises(StaleIdMap, match="1 nodes, deleted 0"):
        sc._delete((), [nid])
    sc.close()


def test_a_trial_with_a_stale_id_rolls_back_and_raises(tiny_rl):
    sc = Scratch.open_copy(tiny_rl)
    counts = sc.counts()
    rid = next(iter(sc.rel_keys))
    sc.commit_delete([rid], ())
    after = sc.counts()
    other = next(r for r in sc.rel_keys)
    with pytest.raises(StaleIdMap):
        sc.trial("MATCH (n) RETURN count(n) AS c", {}, [other, rid], ())
    assert not sc.db.transaction_active() and sc.counts() == after and after != counts
    sc.close()


def test_a_query_that_errors_inside_a_trial_is_inconclusive_not_fatal(tiny_rl):
    sc = Scratch.open_copy(tiny_rl)
    before = sc.counts()
    t = sc.trial("RETURN toInteger('x') +", {}, (), (), check_counts=before)
    assert t.rows is None and t.columns is None and t.results is None
    assert t.error and t.error.startswith("RelateNativeError")
    assert not sc.db.transaction_active() and sc.counts() == before
    sc.close()


def test_a_runtime_error_in_a_later_statement_discards_the_earlier_statements_results(tiny_rl):
    sc = Scratch.open_copy(tiny_rl)
    ok = ("MATCH (n:P) RETURN count(n) AS c", {})
    t = sc.trial_many([ok, ("UNWIND [1, 0] AS d RETURN 1 / d AS q", {})])
    assert t.error is not None and t.results is None and t.rows is None
    good = sc.trial_many([ok, ("MATCH (n:Q) RETURN count(n) AS c", {})])
    assert good.error is None and good.results[0][0] == [{"c": 4}] and good.results[1][0] == [{"c": 1}]
    assert good.rows == [{"c": 4}] and good.columns == ["c"]
    sc.close()


def test_a_trial_that_leaves_the_store_changed_is_an_integrity_error(tiny_rl):
    sc = Scratch.open_copy(tiny_rl)
    real = sc.counts()
    with pytest.raises(IntegrityError, match="counts after rollback"):
        sc.trial("MATCH (n) RETURN count(n) AS c", {}, (), (), check_counts=(real[0] + 1, real[1]))
    sc.close()


def test_commit_delete_with_a_stale_id_rolls_back_and_keeps_the_index(tiny_rl):
    sc = Scratch.open_copy(tiny_rl)
    rids = list(sc.rel_keys)
    sc.commit_delete([rids[0]], ())
    counts, keys = sc.counts(), dict(sc.rel_keys)
    with pytest.raises(StaleIdMap):
        sc.commit_delete([rids[1], rids[0]], ())  # the second id is already gone
    assert not sc.db.transaction_active()
    assert sc.counts() == counts and sc.rel_keys == keys  # nothing half-applied, index untouched
    sc.close()


def test_commit_delete_of_a_node_drops_its_relationships_from_the_index(tiny_rl):
    sc = Scratch.open_copy(tiny_rl)
    d = next(n for n, p in sc.node_props.items() if p["name"] == "D")
    touching = [r for r, (s, e) in sc.rel_ends.items() if d in (s, e)]
    assert len(touching) == 3
    sc.commit_delete((), [d])
    assert d not in sc.node_keys and not set(touching) & set(sc.rel_keys)
    assert sc.counts() == (4, 3) and len(sc.rel_keys) == 3
    sc.close()


def test_the_in_list_delete_form_deletes_the_same_relationships(tiny_rl):
    from witness.store import DEL_RELS_IN_LIST

    sc = Scratch.open_copy(tiny_rl)
    sc.del_rels_stmt = DEL_RELS_IN_LIST
    rid = next(iter(sc.rel_keys))
    t = sc.trial("MATCH (n) RETURN count(n) AS c", {}, [rid], ())
    assert t.deleted_rels == 1 and t.deleted_nodes == 0 and t.error is None
    sc.close()


def test_the_source_is_only_read_and_a_tmpdir_scratch_is_removed_on_close(tiny_rl, tmp_path):
    before = sha256_file(tiny_rl)
    assert before == hashlib.sha256(tiny_rl.read_bytes()).hexdigest()
    sc = Scratch.open_copy(tiny_rl)
    scratch_path = sc.path
    assert scratch_path.exists() and scratch_path != tiny_rl
    sc.close()
    assert not scratch_path.exists() and sha256_file(tiny_rl) == before
    own = tmp_path / "mine"
    own.mkdir()
    sc2 = Scratch.open_copy(tiny_rl, own)
    sc2.close()
    assert sc2.path.exists() and sc2.path.parent == own  # a caller-owned dir is left alone


def test_answer_matches_between_a_scratch_and_its_replay_in_either_order(tiny_rl):
    sc = Scratch.open_copy(tiny_rl)
    q = "MATCH (a:P {name: 'A'})-[r:R]->(h) RETURN h.name AS h, r AS r"
    base = sc.answer(q)
    for rev in (False, True):
        mem = replay(sc, reverse=rev)
        res = mem.execute(q)
        assert res.data and len(res.data) == 3
        mem.close()
    gq = static_checks(q)
    assert answer_of(gq, sc.run(q).data, ["h", "r"], keyer=sc.keyer) == base
    sc.close()


def test_replay_of_an_empty_graph_and_of_a_graph_without_relationships(tmp_path):
    empty = Scratch.open_copy(make_rl(tmp_path, "RETURN 1", "e.rl"))
    mem = replay(empty)
    assert mem.node_count() == 0 and mem.relationship_count() == 0
    mem.close()
    empty.close()
    nodes_only = Scratch.open_copy(make_rl(tmp_path, "CREATE (:P {n: 1}), (:P {n: 2}), (:Q:P {n: 3})", "n.rl"))
    mem = replay(nodes_only, reverse=True)
    assert mem.node_count() == 3 and mem.relationship_count() == 0
    assert mem.execute("MATCH (n:Q:P) RETURN n.n AS n").data == [{"n": 3}]
    mem.close()
    nodes_only.close()


def test_replay_preserves_relationship_types_properties_and_batches_by_type(tmp_path):
    p = make_rl(
        tmp_path,
        "CREATE (a:P {n: 1})-[:R {w: 1.5}]->(b:P {n: 2}), (b)-[:S {w: 2}]->(a), (a)-[:R {w: 3}]->(b)",
    )
    sc = Scratch.open_copy(p)
    mem = replay(sc)
    rows = mem.execute("MATCH (a)-[r]->(b) RETURN type(r) AS t, r.w AS w, a.n AS a, b.n AS b ORDER BY t, w").data
    assert rows == [
        {"t": "R", "w": 1.5, "a": 1, "b": 2},
        {"t": "R", "w": 3, "a": 1, "b": 2},
        {"t": "S", "w": 2, "a": 2, "b": 1},
    ]
    mem.close()
    sc.close()


class ClosesItself:
    """The real database, except that it ends its own transaction behind Witness's back (an engine-side abort or a
    failed commit); an engine that does this cannot be provoked from Cypher, so it is the one thing stood in for."""

    def __init__(self, db, *, after_execute=False, commit_raises=False):
        self._db = db
        self._after_execute = after_execute
        self._commit_raises = commit_raises

    def __getattr__(self, name):
        return getattr(self._db, name)

    def execute(self, *a, **k):
        res = self._db.execute(*a, **k)
        if self._after_execute and self._db.transaction_active():
            self._db.rollback_transaction()
        return res

    def commit_transaction(self):
        if self._commit_raises:
            self._db.rollback_transaction()
            raise OSError("disk full")
        return self._db.commit_transaction()


def test_a_trial_survives_an_engine_that_already_closed_its_own_transaction(tiny_rl):
    sc = Scratch.open_copy(tiny_rl)
    real = sc.db
    sc.db = ClosesItself(real, after_execute=True)
    t = sc.trial("MATCH (n:P) RETURN count(n) AS c", {}, (), (), check_counts=sc.counts())
    assert t.error is None and t.rows == [{"c": 4}] and not real.transaction_active()
    sc.db = real
    sc.close()


def test_commit_delete_reraises_the_original_error_when_the_transaction_is_already_closed(tiny_rl):
    sc = Scratch.open_copy(tiny_rl)
    real = sc.db
    sc.db = ClosesItself(real, commit_raises=True)
    rid = next(iter(sc.rel_keys))
    before = dict(sc.rel_keys)
    with pytest.raises(OSError, match="disk full"):
        sc.commit_delete([rid], ())
    assert sc.rel_keys == before and real.relationship_count() == len(before)  # nothing committed, index untouched
    sc.db = real
    sc.close()
