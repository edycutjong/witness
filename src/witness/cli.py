"""witness: shrink a graph answer to the few relationships it needs, and prove each one is needed.

Commands: demo (the whole judge path) · why (reduce) · check (re-prove a witness) · rerun (query a witness) ·
export (copy a reduction's files) · review (accept or dispute a reduction in the ledger).
Exit codes: 0 verified · 1 NOT verified · 2 refused · 3 trial cap · 4 aborted by the demo watchdog.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
import threading
import time
from pathlib import Path

os.environ.setdefault("DO_NOT_TRACK", "1")

from . import __version__  # noqa: E402
from .guard import Refused  # noqa: E402
from .pipeline import EXIT_REFUSED, EXIT_WATCHDOG, Request, reduce_request, relate_version  # noqa: E402

PKG_ROOT = Path(__file__).resolve().parents[2]
HEADLINE = {
    "query": "queries/two-hub.cypher",
    "absence": "queries/two-hub-absence.cypher",
    "bindings": "queries/two-hub-bindings.cypher",
    "params": {"country": "MX", "dest": "MEX"},
    "name": "two-hub",
    "source": "data/air-routes.rl",
}


def root() -> Path:
    """The repo root: the working directory if it holds the committed data, else the package checkout."""
    cwd = Path.cwd()
    return cwd if (cwd / HEADLINE["source"]).exists() else PKG_ROOT


def shown(p) -> str:
    p = Path(p)
    try:
        return str(p.resolve().relative_to(Path.cwd().resolve()))
    except ValueError:
        return str(p)


def parse_params(items: list[str] | None) -> dict:
    """--param k=v: v as JSON when it parses (numbers, lists, quoted strings), else the bare string."""
    out = {}
    for it in items or []:
        if "=" not in it:
            raise Refused(f"--param needs k=v, got {it!r}", "param")
        k, v = it.split("=", 1)
        try:
            out[k] = json.loads(v)
        except ValueError:
            out[k] = v
    return out


def read_query(path: str) -> str:
    p = Path(path)
    if not p.exists():
        raise Refused(f"query file not found: {path}", "query")
    return p.read_text()


class Progress:
    """A live trial counter on a terminal; silent when stderr is not a TTY."""

    def __init__(self, stream=sys.stderr):
        self.stream = stream
        self.tty = stream.isatty()
        self.last = 0.0

    def __call__(self, red, phase: str) -> None:
        if not self.tty:
            return
        now = time.perf_counter()
        if now - self.last < 0.05:
            return
        self.last = now
        nodes, rels = red.counts
        self.stream.write(
            f"\r  reducing · trial {red.stats.trials:>5} · phase {phase:<11} · "
            f"{rels:>6,} relationships, {nodes:>5,} nodes left "
        )
        self.stream.flush()

    def done(self) -> None:
        if self.tty:
            self.stream.write("\r" + " " * 92 + "\r")
            self.stream.flush()


def fmt_value(v) -> str:
    if isinstance(v, list):
        return "[" + ", ".join(fmt_value(x) for x in v) + "]"
    return str(v)


def print_rows(columns: list[str], rows: list[dict], indent: str = "  ") -> None:
    widths = {c: max(len(c), *(len(fmt_value(r.get(c))) for r in rows)) if rows else len(c) for c in columns}
    print((indent + "  ".join(c.ljust(widths[c]) for c in columns)).rstrip())
    for r in rows:
        print((indent + "  ".join(fmt_value(r.get(c)).ljust(widths[c]) for c in columns)).rstrip())


def cli_flags(params: dict) -> str:
    from .check import cli_param_args

    a = cli_param_args(params)
    return " ".join(f"{a[i]} {a[i + 1]}" for i in range(0, len(a), 2))


def request_from(args, statement: str, source: Path, params: dict) -> Request:
    other = read_query(args.other) if getattr(args, "other", None) else None
    return Request(
        source=source,
        statement=statement,
        params=params,
        predicate=args.predicate,
        expected=args.expected,
        loose=args.loose,
        other=other,
        seed=args.seed,
        strict_lists=args.strict_lists,
        digits=args.float_digits,
        max_trials=args.max_trials,
        max_seconds=args.max_seconds,
        isolate=args.isolate,
        trial_timeout=args.trial_timeout,
        name=args.name,
        out_dir=Path(args.out),
        ledger=None if args.no_ledger else Path(args.ledger or Path(args.out) / "ledger.rl"),
        use_cli=not args.no_cli,
        require_cli=args.require_cli,
    )


def print_outcome(o, verbose_exhibits: bool = True, extra: str | None = None) -> None:
    fc = o.run["final_counts"]
    print(f"\nWITNESS  {fc[1]} relationships · {fc[0]} nodes, out of {o.source_counts[1]:,} · {o.source_counts[0]:,}")
    print(
        f"  reduced in {o.run['seconds']} s · {o.run['trials']} trials · {o.run['inconclusive']} inconclusive · "
        f"seed {o.run.get('seed', 0)} ({o.seconds_total} s end to end: copy, guard, order check, reduce, check)"
    )
    if extra:
        print(f"  {extra}")
    if verbose_exhibits:
        print("\nEXHIBITS  (register order; every one is needed)")
        for x in o.exhibits:
            print(f"  {x['n']:>2}  ({x['start']})-[:{x['type']}]->({x['end']})")
        for n in o.isolated:
            print(f"   ·  ({n})  isolated node")
    print(f"\nCHECK  {o.check.text}")
    print(f"  {o.check.cli_status}")


def verdict_line(o) -> None:
    if o.verified:
        det = "determinism claimed" if o.manifest.get("determinism_claimed") else "determinism not claimed"
        print(
            f"\nVERIFIED · deletion-minimal: no single relationship can be removed without changing the answer · {det}"
        )
    else:
        print("\nNOT verified")
        for r in o.reasons:
            print(f"  - {r}")
        if o.check is not None:
            print(f"  inconclusive: {o.check.inconclusive}")


# ---- commands ----------------------------------------------------------------------------------------------------
def cmd_why(args) -> int:
    params = parse_params(args.param)
    statement = read_query(args.file)
    source = Path(args.store) if args.store else root() / HEADLINE["source"]
    if args.name == "witness":
        args.name = Path(args.file).stem
    prog = Progress()
    try:
        o = reduce_request(request_from(args, statement, source, params), progress=prog)
    finally:
        prog.done()
    if args.json:
        print(
            json.dumps(
                {"exit": o.exit_code, "manifest": o.manifest, "files": o.files, "ledger_id": o.ledger_id},
                indent=2,
                sort_keys=True,
            )
        )
        return o.exit_code
    print(f"ANSWER  {len(o.answer_rows)} rows on the full graph")
    print_rows(o.answer_columns, o.answer_rows)
    for w in o.warnings:
        print(f"  warning: {w}")
    print_outcome(o)
    print(f"\nFILES  {shown(o.files['rl'])} (+ .cypher .manifest.json .html .trace.json)")
    if o.ledger_id:
        print(f"LEDGER  {o.ledger_id}")
    verdict_line(o)
    return o.exit_code


def cmd_check(args) -> int:
    from .check import check, spec_from_args, spec_from_manifest

    w = Path(args.witness)
    if not w.exists():
        raise Refused(f"witness not found: {w}", "check")
    man_path = Path(str(w)[: -len(w.suffix)] + ".manifest.json") if w.suffix else Path(str(w) + ".manifest.json")
    if args.file:
        params = parse_params(args.param)
        other = read_query(args.other) if args.other else None
        spec = spec_from_args(
            read_query(args.file),
            params,
            args.expect,
            args.predicate,
            other,
            args.loose,
            args.strict_lists,
            args.float_digits,
        )
        src = "explicit -f/--param/--expect"
    elif man_path.exists():
        spec = spec_from_manifest(json.loads(man_path.read_text()))
        src = shown(man_path)
    else:
        raise Refused(f"no {man_path.name} beside {w.name}: pass -f, --param and --expect", "check")
    res = check(w, spec, use_cli=not args.no_cli, require_cli=args.require_cli)
    if args.json:
        print(json.dumps(res.to_dict(), indent=2, sort_keys=True))
        return 0 if res.verified else 1
    print(f"CHECK  {shown(w)}  (query, parameters and baseline from {src})")
    print(f"  answer reproduced on W: {'yes' if res.sufficient else 'NO'}")
    print(f"  {res.text}")
    print(f"  {res.cli_status}")
    for p in res.probes:
        if p["necessary"] is not True:
            state = "inconclusive" if p["necessary"] is None else "NOT needed"
            print(f"  - probe {p['i']} {p['element']}: {state}")
    if res.verified:
        print("VERIFIED")
        return 0
    print("NOT verified")
    for r in res.reasons + res.disagreements:
        print(f"  - {r}")
    print(f"  inconclusive: {res.inconclusive}")
    return 1


def cmd_rerun(args) -> int:
    import relate

    from .guard import guard

    params = parse_params(args.param)
    statement = read_query(args.file)
    w = Path(args.witness)
    if args.print_cli:
        print(f"relate query --database {shown(w)} --read-only {cli_flags(params)} < {args.file}")
        return 0
    if not w.exists():
        raise Refused(f"witness not found: {w}", "rerun")
    db = relate.Database(str(w), read_only=True)
    try:
        gq = guard(statement, params, db, "rerun")
        res = db.execute(gq.text, params)
        print(f"RERUN  {shown(w)} · relate-db {relate_version()} · read-only · {len(res.data)} rows")
        from .check import plain

        print_rows(list(res.columns), plain(res.data))
    finally:
        db.close()
    return 0


def cmd_export(args) -> int:
    ref = args.ref
    p = Path(ref)
    if p.suffix == ".rl" and p.exists():
        stem = Path(str(p)[:-3])
    elif p.is_dir():
        mans = sorted(p.glob(f"{args.name or '*'}.manifest.json"))
        if len(mans) != 1:
            raise Refused(f"{len(mans)} manifests in {p}; pass --name", "export")
        stem = Path(str(mans[0])[: -len(".manifest.json")])
    else:
        from .ledger import find

        ledger = Path(args.ledger or "out/ledger.rl")
        if not ledger.exists():
            raise Refused(f"not a .rl, a directory, or an id in {ledger}", "export")
        row = find(ledger, ref)
        if not row or not row.get("w"):
            raise Refused(f"no reduction {ref!r} in {ledger}", "export")
        stem = Path(row["w"]["path_rl"][:-3])
    to = Path(args.to)
    to.mkdir(parents=True, exist_ok=True)
    copied = []
    for suf in (".rl", ".cypher", ".manifest.json", ".html", ".trace.json"):
        src = Path(f"{stem}{suf}")
        if src.exists():
            dst = to / src.name
            if src.resolve() != dst.resolve():
                shutil.copyfile(src, dst)
            copied.append(dst)
    if not any(str(c).endswith(".rl") for c in copied):
        raise Refused(f"{stem}.rl not found", "export")
    print(f"EXPORT  {len(copied)} files → {shown(to)}")
    for c in copied:
        print(f"  {shown(c)}")
    return 0


def cmd_review(args) -> int:
    from .ledger import review, unreviewed

    ledger = Path(args.ledger or "out/ledger.rl")
    if not ledger.exists():
        raise Refused(f"ledger not found: {ledger}", "review")
    if not args.id:
        rows = unreviewed(ledger)
        print(f"UNREVIEWED  {len(rows)} in {shown(ledger)}")
        for r in rows:
            first = next((ln for ln in r["statement"].splitlines() if ln.strip()), "")
            print(f"  {r['id']}  {r['created_at']}  {first[:80]}")
        return 0
    if bool(args.accept) == (args.dispute is not None):
        raise Refused("pass exactly one of --accept or --dispute REASON", "review")
    verdict = "accept" if args.accept else "dispute"
    review(ledger, args.id, verdict, args.dispute or "", by=os.environ.get("WITNESS_REVIEWER", "human"))
    print(f"REVIEW  {args.id}: {verdict}" + (f" — {args.dispute}" if args.dispute else ""))
    return 0


def _prove_one(o, statement: str, params: dict) -> None:
    """Delete one named exhibit from a byte copy of W and re-run the query: the answer must change."""
    from .check import plain
    from .store import Scratch

    col = o.answer_columns[0]
    names = {str(r.get(col)) for r in o.answer_rows}
    ex = next((x for x in o.exhibits if x["start"] in names and x["type"] == "HAS_ROUTE"), o.exhibits[0])
    with tempfile.TemporaryDirectory(prefix="witness-prove-") as tmp:
        sc = Scratch.open_copy(o.files["rl"], tmp)
        try:
            before = plain(sc.run(statement, params).data)
            rid = next(r for r, k in sc.rel_keys.items() if k == ex["key"])
            sc.commit_delete([rid], ())
            after = plain(sc.run(statement, params).data)
        finally:
            sc.close()
    changed = before != after
    gone = sorted({str(r.get(col)) for r in before} - {str(r.get(col)) for r in after})
    print(
        f"\nPROVE ONE  delete exhibit {ex['n']} ({ex['start']})-[:{ex['type']}]->({ex['end']}) from a copy of W, re-run"
    )
    detail = f"{len(before)} rows → {len(after)} rows" + (f" ({', '.join(gone)} drops out)" if gone else "")
    print(f"  {'CHANGED' if changed else 'UNCHANGED'}: {detail}")


def _absence(source: Path, path: Path, params: dict, airports: list) -> None:
    import relate

    from .check import plain
    from .guard import guard

    db = relate.Database(str(source), read_only=True)
    try:
        p = {**params, "airports": airports}
        gq = guard(path.read_text(), p, db, "--absence")
        res = db.execute(gq.text, p)
        print("\nABSENT  checked on the full graph, not part of the witness")
        print_rows(list(res.columns), plain(res.data))
    finally:
        db.close()


def _bindings(source: Path, path: Path, params: dict) -> int | None:
    import relate

    from .guard import guard

    db = relate.Database(str(source), read_only=True)
    try:
        gq = guard(path.read_text(), params, db, "--bindings")
        return len(db.execute(gq.text, params).data)
    except Refused:
        return None
    finally:
        db.close()


def cmd_demo(args) -> int:
    from .check import relate_cli

    r = root()
    source = r / HEADLINE["source"]
    qpath = r / HEADLINE["query"]
    params = {**HEADLINE["params"], **parse_params(args.param)}
    statement = qpath.read_text()
    # repo-relative paths, so the committed manifest and ledger never carry a machine's home directory
    out_dir = Path(shown(r / "witnesses")) if args.update else Path(args.out)
    ledger = Path(shown(r / "witness.rl")) if args.update else out_dir / "ledger.rl"
    cli_path, cli_status = relate_cli() if not args.no_cli else (None, "CLI cross-check off (--no-cli)")
    print(f"Witness {__version__} · Python {sys.version.split()[0]} · relate-db {relate_version()}")
    print(
        f"  {cli_status}"
        + (": answers are cross-checked on the CLI too" if cli_path else " — Python checks only; the CLI is optional")
    )
    stats = json.loads((r / "data/source-stats.json").read_text()) if (r / "data/source-stats.json").exists() else {}
    sc_ = stats.get("store_counts", {})
    print(
        f"  source {shown(source)} · {sc_.get('nodes', 0):,} nodes · {sc_.get('relationships', 0):,} relationships"
        " · air-routes (krlawrence/graph, Apache-2.0)"
    )
    question = next((ln[2:].strip() for ln in statement.splitlines() if ln.strip().startswith("//")), "")
    for k, v in params.items():
        question = question.replace(f"${k}", str(v))
    print(f"\nQUESTION  {question}")
    print(f"  {shown(qpath)} · aggregation, NOT EXISTS, OPTIONAL MATCH · params {json.dumps(params)}")

    def abort():
        sys.stderr.write(
            f"\nwitness demo: aborted by the watchdog after {args.watchdog:g} s "
            f"(the reduction was not changed); partial files in {shown(out_dir)}\n"
        )
        sys.stderr.flush()
        os._exit(EXIT_WATCHDOG)

    timer = threading.Timer(args.watchdog, abort)
    timer.daemon = True
    timer.start()
    prog = Progress()
    try:
        req = Request(
            source=Path(shown(source)),
            statement=statement,
            params=params,
            seed=args.seed,
            strict_lists=True,
            name=HEADLINE["name"],
            out_dir=out_dir,
            ledger=ledger,
            requester="build --update" if args.update else "demo",
            use_cli=not args.no_cli,
        )
        o = reduce_request(req, progress=prog)
    finally:
        prog.done()
        timer.cancel()
    print(f"\nANSWER  {len(o.answer_rows)} rows on the full graph · guard: {' · '.join(o.guard_notes)}")
    print_rows(o.answer_columns, o.answer_rows)
    b = _bindings(source, r / HEADLINE["bindings"], params)
    extra = f"{b} relationships match the answer rows; {o.run['final_counts'][1]} of them suffice" if b else None
    print_outcome(o, extra=extra)
    _absence(source, r / HEADLINE["absence"], params, [row[o.answer_columns[0]] for row in o.answer_rows])
    _prove_one(o, statement, params)
    print(f"\nFILES  {shown(o.files['rl'])} (+ .cypher .manifest.json .html .trace.json)")
    print(f"LEDGER  {shown(ledger)} · {o.ledger_id}")
    if args.update:
        ans = {
            "query": HEADLINE["query"],
            "params": params,
            "columns": o.answer_columns,
            "rows": o.answer_rows,
            "sha256": o.manifest["baseline"]["sha256"],
        }
        (r / "answers").mkdir(exist_ok=True)
        (r / "answers" / f"{HEADLINE['name']}.json").write_text(json.dumps(ans, indent=2, sort_keys=True) + "\n")
        print(f"UPDATED  {shown(r / 'witnesses')} · {shown(r / 'witness.rl')} · answers/{HEADLINE['name']}.json")
    w = shown(o.files["rl"])
    print("\nRE-RUN IT YOURSELF")
    print(f"  uv run witness check {w}")
    print(f"  uv run witness rerun {w} -f {HEADLINE['query']} {cli_flags(params)}")
    print(f"  relate query --database {w} --read-only {cli_flags(params)} < {HEADLINE['query']}   # optional CLI")
    verdict_line(o)
    return o.exit_code


# ---- argument parsing --------------------------------------------------------------------------------------------
def _reduce_opts(p) -> None:
    p.add_argument("--param", action="append", metavar="K=V", help="query parameter (repeatable; JSON or bare string)")
    p.add_argument("--predicate", choices=["keep", "differs", "disagree"], default="keep")
    p.add_argument("--expected", metavar="JSON", help="differs: the expected answer as JSON rows")
    p.add_argument("--loose", action="store_true", help="differs: any non-empty answer other than --expected")
    p.add_argument("--other", metavar="Q2", help="disagree: the second query file")
    p.add_argument("--strict-lists", action="store_true", help="compare lists in order (default: as bags)")
    p.add_argument("--float-digits", type=int, default=12)


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="witness", description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--version", action="store_true", help="print the Witness and relate-db versions")
    sub = ap.add_subparsers(dest="cmd")

    d = sub.add_parser("demo", help="the whole judge path on the committed graph")
    d.add_argument("--param", action="append", metavar="K=V")
    d.add_argument("--seed", type=int, default=0)
    d.add_argument("--out", default="out")
    d.add_argument("--update", action="store_true", help="build only: write witnesses/, witness.rl, answers/")
    d.add_argument("--no-cli", action="store_true", help="skip the relate CLI cross-check")
    d.add_argument("--watchdog", type=float, default=600.0, help="abort-only watchdog in seconds (exit 4)")

    w = sub.add_parser("why", help="reduce a query's answer to a deletion-minimal witness")
    w.add_argument("-f", "--file", required=True, help="the query file")
    w.add_argument("--store", help="source .rl (default: data/air-routes.rl)")
    _reduce_opts(w)
    w.add_argument("--seed", type=int, default=0)
    w.add_argument("--max-trials", type=int, default=20000)
    w.add_argument("--max-seconds", type=float, default=None, help="off by default; when set, no determinism claim")
    w.add_argument("--isolate", action="store_true", help="run each trial in a child process (with --trial-timeout)")
    w.add_argument("--trial-timeout", type=float, default=30.0)
    w.add_argument("--name", default="witness", help="output file stem (default: the query file's stem)")
    w.add_argument("--out", default="out")
    w.add_argument("--ledger", help="ledger .rl (default: <out>/ledger.rl)")
    w.add_argument("--no-ledger", action="store_true")
    w.add_argument("--no-cli", action="store_true")
    w.add_argument("--require-cli", action="store_true")
    w.add_argument("--json", action="store_true")

    c = sub.add_parser("check", help="re-prove a witness: N of N change the answer")
    c.add_argument("witness", help="W.rl (its .manifest.json and .cypher beside it)")
    c.add_argument("-f", "--file", help="without a manifest: the query file")
    _reduce_opts(c)
    c.add_argument("--expect", metavar="JSON", help="without a manifest: the baseline answer as JSON rows")
    c.add_argument("--no-cli", action="store_true")
    c.add_argument("--require-cli", action="store_true", help="a missing or off-version relate CLI is an error")
    c.add_argument("--json", action="store_true")

    r = sub.add_parser("rerun", help="run a query on a witness .rl, read-only, no CLI needed")
    r.add_argument("witness")
    r.add_argument("-f", "--file", required=True)
    r.add_argument("--param", action="append", metavar="K=V")
    r.add_argument("--print-cli", action="store_true", help="print the equivalent plain relate command")

    e = sub.add_parser("export", help="copy a reduction's files (by ledger id, out dir, or W.rl)")
    e.add_argument("ref")
    e.add_argument("--to", default="export")
    e.add_argument("--name")
    e.add_argument("--ledger")

    v = sub.add_parser("review", help="list unreviewed reductions, or accept / dispute one")
    v.add_argument("id", nargs="?")
    v.add_argument("--accept", action="store_true")
    v.add_argument("--dispute", metavar="REASON")
    v.add_argument("--ledger")
    return ap


def main(argv: list[str] | None = None) -> int:
    ap = build_parser()
    args = ap.parse_args(argv)
    if args.version:
        print(f"witness {__version__} (relate-db {relate_version()})")
        return 0
    cmds = {
        "demo": cmd_demo,
        "why": cmd_why,
        "check": cmd_check,
        "rerun": cmd_rerun,
        "export": cmd_export,
        "review": cmd_review,
    }
    if args.cmd not in cmds:
        ap.print_help()
        return 0
    try:
        return cmds[args.cmd](args)
    except Refused as e:
        print(f"refused ({e.door}): {e.reason}", file=sys.stderr)
        return EXIT_REFUSED


if __name__ == "__main__":
    sys.exit(main())
