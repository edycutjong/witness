"""``--other-engine``: one query, two engines, the same trial graph.

The predicate is ``disagree`` with the same query on both sides: Q on the pinned relate-db in this process, and Q on
another engine that holds the same graph and receives the same deletions. A trial holds when the two engines still give
different answers. Two kinds of other engine:

- ``relate-db==X.Y.Z``: a worker process on that Relate release (``uv run --no-project --with relate-db==X.Y.Z``),
  on its own byte copy of the store. ``python:/path/to/python`` runs the worker on an interpreter that already has
  a relate-db.
- ``neo4j``: a Neo4j database over Bolt (``NEO4J_BOLT`` / ``NEO4J_USER`` / ``NEO4J_PASSWORD`` / ``NEO4J_DATABASE``, from
  the environment or ``~/.config/witness/neo4j.env``). The database must be empty; the graph is loaded once, every trial
  is an explicit transaction (delete, query, rollback) and the loaded graph is removed on close.

Deletions cross the boundary as canonical keys (labels, type, properties and endpoints), never as element ids, so the
two sides never need to agree on ids. Answers cross back as the repr of their canonical form, the relation
``same_answer`` compares. An answer the other engine cannot give (an error, a tie at a cut) is inconclusive, never
proof.
"""

from __future__ import annotations

import contextlib
import json
import os
import subprocess
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .guard import Cut, GuardedQuery, Refused, Tie
from .predicates import answer_of

WORKER_MODULE = "witness.engine_worker"
NEO4J_KEYS = ("NEO4J_BOLT", "NEO4J_USER", "NEO4J_PASSWORD", "NEO4J_DATABASE")


class Remote:
    """A canonical answer computed by the other engine, carried as its repr (all ``same_answer`` compares)."""

    def __init__(self, text: str):
        self.text = text

    def __repr__(self) -> str:
        return self.text


@dataclass
class EngineAnswer:
    answer: Any  # Remote | Tie | None
    error: str | None
    ms: float


def query_spec(gq: GuardedQuery) -> dict:
    return {
        "text": gq.text,
        "exec_text": gq.exec_text,
        "params": gq.params,
        "cut": asdict(gq.cut) if gq.cut is not None else None,
    }


def query_from_spec(d: dict) -> GuardedQuery:
    cut = Cut(**d["cut"]) if d.get("cut") else None
    return GuardedQuery(text=d["text"], params=d["params"], exec_text=d["exec_text"], cut=cut, door="--other-engine")


def wire_answer(ans) -> dict:
    """The answer as it crosses a process boundary."""
    if isinstance(ans, Tie):
        return {"tie": True, "answer": repr(ans)}
    return {"tie": False, "answer": repr(ans)}


def from_wire(d: dict) -> EngineAnswer:
    if d.get("error"):
        return EngineAnswer(None, d["error"], d.get("ms", 0.0))
    ans: Any = Tie(d["answer"]) if d.get("tie") else Remote(d["answer"])
    return EngineAnswer(ans, None, d.get("ms", 0.0))


def parse_engine(spec: str) -> tuple[str, str]:
    """``relate-db==1.3.0`` -> ("relate", "1.3.0"); ``python:/p`` -> ("python", "/p"); ``neo4j`` -> ("neo4j", "")."""
    s = (spec or "").strip()
    if s.startswith("relate-db=="):
        v = s[len("relate-db==") :]
        if not v or not all(part.isdigit() for part in v.split(".")) or v.count(".") != 2:
            raise Refused(f"--other-engine relate-db==X.Y.Z needs an exact release, got {spec!r}", "other-engine")
        return "relate", v
    if s.startswith("python:") and len(s) > len("python:"):
        return "python", s[len("python:") :]
    if s == "neo4j":
        return "neo4j", ""
    raise Refused(
        f"unknown --other-engine {spec!r}; use relate-db==X.Y.Z, python:/path/to/python or neo4j", "other-engine"
    )


