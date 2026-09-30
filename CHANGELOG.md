# Changelog

All notable changes to the Master Class Diagnostics Workbench are recorded
here. The application, the collection tasks, the sample data and the guide
ship together and carry one version number.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and
the project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
Every released version is tagged in git as `vMAJOR.MINOR.PATCH`. See
`Docs/Release_Process.md` for the steps to cut a release.

## [Unreleased]

### Added

- Client Performance Loop Analysis, Perfmon Infrastructure Analysis and
  FillDB Performance Analysis modules, each producing its Mini Report,
  Infographic and Excel outputs under one run folder.
- Desktop app with three steps: Folders, Modules and Build. A data folder scan
  fills the module inputs, every input can be chosen by hand, and the run
  streams the engine log with per-module progress.
- Sample data set "BigFix Master Class 2026" so the Workbench runs without a
  deployment.
- Windows launcher that creates a private Python environment on first run.
- Code sweep, packaging script, SBOM and checksum for releases.
- Getting Started and Data Collection guides.
- Continuous integration that lints and runs the suite on every push.

### Changed

### Fixed

- Keep FillDB Mini Report header and body rows aligned by centering both
  tables consistently. Preserve the existing table widths and shared style.
- Correct ten Deployment Information queries and 110 collection section-header
  queries. Add regression coverage confirming the repaired responses preserve
  Agent Performance context and loop workbook/Word output content.
- Include the `xlrd` runtime reader for legacy `.xls` loop inputs.
- Stage release packages in a short, unique temporary folder to avoid Windows
  path-length failures while preserving the archive layout and guarded cleanup.
- Correct collection-task descriptions: `xcopy` returns 0 for successful copies
  and 1 when no matching files are found. Action scripts are unchanged.
- Fail diagnostics runs when a generator fails or a required output is missing
  or empty, including both Perfmon captures and the Mini Report, while
  preserving the run log and avoiding false success messages.
- Retry an interrupted chart browser once. Check Windows chart and sidecar path
  lengths before rendering, and preserve counter matching when shortening
  Perfmon filenames. Unsupported paths request a shorter output folder or name.
