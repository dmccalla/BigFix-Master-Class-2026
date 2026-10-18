# Changelog

All notable changes to the Master Class Diagnostics Workbench are recorded
here. The application, the collection tasks, the sample data and the guide
ship together and carry one version number.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and
the project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
Every released version is tagged in git with a matching `v`-prefixed version. See
the project release process for the steps to cut a release.

## [Unreleased]

### Tests

- Add known-answer Client Performance delivery checks, cross-product result comparison, rendered-output validation, clean release ZIP checks, and explicit lab scenarios. Save build logs and rendered artifacts for diagnosis.

### Fixed

- Run lint and formatting once, separately from the Python 3.12, 3.13 and 3.14 tests, so style failures cannot prevent regression tests from running. Install CI tools from uv.lock, cancel superseded runs, and resolve the outstanding formatting failures.
- Make each generated disable action stay open for the logging duration plus one day. It used a fixed two days, so a duration over 24 hours could outlast the action and leave logging on. The FillDB Performance task now computes the offset from their own duration input. The default 24 hours still gives two days.

### Added

- Add Evaluation Frequency to the Client Performance report. It counts active properties by evaluation interval. Collect Deployment Information now writes an Active Properties by Evaluation Interval block to Property_Info, so run it again to add the section to an older capture.
- Report every Client Performance finding as CLT-01, with one reason per cause: the health score is below 90, active properties are set to every report or to under 15 minutes, or more than 5% of scored devices have no usable loop data. The finding takes the highest impact of its reasons. The Devices Reporting number on the Infographic is red only when missing data is a reason.
- Add an Interval column to the Top 10 Most Expensive Evaluations table and the Evaluation Offenders sheet.
- Name _BESClient_Report_MinimumAnalysisInterval under Evaluation Frequency when a device sets it, and list its values in the Min Analysis Interval sheet. A setting with no value means 60 seconds.

### Changed

- Require the Deployment_Information folder for Client Performance. The builder marks the module Needs A File without it, the Get script warns when it is missing, and the collection task, guide and documentation say so.
- Add the Evaluation Frequency block to the sample Property_Info captures, and say in the lab guide that the Client Performance module requires the Deployment Information results.
- Say in the user guide what the collection tasks change on a server, which tasks change client settings, and how the Collect tasks handle credentials. Rebuild the PDF.

### Removed

- Remove the Cost of Repeated Evaluations section and the Repeated Eval Cost sheet. Its runs per day were an estimate at the average loop time. The Top 10 Interval column shows the fact it rested on.

## [2.1] - 2026-10-15

### Added

- Add a dark mode switch for the desktop application and publish the final
  student user guide in Word and PDF.

### Fixed

- Resolve standalone Action Site Top 10 property IDs to friendly names, while
  retaining analysis lookups and raw IDs for unresolved rows.
- Reject reversed report and collection date ranges before a build starts.
- Match Client Performance capture properties by the exact product analysis
  title in any import site. Warn when that analysis is missing, inactive, or
  duplicated.
- Accept partial Client Performance collector results when some Top 10 lookups
  remain unresolved. Keep the standalone helper in sync with the embedded task
  and its fourteen-field loop capture.
- Align the Client Performance multicore fallback with the other collectors.
- Correct Client Loop score bands, the Report Minimum Interval collection
  header, and the Client Performance report opener.

### Documentation

- Explain how to unblock downloaded Windows launchers in the user guide,
  startup steps, and installation instructions.

## [2.0]

### Added

- Client Performance Analysis, Perfmon Infrastructure Analysis and
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

- Reorganize the Client Performance Mini Report. A key under the Infographic
  explains every tile, followed by Loop Health, Loop Cost, Notification and
  Polling, and Client Settings, in shorter, plainer prose. The tables are
  unchanged.
- Show the top 10 rows in the Client Performance relay and subnet tables, with
  a note when more exist. The workbook keeps every row, including the UDP
  relay and subnet sheets that were previously cut to 10.
- Name the relay with the most UDP issues on the Client Performance
  Infographic.
- Replace the lab sample data with a smaller 10-06-2026 client capture of
  2,537 devices so the lab exercises run faster.
- Label the four classroom client-setting examples as 2.0, matching the other
  collection content. These examples remain Master Class-only; action logic
  is unchanged.

### Fixed

- Explain the FillDB `Not Assessed` state when no captured object has a
  recognized health result, so the Mini Report makes clear that there was not
  enough data to calculate a health score.
- Enable Open Output after a completed build when the engine reports its
  human-readable run-folder summary, including an already-open Build Logs window.
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
