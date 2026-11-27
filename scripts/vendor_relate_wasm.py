"""Self-host Relate's browser build for the landing page: site/relate/<version>/, unchanged from npm.

The landing runs the witness on Relate in the visitor's tab. The engine is the published package
@relate/relate-wasm (Apache-2.0), pinned by version and by the registry's sha512 integrity, and served from this
site, so the page makes no request to a third party to run it. Only the four entries Relate's browser guide says
to serve are copied (relate.js, relate_bg.wasm, trap.js, snippets/), plus package.json for the version and licence.

    uv run python scripts/vendor_relate_wasm.py          # fetch, verify, write site/relate/<v>/ + engines.json
    uv run python scripts/vendor_relate_wasm.py --check  # offline: the committed files match engines.json

1.0.1 is the release every committed witness was reduced on (the relate-db pin). 1.3.0 is the release whose notes
list the fix for the engine case (EXISTS against COUNT over two MATCH clauses), so the page can run both forms on
both releases.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import sys
import tarfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "site" / "relate"
PACKAGE = "@relate/relate-wasm"
# version -> the registry's dist.integrity (npm view @relate/relate-wasm@<v> dist.integrity)
PINS = {
    "1.0.1": "sha512-deNmVx7D7NvWA91AWcN+YgoqrSYr7Z9FzfCK/Q3Jt9hyGx7y94zGAlR7rw6oZXulphW4FPjO5iwupGtVi3fhcw==",
    "1.3.0": "sha512-8jjuA1w7WUWF8gTFybsoRiEpzCZIKeI3nlidAgF4uqsiV4KmXEDcFiwznzNCvDa+sV4iSQQx993tOy5AHkbRnQ==",
}
KEEP = ("relate.js", "relate_bg.wasm", "trap.js", "package.json")


def tarball_url(version: str) -> str:
    return f"https://registry.npmjs.org/{PACKAGE}/-/relate-wasm-{version}.tgz"


def wanted(name: str) -> str | None:
    """The path under site/relate/<v>/ for a tarball member, or None to skip it. Never leaves the directory."""
    if not name.startswith("package/"):
        return None
    rel = name[len("package/") :]
    parts = rel.split("/")
    if any(p in ("", ".", "..") for p in parts):
        return None
    if rel in KEEP:
        return rel
    if parts[0] == "snippets" and rel.endswith(".js"):
        return rel
    return None


def fetch(version: str) -> dict[str, bytes]:
    with urllib.request.urlopen(tarball_url(version), timeout=60) as r:  # noqa: S310 (fixed https registry URL)
        blob = r.read()
    algo, want = PINS[version].split("-", 1)
    got = base64.b64encode(hashlib.new(algo, blob).digest()).decode()
    if got != want:
        sys.exit(f"{PACKAGE}@{version}: integrity mismatch (registry says {want}, the download is {got})")
    files: dict[str, bytes] = {}
    with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as tar:
        for m in tar.getmembers():
            dest = wanted(m.name)
            if dest is None or not m.isfile():
                continue
            f = tar.extractfile(m)
            assert f is not None
            files[dest] = f.read()
    missing = [k for k in KEEP if k not in files] + (
        [] if any(k.startswith("snippets/") for k in files) else ["snippets/"]
    )
    if missing:
        sys.exit(f"{PACKAGE}@{version}: the tarball lacks {missing}")
    return files


def manifest_entry(version: str, files: dict[str, bytes]) -> dict:
    return {
        "package": PACKAGE,
        "version": version,
        "license": json.loads(files["package.json"])["license"],
        "tarball": tarball_url(version),
        "integrity": PINS[version],
        "files": {k: hashlib.sha256(v).hexdigest() for k, v in sorted(files.items())},
    }


def write() -> dict:
    engines = {}
    for v in PINS:
        files = fetch(v)
        d = OUT / v
        for rel, data in files.items():
            p = d / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data)
        engines[v] = manifest_entry(v, files)
        print(f"{PACKAGE}@{v}: {len(files)} files, integrity ok -> {d.relative_to(ROOT)}")
    (OUT / "engines.json").write_text(json.dumps(engines, indent=2) + "\n")
    return engines


def check() -> list[str]:
    """Problems with the committed engines; empty when every file matches engines.json."""
    engines = json.loads((OUT / "engines.json").read_text())
    bad = []
    if sorted(engines) != sorted(PINS):
        bad.append(f"engines.json lists {sorted(engines)}, the pins are {sorted(PINS)}")
    for v, e in engines.items():
        if e.get("integrity") != PINS.get(v):
            bad.append(f"{v}: integrity in engines.json is not the pin")
        on_disk = {p.relative_to(OUT / v).as_posix() for p in (OUT / v).rglob("*") if p.is_file()}
        if on_disk != set(e["files"]):
            bad.append(f"{v}: files on disk {sorted(on_disk ^ set(e['files']))} differ from engines.json")
        for rel, sha in e["files"].items():
            p = OUT / v / rel
            if p.is_file() and hashlib.sha256(p.read_bytes()).hexdigest() != sha:
                bad.append(f"{v}/{rel}: sha256 differs from engines.json")
    return bad


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="verify the committed files offline")
    a = ap.parse_args()
    if a.check:
        bad = check()
        print("\n".join(bad) or "site/relate: every engine file matches engines.json")
        sys.exit(1 if bad else 0)
    write()


if __name__ == "__main__":
    main()
