# Security Policy

## Supported versions

| Version | Supported |
|---|---|
| latest release and `main` | ✅ |

## Reporting a vulnerability

Please **do not** open a public issue for security vulnerabilities. Report them privately with GitHub's
[private vulnerability reporting](https://github.com/edycutjong/witness/security/advisories/new)
(Security → Report a vulnerability).

You will get an acknowledgment within 72 hours and a resolution timeline after triage. Please allow a reasonable window to
patch before public disclosure.

Scope worth reporting: a way to make Witness run a write, a procedure or a file read through its read-only guard
(`src/witness/guard.py`), a path traversal in the exporter, or a secret committed to the repository.
