"""`witness mcp`: a stdio MCP server with two tools, `why` and `check`, beside Relate's own `relate serve --mcp`.

The agent answers with Relate's `read_cypher`; it asks Witness for the evidence behind its own answer.
Agent-written statements run here, so every request is supervised as a whole: the guard, the order check, the
baseline, every trial and `check` run in a child process that is killed at `--request-timeout`; each trial
inside it also has `--trial-timeout` (`--isolate`). A hit is a NOT-verified answer, never a hung agent session.
The `store` input must sit inside an allowlisted directory and is only ever byte-copied (the original is never
opened for writing).
"""

from __future__ import annotations

import json
import multiprocessing as mp
import os
import signal
import threading
import time
from pathlib import Path

DEFAULT_REQUEST_TIMEOUT = 300.0
DEFAULT_TRIAL_TIMEOUT = 30.0
# What crosses MCP stays small (a2a judge r5): a real client caps a tool result, and a recorded Claude Code session
# could not read a 74,771-character `why` reply (68 exhibits, each with its full content key). Exhibits and rows are
# trimmed to REPLY_ROWS and the per-probe list to the failures; the .manifest.json beside the witness keeps all of it.
REPLY_ROWS = 50
# Rows are bounded by size too (a2a arch r7): one row can hold a 3,000-element collect(). Rows are sent whole or not
# at all, never edited, and `rows_truncated` says when the rest is only in the manifest.
REPLY_ROW_CHARS = 20_000
VALUE_CHARS = 80


def lean_check(d: dict) -> dict:
    """A check result without its per-probe list. `not_necessary` names the probes whose deletion kept the answer
    (proven not needed); `inconclusive_probes` the probes whose trial gave no verdict (an error or a timeout: unknown,
    never "not needed", a2a arch r7). Each holds at most REPLY_ROWS names, with its `_total`. `probes_total` counts the
    probes that ran: 0 means the necessity check did not run, so an empty `not_necessary` proves nothing on its own;
    `verified` is the verdict."""
    out = {k: v for k, v in d.items() if k != "probes"}
    probes = d.get("probes", [])
    failed = [p["element"] for p in probes if p.get("necessary") is False]
    unknown = [p["element"] for p in probes if p.get("necessary") is None]
    out["probes_total"] = len(probes)
    out["not_necessary"] = failed[:REPLY_ROWS]
    out["not_necessary_total"] = len(failed)
    out["inconclusive_probes"] = unknown[:REPLY_ROWS]
    out["inconclusive_probes_total"] = len(unknown)
    return out


def fit_rows(rows: list) -> list:
    """The leading answer rows that fit REPLY_ROWS and REPLY_ROW_CHARS of JSON; whole rows only."""
    kept: list = []
    used = 0
    for r in rows[:REPLY_ROWS]:
        used += len(json.dumps(r, default=str))
        if used > REPLY_ROW_CHARS:
            break
        kept.append(r)
    return kept


def compact_reply(res: dict) -> dict:
    """The `why` reply as sent: exhibits as n/start/type/end, at most REPLY_ROWS exhibits, answer rows bounded by count
    and size (`rows_truncated` when some are only in the manifest)."""
    ex = [{k: x[k] for k in ("n", "start", "type", "end")} for x in res["exhibits"]]
    rows = res["answer"]["rows"]
    sent = fit_rows(rows)
    return {
        **res,
        "answer": {**res["answer"], "rows": sent, "rows_total": len(rows), "rows_truncated": len(sent) < len(rows)},
        "exhibits": ex[:REPLY_ROWS],
        "exhibits_total": len(ex),
        "check": lean_check(res["check"]),
    }


MAX_EVIDENCE_LINES = 25


def package_root() -> Path:
    """The repo root: the working directory if it holds the committed data (a wheel install started from a clone, as an
    MCP client's `cwd` setting does), else the source checkout this module sits in (a2a arch r7; the CLI's rule)."""
    cwd = Path.cwd()
    return cwd if (cwd / "data" / "air-routes.rl").is_file() else Path(__file__).resolve().parents[2]


class ToolError(Exception):
    """A refusal or failure the agent can read: returned as an error object, never raised into the MCP transport."""

    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind
        self.message = message

    def to_dict(self) -> dict:
        return {"error": {"kind": self.kind, "message": self.message}, "verified": False}


