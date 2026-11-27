"""`check` from the files alone: CLI discovery, spec construction, tampered files, probe failures, CLI surface."""

import json
import shutil
import stat
import sys
from pathlib import Path

import pytest
import relate

from witness import check as check_mod
from witness.check import (
    CheckSpec,
    _cli_canon,
    _cli_run,
    check,
    cli_param_args,
    has_graph_values,
    plain,
    relate_cli,
    spec_from_args,
    spec_from_manifest,
)
from witness.guard import Refused, static_checks
from witness.pipeline import Request, reduce_request

NAMES = "MATCH (a:P {name: 'A'})-[:R]->(h)-[:R]->(:P {name: 'D'}) RETURN h.name AS hub"
REAL_CLI = shutil.which("relate")
needs_cli = pytest.mark.skipif(relate_cli()[0] is None, reason="pinned relate CLI not on PATH")


def reduce_to(tiny_rl, tmp_path, statement=NAMES, **kw):
    o = reduce_request(
        Request(
            source=Path(tiny_rl),
            statement=statement,
            params=kw.pop("params", {}),
            out_dir=tmp_path / "out",
            ledger=None,
            use_cli=False,
            name=kw.pop("name", "w"),
            **kw,
        )
    )
    return o


@pytest.fixture
def reduced(tiny_rl, tmp_path):
    o = reduce_to(tiny_rl, tmp_path)
    assert o.verified
    return o


def spec_of(o):
    return spec_from_manifest(json.loads(Path(o.files["manifest"]).read_text()))


def fake_cli(tmp_path, body, name="relate-fake"):
    """A stand-in `relate` executable (the one thing we cannot make misbehave on demand)."""
    p = tmp_path / name
    p.write_text(f"#!{sys.executable}\nimport os, sys\n{body}\n")
    p.chmod(p.stat().st_mode | stat.S_IEXEC)
    return str(p)


# ---- CLI discovery ---------------------------------------------------------------------------------------------


def test_a_missing_cli_is_reported_with_where_the_pinned_one_is(monkeypatch, tmp_path):
    monkeypatch.delenv("WITNESS_RELATE_BIN", raising=False)
    monkeypatch.setenv("PATH", str(tmp_path))
    path, status = relate_cli()
    # Relate's installer installs the latest release, never the pinned one: the hint names the pinned release itself
    assert path is None and status.startswith("relate not on PATH")
    assert "github.com/relatedb/relate/releases/tag/v1.0.1" in status and "install.sh" not in status


def test_a_cli_of_the_wrong_version_never_counts_as_present(monkeypatch, tmp_path):
    monkeypatch.setenv("WITNESS_RELATE_BIN", fake_cli(tmp_path, "print('Relate v9.9.9')"))
    path, status = relate_cli()
    assert path is None and "9.9.9 != pinned 1.0.1" in status
    assert "releases/tag/v1.0.1" in status and "WITNESS_RELATE_BIN" in status and "install.sh" not in status


def test_a_cli_whose_version_cannot_be_parsed_is_reported_by_its_first_words(monkeypatch, tmp_path):
    monkeypatch.setenv("WITNESS_RELATE_BIN", fake_cli(tmp_path, "print('nightly build')"))
    path, status = relate_cli()
    assert path is None and "nightly build != pinned" in status


def test_a_cli_that_cannot_be_executed_is_reported_as_failed(monkeypatch, tmp_path):
    not_exec = tmp_path / "relate-noexec"
    not_exec.write_text("not a program")
    monkeypatch.setenv("WITNESS_RELATE_BIN", str(not_exec))
    path, status = relate_cli()
    assert path is None and status == "relate --version failed: PermissionError"


# ---- value helpers ---------------------------------------------------------------------------------------------


def test_plain_describes_graph_values_by_content_never_by_store_id(tiny_rl):
    db = relate.Database(str(tiny_rl))
    row = db.execute(
        "MATCH p = (a:P {name: 'A'})-[r:R]->(b:P {name: 'B'}) RETURN a, r, p, [a] AS xs, {k: b} AS m, b.name AS s"
    ).data[0]
    db.close()
    assert plain(row["a"]) == {"labels": ["P"], "properties": {"name": "A"}}
    assert plain(row["r"]) == {"type": "R", "properties": {}}
    assert plain(row["p"]) == {
        "nodes": [plain(row["a"]), {"labels": ["P"], "properties": {"name": "B"}}],
        "relationships": [{"type": "R", "properties": {}}],
    }
    assert plain(row["xs"]) == [plain(row["a"])]
    assert plain(row["m"]) == {"k": {"labels": ["P"], "properties": {"name": "B"}}}
    assert plain(row["s"]) == "B" and plain(None) is None
    assert "id=" not in json.dumps(plain(row))


