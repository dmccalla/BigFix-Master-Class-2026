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
