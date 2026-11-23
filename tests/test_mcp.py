"""`witness mcp`: the `why` and `check` tools, directly and through a real stdio client (no mocks)."""

import asyncio
import json
import sys
from pathlib import Path

import pytest

from witness.mcp_server import ToolError, WitnessTools, evidence_markdown, resolve_store

ROOT = Path(__file__).resolve().parent.parent
HUBS = "MATCH (a:P {name: 'A'})-[:R]->(h)-[:R]->(:P {name: 'D'}) RETURN h.name AS hub ORDER BY hub"


@pytest.fixture
def tools(tmp_path, tiny_rl):
    return WitnessTools(
        allow=[tmp_path], out_root=tmp_path / "out", use_cli=False, trial_timeout=20, request_timeout=120
    )


def test_why_returns_a_witness_whose_check_passes(tools, tiny_rl):
    r = tools.why(HUBS, store=str(tiny_rl), client="pytest")
    assert "error" not in r, r
    assert r["verified"] is True
    assert r["answer"]["rows"] == [{"hub": "B"}, {"hub": "C"}]
    assert r["witness"]["relationships"] == 4  # A->B->D and A->C->D; the E detour is not needed
    assert r["check"]["check_text"].startswith("4 of 4 change the answer")
    assert r["source_sha256"] and r["ledger_id"] and r["relate_version"]
    assert r["trials"] > 0
    assert Path(r["files"]["rl"]).is_file() and Path(r["files"]["cypher"]).is_file()
    # the agent can re-prove the witness from its files through the second tool
    c = tools.check(r["files"]["rl"])
    assert c["verified"] is True and c["check_text"].startswith("4 of 4")
    md = r["evidence_markdown"]
    assert 4 <= len(md.splitlines()) <= 25
    assert "verified deletion-minimal" in md and "4 of 4 change the answer" in md


def test_the_source_is_never_modified_and_the_ledger_records_the_agent(tools, tiny_rl):
    import hashlib

    before = hashlib.sha256(tiny_rl.read_bytes()).hexdigest()
    r = tools.why(HUBS, store=str(tiny_rl), client="claude-code")
    assert hashlib.sha256(tiny_rl.read_bytes()).hexdigest() == before == r["source_sha256"]
    import relate

    db = relate.Database(r["ledger_path"], read_only=True)
    rows = db.execute("MATCH (r:Reduction) RETURN r.requester AS who").data
    db.close()
    assert {"who": "mcp:claude-code"} in rows


@pytest.mark.parametrize(
    "stmt,kind",
    [
        ("CREATE (x:P {name: 'Z'}) RETURN x", "query"),
        ("MATCH (a:P) DETACH DELETE a RETURN 1", "query"),
        ("CALL db.labels() YIELD label RETURN label", "query"),
        ("MATCH (a:P) RETURN rand() AS r", "query"),
        ("LOAD CSV FROM 'file:///x.csv' AS row RETURN row", "query"),
    ],
)
def test_writes_and_nondeterminism_come_back_as_an_error_object(tools, tiny_rl, stmt, kind):
    r = tools.why(stmt, store=str(tiny_rl))
    assert r["verified"] is False
    assert r["error"]["kind"] == kind and r["error"]["message"]
    assert "witness" not in r


def test_empty_answer_is_refused(tools, tiny_rl):
    r = tools.why("MATCH (a:P {name: 'nobody'}) RETURN a.name AS n", store=str(tiny_rl))
    assert "empty" in r["error"]["message"]


def test_store_outside_the_allowlist_is_refused(tools, tmp_path, tiny_rl):
    other = tmp_path.parent / "outside.rl"
    other.write_bytes(tiny_rl.read_bytes())
    try:
        r = tools.why(HUBS, store=str(other))
        assert r["error"]["kind"] == "store" and "allowlisted" in r["error"]["message"]
    finally:
        other.unlink()
    assert tools.why(HUBS, store=str(tiny_rl.with_suffix(".txt")))["error"]["kind"] == "store"
    assert tools.why(HUBS, store=str(tmp_path / "missing.rl"))["error"]["kind"] == "store"


