"""`witness check`: re-prove a witness from its files alone, on two engine surfaces.

Independent of any reducer state. Every probe starts from a fresh, intact copy of W:
- Python surface (relate-db): P holds on W.rl and on a store rebuilt from W.cypher (sufficiency); then for each kept
  relationship (its endpoints stay) and each kept isolated node, byte-copy W.rl, delete that one element, evaluate P.
- CLI surface (the pinned `relate` binary, optional): sufficiency via `relate query --database W.rl --read-only`;
  necessity via one `relate query --load W.rl --database <new copy>` per probe with `.begin`, the delete (by content,
  not by id), the query and `.rollback`. Both surfaces are compared on canonical and raw rows; any disagreement prints
  NOT verified. A missing or off-version CLI is skipped with a notice, never counted as cross-verified.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from .canon import canon_rows
from .export import _lit
from .guard import GuardedQuery, Refused, Tie, static_checks, strip_comments
from .predicates import answer_of, answer_sha, expected_answer
from .store import Scratch

PINNED_RELATE_CLI = "1.0.1"
INSTALL_HINT = "curl -sSfL https://relatedb.ai/install.sh | bash"


def relate_cli() -> tuple[str | None, str]:
    """(path or None, one-line status). Only the pinned version counts as present."""
    path = os.environ.get("WITNESS_RELATE_BIN") or shutil.which("relate")
    if not path:
        return None, f"relate not on PATH (install: {INSTALL_HINT})"
    try:
        out = subprocess.run(
            [path, "--version"], capture_output=True, text=True, timeout=30, env={**os.environ, "DO_NOT_TRACK": "1"}
        ).stdout.strip()
    except Exception as e:  # noqa: BLE001
        return None, f"relate --version failed: {type(e).__name__}"
    m = re.search(r"v?(\d+\.\d+\.\d+)", out)
    ver = m.group(1) if m else out[:40]
    if ver != PINNED_RELATE_CLI:
        return None, f"relate {ver} != pinned {PINNED_RELATE_CLI} (install the pinned one: {INSTALL_HINT})"
    return path, f"relate CLI v{ver}"


def cli_param_args(params: dict) -> list[str]:
    """`--param k=v` flags. Strings go bare unless they would parse as another JSON type; the rest as JSON."""
    out = []
    for k, v in params.items():
        if isinstance(v, str):
            try:
                bare_ok = isinstance(json.loads(v), str)
            except ValueError:
                bare_ok = True
            out += ["--param", f"{k}={v}" if bare_ok else f"{k}={json.dumps(v)}"]
        else:
            out += ["--param", f"{k}={json.dumps(v)}"]
    return out


def plain(v):
    """JSON-safe raw value for the raw-row comparison."""
    if v is None or isinstance(v, (bool, int, float, str)):
        return v
    if isinstance(v, (list, tuple)):
        return [plain(x) for x in v]
    if isinstance(v, dict):
        return {str(k): plain(x) for k, x in v.items()}
    return repr(v)


def has_graph_values(rows: list[dict]) -> bool:
    def g(v):
        if hasattr(v, "properties") or (hasattr(v, "nodes") and hasattr(v, "relationships")):
            return True
        if isinstance(v, (list, tuple)):
            return any(g(x) for x in v)
        if isinstance(v, dict):
            return any(g(x) for x in v.values())
        return False

    return any(g(v) for r in rows for v in r.values())


def raw_bag(rows: list[dict]) -> Counter:
    return Counter(json.dumps(plain(r), sort_keys=True) for r in rows)


@dataclass
class CheckSpec:
    queries: list[GuardedQuery]
    kind: str  # keep | differs | disagree
    baseline_sha: str
    expected_sha: str | None = None
    loose: bool = False
    strict_lists: bool = False
    digits: int = 12
    expect_rows: list | None = None  # no manifest: the stated answer, resolved against W's columns at check time

    def resolve(self, columns: list[str]) -> None:
        if self.expect_rows is None or self.baseline_sha:
            return
        sha = answer_sha(expected_answer(self.expect_rows, columns, strict_lists=self.strict_lists, digits=self.digits))
        self.baseline_sha = sha
        if self.kind == "differs":
            self.expected_sha = sha

    def holds(self, answers: list) -> bool | None:
        if any(a is None or isinstance(a, Tie) for a in answers):
            return None
        if self.kind == "disagree":
            return answers[0] != answers[1]
        if self.kind == "differs" and self.loose:
            return answer_sha(answers[0]) != self.expected_sha and len(answers[0]) > 0
        return answer_sha(answers[0]) == self.baseline_sha

    @property
    def change_phrase(self) -> str:
        return "end the disagreement" if self.kind == "disagree" else "change the answer"


def spec_from_manifest(manifest: dict) -> CheckSpec:
    params = manifest["params"]
    qs = [static_checks(manifest["statement"], params, "check")]
    pred = manifest["predicate"]
    if pred["kind"] == "disagree":
        qs.append(static_checks(pred["other_statement"], params, "check --other"))
    cmp_ = manifest.get("comparison", {})
    return CheckSpec(
        queries=qs,
        kind=pred["kind"],
        baseline_sha=manifest["baseline"]["sha256"],
        expected_sha=pred.get("expected_sha256"),
        loose=bool(pred.get("loose")),
        strict_lists=bool(cmp_.get("strict_lists")),
        digits=int(cmp_.get("float_digits", 12)),
    )


def spec_from_args(statement, params, expect_json, kind="keep", other=None, loose=False, strict_lists=False, digits=12):
    """No manifest: the caller states the query, parameters and expected answer explicitly (refused otherwise)."""
    if kind == "disagree":
        if not other:
            raise Refused("check without a manifest: disagree needs --other", "check")
    elif expect_json is None:
        raise Refused("check without a manifest needs -f, --param and --expect (the baseline answer as JSON rows)")
    qs = [static_checks(statement, params, "check")]
    if kind == "disagree":
        qs.append(static_checks(other, params, "check --other"))
    rows = json.loads(expect_json) if expect_json is not None else None
    if rows is not None and not isinstance(rows, list):
        raise Refused("--expect must be a JSON list of row objects", "check")
    return CheckSpec(qs, kind, "", None, loose, strict_lists, digits, expect_rows=rows)


@dataclass
class CheckResult:
    sufficient: bool | None = None
    probes: list[dict] = field(default_factory=list)
    cli_status: str = ""
    cli_used: bool = False
    disagreements: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    change_phrase: str = "change the answer"

    @property
    def inconclusive(self) -> int:
        return sum(p["necessary"] is None for p in self.probes)

    @property
    def necessary(self) -> int:
        return sum(p["necessary"] is True for p in self.probes)

    @property
    def verified(self) -> bool:
        return (
            self.sufficient is True
            and len(self.probes) > 0  # an empty W proves nothing
            and self.inconclusive == 0
            and self.necessary == len(self.probes)
            and not self.disagreements
            and not self.reasons
        )

    @property
    def text(self) -> str:
        rels = [p for p in self.probes if p["kind"] == "rel"]
        nodes = [p for p in self.probes if p["kind"] == "node"]
        n = len(self.probes)
        t = f"{self.necessary} of {n} {self.change_phrase}"
        t += f" ({sum(p['necessary'] is True for p in rels)} of {len(rels)} relationships"
        t += f", {sum(p['necessary'] is True for p in nodes)} of {len(nodes)} isolated nodes)"
        return t

    def to_dict(self) -> dict:
        return {
            "check_text": self.text,
            "verified": self.verified,
            "sufficient": self.sufficient,
            "inconclusive": self.inconclusive,
            "cli": self.cli_status,
            "cli_used": self.cli_used,
            "disagreements": self.disagreements,
            "reasons": self.reasons,
            "probes": self.probes,
        }


def _answers(sc: Scratch, spec: CheckSpec) -> tuple[list, list]:
    """Canonical answers (cut applied, Tie on a boundary tie) and raw rows of each query on ``sc``."""
    answers, raws = [], []
    for gq in spec.queries:
        try:
            res = sc.run(gq.exec_text, gq.params)
            answers.append(
                answer_of(gq, res.data, res.columns, keyer=sc.keyer, strict_lists=spec.strict_lists, digits=spec.digits)
            )
            raws.append(res)
        except Exception:  # noqa: BLE001 - an error is inconclusive
            answers.append(None)
            raws.append(None)
    return answers, raws


def _element_label(sc: Scratch, kind: str, eid: str) -> str:
    def nm(n):
        p = sc.node_props[n]
        for k in ("iata", "code", "name", "title", "id"):
            if k in p:
                return str(p[k])
        return sc.node_keys[n][:24]

    if kind == "node":
        return f"({nm(eid)})"
    s, e = sc.rel_ends[eid]
    return f"({nm(s)})-[:{sc.rel_type[eid]}]->({nm(e)})"


def _content_delete(sc: Scratch, kind: str, eid: str) -> str:
    def pat(n, var):
        labels = "".join(f":`{lb}`" for lb in sorted(sc.node_labels[n]))
        props = sc.node_props[n]
        return f"({var}{labels} {_lit(props)})" if props else f"({var}{labels})"

    if kind == "node":
        return f"MATCH {pat(eid, 'n')} DETACH DELETE n RETURN count(*) AS deleted"
    s, e = sc.rel_ends[eid]
    rp = sc.rel_props[eid]
    rprops = f" {_lit(rp)}" if rp else ""
    return f"MATCH {pat(s, 'a')}-[r:`{sc.rel_type[eid]}`{rprops}]->{pat(e, 'b')} DELETE r RETURN count(*) AS deleted"


def _cli_run(cli: str, args: list[str], stdin: str) -> tuple[int, list[dict], str]:
    r = subprocess.run(
        [cli, "query", *args, "--mode", "json", "--max-rows", "0", "--timeout", "30s"],
        input=stdin,
        capture_output=True,
        text=True,
        timeout=120,
        env={**os.environ, "DO_NOT_TRACK": "1"},
    )
    docs = []
    for line in r.stdout.splitlines():
        line = line.strip()
        if line.startswith("{"):
            try:
                docs.append(json.loads(line))
            except ValueError:
                pass
    return r.returncode, docs, r.stderr[-400:]


def _cli_canon(spec: CheckSpec, gq: GuardedQuery, doc: dict, columns: list[str]):
    rows = doc.get("data")
    if rows is None:
        return None, None
    rows = [{c: r.get(c) for c in columns} for r in rows]
    return canon_rows(rows, columns, strict_lists=spec.strict_lists, digits=spec.digits), rows


def check(w_rl: str | Path, spec: CheckSpec, *, use_cli: bool = True, require_cli: bool = False) -> CheckResult:
    w_rl = Path(w_rl)
    out = CheckResult(change_phrase=spec.change_phrase)
    w_cypher = w_rl.with_suffix(".cypher")
    with tempfile.TemporaryDirectory(prefix="witness-check-") as tmp:
        tmp = Path(tmp)
        # ---- Python sufficiency: on W.rl, and on a store rebuilt from W.cypher ----------------------------------
        base = Scratch.open_copy(w_rl, tmp)
        try:
            ans_w, raw_w = _answers(base, spec)
            if raw_w[0] is not None:
                spec.resolve(list(raw_w[0].columns))
            suff = spec.holds(ans_w)
            if w_cypher.exists():
                from .export import write_rl

                rebuilt = tmp / "from-cypher.rl"
                write_rl(w_cypher.read_text(), rebuilt)
                sc2 = Scratch.open_copy(rebuilt, tmp)
                ans_c, _ = _answers(sc2, spec)
                same_graph = set(sc2.node_keys.values()) == set(base.node_keys.values()) and set(
                    sc2.rel_keys.values()
                ) == set(base.rel_keys.values())
                sc2.close()
                if not same_graph:
                    out.disagreements.append("W.rl and W.cypher hold different graphs")
                if ans_c != ans_w:
                    out.disagreements.append("W.rl and the store rebuilt from W.cypher give different answers")
            else:
                out.reasons.append(f"cypher cross-check unavailable: {w_cypher.name} missing beside {w_rl.name}")
            out.sufficient = suff
            if suff is not True:
                why = "the predicate does not hold on W" if suff is False else "sufficiency inconclusive"
                out.reasons.append(why)
            elements = [("rel", r) for r in sorted(base.rel_keys, key=base.rel_keys.get)]
            touched = {x for ends in base.rel_ends.values() for x in ends}
            elements += [("node", n) for n in sorted(base.node_keys, key=base.node_keys.get) if n not in touched]
            labels = {eid: _element_label(base, k, eid) for k, eid in elements}
            deletes = {eid: _content_delete(base, k, eid) for k, eid in elements}
            py_raw_cols = [r.columns if r is not None else None for r in raw_w]
            graph_cols = any(r is not None and has_graph_values(r.data) for r in raw_w)
        finally:
            base.close()

        # ---- Python necessity: one fresh copy of W per probe ----------------------------------------------------
        for i, (kind, eid) in enumerate(elements, 1):
            sc = Scratch.open_copy(w_rl, tmp)
            try:
                sc.commit_delete([eid] if kind == "rel" else [], [eid] if kind == "node" else [])
                ans, raws = _answers(sc, spec)
                h = spec.holds(ans)
                probe = {"i": i, "kind": kind, "element": labels[eid], "necessary": None if h is None else (not h)}
                probe["_raw"] = [raw_bag(r.data) if r is not None else None for r in raws]
                probe["_canon"] = ans
            except Exception as e:  # noqa: BLE001
                probe = {"i": i, "kind": kind, "element": labels[eid], "necessary": None, "error": str(e)[:200]}
            finally:
                sc.close()
            out.probes.append(probe)

        # ---- CLI surface ----------------------------------------------------------------------------------------
        cli, status = relate_cli() if use_cli else (None, "CLI cross-check off")
        if cli and graph_cols:
            cli, status = None, "CLI cross-check skipped: the answer holds graph elements (Python surface only)"
        if cli is None:
            out.cli_status = f"CLI cross-check skipped: {status}" if not status.startswith("CLI") else status
            if require_cli:
                out.reasons.append("--require-cli: " + status)
        else:
            out.cli_used = True
            cut = any(gq.cut is not None for gq in spec.queries)
            params = spec.queries[0].params
            pargs = cli_param_args(params)
            texts = [strip_comments(gq.text) for gq in spec.queries]
            # sufficiency, read-only on W
            stdin = "".join(t + ";\n" for t in texts)
            code, docs, err = _cli_run(cli, ["--database", str(w_rl), "--read-only", *pargs], stdin)
            if code != 0 or len(docs) != len(texts):
                out.disagreements.append(f"CLI sufficiency run failed (exit {code}): {err.strip()[:160]}")
            else:
                cli_ans = []
                for gq, doc, cols, pyraw in zip(spec.queries, docs, py_raw_cols, raw_w, strict=True):
                    c, rows = _cli_canon(spec, gq, doc, cols or [])
                    cli_ans.append(c)
                    if pyraw is not None and gq.cut is None and raw_bag(rows) != raw_bag(pyraw.data):
                        out.disagreements.append("raw rows differ between the CLI and Python on W")
                if cli_ans != ans_w:
                    out.disagreements.append("canonical answers differ between the CLI and Python on W")
            # necessity, one fresh writable copy per probe (skipped for order-cut queries)
            if cut:
                out.cli_status = "relate CLI: sufficiency cross-checked; CLI necessity skipped: order-cut query"
            else:
                agree = 0
                for (_kind, eid), probe in zip(elements, out.probes, strict=True):
                    target = tmp / f"cli-probe-{probe['i']}.rl"
                    script = ".begin\n" + deletes[eid] + ";\n" + "".join(t + ";\n" for t in texts) + ".rollback\n"
                    code, docs, err = _cli_run(cli, ["--load", str(w_rl), "--database", str(target), *pargs], script)
                    deleted = (docs[0].get("data") or [{}])[0].get("deleted") if docs else None
                    ok = code == 0 and len(docs) == 1 + len(texts) and deleted == 1
                    if not ok:
                        out.disagreements.append(f"CLI probe {probe['i']} failed (exit {code}): {err.strip()[:120]}")
                        continue
                    pairs = [
                        _cli_canon(spec, gq, d, c or [])
                        for gq, d, c in zip(spec.queries, docs[1:], py_raw_cols, strict=True)
                    ]
                    cans = [c for c, _ in pairs]
                    rows_l = [r for _, r in pairs]
                    h = spec.holds(cans)
                    cli_nec = None if h is None else (not h)
                    raw_ok = list(probe.get("_raw") or []) == [raw_bag(r) for r in rows_l]
                    if cli_nec != probe["necessary"] or cans != list(probe.get("_canon") or []) or not raw_ok:
                        out.disagreements.append(f"probe {probe['i']} {probe['element']}: CLI and Python disagree")
                    else:
                        agree += 1
                    probe["cli_necessary"] = cli_nec
                out.cli_status = f"relate CLI: sufficiency + {agree} of {len(elements)} necessity probes cross-checked"
    for p in out.probes:
        p.pop("_raw", None)
        p.pop("_canon", None)
    return out