def test_plain_falls_back_to_repr_for_a_value_with_no_json_form():
    assert plain(b"x") == "b'x'" and plain((1, (2,))) == [1, [2]]


def test_has_graph_values_looks_inside_lists_and_maps(tiny_rl):
    db = relate.Database(str(tiny_rl))
    n = db.execute("MATCH (a:P {name: 'A'}) RETURN a").data[0]["a"]
    db.close()
    assert has_graph_values([{"x": n}]) and has_graph_values([{"x": [1, [n]]}]) and has_graph_values([{"x": {"k": n}}])
    assert not has_graph_values([{"x": [1, {"k": "v"}], "y": None}]) and not has_graph_values([])


def test_cli_param_args_quotes_strings_that_would_read_back_as_other_types():
    args = cli_param_args({"a": "true", "b": " pad ", "c": "", "d": "plain", "e": 1.5, "f": None})
    assert args == [
        "--param", 'a="true"', "--param", 'b=" pad "', "--param", 'c=""', "--param", "d=plain",
        "--param", "e=1.5", "--param", "f=null",
    ]  # fmt: skip


# ---- spec construction -----------------------------------------------------------------------------------------


def test_check_without_a_manifest_refuses_disagree_without_a_second_query_or_an_expectation():
    with pytest.raises(Refused, match="disagree needs --other"):
        spec_from_args("RETURN 1 AS x", {}, None, kind="disagree")
    with pytest.raises(Refused, match="needs -f, --param and --expect"):
        spec_from_args("RETURN 1 AS x", {}, None)


def test_check_without_a_manifest_refuses_an_expectation_that_is_not_a_list_of_rows():
    with pytest.raises(Refused, match="--expect must be a JSON list"):
        spec_from_args("RETURN 1 AS x", {}, '{"x": 1}')


def test_check_without_a_manifest_guards_the_second_query_of_a_disagreement():
    spec = spec_from_args("RETURN 1 AS x", {}, None, kind="disagree", other="RETURN 2 AS x")
    assert [q.door for q in spec.queries] == ["check", "check --other"]
    with pytest.raises(Refused, match="write keyword"):
        spec_from_args("RETURN 1 AS x", {}, None, kind="disagree", other="CREATE (n) RETURN n")


def test_a_differs_spec_without_a_manifest_resolves_its_expected_hash_against_the_columns(reduced, tmp_path):
    w = tmp_path / "bare.rl"
    shutil.copyfile(reduced.files["rl"], w)
    shutil.copyfile(reduced.files["cypher"], tmp_path / "bare.cypher")
    spec = spec_from_args(NAMES, {}, json.dumps([{"hub": "B"}, {"hub": "C"}]), kind="differs")
    assert spec.baseline_sha == "" and spec.expected_sha is None
    res = check(w, spec, use_cli=False)
    assert spec.baseline_sha and spec.expected_sha == spec.baseline_sha
    assert res.verified
    spec.resolve(["other"])  # already resolved: a second call is a no-op
    assert spec.baseline_sha == spec.expected_sha


def test_check_spec_holds_for_each_predicate_kind():
    q = static_checks("RETURN 1 AS x")
    from witness.canon import canon_rows
    from witness.predicates import answer_sha

    a, b = canon_rows([{"x": 1}]), canon_rows([{"x": 2}])
    keep = CheckSpec([q], "keep", answer_sha(a))
    assert keep.holds([a]) is True and keep.holds([b]) is False and keep.holds([None]) is None
    loose = CheckSpec([q], "differs", answer_sha(a), expected_sha=answer_sha(b), loose=True)
    assert loose.holds([a]) is True and loose.holds([b]) is False and loose.holds([canon_rows([])]) is False
    dis = CheckSpec([q, q], "disagree", answer_sha(a))
    assert dis.holds([a, b]) is True and dis.holds([a, a]) is False
    assert (keep.change_phrase, loose.change_phrase, dis.change_phrase) == (
        "change the answer", "end the mismatch", "end the disagreement"
    )  # fmt: skip


