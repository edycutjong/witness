.PHONY: help lint lint-fix typecheck test test-coverage audit perf site ci

help: ## list targets
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | sed 's/:.*##/ -/'

# ── Code quality ────────────────────────────────────────────
lint: ## ruff
	uv run ruff check .

lint-fix: ## ruff --fix
	uv run ruff check --fix .

typecheck: ## mypy
	uv run mypy src --ignore-missing-imports

test: ## pytest against real Relate
	DO_NOT_TRACK=1 uv run pytest

test-coverage: ## pytest with the 100% coverage gate (config in pyproject.toml)
	DO_NOT_TRACK=1 uv run pytest --cov=witness --cov-report=term-missing --cov-report=xml

# ── Security ────────────────────────────────────────────────
audit: ## pip-audit + gitleaks over the full history
	uv run pip-audit --skip-editable
	@if command -v gitleaks >/dev/null 2>&1; then gitleaks detect --no-banner --redact; \
	else echo "gitleaks is not installed (not a Python package): skipped here; CI runs it on every push"; fi

# ── Performance and site ────────────────────────────────────
perf: ## throughput floor (CI uses the same script)
	DO_NOT_TRACK=1 uv run python scripts/perf_gate.py

site: ## rebuild site/ and JUDGE.md from the committed evidence
	uv run python scripts/build_site.py

ci: lint typecheck test-coverage audit ## everything CI runs in stages 1-2