def resolve_store(store: str | None, allow: list[Path], default: Path) -> Path:
    """`store` must be a `.rl` file inside an allowlisted directory (symlinks resolved first)."""
    p = Path(store).expanduser() if store else default
    if not p.is_absolute():
        p = package_root() / p
    p = p.resolve()
    if p.suffix != ".rl":
        raise ToolError("store", f"store must be a .rl file, got {p.name!r}")
    if not any(a == p.parent or a in p.parents for a in allow):
        shown = ", ".join(str(a.relative_to(package_root())) if package_root() in a.parents else str(a) for a in allow)
        raise ToolError("store", f"store is outside the allowlisted directories ({shown})")
    if not p.is_file():
        raise ToolError("store", f"store not found: {p.name}")
    return p


def _short(v) -> str:
    s = str(v)
    return s if len(s) <= VALUE_CHARS else s[: VALUE_CHARS - 1] + "…"


def evidence_markdown(res: dict) -> str:
    """What the agent pastes into its answer: <= 25 lines."""
    lines = []
    ans = res["answer"]
    shown_rows = ans["rows"][:6]
    lines.append(
        f"**Answer** ({len(ans['rows'])} rows): "
        + "; ".join(", ".join(_short(v) for v in r.values()) for r in shown_rows)
    )
    if len(ans["rows"]) > len(shown_rows):
        lines[-1] += f"; … (+{len(ans['rows']) - len(shown_rows)} more)"
    w = res["witness"]
    chk = res["check"]
    stamp = chk["check_text"].split(" (")[0] if res["verified"] else chk["check_text"]
    total = f"{res['source_relationships']:,}"
    kept = "reproduce it"  # keep / strict differs
    if not res["verified"]:
        kept = "were kept"
    elif "end the disagreement" in stamp:
        kept = "keep the two queries disagreeing"
    elif "end the mismatch" in stamp:
        kept = "keep the mismatch"
    head = f"**Evidence:** {w['relationships']} relationships (of {total}) {kept}; {stamp}"
    tail = " — verified deletion-minimal." if res["verified"] else " — NOT verified."
    head += tail
    lines.append(head)
    lines.append("```")
    ex = [f"{x['n']:>2} ({x['start']})-[:{x['type']}]->({x['end']})" for x in res["exhibits"]]
    room = MAX_EVIDENCE_LINES - 6  # answer, evidence, 2 fences, re-run line, one spare for "not verified"
    per = 1 if len(ex) <= room else 2  # two per line when the register is long, so it still fits a chat reply
    rows = [ex[i : i + per] for i in range(0, len(ex), per)]
    if len(rows) > room:
        room -= 1  # the "… more lines" marker takes a line too, so the verdict line below is never cut (a2a arch r7)
    for r in rows[:room]:
        lines.append("   ".join(r))
    if len(rows) > room:
        lines.append(f"… +{len(rows) - room} more lines in the file")
    lines.append("```")
    lines.append(f"Re-run with plain `relate`: `{res['files']['rl']}` (+ `.cypher`). Relate {res['relate_version']}.")
    if not res["verified"]:
        lines.append("Not verified: " + "; ".join(res["reasons"][:2]) if res["reasons"] else "Not verified.")
    return "\n".join(lines[:MAX_EVIDENCE_LINES])


def _own_group() -> None:
    """Lead a new process group: a request kill then reaches the isolate trial child too (a2a arch r1)."""
    if hasattr(os, "setsid"):
        try:
            os.setsid()
        except OSError:
            pass


def _kill_group(proc) -> None:
    if hasattr(os, "killpg") and proc.pid:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            pass
    if proc.is_alive():
        proc.kill()


def override_spec(manifest: dict, statement: str, parameters: dict | None):
    """`check` with an agent's own statement: keep-compared against W's baseline rows, the way W was compared
    (its manifest's strict_lists / float_digits, not hard-coded defaults; a2a arch r1)."""
    from .check import CheckSpec
    from .guard import static_checks

    cmp_ = manifest.get("comparison", {})
    # Against the baseline's own sha256, not rows re-parsed from JSON: rows that hold nodes or relationships are
    # display dicts and could never match a canonical node again (P1d QA r2).
    return CheckSpec(
        queries=[static_checks(statement, dict(parameters or {}), "check")],
        kind="keep",
        baseline_sha=manifest["baseline"]["sha256"],
        strict_lists=bool(cmp_.get("strict_lists")),
        digits=int(cmp_.get("float_digits", 12)),
    )