# ---- tampered or incomplete files ------------------------------------------------------------------------------


def test_a_witness_without_its_cypher_is_not_verified_and_says_why(reduced, tmp_path):
    w = tmp_path / "nocypher.rl"
    shutil.copyfile(reduced.files["rl"], w)
    res = check(w, spec_of(reduced), use_cli=False)
    assert res.sufficient is True and not res.verified
    assert res.reasons == ["cypher cross-check unavailable: nocypher.cypher missing beside nocypher.rl"]
    assert res.text.startswith("NOT VERIFIED: 4 of 4 change the answer")


def test_a_cypher_that_describes_a_different_answer_than_the_rl_is_flagged(reduced, tmp_path):
    w = tmp_path / "forged.rl"
    shutil.copyfile(reduced.files["rl"], w)
    forged = Path(reduced.files["cypher"]).read_text().replace("'B'", "'Bee'")
    assert forged != Path(reduced.files["cypher"]).read_text()
    (tmp_path / "forged.cypher").write_text(forged)
    res = check(w, spec_of(reduced), use_cli=False)
    assert "W.rl and the store rebuilt from W.cypher give different answers" in res.disagreements
    assert "W.rl and W.cypher hold different graphs" in res.disagreements and not res.verified


def test_a_query_that_errors_on_the_witness_is_inconclusive_not_a_crash(tmp_path):
    w = tmp_path / "e.rl"
    db = relate.Database(str(w))
    db.execute("CREATE (:P {n: 1})-[:R]->(:P {n: 2})")
    db.close()
    (tmp_path / "e.cypher").write_text("")
    spec = spec_from_args("MATCH (a:P) RETURN 1 / (a.n - 1) AS q", {}, '[{"q": 1}]')
    res = check(w, spec, use_cli=False)
    assert res.sufficient is None and not res.verified
    assert res.text.startswith("NOT SUFFICIENT: sufficiency inconclusive")
    assert "sufficiency inconclusive" in res.reasons


def test_an_element_whose_properties_name_nothing_is_labelled_by_a_prefix_of_its_key(tmp_path):
    src = tmp_path / "anon.rl"
    db = relate.Database(str(src))
    db.execute("CREATE (:P {x: 1})-[:R]->(:P {x: 2})")
    db.close()
    o = reduce_request(
        Request(
            source=src, statement="MATCH (a:P)-[:R]->(b:P) RETURN a.x AS ax", params={}, out_dir=tmp_path / "o",
            ledger=None, use_cli=False, name="w",
        )
    )  # fmt: skip
    assert o.verified
    (probe,) = [p for p in check(o.files["rl"], spec_of(o), use_cli=False).probes]
    assert probe["element"] == '(["N",["P"],{"x":1}])-[:R]->(["N",["P"],{"x":2}])'


def test_a_probe_that_hits_an_engine_error_is_recorded_as_inconclusive(reduced, monkeypatch):
    from witness.store import Scratch

    real = Scratch.commit_delete
    calls = {"n": 0}

    def flaky(self, rel_ids=(), node_ids=()):
        calls["n"] += 1
        if calls["n"] == 2:
            raise OSError("disk went away")
        return real(self, rel_ids, node_ids)

    monkeypatch.setattr(Scratch, "commit_delete", flaky)
    res = check(reduced.files["rl"], spec_of(reduced), use_cli=False)
    bad = [p for p in res.probes if p.get("error")]
    assert [p["i"] for p in bad] == [2] and bad[0]["necessary"] is None and "disk went away" in bad[0]["error"]
    assert res.inconclusive == 1 and not res.verified and res.necessary == 3
    assert res.text.startswith("NOT VERIFIED: 3 of 4 change the answer")


# ---- the CLI surface -------------------------------------------------------------------------------------------


