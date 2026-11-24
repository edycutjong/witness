"""The scratch store: a writable temp copy of a source `.rl`, indexed by canonical key.

The source file is only ever byte-copied (and read), never opened for writing. Trials run inside Relate
transactions on the copy: begin -> delete -> query -> rollback.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

os.environ.setdefault("DO_NOT_TRACK", "1")

import relate  # noqa: E402

from .canon import canon_rows, cypher_name, node_key, rel_key  # noqa: E402

NODES_Q = "MATCH (n) RETURN elementId(n) AS id, labels(n) AS labels, properties(n) AS props"
RELS_Q = (
    "MATCH (a)-[r]->(b) RETURN elementId(r) AS id, type(r) AS type, elementId(a) AS s, "
    "elementId(b) AS e, properties(r) AS props"
)
# Trial deletes. The spike measured both forms on the full graph (evidence/spike-*.md): the IN-list form scans every
# relationship (~41 ms/trial), the UNWIND form resolves each elementId directly (~2.6 ms/trial). UNWIND is the default.
DEL_RELS_IN_LIST = "MATCH ()-[r]->() WHERE elementId(r) IN $ids DELETE r RETURN count(*) AS c"
DEL_RELS = "UNWIND $ids AS i MATCH ()-[r]->() WHERE elementId(r) = i DELETE r RETURN count(*) AS c"
DEL_NODES = "UNWIND $ids AS i MATCH (n) WHERE elementId(n) = i DETACH DELETE n RETURN count(*) AS c"


class StaleIdMap(RuntimeError):
    """A delete removed fewer elements than asked: the id map no longer matches the store."""


class IntegrityError(RuntimeError):
    """Counts after a rollback differ from the counts before the trial."""


class CollisionError(ValueError):
    """Two elements share a canonical key; Witness needs distinguishable elements."""


@dataclass
class TrialResult:
    rows: list | None  # the first statement's rows (kept for the spike bench)
    columns: list | None
    error: str | None
    ms: float
    deleted_rels: int = 0
    deleted_nodes: int = 0
    results: list | None = None  # [(rows, columns)] per statement, None on error


def sha256_file(path: str | Path) -> str:
    import hashlib

    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


@dataclass
class Scratch:
    source: Path
    path: Path
    db: relate.Database
    node_keys: dict[str, str] = field(default_factory=dict)  # elementId -> canonical key
    rel_keys: dict[str, str] = field(default_factory=dict)
    rel_ends: dict[str, tuple[str, str]] = field(default_factory=dict)  # rel elementId -> (start, end) node ids
    rel_type: dict[str, str] = field(default_factory=dict)
    node_labels: dict[str, list[str]] = field(default_factory=dict)
    node_props: dict[str, dict] = field(default_factory=dict)
    rel_props: dict[str, dict] = field(default_factory=dict)
    del_rels_stmt: str = DEL_RELS
    _tmp: tempfile.TemporaryDirectory | None = None

    # ---- construction -------------------------------------------------------------------------
    @classmethod
    def open_copy(cls, source: str | Path, tmpdir: str | Path | None = None) -> Scratch:
        source = Path(source)
        tmp = None
        if tmpdir is None:
            tmp = tempfile.TemporaryDirectory(prefix="witness-")
            tmpdir = tmp.name
        path = Path(tmpdir) / f"scratch-{time.monotonic_ns()}.rl"
        shutil.copyfile(source, path)
        sc = cls(source=source, path=path, db=relate.Database(str(path)), _tmp=tmp)
        sc.reindex()
        return sc

    def reindex(self) -> None:
        nodes = self.db.execute(NODES_Q).data
        self.node_keys, self.node_labels, self.node_props = {}, {}, {}
        for r in nodes:
            self.node_labels[r["id"]] = list(r["labels"])
            self.node_props[r["id"]] = dict(r["props"])
            self.node_keys[r["id"]] = node_key(r["labels"], r["props"])
        if len(set(self.node_keys.values())) != len(self.node_keys):
            raise CollisionError(f"{len(self.node_keys) - len(set(self.node_keys.values()))} content-identical nodes")
        rels = self.db.execute(RELS_Q).data
        self.rel_keys, self.rel_ends, self.rel_type, self.rel_props = {}, {}, {}, {}
        for r in rels:
            self.rel_ends[r["id"]] = (r["s"], r["e"])
            self.rel_type[r["id"]] = r["type"]
            self.rel_props[r["id"]] = dict(r["props"])
            self.rel_keys[r["id"]] = rel_key(r["type"], self.node_keys[r["s"]], self.node_keys[r["e"]], r["props"])
        if len(set(self.rel_keys.values())) != len(self.rel_keys):
            raise CollisionError(
                f"{len(self.rel_keys) - len(set(self.rel_keys.values()))} content-identical relationships"
            )

    def close(self) -> None:
        try:
            self.db.close()
        finally:
            if self._tmp is not None:
                self._tmp.cleanup()

    # ---- reads --------------------------------------------------------------------------------
    def counts(self) -> tuple[int, int]:
        return self.db.node_count(), self.db.relationship_count()

    def keyer(self, rel) -> str:
        """Canonical key of a relationship value from a result row."""
        rid = rel.element_id
        if rid in self.rel_keys:
            return self.rel_keys[rid]
        return rel_key(
            rel.type,
            self.node_keys[rel.start_node_element_id],
            self.node_keys[rel.end_node_element_id],
            dict(rel.properties),
        )

    def run(self, query: str, params: dict | None = None):
        return self.db.execute(query, params or {})

    def answer(self, query: str, params: dict | None = None, strict_lists: bool = False) -> tuple:
        res = self.run(query, params)
        return canon_rows(res.data, res.columns, strict_lists=strict_lists, keyer=self.keyer)

    # ---- trials -------------------------------------------------------------------------------
    def _delete(self, rel_ids, node_ids) -> tuple[int, int]:
        """Relationships first, then nodes (DETACH), so neither count includes the other's cascade."""
        dn = dr = 0
        if rel_ids:
            res = self.db.execute(self.del_rels_stmt, {"ids": list(rel_ids)})
            dr = res.stats.get("relationships_deleted", 0)
            if dr != len(rel_ids) or res.data[0]["c"] != len(rel_ids):
                raise StaleIdMap(f"asked to delete {len(rel_ids)} relationships, deleted {dr}")
        if node_ids:
            res = self.db.execute(DEL_NODES, {"ids": list(node_ids)})
            dn = res.stats.get("nodes_deleted", 0)
            if dn != len(node_ids) or res.data[0]["c"] != len(node_ids):
                raise StaleIdMap(f"asked to delete {len(node_ids)} nodes, deleted {dn}")
        return dr, dn

    def trial(
        self,
        query: str,
        params: dict | None = None,
        rel_ids=(),
        node_ids=(),
        check_counts: tuple[int, int] | None = None,
    ) -> TrialResult:
        """begin -> delete -> query -> rollback. Errors make the trial inconclusive (error set, rows None)."""
        return self.trial_many([(query, params or {})], rel_ids, node_ids, check_counts)

    def trial_many(
        self,
        statements: list[tuple[str, dict]],
        rel_ids=(),
        node_ids=(),
        check_counts: tuple[int, int] | None = None,
    ) -> TrialResult:
        """begin -> delete -> every statement -> rollback, in one transaction."""
        t0 = time.perf_counter()
        self.db.begin_transaction()
        results: list[tuple[Any, Any]] | None = None
        err: str | None = None
        dr = dn = 0
        try:
            dr, dn = self._delete(rel_ids, node_ids)
            results = []
            for q, p in statements:
                res = self.db.execute(q, p or {})
                results.append((res.data, res.columns))
        except StaleIdMap:
            self.db.rollback_transaction()
            raise
        except Exception as e:  # noqa: BLE001 - any engine error makes the trial inconclusive
            err = f"{type(e).__name__}: {e}"
            results = None
        finally:
            if self.db.transaction_active():
                self.db.rollback_transaction()
        ms = (time.perf_counter() - t0) * 1000
        if check_counts is not None and self.counts() != check_counts:
            raise IntegrityError(f"counts after rollback {self.counts()} != {check_counts}")
        first = results[0] if results else (None, None)
        return TrialResult(first[0], first[1], err, ms, dr, dn, results)

    def commit_delete(self, rel_ids=(), node_ids=()) -> None:
        self.db.begin_transaction()
        try:
            self._delete(rel_ids, node_ids)
            self.db.commit_transaction()
        except Exception:
            if self.db.transaction_active():
                self.db.rollback_transaction()
            raise
        gone = set(node_ids)
        for n in gone:
            self.node_keys.pop(n, None)
            self.node_labels.pop(n, None)
            self.node_props.pop(n, None)
        drop = set(rel_ids) | {r for r, (s, e) in self.rel_ends.items() if s in gone or e in gone}
        for r in drop:
            for m in (self.rel_keys, self.rel_ends, self.rel_type, self.rel_props):
                m.pop(r, None)


