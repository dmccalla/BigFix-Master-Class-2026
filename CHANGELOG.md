# Changelog

All notable changes to the Master Class Diagnostics Workbench are recorded
here. The application, collection tasks, and sample data carry one version
number. Class guides are delivered separately.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and
the project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
Every released version is tagged in git as `vMAJOR.MINOR.PATCH`.

## [Unreleased]

## [2.0.0] - 2026-10-04

### Initial distribution

- Initial distribution of the Master Class Diagnostics Workbench for the
  classroom and practice lab.

### Included analysis modules

- Client Performance Analysis, Perfmon Infrastructure Analysis, and FillDB
  Performance Analysis, each producing Mini Report, Infographic, and Excel
  outputs under one run folder as applicable.
- Desktop app with three steps: Folders, Modules and Build. A data folder scan
  fills the module inputs, every input can be chosen by hand, and the run
  streams the engine log with per-module progress.
- Sample data set "BigFix Master Class 2026" so the Workbench runs without a
  deployment.
- Windows launcher that creates a private Python environment on first run.
- Master Class collection tasks and analyses, plus a fictional sample data set
  that lets attendees run the application before collecting deployment data.

### Release assurance

- A complete test suite, package manifest, SHA-256 checksum, CycloneDX SBOM,
  third-party notices, and continuous-integration checks.