@needs_cli
def test_an_answer_holding_graph_elements_is_checked_on_the_python_surface_only(tiny_rl, tmp_path):
    o = reduce_to(tiny_rl, tmp_path, "MATCH (a:P {name: 'A'})-[:R]->(h)-[:R]->(:P {name: 'D'}) RETURN h")
    assert o.verified
    res = check(o.files["rl"], spec_of(o), use_cli=True)
    assert res.verified and not res.cli_used
    assert res.cli_status == "CLI cross-check skipped: the answer holds graph elements (Python surface only)"
    strict = check(o.files["rl"], spec_of(o), use_cli=True, require_cli=True)
    assert not strict.verified and any(r.startswith("--require-cli: ") for r in strict.reasons)


@needs_cli
def test_an_order_cut_query_cross_checks_sufficiency_but_skips_cli_necessity(tiny_rl, tmp_path):
    o = reduce_to(tiny_rl, tmp_path, "MATCH (a:P {name: 'A'})-[:R]->(h) RETURN h.name AS hub ORDER BY hub LIMIT 2")
    assert o.verified
    res = check(o.files["rl"], spec_of(o), use_cli=True)
    assert res.cli_used and res.cli_status == (
        "relate CLI: sufficiency cross-checked; CLI necessity skipped: order-cut query"
    )
    assert not res.disagreements and all("cli_necessary" not in p for p in res.probes)


FAKE_MODES = r"""
import json, subprocess
real = os.environ["REAL_RELATE"]
mode = os.environ.get("FAKE_MODE", "")
argv = sys.argv[1:]
phase = "version" if argv[:1] == ["--version"] else ("read" if "--read-only" in argv else "probe")
stdin = sys.stdin.read() if phase != "version" else ""
if mode == "fail-" + phase:
    sys.stderr.write("boom: injected failure")
    sys.exit(3)
r = subprocess.run([real, *argv], input=stdin, capture_output=True, text=True)
out = []
for line in r.stdout.splitlines():
    if line.startswith("{") and mode in ("float-" + phase, "change-" + phase) and '"data":[{' in line:
        doc = json.loads(line)
        for row in doc["data"]:
            for k, v in row.items():
                if mode.startswith("float") and isinstance(v, float):
                    row[k] = v + 1e-14
                if mode.startswith("change") and isinstance(v, str):
                    row[k] = v + "!"
        line = json.dumps(doc)
    out.append(line)
sys.stdout.write("\n".join(out) + "\n")
sys.stderr.write(r.stderr)
sys.exit(r.returncode)
"""


@pytest.fixture
def wrapped(monkeypatch, tmp_path):
    """The real pinned CLI behind a wrapper that can be told to fail or to alter rows in one phase."""
    monkeypatch.setenv("REAL_RELATE", REAL_CLI)
    monkeypatch.setenv("WITNESS_RELATE_BIN", fake_cli(tmp_path, FAKE_MODES))

    def mode(m):
        monkeypatch.setenv("FAKE_MODE", m)

    return mode


@needs_cli
def test_the_wrapper_is_transparent_when_it_changes_nothing(reduced, wrapped):
    wrapped("")
    res = check(reduced.files["rl"], spec_of(reduced), use_cli=True, require_cli=True)
    assert res.verified and res.cli_used and "4 of 4 necessity probes cross-checked" in res.cli_status


@needs_cli
def test_a_cli_that_fails_the_sufficiency_run_is_a_disagreement(reduced, wrapped):
    wrapped("fail-read")
    res = check(reduced.files["rl"], spec_of(reduced), use_cli=True)
    assert not res.verified
    assert any(d.startswith("CLI sufficiency run failed (exit 3): boom: injected failure") for d in res.disagreements)


@needs_cli
def test_raw_rows_that_differ_between_the_cli_and_python_are_a_disagreement_even_when_canonical_forms_agree(
    tiny_rl, tmp_path, wrapped
):
    src = tmp_path / "f.rl"
    db = relate.Database(str(src))
    db.execute("CREATE (a:P {name: 'A'})-[:R]->(:P {name: 'B', w: 0.5})")
    db.close()
    o = reduce_to(src, tmp_path, "MATCH (:P {name: 'A'})-[:R]->(h) RETURN h.name AS hub, h.w AS w")
    assert o.verified
    wrapped("float-read")
    res = check(o.files["rl"], spec_of(o), use_cli=True)
    assert "raw rows differ between the CLI and Python on W" in res.disagreements
    assert not any("canonical answers differ" in d for d in res.disagreements) and not res.verified


