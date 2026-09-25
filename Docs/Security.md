# Security

The Workbench runs on an attendee's own machine against data they collected
themselves. These are the rules the code follows and the checks that enforce
them.

## Model

- Everything read from a data folder is untrusted input. Paths are resolved
  and typed, extensions are enforced, and module-specific checks reject
  unsupported captures before any parsing starts.
- Generation is local only. No shipped script imports an HTTP client or opens
  a network connection. `Tests/test_security_guardrails.py` fails the suite
  if one appears. The Infographic renderer drives the system browser
  (Edge or Chrome) in headless mode to draw a local HTML file. It fetches
  nothing.
- Child processes receive argument lists, never shell strings. The same test
  fails the suite on `shell=True`.
- Dependencies are pinned in `requirements.txt`, audited for known
  vulnerabilities, and inventoried in the SBOM and the third-party notices
  that ship with every release.
- The sample data is fictional. Nothing in the repository or the package
  comes from a customer environment.

## Gate

Run before every release, from the repository root:

```powershell
.\Tools\run-code-sweep.ps1
```

| Check | Tool | Blocks a release when |
|---|---|---|
| Tests | pytest | Any test fails. |
| Lint and format | ruff | Any finding. |
| Static security analysis | bandit | Any high-severity finding. Medium findings need a recorded decision. |
| Known vulnerabilities | pip-audit | Any finding against the installed packages. |
| Secrets | gitleaks | Any finding. |
| License inventory | pip-licenses | Never blocks. Reviewed for license compatibility. |
| SBOM | cyclonedx-py | Never blocks. Ships with the release. |
| Dead code, types | vulture, mypy | Never block. Advisory. |

The executive summary written by the sweep states the overall result as
**Clean**, **Review Recommended** or **Action Required**.

## Reporting A Problem

Attendees who find a security problem should report it to the presenter
directly rather than in a public channel.