class WorkerEngine:
    """The same query on another relate-db, in a worker process speaking JSON lines (see ``engine_worker``)."""

    def __init__(self, spec: str, source: str | Path, gq: GuardedQuery, *, strict_lists=False, digits=12):
        kind, arg = parse_engine(spec)
        if kind == "relate":
            cmd = ["uv", "run", "--no-project", "--quiet", "--with", f"relate-db=={arg}", "python"]
        else:
            cmd = [arg]
        self._tmp = tempfile.TemporaryDirectory(prefix="witness-engine-")
        spec_path = Path(self._tmp.name) / "spec.json"
        spec_path.write_text(
            json.dumps(
                {
                    "source": str(Path(source).resolve()),
                    "query": query_spec(gq),
                    "strict_lists": strict_lists,
                    "digits": digits,
                }
            )
        )
        src_dir = str(Path(__file__).resolve().parent.parent)
        env = {**os.environ, "DO_NOT_TRACK": "1", "PYTHONPATH": src_dir + os.pathsep + os.environ.get("PYTHONPATH", "")}
        try:
            self.proc = subprocess.Popen(
                [*cmd, "-m", WORKER_MODULE, str(spec_path)],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=env,
                start_new_session=True,
            )
        except OSError as e:
            self._tmp.cleanup()
            raise Refused(f"--other-engine {spec}: cannot start the worker ({e})", "other-engine") from e
        hello = self._read()
        if hello is None:
            err = self._stderr_tail()
            self.close()
            raise Refused(f"--other-engine {spec}: the worker did not start: {err}", "other-engine")
        self.version = hello["relate_db"]
        self.label = f"relate-db {self.version}"
        self.counts = (hello["nodes"], hello["relationships"])

    def _stderr_tail(self) -> str:
        """The last stderr line of a worker that has stopped answering (it is killed first, so this never blocks)."""
        self.proc.kill()
        self.proc.wait(5)
        assert self.proc.stderr is not None
        lines = self.proc.stderr.read().strip().splitlines()
        return lines[-1][:200] if lines else "no output"

    def _read(self) -> dict | None:
        assert self.proc.stdout is not None
        line = self.proc.stdout.readline()
        return json.loads(line) if line else None

    def _call(self, msg: dict) -> dict:
        assert self.proc.stdin is not None
        try:
            self.proc.stdin.write(json.dumps(msg) + "\n")
            self.proc.stdin.flush()
        except OSError as e:  # BrokenPipeError: the worker is gone
            return {"error": f"worker gone: {e}"}
        return self._read() or {"error": f"worker gone: {self._stderr_tail()}"}

    def answer(self, rel_keys=(), node_keys=()) -> EngineAnswer:
        return from_wire(self._call({"op": "trial", "rels": list(rel_keys), "nodes": list(node_keys)}))

    def commit(self, rel_keys=(), node_keys=()) -> None:
        out = self._call({"op": "commit", "rels": list(rel_keys), "nodes": list(node_keys)})
        if out.get("error"):
            raise RuntimeError(f"other engine commit failed: {out['error']}")

    def close(self) -> None:
        if self.proc.poll() is None:
            self._call({"op": "stop"})
        self.proc.kill()  # a no-op once the worker has exited
        self.proc.wait(10)
        for f in (self.proc.stdin, self.proc.stdout, self.proc.stderr):
            with contextlib.suppress(OSError):  # closing stdin flushes into a worker that may be gone
                f.close()  # type: ignore[union-attr]
        self._tmp.cleanup()


def read_env_file(path: Path) -> dict:
    out = {}
    if path.exists():
        for line in path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def neo4j_settings(env: dict | None = None, path: Path | None = None) -> dict:
    """Bolt settings: the environment first, then ``~/.config/witness/neo4j.env``. Never printed."""
    src: dict = dict(os.environ) if env is None else env
    f = read_env_file(path or Path.home() / ".config" / "witness" / "neo4j.env")
    out = {k: src.get(k) or f.get(k) for k in NEO4J_KEYS}
    if not out["NEO4J_BOLT"] or not out["NEO4J_USER"] or not out["NEO4J_PASSWORD"]:
        raise Refused(
            "--other-engine neo4j needs NEO4J_BOLT, NEO4J_USER and NEO4J_PASSWORD "
            "(environment or ~/.config/witness/neo4j.env)",
            "other-engine",
        )
    out["NEO4J_DATABASE"] = out["NEO4J_DATABASE"] or "neo4j"
    return out


DEL_RELS = "UNWIND $ids AS i MATCH ()-[r]->() WHERE elementId(r) = i DELETE r"
DEL_NODES = "UNWIND $ids AS i MATCH (n) WHERE elementId(n) = i DETACH DELETE n"


