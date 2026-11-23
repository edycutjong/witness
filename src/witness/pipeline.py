"""One reduction, end to end: the single code path behind `witness why`, `witness demo` and the MCP `why` tool.

guard every statement -> order check (a second store in reverse order) -> baseline -> predicate -> ddmin with
Relate transactions as the inner loop -> export W (.rl, .cypher) -> `check` from the files alone -> manifest, trace,
exhibit view -> ledger row. The source `.rl` is only byte-copied; its SHA-256 is compared before and after.
"""

from __future__ import annotations

import json
import os
import platform
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import __version__
from .canon import bad_name, same_answer
from .check import CheckResult, check, plain, spec_from_manifest
from .export import cypher_script, exhibit_html, exhibits, isolated, write_rl
from .guard import GuardedQuery, Refused, Tie, guard
from .predicates import Predicate, answer_of, answer_sha, expected_answer
from .reduce import EmptyGraphPredicate, Reducer, TrialCapReached
from .store import CollisionError, Scratch, replay, sha256_file

EXIT_OK, EXIT_NOT_VERIFIED, EXIT_REFUSED, EXIT_CAP, EXIT_WATCHDOG = 0, 1, 2, 3, 4


def relate_version() -> str:
    try:
        import relate

        return relate.__version__
    except Exception:  # noqa: BLE001
        return "unknown"


@dataclass
class Request:
    source: Path
    statement: str
    params: dict
    predicate: str = "keep"
    expected: str | list | None = None
    loose: bool = False
    other: str | None = None
    seed: int = 0
    strict_lists: bool = False
    digits: int = 12
    max_trials: int = 20000
    max_seconds: float | None = None
    isolate: bool = False
    trial_timeout: float = 30.0
    name: str = "witness"
    out_dir: Path = Path("out")
    ledger: Path | None = Path("out/ledger.rl")
    requester: str = "cli"
    use_cli: bool = True
    require_cli: bool = False
    order_check: bool = True
    claimed: list | None = None  # rows the caller already showed; a mismatch refuses before anything is written


@dataclass
class Outcome:
    exit_code: int
    answer_columns: list = field(default_factory=list)
    answer_rows: list = field(default_factory=list)
    run: dict = field(default_factory=dict)
    check: CheckResult | None = None
    files: dict = field(default_factory=dict)
    exhibits: list = field(default_factory=list)
    isolated: list = field(default_factory=list)
    manifest: dict = field(default_factory=dict)
    ledger_id: str | None = None
    warnings: list = field(default_factory=list)
    reasons: list = field(default_factory=list)
    source_counts: tuple = (0, 0)
    source_sha256: str = ""
    seconds_total: float = 0.0
    guard_notes: list = field(default_factory=list)

    @property
    def verified(self) -> bool:
        return self.exit_code == EXIT_OK


def _answer(sc: Scratch, gq: GuardedQuery, req: Request):
    res = sc.run(gq.exec_text, gq.params)
    ans = answer_of(gq, res.data, res.columns, keyer=sc.keyer, strict_lists=req.strict_lists, digits=req.digits)
    return ans, res


def _cut_rows(gq: GuardedQuery, rows: list[dict]) -> list[dict]:
    if gq.cut is None:
        return rows
    hi = None if gq.cut.limit is None else gq.cut.skip + gq.cut.limit
    return rows[gq.cut.skip : hi]


OUT_SUFFIXES = (".rl", ".cypher", ".manifest.json", ".html", ".trace.json")


def _refuse_aliased_outputs(req: Request, source: Path) -> None:
    """No output may land on the source store: write_rl() unlinks its target first, and the source SHA-256 is only
    compared after the export (`why -f g.cypher --store g.rl --out .` would otherwise replace g.rl; a2a arch r1)."""
    name = req.name
    if not name or name in (".", "..") or "/" in name or "\\" in name or bad_name(name) or "\x00" in name:
        raise Refused(f"the output name must be a plain file stem, got {name!r}", "out")
    if Path(name).name != name:
        raise Refused(f"the output name must be a plain file stem, got {name!r}", "out")
    src = source.resolve()
    outs = [Path(f"{Path(req.out_dir) / name}{s}") for s in OUT_SUFFIXES]
    if req.ledger is not None:
        outs.append(Path(req.ledger))
    for o in outs:
        if o.resolve() == src or (o.exists() and os.path.samefile(o, src)):
            raise Refused(f"{o} would overwrite the source store; choose another --out or --name", "out")
    # ... nor on each other: `--name ledger --out out` made the witness out/ledger.rl, the ledger's own file, and a
    # symlinked x.html -> x.rl would overwrite the checked witness after the check (a2a arch r2)
    seen: dict[Path, Path] = {}
    for o in outs:
        r = Path(os.path.normcase(str(o.resolve())).casefold())  # macOS/Windows: Out/W.RL is out/w.rl
        if r in seen:
            raise Refused(f"{o} and {seen[r]} are the same file; choose another --name or --ledger", "out")
        seen[r] = o


