# Changelog

All notable changes to the Master Class Diagnostics Workbench are recorded
here. The application, the collection tasks, the sample data and the guide
ship together and carry one version number.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and
the project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
Every released version is tagged in git with a matching `v`-prefixed version. See
the project release process for the steps to cut a release.

## [Unreleased]

- Apply the approved 2026-10-26 security cooldown exception for certifi; update filelock and Pillow under the standard cutoff. See Docs/Reference/Dependency_Cooldown_Exception_2026-10-26.md.

- Complete the Design D-item report pass: clear cover metadata, nest investigation methods, use portable callout symbols, improve identifier wrapping and tighten sparse-page spacing. Preserve scoring and PerfMon plots.

- Keep short evidence groups together in report pagination, left-align the Client query and remove the empty trailing findings row. Preserve report words, charts and scores.

- Display long Client loop durations as hours and minutes, retaining remaining whole seconds. Replace decimal-hour rounding with the approved duration format.

- Accept both captured master-operator analyses labels. Group relay names without case differences and round displayed hours consistently. Keep local validation instructions specific to this application.

- Reconcile delivery documentation with manual workflows, update the current Deployment Information contract, and distinguish shared guide rules from product scope and informational storage checks.

- Enlarged report chart legend dots for readability at their Word placement size.

- Reserve a consistent gap below chapter dividers before following notes and tables.

- Keep Client Performance peer sections at Heading 3 and their child headings at Heading 4 in full and mini reports. Remove conflicting heading promotion and injection remapping.

- Add shared capacity host and role styles for consistent report formatting.

- Apply compact table headers and consistent row alignment to pre-aligned percentage tables.

### Changed
- Keep full and mini Client guidance aligned, keep the infographic key Heading 3,
  strengthen subsection headings, color evaluation statuses, compact table headers,
  and remove references to consultant workbooks and raw output files from reports.


- State exact PerfMon exceedance counts instead of estimating how much of the capture was over the limit. Preserve thresholds, measurements, all plots and scoring rules.

- Keep long PerfMon chart footers clear of legends and axis labels. Preserve raw values, scoring, plotted series and display caps.

- Keep Reading the Infographic at the same heading level as How the Score Is Calculated: H3 in both full and mini reports.

- Center the Document Control Version column and its header, overriding automatic numeric alignment.

- Reconcile synthetic sample dates into one June assessment period, preserve changed originals, and verify input fingerprints. Preserve performance timings and scoring rules.

- Separate report sections with heading spacing instead of repeated divider lines. Preserve chapter rules, heading levels, fonts, lists and report content.

- Clarify evaluation interval populations, FillDB guide coverage and PerfMon context using approved wording. Correct report references and count grammar. Omit the derived FillDB check name. Preserve scoring and all PerfMon plots.

- Prevent missing-memory PerfMon tile collisions and keep observation text with the following chart. Correct document stamp encoding and date formatting. Preserve historical cross-product evidence outside the standalone distribution.

- Preserve unset CPU Idle devices in Client Performance charts and cover configured, mixed and entirely unset populations. Refresh sample validation fingerprints. Scoring rules are unchanged.

- Apply one heading typeface through all levels, keep subsection headings compact without divider lines, and align PerfMon area headings across full and mini reports.

- Remove imported character-style overrides from headings so the shared heading font and weight render consistently in Word.

- Normalize report section spacing through the shared heading styles, remove redundant empty heading spacers, and give chapter separator paragraphs explicit spacing. Preserve cover, table, and page-break layout.

- Standardize report score, distribution, and data bars with the same thickness and rounded ends.

- Restore report page numbers, keep every PerfMon counter plot, remove redundant chart footnotes, and correct heading hierarchy and About-page pagination. Scoring and plotted values are unchanged.

- Correct report portability and integration after independent review. Use shipped chart fonts when local fonts are absent, preserve template-owned Client guidance, restore approved frequency explanations and standalone font/spacing rules, and report an unchecked VM flag as not supplied. Scoring is unchanged.

- Capture retrieved properties in Collect Deployment Information and use them in Client Performance. The Top 10 names a retrieved or reserved property and shows its interval. Evaluation Frequency and CLT-01 count default and custom retrieved properties and leave reserved properties out.

- Clarify Client Performance loop averages, UDP coverage populations, property classifications and tiny nonzero percentages. Preserve scoring and finding rules.

- Apply Design's 10-20 change list and review fixes. Loop Health takes in Reporting Issues, Evaluation Frequency comes before Contributing Factors, and PerfMon opens with Capture Summary and closes with Assessment by Area.

