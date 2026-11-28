"""The landing's live pulls run on Relate's browser build; they must give the rows the Python run recorded.

scripts/wasm_parity.mjs runs site/relate/live.js (the file the page's worker imports) on the self-hosted
@relate/relate-wasm engines under Node, and compares every pull with evidence/pull-each-tag.json and the engine case
with evidence/relate-versions.jsonl. The engines themselves are checked against their pinned checksums.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import vendor_relate_wasm as vrw  # noqa: E402

NODE = shutil.which("node")


def test_self_hosted_engines_match_their_pins():
    assert vrw.check() == []
    engines = json.loads((ROOT / "site" / "relate" / "engines.json").read_text())
    assert sorted(engines) == sorted(vrw.PINS)
    for v, e in engines.items():
        assert e["license"] == "Apache-2.0" and e["integrity"] == vrw.PINS[v]
        assert json.loads((ROOT / "site" / "relate" / v / "package.json").read_text())["version"] == v


def test_vendor_only_takes_the_served_entries():
    assert vrw.wanted("package/relate.js") == "relate.js"
    assert vrw.wanted("package/snippets/relate-wasm-abc/js/opfs.js") == "snippets/relate-wasm-abc/js/opfs.js"
    for name in (
        "package/README.md",
        "package/relate.d.ts",
        "package/../evil.js",
        "other/relate.js",
        "package/snippets/../x.js",
    ):
        assert vrw.wanted(name) is None, name


def test_verify_compares_every_served_file_with_the_registry_tarball(monkeypatch):
    """--verify is what "unmodified" rests on. Here the registry is stood in by the committed files (no network in
    tests); the real download is one command: uv run python scripts/vendor_relate_wasm.py --verify."""

    def committed(v):
        return {p.relative_to(vrw.OUT / v).as_posix(): p.read_bytes() for p in (vrw.OUT / v).rglob("*") if p.is_file()}

    def tampered(v):
        files = committed(v)
        files["relate.js"] += b"// changed"
        files.pop("trap.js")
        return files

    monkeypatch.setattr(vrw, "fetch", committed)
    assert vrw.verify() == []
    monkeypatch.setattr(vrw, "fetch", tampered)
    bad = vrw.verify()
    assert any("relate.js: differs from the registry's tarball" in b for b in bad), bad
    assert any("trap.js" in b and "are not the tarball's" in b for b in bad), bad
    monkeypatch.setattr(vrw, "PACKAGE", "@someone/else")
    assert any("package, version or tarball" in b for b in vrw.check())
    monkeypatch.setattr(vrw, "LICENSE_TEXT", vrw.OUT / "no-such-file.txt")  # the licence text travels with the engines
    assert any("LICENSE.txt" in b for b in vrw.check())


def test_the_page_serves_the_live_steps_it_was_checked_with():
    for f in ("live.js", "worker.js"):
        assert (ROOT / "site" / "relate" / f).read_bytes() == (ROOT / "scripts" / "site" / f).read_bytes()
    rec = json.loads((ROOT / "evidence" / "wasm-parity.json").read_text())
    assert rec["live_js_sha256"] == hashlib.sha256((ROOT / "site" / "relate" / "live.js").read_bytes()).hexdigest()


@pytest.mark.skipif(NODE is None, reason="needs Node.js to run Relate's browser build outside a browser")
def test_live_pulls_match_the_recorded_run(tmp_path):
    out = tmp_path / "parity.json"
    r = subprocess.run(
        [NODE, str(ROOT / "scripts" / "wasm_parity.mjs"), "--out", str(out)],
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    assert r.returncode == 0, r.stdout + r.stderr
    got = json.loads(out.read_text())
    recorded = json.loads((ROOT / "evidence" / "pull-each-tag.json").read_text())
    assert got["ok"] and got["engine"]["reported"] == recorded["run"]["relate_db"]
    assert got["pulls"]["of"] == got["pulls"]["same_rows"] == got["pulls"]["changed"] == recorded["of"]
    assert [(p["n"], p["rel"], p["rows_after"]) for p in got["pulls"]["rows"]] == [
        (t["n"], t["rel"], t["rows_after"]) for t in recorded["tags"]
    ]
    assert got["baseline_same"] and got["write_refused"]
    by_v = {e["version"]: e for e in got["engine_case"]}
    assert by_v["1.0.1"]["agree"] is False and by_v["1.3.0"]["agree"] is True
    assert all(e["same_as_recorded"] and e["reported"] == e["version"] for e in got["engine_case"])
    # the committed evidence says the same thing as this fresh run (timings aside)
    committed = json.loads((ROOT / "evidence" / "wasm-parity.json").read_text())
    strip = lambda d: [{k: v for k, v in p.items() if k != "ms"} for p in d["pulls"]["rows"]]  # noqa: E731
    assert strip(committed) == strip(got) and committed["engine_case"] == got["engine_case"]