@needs_cli
def test_canonical_answers_that_differ_between_the_cli_and_python_are_a_disagreement(reduced, wrapped):
    wrapped("change-read")
    res = check(reduced.files["rl"], spec_of(reduced), use_cli=True)
    assert "canonical answers differ between the CLI and Python on W" in res.disagreements and not res.verified


@needs_cli
def test_a_cli_that_fails_a_necessity_probe_is_a_disagreement_naming_the_probe(reduced, wrapped):
    wrapped("fail-probe")
    res = check(reduced.files["rl"], spec_of(reduced), use_cli=True)
    assert [d.split(" failed")[0] for d in res.disagreements] == [f"CLI probe {i}" for i in (1, 2, 3, 4)]
    assert res.cli_status == "relate CLI: sufficiency + 0 of 4 necessity probes cross-checked" and not res.verified


@needs_cli
def test_a_cli_that_answers_a_probe_differently_from_python_is_a_disagreement(reduced, wrapped):
    wrapped("change-probe")
    res = check(reduced.files["rl"], spec_of(reduced), use_cli=True)
    assert len([d for d in res.disagreements if d.endswith("CLI and Python disagree")]) == 4
    assert res.cli_status.endswith("0 of 4 necessity probes cross-checked") and not res.verified


# ---- _cli_run / _cli_canon -------------------------------------------------------------------------------------


def test_cli_run_keeps_only_well_formed_json_documents_and_the_tail_of_stderr(tmp_path):
    body = (
        'sys.stdout.write(\'note: not json\\n{"data": [1]}\\n{broken json\\n  {"data": []}  \\n\')\n'
        "sys.stderr.write('x' * 1000 + 'END')\n"
        "sys.exit(7)"
    )
    code, docs, err = _cli_run(fake_cli(tmp_path, body), ["--database", "x"], "ignored")
    assert code == 7 and docs == [{"data": [1]}, {"data": []}]
    assert len(err) == 400 and err.endswith("END")


def test_cli_canon_gives_nothing_for_a_document_without_data_and_projects_the_columns():
    spec = spec_from_args("RETURN 1 AS x", {}, '[{"x": 1}]')
    gq = spec.queries[0]
    assert _cli_canon(spec, gq, {"error": "nope"}, ["x"]) == (None, None)
    canon, rows = _cli_canon(spec, gq, {"data": [{"x": 1, "extra": 2}, {"x": 3}]}, ["x"])
    assert rows == [{"x": 1}, {"x": 3}] and canon == check_mod.canon_rows(rows, ["x"])


# ---- isolated nodes and disagreements --------------------------------------------------------------------------


def test_a_witness_that_is_a_single_isolated_node_is_probed_by_deleting_the_node(tiny_rl, tmp_path):
    o = reduce_to(tiny_rl, tmp_path, "MATCH (n:P {name: 'A'}) RETURN n.name AS who")
    assert o.verified and o.run["final_counts"] == (1, 0)
    res = check(o.files["rl"], spec_of(o), use_cli=shutil.which("relate") is not None and relate_cli()[0] is not None)
    assert res.verified and [(p["kind"], p["element"]) for p in res.probes] == [("node", "(A)")]
    assert res.text == "1 of 1 change the answer (0 of 0 relationships, 1 of 1 isolated nodes)"


def test_a_disagreement_manifest_rebuilds_both_guarded_queries_for_the_check(tiny_rl, tmp_path):
    hubs = "MATCH (a:P {name: 'A'})-[:R]->(h)-[:R]->(:P {name: 'D'}) RETURN count(DISTINCT h) AS hubs"
    firsts = "MATCH (a:P {name: 'A'})-[:R]->(h) RETURN count(DISTINCT h) AS hubs"
    o = reduce_to(tiny_rl, tmp_path, hubs, predicate="disagree", other=firsts)
    assert o.verified
    spec = spec_of(o)
    assert spec.kind == "disagree" and [q.door for q in spec.queries] == ["check", "check --other"]
    assert spec.queries[1].text == firsts
    res = check(o.files["rl"], spec, use_cli=False)
    assert res.verified and res.change_phrase == "end the disagreement"
    assert res.text.startswith("1 of 1 end the disagreement")  # one A->h edge is all the two queries disagree over
