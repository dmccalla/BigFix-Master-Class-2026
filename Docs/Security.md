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
.\Build\run-code-sweep.ps1
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

## Accepted Findings

Bandit reports these at Low severity on every sweep. Each is a deliberate
design choice with a compensating control, recorded here so the next reader
does not re-triage them.

| Finding | Where | Why it is accepted |
|---|---|---|
| B404, B603, B607 subprocess use and partial executable paths | `App/run_diagnostics.py`, `App/diagnostics_workbench_ui.py`, `Get/get_perfmon_charts.py`, `Lib/Analysis/filldb_perf_log.py`, `Lib/Core/input_utils.py`, `Lib/Design/html_charts.py`, `Lib/Core/subprocess_window.py` | The Workbench runs `relog.exe`, `pythonw.exe`, `MXFillDBPerf.exe` and the system browser by design. Every call passes an argument list with `shell=False`, which `Tests/test_security_guardrails.py` enforces. `relog.exe` is resolved on PATH because it ships with Windows. |
| B606 `os.startfile` | `Lib/Core/input_utils.py` | Opens the run folder or a produced file in the user's default application. The path is one the Workbench wrote itself. |
| B110, B112 broad except in fallbacks | `Get/get_perfmon_charts.py`, `Inject/inject_perfmon_charts.py`, `Lib/Themes/chart_theme.py` | Best-effort paths (font registration, optional observation files, chart mapping) where failure means falling back to a default, never hiding a security error. |
| B105 "hardcoded password" | `Inject/inject_perfmon_charts.py` | The string is the status label `PASS` in a scoring table, not a credential. Annotated in place. |

A new Low finding outside this table is not accepted until it is added here
with a reason.

## Reporting A Problem

Attendees who find a security problem should report it to the presenter
directly rather than in a public channel.