- Lay out every report table by one rule. Cell and table properties are written in schema order, each header takes its column's alignment, number columns are right aligned, and widths come from Design's fixed sets, the template's proportions or the measured method.

- Read relevant counts as "N relevant of M total" and name the Content_Info capture time beside the Fixlets and Analyses counts. PerfMon findings say advisory instead of warning.

- Remove the FillDB Objects Not Healthy block, the sentence that named the Poor object and the list behind them. The rating counts stay. Show the FillDB Report Generated date as MM-DD-YYYY.

- Name Client Performance Counters in the Enable Client CPU Multicore Scaling task description. The task change is untested and has not been imported.

- Record which code and template built each report. The run log names the commit and the full template path, and each report's Comments property names the commit and the template file.

- Extend the synthetic delivery dataset to the full current client schema, including polling, UDP, FastHashVerify, CPU idle, multicore and core counts, while retaining property interval, retrieved-property and missing-value cases.

- Verify the default demonstration data with current Client Performance, PerfMon and FillDB report builds. Record capture provenance, current-field coverage and input hashes without changing original capture dates.

- Build a separate versioned large-Perfmon sample ZIP and SHA-256 with each release package. Keep the small default sample separate, validate external BLG inputs before staging, and record hashes and extraction paths in the companion manifest.

### Sample data

- Track the Client Loop and Deployment Information demonstration inputs directly under the default sample folder. Include minimum analysis and property evaluation intervals, a Retrieved Property Top 10 example, consistent timing totals, and local test instructions.

### Documentation

- Add Docs/Reference/Guide_Versions.md. It records the NFR guide (11.x.4) edition the thresholds are built against, the value each check takes from them, and the house values neither guide states.

### Deployment collection

- Add an always-written deployment diagnostics summary with runtime totals, slowest query IDs, failure examples, selected settings and version fingerprints.
- Reuse deployment counts and root details in diagnostic context and collect a local hardware allowlist without adding BigFix API queries. Keep missing context distinct from zero and preserve XML/log consumers.

- Use the standard form-encoded Session Relevance route for lab preflight checks. Explorer-only JSON requests could return HTTP 503 while the collector's normal route was healthy. Keep normal engine selection and test the request contract.

- Record per-request timings and failure categories in CSV/JSON diagnostics, stop on rejected authentication or three consecutive availability failures, and report distinct BigFix action exit codes. Preserve partial XML evidence, distinguish permission and relevance errors from outages, and document the policy in the collection design and task descriptions.

- Default the standalone Collect Deployment Information pause to 5 seconds. Explain capacity differences, the 1-second override, and console reauthentication after an expected root service restart.
- Generate 113 headings and blank lines locally as BESAPI XML fragments. Preserve the 177 real API queries, capture order, and optional human readable log conversion.
- Capture Actionsite Size and the 12 root-server client relevance results in XML even with logs off. Stop creating the partial Root_Server_Info log when log output is disabled.
- Add offline capture and pacing contracts plus controlled log-on and log-off lab scenarios. Live lab validation is required before updating the combined task.


### Tests

- Extend the known-answer delivery evidence with the cases the 10-19 lab run exposed: a site evaluation and a Retrieved Property in the Top 10, a headerless UDP .xml in the collector's format, and _BESClient_Report_MinimumAnalysisInterval set with and without a value.
- Add known-answer Client Performance delivery checks, cross-product result comparison, rendered-output validation, clean release ZIP checks, and explicit lab scenarios. Save build logs and rendered artifacts for diagnosis.

### Fixed

- Correct the Mini Report wording Design's 10-19 review found inaccurate (CP-01, CP-03, CP-05 to CP-09, CP-12, PM-01 to PM-04, PM-06, FD-02). Minimum Analysis Interval states each value without comparing it to the deployment average. The Top 10 relay and subnet notes name their Excel sheet and count the devices with no relay or address. Excel Health Summary shows Devices Scored and Devices Reporting. PerfMon calls a failure sustained only when most readings were over the limit and says Memory Health earns 25 points as Cannot Verify. FillDB counts lines processed.
- Read the active analyses count in Contributing Factors. The Deployment Information capture writes "Number of Activated Analyses", which the report did not match, so it always showed 0 active and never checked the 500 limit.
- Count only named relays and subnets in the Top 10 notes. Devices with no relay or no usable address were counted as one more relay or subnet.
- Leave the collection span out of the Client Performance Infographic header when no report dates were given. It read "Not provided collection".
- Label a Retrieved Property in the Top 10 Interval column as Not collected. It said Not a property, but retrieved properties have intervals that the Property_Info capture does not list. Site evaluations still read Not a property.
- Read a UDP notifications .xml capture chosen as the input. It has no header row, so the report said Not collected. It is now split the way the collector splits it and gives the same counts as the collector's CSV.
- Run lint and formatting once, separately from the Python 3.12, 3.13 and 3.14 tests, so style failures cannot prevent regression tests from running. Install CI tools from uv.lock, cancel superseded runs, and resolve the outstanding formatting failures.
- Make each generated disable action stay open for the logging duration plus one day. It used a fixed two days, so a duration over 24 hours could outlast the action and leave logging on. The FillDB Performance task now computes the offset from their own duration input. The default 24 hours still gives two days.