def _recv_within(conn, timeout: float):
    """poll() only says a reply has started; recv() can still block on the rest of the frame. Receive under the
    request deadline instead (a2a arch r2): TimeoutError when it does not complete in time."""
    box: dict = {}

    def run():
        try:
            box["v"] = conn.recv()
        except BaseException as e:  # noqa: BLE001 - re-raised in the caller
            box["e"] = e

    th = threading.Thread(target=run, daemon=True)
    th.start()
    th.join(timeout)
    if th.is_alive():
        raise TimeoutError
    if "e" in box:
        raise box["e"]
    return box["v"]


def _check_worker(conn, args: dict) -> None:
    os.environ.setdefault("DO_NOT_TRACK", "1")
    from .check import check, spec_from_manifest
    from .guard import Refused

    _own_group()
    try:
        manifest = json.loads(Path(args["manifest"]).read_text())
        spec = spec_from_manifest(manifest)
        if args["statement"] is not None:
            spec = override_spec(manifest, args["statement"], args["parameters"])
        conn.send(("ok", lean_check(check(Path(args["witness"]), spec, use_cli=args["use_cli"]).to_dict())))
    except Refused as e:
        conn.send(("refused", {"kind": e.door, "message": e.reason}))
    except (ValueError, KeyError, TypeError) as e:
        conn.send(("refused", {"kind": "witness", "message": f"unreadable manifest: {type(e).__name__}: {e}"}))
    except Exception as e:  # noqa: BLE001
        conn.send(("error", {"kind": "internal", "message": f"{type(e).__name__}: {e}"}))
    finally:
        conn.close()


def _why_worker(conn, req_dict: dict) -> None:
    os.environ.setdefault("DO_NOT_TRACK", "1")
    _own_group()
    from .guard import Refused
    from .pipeline import Request, reduce_request

    try:
        req = Request(
            **{
                **req_dict,
                "source": Path(req_dict["source"]),
                "out_dir": Path(req_dict["out_dir"]),
                "ledger": Path(req_dict["ledger"]) if req_dict.get("ledger") else None,
            }
        )
        o = reduce_request(req)
        m = o.manifest
        files = {k: str(v) for k, v in o.files.items()}
        res = {
            "answer": {"columns": o.answer_columns, "rows": o.answer_rows},
            "source_sha256": o.source_sha256,
            "source_relationships": o.source_counts[1],
            "witness": {
                "relationships": o.run["final_counts"][1],
                "nodes": o.run["final_counts"][0],
                "deletion_minimal_verified": o.verified,
            },
            "check": o.check.to_dict() if o.check is not None else {"check_text": "not run", "verified": False},
            "verified": o.verified,
            "determinism_claimed": bool(m.get("determinism_claimed")),
            "exhibits": o.exhibits,
            "files": files,
            "out_dir": str(req.out_dir),
            "ledger_path": str(req.ledger) if req.ledger else None,
            "ledger_id": o.ledger_id,
            "trials": o.run["trials"],
            "inconclusive": o.run["inconclusive"],
            "seconds": o.run["seconds"],
            "seconds_total": o.seconds_total,
            "relate_version": __import__("witness.pipeline", fromlist=["x"]).relate_version(),
            "reasons": o.reasons,
            "warnings": o.warnings,
        }
        res["evidence_markdown"] = evidence_markdown(res)
        conn.send(("ok", compact_reply(res)))
    except Refused as e:
        conn.send(("refused", {"kind": e.door, "message": e.reason}))
    except Exception as e:  # noqa: BLE001
        conn.send(("error", {"kind": "internal", "message": f"{type(e).__name__}: {e}"}))
    finally:
        conn.close()


