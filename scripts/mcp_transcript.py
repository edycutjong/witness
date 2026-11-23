"""Record an agent-style MCP session: Relate's own `read_cypher` answers, `witness mcp` supplies the evidence.

A SCRIPTED MCP client plays the agent's calls (no language model is in the loop here; the video's Claude Code session
is separate). It attaches both servers over stdio, asks the headline question through Relate's `read_cypher`, hands the
rows it got to Witness's `why` as `answer`, re-proves the file with `check`, and is refused when it tries a write.
Output: evidence/mcp-transcript.json (every request and result, trimmed only by the answer rows already shown)
and evidence/mcp-transcript.md (the readable version). Run: `uv run --extra mcp python scripts/mcp_transcript.py`.
"""

from __future__ import annotations

import asyncio
import json
import os
import platform
import shutil
import sys
import tempfile
import time
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parent.parent
PARAMS = {"country": "MX", "dest": "MEX"}


def relate_bin() -> str:
    return os.environ.get("WITNESS_RELATE_BIN") or shutil.which("relate") or os.path.expanduser("~/.local/bin/relate")


def payload(res) -> dict:
    d = res.structured_content or json.loads(res.content[0].text)
    return d.get("result", d)


async def main() -> int:
    query = (ROOT / "queries/two-hub.cypher").read_text()
    out = Path(tempfile.mkdtemp(prefix="witness-mcp-"))
    env = {"DO_NOT_TRACK": "1", "PATH": "/usr/bin:/bin"}
    relate = StdioServerParameters(
        command=relate_bin(),
        args=["serve", "--database", "data/air-routes.rl", "--read-only", "--mcp", "stdio"],
        env=env,
        cwd=str(ROOT),
    )
    witness = StdioServerParameters(
        command=sys.executable, args=["-m", "witness", "mcp", "--out", str(out)], env=env, cwd=str(ROOT)
    )
    log: list[dict] = []

    def rec(server, tool, args, result, secs):
        log.append({"server": server, "tool": tool, "arguments": args, "result": result, "seconds": round(secs, 3)})

    async with stdio_client(relate) as (rr, rw), stdio_client(witness) as (wr, ww):
        async with ClientSession(rr, rw) as rs, ClientSession(wr, ww) as ws:
            await rs.initialize()
            await ws.initialize()
            tools = {
                "relate": sorted(t.name for t in (await rs.list_tools()).tools),
                "witness": sorted(t.name for t in (await ws.list_tools()).tools),
            }
            # 1. the agent answers with Relate's own tool
            t = time.perf_counter()
            args = {"statement": query, "parameters": PARAMS}
            r = await rs.call_tool("read_cypher", args)
            ans = payload(r)
            rec("relate", "read_cypher", args, ans, time.perf_counter() - t)
            rows = ans["rows"] if isinstance(ans, dict) and "rows" in ans else ans
            # 2. it asks Witness for the evidence behind that answer, handing over the rows it showed
            t = time.perf_counter()
            args = {"statement": query, "parameters": PARAMS, "answer": rows}
            why = payload(await ws.call_tool("why", args))
            rec("witness", "why", {**args, "answer": f"<the {len(rows)} rows above>"}, why, time.perf_counter() - t)
            # 3. it re-proves the witness file it is about to cite
            t = time.perf_counter()
            args = {"witness_path": why["files"]["rl"]}
            chk = payload(await ws.call_tool("check", args))
            rec(
                "witness",
                "check",
                args,
                {k: chk[k] for k in ("check_text", "verified", "sufficient", "inconclusive", "cli")},
                time.perf_counter() - t,
            )
            # 4. a write is refused, with the reason, as an error object
            t = time.perf_counter()
            args = {"statement": "MATCH (a:Airport) DETACH DELETE a RETURN 1", "store": "data/air-routes.rl"}
            bad = payload(await ws.call_tool("why", args))
            rec("witness", "why", args, bad, time.perf_counter() - t)
            # 5. a wrong answer is refused: nothing is attached
            t = time.perf_counter()
            args = {
                "statement": query,
                "parameters": PARAMS,
                "answer": [{"airport": "PBC", "hub_countries": ["MX", "US"]}],
            }
            wrong = payload(await ws.call_tool("why", args))
            rec("witness", "why", args, wrong, time.perf_counter() - t)

    doc = {
        "what": "scripted MCP client (no model in the loop) against Relate's own MCP server and `witness mcp`, stdio",
        "recorded": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "machine": f"{platform.platform()} {platform.machine()}, Python {platform.python_version()}",
        "relate_cli": os.popen(f"{relate_bin()} --version 2>/dev/null").read().strip().splitlines()[0],
        "tools": tools,
        "calls": log,
    }
    # keep absolute temp paths out of the committed record
    text = json.dumps(doc, indent=2, sort_keys=True).replace(str(out.resolve()), "<out>").replace(str(out), "<out>")
    (ROOT / "evidence").mkdir(exist_ok=True)
    (ROOT / "evidence/mcp-transcript.json").write_text(text + "\n")

    md = ["# `witness mcp` — agent-style transcript", "", f"{doc['what']}. {doc['machine']}; {doc['relate_cli']}.", ""]
    md.append(f"Tools: Relate `{', '.join(tools['relate'])}` · Witness `{', '.join(tools['witness'])}`\n")
    for i, c in enumerate(log, 1):
        res = c["result"]
        md.append(f"## {i}. {c['server']} `{c['tool']}` ({c['seconds']} s)")
        if c["tool"] == "why" and isinstance(res, dict) and "evidence_markdown" in res:
            md += ["", res["evidence_markdown"].replace(str(out.resolve()), "<out>").replace(str(out), "<out>"), ""]
            md.append(
                f"verified={res['verified']} · trials={res['trials']} · reduction {res['seconds']} s"
                f" · ledger {res['ledger_id']}\n"
            )
        else:
            if (
                c["tool"] == "read_cypher"
            ):  # Relate's reply carries plan and timing detail; the rows are what the agent uses
                res = {k: res[k] for k in ("columns", "rows") if k in res}
            md += ["", "```json", json.dumps(res, indent=2, sort_keys=True)[:1800], "```", ""]
    (ROOT / "evidence/mcp-transcript.md").write_text(
        "\n".join(md).replace(str(out.resolve()), "<out>").replace(str(out), "<out>") + "\n"
    )
    ok = (
        why.get("verified") is True
        and chk.get("verified") is True
        and "error" in bad
        and wrong.get("error", {}).get("kind") == "answer"
    )
    print("transcript:", "OK" if ok else "FAILED", "→ evidence/mcp-transcript.{json,md}")
    shutil.rmtree(out, ignore_errors=True)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
