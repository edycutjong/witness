"""The ledger: a Relate store (`out/ledger.rl` by default; the committed `witness.rl` only with `--update`).

    (:Reduction {...})-[:PRODUCED]->(:Witness {path_rl, path_cypher, sha256})
    (:Review {verdict, reason, by, at})-[:ON]->(:Reduction)

An agent (MCP `why`) or a person (`witness why`) writes a Reduction; a person writes the Review. One writer per file:
Witness opens the ledger, writes one transaction, closes it, and retries on `storage locked` with backoff. Anyone can
read it with plain `relate`, e.g. which answers nobody has reviewed:

    relate query -d out/ledger.rl --read-only \
      "MATCH (r:Reduction) WHERE NOT EXISTS { (:Review)-[:ON]->(r) } RETURN r.id, r.statement"
"""

from __future__ import annotations

import hashlib
import os
import time
from datetime import datetime, timezone
from pathlib import Path

os.environ.setdefault("DO_NOT_TRACK", "1")

import relate  # noqa: E402

REDUCTION_FIELDS = (
    "id created_at requester statement params_json predicate expected_json other_statement answer_json answer_sha256 "
    "source_path source_sha256 seed trials inconclusive seconds rels_before rels_after nodes_before nodes_after "
    "verified check_text relate_version witness_version"
).split()


def _open(path: Path, attempts: int = 8) -> relate.Database:
    path.parent.mkdir(parents=True, exist_ok=True)
    delay = 0.05
    for i in range(attempts):
        try:
            return relate.Database(str(path))
        except Exception as e:  # noqa: BLE001
            if "locked" not in str(e) or i == attempts - 1:
                raise
            time.sleep(delay)
            delay *= 2
    raise RuntimeError("unreachable")


def _write(path: Path, statement: str, params: dict) -> list[dict]:
    db = _open(Path(path))
    try:
        db.begin_transaction()
        try:
            rows = db.execute(statement, params).data
            db.commit_transaction()
        except Exception:
            if db.transaction_active():
                db.rollback_transaction()
            raise
        return rows
    finally:
        db.close()


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def new_id(created_at: str, statement: str, params_json: str) -> str:
    h = hashlib.sha256(f"{created_at}\n{statement}\n{params_json}".encode()).hexdigest()[:8]
    return "r-" + created_at.replace("-", "").replace(":", "").replace("T", "-").rstrip("Z") + "-" + h


def record_reduction(path: str | Path, fields: dict, witness: dict) -> str:
    """Write one Reduction and its Witness node in one transaction; returns the reduction id."""
    props = {k: fields.get(k) for k in REDUCTION_FIELDS}
    props["created_at"] = props["created_at"] or now_iso()
    props["id"] = props["id"] or new_id(props["created_at"], props["statement"] or "", props["params_json"] or "")
    _write(
        Path(path),
        "CREATE (r:Reduction) SET r = $r CREATE (w:Witness) SET w = $w CREATE (r)-[:PRODUCED]->(w) RETURN r.id AS id",
        {"r": {k: v for k, v in props.items() if v is not None}, "w": witness},
    )
    return props["id"]


def review(path: str | Path, reduction_id: str, verdict: str, reason: str = "", by: str = "human") -> dict:
    if verdict not in ("accept", "dispute"):
        raise ValueError("verdict must be accept or dispute")
    if verdict == "dispute" and not reason.strip():
        raise ValueError("a dispute needs a reason")
    rows = _write(
        Path(path),
        "MATCH (r:Reduction {id: $id}) CREATE (v:Review {verdict: $verdict, reason: $reason, by: $by, at: $at})"
        "-[:ON]->(r) RETURN r.id AS id",
        {"id": reduction_id, "verdict": verdict, "reason": reason, "by": by, "at": now_iso()},
    )
    if not rows:
        raise KeyError(f"no Reduction {reduction_id!r} in {path}")
    return {"id": reduction_id, "verdict": verdict, "reason": reason}


def read(path: str | Path, statement: str, params: dict | None = None) -> list[dict]:
    db = relate.Database(str(path), read_only=True)
    try:
        return db.execute(statement, params or {}).data
    finally:
        db.close()


def find(path: str | Path, reduction_id: str) -> dict | None:
    rows = read(
        path,
        "MATCH (r:Reduction {id: $id}) OPTIONAL MATCH (r)-[:PRODUCED]->(w:Witness) "
        "RETURN properties(r) AS r, properties(w) AS w",
        {"id": reduction_id},
    )
    return rows[0] if rows else None


def unreviewed(path: str | Path) -> list[dict]:
    return read(
        path,
        "MATCH (r:Reduction) WHERE NOT EXISTS { (:Review)-[:ON]->(r) } "
        "RETURN r.id AS id, r.created_at AS created_at, r.statement AS statement ORDER BY created_at",
    )