class Neo4jEngine:
    """The same query on Neo4j over Bolt. The graph comes from ``sc`` (a ``store.Scratch``), loaded once."""

    def __init__(self, sc, gq: GuardedQuery, *, strict_lists=False, digits=12, driver=None, settings=None):
        self.gq = gq
        self.strict_lists = strict_lists
        self.digits = digits
        if driver is None:
            try:
                from neo4j import GraphDatabase  # type: ignore[import-not-found]
            except ImportError as e:
                msg = "--other-engine neo4j needs the neo4j driver: uv run --with neo4j ..."
                raise Refused(msg, "other-engine") from e
            settings = settings or neo4j_settings()
            driver = GraphDatabase.driver(
                settings["NEO4J_BOLT"], auth=(settings["NEO4J_USER"], settings["NEO4J_PASSWORD"])
            )
        self.database = (settings or {}).get("NEO4J_DATABASE") or "neo4j"
        self.driver = driver
        self.node_ids: dict[str, str] = {}  # canonical key -> Neo4j element id
        self.rel_ids: dict[str, str] = {}
        try:
            with self.driver.session(database=self.database) as s:
                rec = s.run("CALL dbms.components() YIELD versions RETURN versions[0] AS v").single()
                self.version = rec["v"] if rec else "unknown"
                if s.run("MATCH (n) RETURN count(n) AS c").single()["c"]:
                    raise Refused(
                        "--other-engine neo4j: the Neo4j database is not empty; Witness loads the graph into an empty "
                        "database and removes it again on close",
                        "other-engine",
                    )
            self.label = f"Neo4j {self.version}"
            self._load(sc)
        except Exception:
            self.close()
            raise
        self.counts = (len(self.node_ids), len(self.rel_ids))

    def _load(self, sc, batch: int = 2000) -> None:
        from .canon import cypher_name

        groups: dict[tuple, list[str]] = {}
        for nid, labels in sc.node_labels.items():
            groups.setdefault(tuple(sorted(labels)), []).append(nid)
        with self.driver.session(database=self.database) as s:
            for labels, ids in sorted(groups.items()):
                lab = "".join(":" + cypher_name(x) for x in labels)
                for i in range(0, len(ids), batch):
                    chunk = ids[i : i + batch]
                    rows = [{"k": sc.node_keys[n], "p": sc.node_props[n]} for n in chunk]
                    stmt = f"UNWIND $rows AS r CREATE (n{lab}) SET n = r.p RETURN r.k AS k, elementId(n) AS id"
                    for rec in s.run(stmt, rows=rows):
                        self.node_ids[rec["k"]] = rec["id"]
            by_type: dict[str, list[str]] = {}
            for rid, t in sc.rel_type.items():
                by_type.setdefault(t, []).append(rid)
            for t, ids in sorted(by_type.items()):
                for i in range(0, len(ids), batch):
                    chunk = ids[i : i + batch]
                    rows = [
                        {
                            "k": sc.rel_keys[r],
                            "s": self.node_ids[sc.node_keys[sc.rel_ends[r][0]]],
                            "e": self.node_ids[sc.node_keys[sc.rel_ends[r][1]]],
                            "p": sc.rel_props[r],
                        }
                        for r in chunk
                    ]
                    stmt = (
                        "UNWIND $rows AS r MATCH (a) WHERE elementId(a) = r.s MATCH (b) WHERE elementId(b) = r.e "
                        f"CREATE (a)-[x:{cypher_name(t)}]->(b) SET x = r.p RETURN r.k AS k, elementId(x) AS id"
                    )
                    for rec in s.run(stmt, rows=rows):
                        self.rel_ids[rec["k"]] = rec["id"]

    def _ids(self, rel_keys, node_keys) -> tuple[list[str], list[str]]:
        missing = [k for k in rel_keys if k not in self.rel_ids] + [k for k in node_keys if k not in self.node_ids]
        if missing:
            raise KeyError(f"{len(missing)} element(s) not on the other engine")
        return [self.rel_ids[k] for k in rel_keys], [self.node_ids[k] for k in node_keys]

    def answer(self, rel_keys=(), node_keys=()) -> EngineAnswer:
        t0 = time.perf_counter()
        try:
            rids, nids = self._ids(rel_keys, node_keys)
            with self.driver.session(database=self.database) as s:
                tx = s.begin_transaction()
                try:
                    if rids:
                        tx.run(DEL_RELS, ids=rids).consume()
                    if nids:
                        tx.run(DEL_NODES, ids=nids).consume()
                    res = tx.run(self.gq.exec_text, self.gq.params)
                    cols = list(res.keys())
                    rows = [dict(zip(cols, rec.values(), strict=True)) for rec in res]
                finally:
                    tx.rollback()
            if any(_graph_value(v) for r in rows for v in r.values()):
                raise ValueError("Neo4j returned graph values; return properties or ids to compare across engines")
            ans = answer_of(self.gq, rows, cols, strict_lists=self.strict_lists, digits=self.digits)
        except Exception as e:  # noqa: BLE001 - any engine error is inconclusive
            return EngineAnswer(None, f"{type(e).__name__}: {str(e)[:300]}", (time.perf_counter() - t0) * 1000)
        ms = (time.perf_counter() - t0) * 1000
        return from_wire({**wire_answer(ans), "ms": ms})

    def commit(self, rel_keys=(), node_keys=()) -> None:
        rids, nids = self._ids(rel_keys, node_keys)
        with self.driver.session(database=self.database) as s:
            with s.begin_transaction() as tx:
                if rids:
                    tx.run(DEL_RELS, ids=rids).consume()
                if nids:
                    tx.run(DEL_NODES, ids=nids).consume()
                tx.commit()
        for k in rel_keys:
            self.rel_ids.pop(k, None)
        for k in node_keys:
            self.node_ids.pop(k, None)

    def close(self) -> None:
        """Remove every node this engine created (its relationships go with it), then close the driver."""
        try:
            ids = list(self.node_ids.values())
            if ids:
                with self.driver.session(database=self.database) as s:
                    for i in range(0, len(ids), 2000):
                        s.run(DEL_NODES, ids=ids[i : i + 2000]).consume()
            self.node_ids, self.rel_ids = {}, {}
        finally:
            self.driver.close()