def reduce_request(req: Request, progress=None) -> Outcome:
    t_start = time.perf_counter()
    req.out_dir = Path(req.out_dir)
    source = Path(req.source)
    if not source.exists():
        raise Refused(f"store not found: {source}", "store")
    _refuse_aliased_outputs(req, source)
    sha_before = sha256_file(source)
    try:
        sc = Scratch.open_copy(source)
    except CollisionError as e:
        raise Refused(f"{e}; Witness needs distinguishable elements", "store") from e
    out = Outcome(exit_code=EXIT_OK, source_sha256=sha_before)
    backend = None
    try:
        out.source_counts = sc.counts()
        names = {lb for ls in sc.node_labels.values() for lb in ls} | set(sc.rel_type.values())
        names |= {k for p in (*sc.node_props.values(), *sc.rel_props.values()) for k in p}
        bad = sorted(n for n in names if bad_name(n))
        if bad:
            raise Refused(f"label/type/key {bad[0]!r} holds a control character; no witness could be exported", "store")
        # ---- guard every user statement (W2) ----------------------------------------------------------------
        queries = [guard(req.statement, req.params, sc.db, "query")]
        if req.predicate == "disagree":
            if not req.other:
                raise Refused("disagree needs --other", "predicate")
            queries.append(guard(req.other, req.params, sc.db, "--other"))
        out.guard_notes.append("read-only: Relate query_type 'r'")
        # ---- order check: same answer from a second store built in reverse canonical order ----------------
        answers, results = [], []
        for gq in queries:
            try:
                a, r = _answer(sc, gq, req)
            except ValueError as e:  # e.g. a result value with no canonical form (canon._opaque)
                raise Refused(f"the answer cannot be compared: {e}", gq.door) from e
            if isinstance(a, Tie):
                raise Refused(f"a tie straddles the SKIP/LIMIT cut on the full graph: {plain(a.rows)}", gq.door)
            answers.append(a)
            results.append(r)
        if req.order_check:
            mem = replay(sc, reverse=True)
            rev = Scratch(source=source, path=Path(":memory:"), db=mem)
            rev.reindex()
            try:
                for gq, a in zip(queries, answers, strict=True):
                    b, _ = _answer(rev, gq, req)
                    if isinstance(b, Tie) or not same_answer(b, a):
                        raise Refused(
                            "the answer depends on storage order (a second store built in reverse order disagrees)",
                            gq.door,
                        )
            finally:
                mem.close()
            out.guard_notes.append("order check: same answer from a store built in reverse order")
        base, res0 = answers[0], results[0]
        if len(base) == 0:
            raise Refused("nothing to witness: the answer is empty", "query")
        if req.claimed is not None:
            cols = list(res0.columns)
            claimed = expected_answer(req.claimed, cols, strict_lists=req.strict_lists, digits=req.digits)
            if not same_answer(claimed, base):
                raise Refused(
                    "the answer you gave differs from this store's answer to this query; nothing attached", "answer"
                )
        out.answer_columns = list(res0.columns)
        out.answer_rows = plain(_cut_rows(queries[0], res0.data))
        if len(res0.columns) == 1 and len(out.answer_rows) == 1:
            out.warnings.append(
                "a bare scalar answer: different rows can give the same value; return the identities to keep the reason"
            )
        expected = None
        if req.predicate == "differs":
            if req.expected is None:
                raise Refused("differs needs --expected", "predicate")
            expected = expected_answer(
                req.expected, out.answer_columns, strict_lists=req.strict_lists, digits=req.digits
            )
        pred = Predicate(
            req.predicate,
            queries,
            base,
            other_baseline=answers[1] if len(answers) > 1 else None,
            expected=expected,
            loose=req.loose,
        )
        # ---- reduce ---------------------------------------------------------------------------------------
        if req.isolate:
            from .isolate import IsolatedTrials

            backend = IsolatedTrials(
                source, queries, timeout=req.trial_timeout, strict_lists=req.strict_lists, digits=req.digits
            )
        red = Reducer(
            sc,
            predicate=pred,
            seed=req.seed,
            strict_lists=req.strict_lists,
            digits=req.digits,
            max_trials=req.max_trials,
            max_seconds=req.max_seconds,
            progress=progress,
            backend=backend,
        )
        capped = None
        try:
            run = red.run()
        except EmptyGraphPredicate as e:
            raise Refused("the predicate holds on the empty graph: the answer does not depend on the data") from e
        except TrialCapReached as e:
            capped = str(e)
            run = {"seed": req.seed, "start_counts": out.source_counts, "capped": capped}
        run.setdefault("final_counts", sc.counts())
        run["trials"], run["inconclusive"], run["ties"] = red.stats.trials, red.stats.inconclusive, red.stats.ties
        run["commits"] = red.stats.committed
        run["seconds"] = round(time.perf_counter() - red._t0, 3)
        ms = sorted(red.stats.trial_ms)
        if ms:
            run["trial_ms_p50"] = round(ms[len(ms) // 2], 3)
            run["trial_ms_p95"] = round(ms[min(len(ms) - 1, int(len(ms) * 0.95))], 3)
        if backend is not None:
            run["isolate_restarts"] = backend.restarts
        out.run = run
        # ---- export W --------------------------------------------------------------------------------------
        req.out_dir.mkdir(parents=True, exist_ok=True)
        stem = req.out_dir / req.name
        header = (
            f"Witness {__version__} · relate-db {relate_version()} · seed {req.seed}\n"
            f"source sha256 {sha_before}\nparams {json.dumps(req.params, sort_keys=True)}"
        )
        script = cypher_script(sc, header)
        Path(f"{stem}.cypher").write_text(script)
        write_rl(script, Path(f"{stem}.rl"))
        exported = Scratch.open_copy(Path(f"{stem}.rl"))
        try:
            lost = set(sc.node_keys.values()) ^ set(exported.node_keys.values())
            lost |= set(sc.rel_keys.values()) ^ set(exported.rel_keys.values())
        finally:
            exported.close()
        if lost:
            raise RuntimeError(f"export changed the witness: {len(lost)} element(s) differ from the reduced graph")
        out.exhibits = exhibits(sc)
        out.isolated = isolated(sc)
        trace_log = red.stats.log
    finally:
        if backend is not None:
            backend.close()
        sc.close()
    sha_after = sha256_file(source)
    if sha_after != sha_before:
        raise RuntimeError(f"source store changed during the run: {sha_before} -> {sha_after}")

    # ---- manifest + check from the files alone ------------------------------------------------------------
    files = {
        k: f"{stem}{s}"
        for k, s in (
            ("rl", ".rl"),
            ("cypher", ".cypher"),
            ("manifest", ".manifest.json"),
            ("html", ".html"),
            ("trace", ".trace.json"),
        )
    }
    out.files = files
    manifest = {
        "schema": "witness.manifest/v1",
        "name": req.name,
        "source": {
            "path": str(source),
            "sha256": sha_before,
            "nodes": out.source_counts[0],
            "relationships": out.source_counts[1],
        },
        "statement": req.statement,
        "params": req.params,
        "predicate": pred.describe(),
        "baseline": {"columns": out.answer_columns, "rows": out.answer_rows, "sha256": answer_sha(base)},
        "comparison": {"strict_lists": req.strict_lists, "float_digits": req.digits, "rows": "bag"},
        "seed": req.seed,
        "witness": {
            "relationships": out.run["final_counts"][1],
            "nodes": out.run["final_counts"][0],
            "isolated_nodes": len(out.isolated),
        },
        "run": {k: out.run.get(k) for k in ("trials", "inconclusive", "ties", "commits", "seconds", "capped")},
        "versions": {"witness": __version__, "relate_db": relate_version(), "python": platform.python_version()},
        "determinism_claimed": out.run["inconclusive"] == 0 and not capped and req.order_check,
    }
    if expected is not None:
        manifest["predicate"]["expected_rows"] = plain(
            req.expected if isinstance(req.expected, list) else json.loads(req.expected)
        )
    chk = check(
        files["rl"],
        spec_from_manifest(manifest),
        use_cli=req.use_cli,
        require_cli=req.require_cli,
        necessity=not capped,
    )
    out.check = chk
    reasons = list(chk.reasons) + chk.disagreements
    if capped:
        reasons.insert(
            0, f"{capped}: reduced to {out.run['final_counts'][1]} relationships, deletion-minimality NOT verified"
        )
    if chk.inconclusive:
        reasons.append(f"inconclusive: {chk.inconclusive}")
    if not chk.verified and not reasons:
        reasons.append(f"{len(chk.probes) - chk.necessary} element(s) can be deleted without changing the answer")
    out.reasons = reasons
    verified = chk.verified and not capped
    out.exit_code = EXIT_OK if verified else (EXIT_CAP if capped else EXIT_NOT_VERIFIED)
    manifest["verified"] = verified
    manifest["reasons"] = reasons
    manifest["check"] = {k: v for k, v in chk.to_dict().items() if k != "probes"}
    manifest["check"]["probes"] = chk.probes
    out.manifest = manifest
    Path(files["manifest"]).write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    trace = {
        "schema": "witness.trace/v1",
        "name": req.name,
        "plan": out.run.get("plan"),
        "phases": {k: v for k, v in out.run.items() if k not in ("plan",)},
        "trials": trace_log,
    }
    Path(files["trace"]).write_text(json.dumps(trace, indent=1, sort_keys=True) + "\n")
    question = next((ln[2:].strip() for ln in req.statement.splitlines() if ln.strip().startswith("//")), "")
    meta = [
        ("query", " ".join(ln.strip() for ln in req.statement.splitlines() if not ln.strip().startswith("//"))),
        ("params", json.dumps(req.params, sort_keys=True)),
        ("source", f"{source.name} · {out.source_counts[0]:,} nodes · {out.source_counts[1]:,} relationships"),
        ("source sha256", sha_before),
        ("reduction", f"{out.run['trials']} trials · {out.run['inconclusive']} inconclusive · {out.run['seconds']} s"),
        ("check", chk.text + " · " + chk.cli_status),
        ("versions", f"Witness {__version__} · relate-db {relate_version()}"),
    ]
    stamp = chk.text.split(" (")[0].upper() if verified else "NOT VERIFIED"
    Path(files["html"]).write_text(
        exhibit_html(req.name, question, out.answer_rows, out.answer_columns, out.exhibits, stamp, verified, meta)
    )
    # ---- ledger ---------------------------------------------------------------------------------------------
    if req.ledger is not None:
        from .ledger import record_reduction

        out.ledger_id = record_reduction(
            req.ledger,
            {
                "requester": req.requester,
                "statement": req.statement,
                "params_json": json.dumps(req.params, sort_keys=True),
                "predicate": req.predicate,
                "expected_json": (
                    json.dumps(manifest["predicate"].get("expected_rows")) if expected is not None else None
                ),
                "other_statement": req.other,
                "answer_json": json.dumps(out.answer_rows, sort_keys=True),
                "answer_sha256": manifest["baseline"]["sha256"],
                "source_path": str(source),
                "source_sha256": sha_before,
                "seed": req.seed,
                "trials": out.run["trials"],
                "inconclusive": out.run["inconclusive"],
                "seconds": out.run["seconds"],
                "rels_before": out.source_counts[1],
                "rels_after": out.run["final_counts"][1],
                "nodes_before": out.source_counts[0],
                "nodes_after": out.run["final_counts"][0],
                "verified": verified,
                "check_text": chk.text,
                "relate_version": relate_version(),
                "witness_version": __version__,
            },
            {"path_rl": files["rl"], "path_cypher": files["cypher"], "sha256": sha256_file(files["rl"])},
        )
    out.seconds_total = round(time.perf_counter() - t_start, 3)
    return out


def python_line() -> str:
    return f"Python {platform.python_version()} ({sys.platform})"