def replay(sc: Scratch, reverse: bool = False) -> relate.Database:
    """Rebuild the scratch's graph into a fresh `:memory:` store, elements in canonical-key order (or reversed).

    Used by the guard's order check (a second store in reverse order). Nodes are created per label set with batched
    UNWIND; relationships are wired by the new elementIds, so no helper property is ever added to the graph.
    """
    mem = relate.Database(":memory:")
    nodes = sorted(sc.node_keys, key=lambda n: sc.node_keys[n], reverse=reverse)
    new_id: dict[str, str] = {}
    batch: list[str] = []

    def flush_nodes(group: list[str]) -> None:
        labels = "".join(f":{cypher_name(lb)}" for lb in sorted(sc.node_labels[group[0]]))
        rows = [{"i": i, "p": sc.node_props[n]} for i, n in enumerate(group)]
        stmt = f"UNWIND $rows AS r CREATE (n{labels}) SET n = r.p RETURN r.i AS i, elementId(n) AS id"
        out = mem.execute(stmt, {"rows": rows})
        for row in out.data:
            new_id[group[row["i"]]] = row["id"]

    for n in nodes:  # consecutive runs of one label set keep the canonical creation order
        if batch and (sorted(sc.node_labels[batch[-1]]) != sorted(sc.node_labels[n]) or len(batch) >= 2000):
            flush_nodes(batch)
            batch = []
        batch.append(n)
    if batch:
        flush_nodes(batch)
    rels = sorted(sc.rel_keys, key=lambda r: sc.rel_keys[r], reverse=reverse)
    batch = []

    def flush_rels(group: list[str]) -> None:
        rows = [{"s": new_id[sc.rel_ends[r][0]], "e": new_id[sc.rel_ends[r][1]], "p": sc.rel_props[r]} for r in group]
        mem.execute(
            "UNWIND $rows AS r MATCH (a) WHERE elementId(a) = r.s MATCH (b) WHERE elementId(b) = r.e "
            f"CREATE (a)-[x:{cypher_name(sc.rel_type[group[0]])}]->(b) SET x = r.p",
            {"rows": rows},
        )

    for r in rels:
        if batch and (sc.rel_type[batch[-1]] != sc.rel_type[r] or len(batch) >= 2000):
            flush_rels(batch)
            batch = []
        batch.append(r)
    if batch:
        flush_rels(batch)
    return mem
