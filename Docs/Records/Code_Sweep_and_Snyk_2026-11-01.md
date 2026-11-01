# Code Sweep and Snyk Results, 2026-11-01

Product: Master Class Diagnostics Workbench 2.2, main at `34350ce`.

This record repeats the 2026-10-29 release clearance checks on 2026-11-01.

## Quality and security gate

The full gate ran with the repository's own tools. Result: **required gates passed**.

| Check | Result |
| --- | --- |
| Tests | 1,061 passed and 38 skipped in 5 min 18 sec |
| Ruff lint and format | Passed |
| Bandit | 0 high, 0 medium, 28 low |
| pip-audit | No known vulnerabilities. The first run hit a PyPI response error and passed on rerun. |
| Gitleaks | Passed |
| License inventory | Passed |
| CycloneDX SBOM | 92 components |
| Dead-code scan (vulture) | Passed |
| mypy | 154 error lines, advisory |

## Snyk

Snyk CLI 1.1305.0, run on 2026-11-01 against the committed lockfile and source.

| Scan | Result |
| --- | --- |
| Open Source (26 dependencies) | 0 vulnerabilities |
| Code | 13 warnings and 50 notes, no errors. Same counts as 2026-10-29. |

The Snyk Code warnings are in the same places as 2026-10-29: command calls in the release smoke and sweep tools, operator-supplied lab regex patterns and one tar extraction. The notes are mostly file-path notices.

## GitHub Dependabot alerts

None open.

## Defects found and fixed during the sweep

- The first gate run failed the banned strings test because the new benchmark record named the path of a sibling project. The reference was removed.
- The first gate run also failed the format check on one launcher test line, which the Docs reorganization had lengthened. It was reformatted.
