# Contributing

Thanks for your interest in improving Witness.

## Getting started

1. Fork the repo and branch from `main`: `git checkout -b feat/your-feature`
2. Install: `uv sync` (Python 3.10 or newer; the pinned `relate-db` is installed for you)
3. Optional, for the cross-check against the Relate CLI: install the CLI from <https://relatedb.ai> (the version pinned in
   `.github/workflows/ci.yml`), then run everything with `DO_NOT_TRACK=1` set.
4. Try it: `uv run witness demo`

## Before you open a PR

- `make ci` passes: ruff, mypy, the test suite with a **100% coverage** gate, and `pip-audit`.
- Tests run against real Relate. Do not mock the graph store or the rollback transactions; add a test named after the
  behaviour or defect it proves.
- If you change the site or the committed evidence, run `uv run python scripts/build_site.py` and commit the result.
- Keep commits conventional (see Releases).

## Releases

Versions come from commit messages (Angular convention) when a change lands on `main`, via `.github/workflows/release.yml`:

| Commit prefix | Bump |
|---|---|
| `fix:` `perf:` | patch |
| `feat:` | minor |
| `feat!:` or a `BREAKING CHANGE:` footer | major |
| `docs:` `chore:` `test:` `refactor:` `style:` `ci:` | none |

## Reporting bugs and requesting features

Open an issue with the templates. For a wrong or surprising witness, attach the query, the parameters, and the Relate and
Witness versions (`uv run witness --version`, `relate --version`).