def _graph_value(v) -> bool:
    if isinstance(v, list):
        return any(_graph_value(x) for x in v)
    if isinstance(v, dict):
        return any(_graph_value(x) for x in v.values())
    return type(v).__module__.startswith("neo4j.graph")


def open_engine(spec: str, source: str | Path, gq: GuardedQuery, *, sc=None, strict_lists=False, digits=12):
    """Open the other engine on ``source`` (a worker) or from ``sc`` (Neo4j loads the graph the Scratch holds)."""
    kind, _ = parse_engine(spec)
    if kind == "neo4j":
        from .store import Scratch

        own = sc is None
        sc = Scratch.open_copy(source) if own else sc
        try:
            return Neo4jEngine(sc, gq, strict_lists=strict_lists, digits=digits)
        finally:
            if own:
                sc.close()
    return WorkerEngine(spec, source, gq, strict_lists=strict_lists, digits=digits)


@dataclass
class EngineTrialResult:
    error: str | None
    ms: float
    answers: list | None = None


class TwoEngines:
    """Reducer backend: Q on the primary ``Scratch`` and Q on the other engine, one trial, the same deletions.

    The id -> key maps are a snapshot taken at the start: the reducer commits on the primary first, which drops the
    deleted ids from the Scratch's own maps before this backend forwards the same deletion to the other engine."""

    def __init__(self, sc, gq: GuardedQuery, engine, *, strict_lists=False, digits=12):
        self.sc = sc
        self.gq = gq
        self.engine = engine
        self.strict_lists = strict_lists
        self.digits = digits
        self.rel_key = dict(sc.rel_keys)
        self.node_key = dict(sc.node_keys)
        self.restarts = 0
        self.other_ms: list[float] = []

    def trial_many(self, statements, rel_ids=(), node_ids=(), check_counts=None) -> EngineTrialResult:
        t0 = time.perf_counter()
        t = self.sc.trial_many(statements[:1], rel_ids, node_ids, check_counts=check_counts)
        if t.error is not None:
            return EngineTrialResult(t.error, (time.perf_counter() - t0) * 1000)
        assert t.results is not None  # error is None, so the trial returned its results
        rows, cols = t.results[0]
        try:
            mine = answer_of(
                self.gq, rows, cols, keyer=self.sc.keyer, strict_lists=self.strict_lists, digits=self.digits
            )
        except Exception as e:  # noqa: BLE001
            return EngineTrialResult(f"{type(e).__name__}: {e}", (time.perf_counter() - t0) * 1000)
        other = self.engine.answer([self.rel_key[r] for r in rel_ids], [self.node_key[n] for n in node_ids])
        self.other_ms.append(other.ms)
        ms = (time.perf_counter() - t0) * 1000
        if other.error is not None:
            return EngineTrialResult(f"other engine: {other.error}", ms)
        return EngineTrialResult(None, ms, [mine, other.answer])

    def commit_delete(self, rel_ids=(), node_ids=()) -> None:
        self.engine.commit([self.rel_key[r] for r in rel_ids], [self.node_key[n] for n in node_ids])

    def close(self) -> None:
        self.engine.close()