### Added

- Add Evaluation Frequency to the Client Performance report. It counts active properties by evaluation interval. Collect Deployment Information now writes an Active Properties by Evaluation Interval block to Property_Info, so run it again to add the section to an older capture.
- Report every Client Performance finding as CLT-01, with one reason per cause: the health score is below 90, active properties are set to every report or to under 15 minutes, or more than 5% of scored devices have no usable loop data. The finding takes the highest impact of its reasons. The Devices Reporting number on the Infographic is red only when missing data is a reason.
- Add an Interval column to the Top 10 Most Expensive Evaluations table and the Evaluation Offenders sheet.
- Name _BESClient_Report_MinimumAnalysisInterval under Evaluation Frequency when a device sets it, and list its values in the Min Analysis Interval sheet. A setting with no value means 60 seconds.

### Changed
- Updated Client Performance, PerfMon and FillDB mini-report charts, headings, source explanations and page flow. Added regression checks while retaining the existing scores, thresholds and PerfMon plot data.

- Set Heading 3, 4 and 5 to 16, 14 and 12 pt, with the spacing in Design's 10-20 change list, Section 1. No border, font or Normal change.
- Spell PerfMon in the text readers see: report titles, app labels and messages, console and log lines, and help text. File and folder names, identifiers, globs and config keys keep Perfmon.
- Rate ActionSite size against a 10 MB soft warning (Needs Attention) and a 25 MB hard ceiling (Critical), by Duncan's 10-19 ruling. It used a "Review" word no other Contributing Factors row uses.
- Apply only the NFR guide's limits in PerfMon, by Duncan's 10-19 ruling. The warning levels the guide does not state (CPU 70%, privileged time 8%, CPU queue 3, page file 4%) are removed. A virtual machine under the guide's 50% CPU floor still reads Advisory.
- Score FillDB on the four checks named in NFR PRF-BIG-30 (version 11.x.4, page 25), by Duncan's 10-19 ruling. Good or Great meets the standard and earns 100. Poor earns 0. Other objects stay in the table and chart, colored by the analyzer's rating, and are not scored. Good shows as Healthy. How This Score Is Calculated cites the guide. The Infographic header reads "N objects Â· M assessed" (FD-01), and an Objects Not Healthy block names any object rated Poor (FD-03).
- Score client loops in four groups, by Duncan's 10-19 ruling on Design's review. Healthy is under 15 minutes (100 points), Good is 15 to 30 (85), Warning is 30 to 60 (67) and Critical is over 60 or no usable data (34). The Infographic draws no usable data as a hatched part of Critical, and the Loop Health table gives it its own row. Excel adds Good rows and a Good Threshold. `--good-threshold` joins `--healthy-threshold`, whose default is now 00:15:00.
- Use one set of score cut-offs in all three Mini Reports: 90 to 100 Healthy, 70 to 89 Needs Attention or Warning, 0 to 69 Critical. PerfMon and FillDB move from 85 and 60.
- Require the Deployment_Information folder for Client Performance. The builder marks the module Needs A File without it, the Get script warns when it is missing, and the collection task, guide and documentation say so.
- Add the Evaluation Frequency block to the sample Property_Info captures, and say in the lab guide that the Client Performance module requires the Deployment Information results.
- Add the _BESClient_Report_MinimumAnalysisInterval rows from the 10-18 lab capture to the sample Client_Settings_Info, so the sample report shows the Minimum Analysis Interval paragraph.
- Bring the sample Client_Loop captures to the current collector format: every CSV field quoted and UDP answers separated by ", ". Top 10 row 10 in the sample is now a Retrieved Property, a row kind the lab Top 10 has. The sample is synthetic, so the row keeps the numbers of the site evaluation it replaces.
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