class WitnessTools:
    """The two tools as plain methods (the MCP layer is a thin wrapper), one request at a time (one ledger writer)."""

    def __init__(
        self,
        *,
        allow: list[Path] | None = None,
        out_root: Path | None = None,
        ledger: Path | None = None,
        isolate: bool = True,
        trial_timeout: float = DEFAULT_TRIAL_TIMEOUT,
        request_timeout: float = DEFAULT_REQUEST_TIMEOUT,
        use_cli: bool = True,
    ):
        root = package_root()
        self.allow = [a.resolve() for a in (allow or [root / "data", root / "witnesses"])]
        self.default_store = root / "data" / "air-routes.rl"
        self.out_root = Path(out_root or root / "out").resolve()
        self.ledger = Path(ledger) if ledger else self.out_root / "ledger.rl"
        self.isolate = isolate
        self.trial_timeout = trial_timeout
        self.request_timeout = request_timeout
        self.use_cli = use_cli
        self._lock = threading.Lock()
        self._n = 0

    # ---- why ---------------------------------------------------------------------------------------------------
    def why(
        self,
        statement: str,
        parameters: dict | None = None,
        store: str | None = None,
        predicate: str = "keep",
        expected: list | None = None,
        other_statement: str | None = None,
        answer: list | None = None,
        client: str = "agent",
    ) -> dict:
        try:
            src = resolve_store(store, self.allow, self.default_store)
            if not isinstance(statement, str) or not statement.strip():
                raise ToolError("query", "statement must be a non-empty Cypher string")
            with self._lock:
                self._n += 1
                name = f"mcp-{int(time.time())}-{self._n}"
                out_dir = self.out_root / name
                req = {
                    "source": str(src),
                    "statement": statement,
                    "params": dict(parameters or {}),
                    "predicate": predicate,
                    "expected": expected,
                    "other": other_statement,
                    "isolate": self.isolate,
                    "trial_timeout": self.trial_timeout,
                    # the reducer stops itself first (a partial reduction marked NOT verified); the kill is the backstop
                    "max_seconds": max(1.0, self.request_timeout * 0.8),
                    "name": "witness",
                    "out_dir": str(out_dir),
                    "ledger": str(self.ledger),
                    "requester": f"mcp:{client}",
                    "use_cli": self.use_cli,
                    "claimed": answer,
                }
                return self._supervise(_why_worker, req)
        except ToolError as e:
            return e.to_dict()

    def _supervise(self, target, req: dict) -> dict:
        ctx = mp.get_context("spawn")
        parent, child = ctx.Pipe()
        proc = ctx.Process(target=target, args=(child, req))  # not a daemon: it spawns the isolate child
        t0 = time.monotonic()
        proc.start()
        child.close()
        try:
            if not parent.poll(self.request_timeout):
                _kill_group(proc)
                proc.join(5)
                return ToolError(
                    "timeout",
                    f"no result within the {self.request_timeout:g} s request deadline; "
                    "NOT verified, no witness attached "
                    "(determinism not claimed)",
                ).to_dict()
            try:
                kind, payload = _recv_within(parent, max(0.1, t0 + self.request_timeout - time.monotonic()))
            except TimeoutError:
                _kill_group(proc)
                proc.join(5)
                return ToolError("timeout", f"the reply did not complete within {self.request_timeout:g} s").to_dict()
            except Exception as e:  # noqa: BLE001 - EOFError (worker died) or an unreadable reply (a2a arch r2)
                if not isinstance(e, EOFError):
                    _kill_group(proc)
                    return ToolError("internal", f"unreadable reply from the worker: {type(e).__name__}").to_dict()
                return ToolError("internal", f"the reduction process died (exit code {proc.exitcode})").to_dict()
            if kind == "ok":
                payload["request_seconds"] = round(time.monotonic() - t0, 3)
                return payload
            return ToolError(payload["kind"], payload["message"]).to_dict()
        finally:
            proc.join(5)
            if proc.is_alive():  # never killpg a reaped pid: it may have been recycled
                _kill_group(proc)

    # ---- check -------------------------------------------------------------------------------------------------
    def check(self, witness_path: str, statement: str | None = None, parameters: dict | None = None) -> dict:
        try:
            w = Path(witness_path).expanduser()
            if not w.is_absolute():
                w = package_root() / w
            w = w.resolve()
            allowed = self.allow + [self.out_root]
            if w.suffix != ".rl" or not any(a == w.parent or a in w.parents for a in allowed):
                raise ToolError(
                    "witness", "witness_path must be a .rl file inside the witness, data or out directories"
                )
            if not w.is_file():
                raise ToolError("witness", f"witness not found: {w.name}")
            man = w.with_suffix(".manifest.json")
            if not man.is_file():
                raise ToolError("witness", f"no {man.name} beside {w.name}")
            if parameters and statement is None:
                raise ToolError("check", "parameters without statement: pass both or neither")
            args = {
                "witness": str(w),
                "manifest": str(man),
                "statement": statement,
                "parameters": dict(parameters or {}),
                "use_cli": self.use_cli,
            }
            # Same supervision as `why` (a2a arch r1): an agent-written override query is killed at the request
            # deadline, and one request runs at a time.
            with self._lock:
                d = self._supervise(_check_worker, args)
        except ToolError as e:
            return e.to_dict()
        if "error" in d:
            return d
        d.pop("request_seconds", None)
        d["overridden"] = ["statement"] if statement is not None else []
        d["witness_path"] = str(w)
        return d