def test_symlink_out_of_the_allowlist_is_refused(tmp_path, tiny_rl):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    outside = tmp_path.parent / "elsewhere.rl"
    outside.write_bytes(tiny_rl.read_bytes())
    (allowed / "link.rl").symlink_to(outside)
    try:
        with pytest.raises(ToolError):
            resolve_store(str(allowed / "link.rl"), [allowed.resolve()], allowed / "x.rl")
    finally:
        outside.unlink()


def test_a_wrong_claimed_answer_attaches_nothing(tools, tiny_rl, tmp_path):
    r = tools.why(HUBS, store=str(tiny_rl), answer=[{"hub": "B"}])
    assert r["error"]["kind"] == "answer" and "nothing attached" in r["error"]["message"]
    assert not (tmp_path / "out").exists() or not list((tmp_path / "out").glob("mcp-*/witness.rl"))
    ok = tools.why(HUBS, store=str(tiny_rl), answer=[{"hub": "C"}, {"hub": "B"}])
    assert ok["verified"] is True  # the same rows as a bag, in another order


def test_request_deadline_returns_not_verified_instead_of_hanging(tmp_path, tiny_rl):
    t = WitnessTools(allow=[tmp_path], out_root=tmp_path / "out", use_cli=False, request_timeout=0.2)
    r = t.why(HUBS, store=str(tiny_rl))
    assert r["verified"] is False and r["error"]["kind"] == "timeout"
    assert "determinism not claimed" in r["error"]["message"]


def test_check_errors_are_objects(tools, tmp_path):
    assert tools.check(str(tmp_path / "nope.rl"))["error"]["kind"] == "witness"
    assert tools.check("/etc/passwd")["error"]["kind"] == "witness"
    bare = tmp_path / "bare.rl"
    bare.write_bytes(b"")
    assert "manifest" in tools.check(str(bare))["error"]["message"]


def test_check_override_is_reported(tools, tiny_rl):
    r = tools.why(HUBS, store=str(tiny_rl))
    c = tools.check(r["files"]["rl"], statement=HUBS)
    assert c["overridden"] == ["statement"] and c["verified"] is True


def test_evidence_markdown_fits_a_chat_reply_even_for_a_long_register():
    ex = [{"n": i, "start": f"S{i}", "type": "HAS_ROUTE", "end": f"E{i}"} for i in range(1, 60)]
    res = {
        "answer": {"rows": [{"a": i} for i in range(9)]},
        "witness": {"relationships": 59},
        "check": {"check_text": "59 of 59 change the answer (59 of 59 relationships, 0 of 0 isolated nodes)"},
        "verified": True,
        "source_relationships": 57645,
        "exhibits": ex,
        "files": {"rl": "out/w.rl"},
        "relate_version": "1.0.1",
        "reasons": [],
    }
    md = evidence_markdown(res)
    assert len(md.splitlines()) <= 25 and "more lines in the file" in md


def test_a_real_mcp_client_lists_both_tools_and_gets_a_witness(tmp_path, tiny_rl):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "witness", "mcp", "--allow", str(tmp_path), "--out", str(tmp_path / "out"), "--no-cli"],
        env={"DO_NOT_TRACK": "1", "PATH": "/usr/bin:/bin"},
        cwd=str(ROOT),
    )

    async def go():
        async with stdio_client(params) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                names = sorted(t.name for t in (await s.list_tools()).tools)
                why = await s.call_tool("why", {"statement": HUBS, "store": str(tiny_rl)})
                bad = await s.call_tool("why", {"statement": "CREATE (n:P) RETURN n", "store": str(tiny_rl)})
                return names, why, bad

    names, why, bad = asyncio.run(asyncio.wait_for(go(), 180))
    assert names == ["check", "why"]
    res = why.structured_content or json.loads(why.content[0].text)
    res = res.get("result", res)
    assert res["verified"] is True and res["check"]["check_text"].startswith("4 of 4")
    badres = bad.structured_content or json.loads(bad.content[0].text)
    badres = badres.get("result", badres)
    assert badres["error"]["kind"] == "query"
