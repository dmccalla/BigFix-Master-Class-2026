# Working In This Repo

Conventions for anyone contributing here, human or AI agent. Claude Code reads
this through `CLAUDE.md`, Codex reads it directly. Keep it as the single source
of truth. Do not copy these rules into a second file.

## What This Is

The Master Class Diagnostics Workbench: the training copy of the diagnostics
tool, used in the BigFix Master Class lab. It takes Client Performance, PerfMon
and FillDB evidence from a BigFix deployment and builds a mini report for each
one.

It is one of three sibling repos: the main Workbench, a Technical Advisor copy
and this training copy. Shared module content stays consistent across all
three. Naming and branding differ.

**A fix made here stays here.** Port a change to or from another repo only
when asked. Do not add modules or features on your own.

## Layout

```
Master Class Diagnostics Workbench/   repo root
  CHANGELOG.md                release notes
  pyproject.toml              the version lives here
  App/                        UI and the diagnostics runner
  Get/                        per-module analysis scripts
  Inject/                     per-module Word injection scripts
  Lib/                        shared helpers, analysis, design, themes
  Templates/                  Word report templates
  Tasks and Analyses/         BigFix collection tasks (.bes)
  Utilities/                  scripts embedded in or used by the tasks
  Build/                      packaging, code sweep, release rules
  Docs/                       all documentation, see Docs/README.md
  Tests/                      pytest suite
  SampleData/                 sample evidence for testing
  Launchers/                  Run Diagnostics Workbench.cmd
```

## Running Things

All commands run from the repo root.

```
uv run pytest                          run the suite
uv run pytest Tests/test_version.py    run one file
Launchers/Run Diagnostics Workbench.cmd  start the app (Windows)
Build/run-code-sweep.ps1               code sweep
Build/refresh-lockfile.ps1             refresh uv.lock, respects the cooldown
Build/package_release.ps1              build the release ZIP
```

## Hard Rules

These have tests behind them. Breaking one fails the suite.

**No em-dashes.** Banned project-wide, in code, docs, and report output. Rewrite
with a colon, comma, or parentheses. Never substitute a hyphen.
`Tests/test_no_emdash.py`.

**The version comes from `pyproject.toml`.** Never hardcode a version.
`Tests/test_version.py`.

**Docs holds only `README.md` and folders.** Every other file lives in the
folder that matches its kind, and relative Markdown links must resolve.
`Tests/test_docs_layout.py`.

**The release ZIP follows `Build/RELEASE_RULES.md`.** No `.md` files in the
ZIP and PDF-only docs. `Tests/test_package_release.py`.

## Report Rules

The mini reports are what a customer reads. These are approval-gated.

**Never change report prose without approval.** Quote the current wording and
the proposed wording, get sign-off, then edit.

**Mini reports share approved module content with the main Workbench.** Keep
guidance and task references consistent across all three repos.

**PerfMon charts are exempt from the chart standard.** Do not restyle them.

**Use Microsoft Word for document rendering and pagination checks.** Export to
PDF with Microsoft Word, then inspect the PDF. LibreOffice output does not
count as verification.

**Colors.** Text is midnight navy `#000032`. The light greys `#5b677a` and
`#3b4657` are banned.

## Code Conventions

**The tool is UI-driven.** Nobody runs it with CLI switches. Put behavior in the
core flow, not behind a flag.

**Say Client, not Agent,** for the BigFix client in anything a person reads.

**`relog.exe` calls need `-y`, `capture_output=True`, and
`stdin=subprocess.DEVNULL`.** Without them the subprocess hangs waiting on
stdin.

**Prose is plain and short.** In code comments, UI strings, docs, and report
text. US English. Avoid using a semicolon or colon where a period belongs.

## Lab Sync

**GitHub is the source of truth for lab content.** Commit and push every
`.bes` change. The rebuilt lab will gather the published branch for this repo
through the `Performance and Config Analysis` [External Repository Site](https://help.hcl-software.com/bigfix/11.0/platform/Platform/Config/c_repository_site.html).
Use the Repository Site gather for routine content publication once configured.

Verify the gathered site version and changed content in the BigFix Console.
In your report list every `.bes` file you changed and say whether the lab
copy is current. Leave lab verification open while the server or Repository
Site is unavailable.

## Working Alongside Other Agents

You may be sharing this checkout. Other agents' changes can appear in
`git status` mid-task.

- **Scope every change to what was asked.** Flag adjacent problems in writing
  and wait. No opportunistic side fixes.
- **Never commit another agent's work.** Stage your own files by name. Do not
  use `git add -A` or `git commit -a`.
- **Check before assuming a failure is yours.** Diff the file against `HEAD`.
- **Analysis and review requests are read-only** until someone explicitly
  assigns the implementation.

## Releases

`CHANGELOG.md`, `project.version` in `pyproject.toml` and the git tag have to
agree. Record changes in `CHANGELOG.md` as they land, not at release time.
Follow `Build/RELEASE_RULES.md` before cutting a release.

## Documentation

`Docs/README.md` is the index. Keep new documentation short and link to code
rather than restating it. Documentation that describes a shipped artifact
defers to the artifact: if the doc and the rendered file disagree, the file is
right and the doc is stale.