def serve(tools: WitnessTools) -> None:
    from mcp.server.mcpserver import MCPServer

    server = MCPServer("witness")

    @server.tool()
    def why(
        statement: str,
        parameters: dict | None = None,
        store: str | None = None,
        predicate: str = "keep",
        expected: list | None = None,
        other_statement: str | None = None,
        answer: list | None = None,
    ) -> dict:
        """Shrink a read-only Cypher answer to the few relationships it needs, and prove each one is needed.

        Returns a tiny `.rl` store you can re-run with plain `relate`, the exhibit list, a `check` result
        ("N of N change the answer"; "end the disagreement" for disagree) and `evidence_markdown` to paste into your
        reply. When `verified` is false the sentence starts NOT VERIFIED or NOT SUFFICIENT. `answer` = the rows you
        already showed (rows as objects keyed by column); if they differ from the store's answer, nothing is attached.
        `predicate`: keep (default) | differs (needs `expected`) | disagree (needs `other_statement`).
        Read-only queries in the supported subset only; refusals come back as an `error` object."""
        return tools.why(statement, parameters, store, predicate, expected, other_statement, answer)

    @server.tool()
    def check(witness_path: str, statement: str | None = None, parameters: dict | None = None) -> dict:
        """Re-prove a witness from its files alone: sufficiency, then one fresh copy per relationship with that one
        relationship deleted. The `.manifest.json` beside the `.rl` supplies query, parameters and baseline."""
        return tools.check(witness_path, statement, parameters)

    server.run("stdio")


def main(argv: list[str] | None = None) -> int:
    import argparse
    import os
    import sys

    os.environ.setdefault("DO_NOT_TRACK", "1")
    ap = argparse.ArgumentParser(prog="witness mcp", description=__doc__)
    ap.add_argument("--out", default=None, help="where reductions are written (default: ./out)")
    ap.add_argument("--ledger", default=None, help="ledger .rl (default: <out>/ledger.rl)")
    ap.add_argument(
        "--allow", action="append", default=None, metavar="DIR", help="allowlisted store directory (repeatable)"
    )
    ap.add_argument(
        "--no-isolate", action="store_true", help="run trials in the request process (no per-trial timeout)"
    )
    ap.add_argument("--trial-timeout", type=float, default=DEFAULT_TRIAL_TIMEOUT)
    ap.add_argument("--request-timeout", type=float, default=DEFAULT_REQUEST_TIMEOUT)
    ap.add_argument("--no-cli", action="store_true")
    a = ap.parse_args(argv)
    try:
        import mcp  # noqa: F401
    except ImportError:
        print(
            "witness mcp needs the MCP SDK. From the clone: uv run --extra mcp witness mcp"
            "   (or pip install -e '.[mcp]')."
            " Witness is not on PyPI: `pip install witness` installs an unrelated package.",
            file=sys.stderr,
        )
        return 2
    serve(
        WitnessTools(
            allow=[Path(x) for x in a.allow] if a.allow else None,
            out_root=Path(a.out) if a.out else None,
            ledger=Path(a.ledger) if a.ledger else None,
            isolate=not a.no_isolate,
            trial_timeout=a.trial_timeout,
            request_timeout=a.request_timeout,
            use_cli=not a.no_cli,
        )
    )
    return 0
