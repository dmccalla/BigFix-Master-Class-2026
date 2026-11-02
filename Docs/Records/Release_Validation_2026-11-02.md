# Master Class Workbench release validation, 2 November 2026

This record covers the reviewed source files and the recorded follow-up checks.
It is test evidence, not approval to publish a release.

## Results

| Check | Result |
|---|---|
| Full automated suite | 1,115 passed, 6 skipped, 0 failed |
| Lab definitions | Match the current disk definitions. See the saved content comparison. |
| Tool run on fresh lab evidence | Completed from the recovered, nonempty fresh lab capture. |
| Microsoft Word review | Passed. Microsoft Word PDFs reviewed: mc-live-loop-word (11 pages), mc-live-filldb-word (3 pages), mc-live-perfmon-word (10 pages). |
| Packaged build | Clean-runtime installation and report-generation checks passed. The final source refresh is recorded in the package receipt. |
| Dependency audit | No known Python dependency vulnerabilities reported. Lockfile and exported requirements agree. |
| Runtime SBOM | CycloneDX inventory generated from the package runtime. Development and runtime inventories are kept separately. |

## Live lab collection

BFROOT1 was used for this run. Logging auto-disable delays were at most one
hour. Shortened performance captures test collection and processing, not a
customer assessment's required observation period.

| Stage | Action | Result |
|---|---|---|
| archive-8317784 | 2113 | Completed |
| client | 2097 | Completed |
| deployment | 2096 | Failed (known lab issue: DI-107, DI-108, DI-109) |
| disable | 2111 | Completed |
| filldb | 2099 | Completed |
| perfmon-restart | 2106 | Completed |
| perfmon-state-after-start | 2108 | Completed |
| perfmon-state | 2104 | Completed |
| perfmon | 2098 | Completed |
| stopperf-8317784-reboot | 2110 | Completed |
| stopperf-8317784 | 2102 | Failed |

Deployment collection attempts all 180 queries. The known BigFix 11.0.7
administered-computers inspector failure remains visible. It is not treated
as successful collection of the affected operator fields. Other collection
stages and the tool run are evaluated separately.

## FillDB score verification

The normal shipped sample was also run through all three FillDB generators.
Each report shows Healthy, 100 of 100, with three of four guide checks assessed.
The zero-message Parallel DB Update check is excluded. Source values, embedded
charts and all nine native Word pages were verified. See
[FillDB score verification](FillDB_Score_Verification_2026-11-02.md).

## Limits and follow-up

- Generated reports still need consultant review and manual assessment input.
- Existing type-check and static-scanner advisories remain visible in the
  quality records. A passing test suite is not a clean security audit.
- The retained large PerfMon capture is available under the neutral filename
  `Perfmon_24_Hour.blg`. It contains 1,252 readings over 20:51:07 and is
  packaged as the separate large-sample download. The earlier validation
  command explicitly skipped this download; the source was not missing.
- Package validation used a short output path to avoid Windows path-length
  limits. Source changes were subsequently committed and pushed. No release was published.

## Evidence

The local evidence folder is `Report Builder/Temp/Release_Validation_20261102`
in the main repository. Use its `mc` folder for the full suite log and
JUnit results, lab task receipts, downloaded capture, tool run log, dependency
checks, runtime SBOM, source fingerprints and package result. The top-level
README links the current results across all three repositories.

Recorded 2026-11-02 15:44 Eastern Standard Time.

Follow-up: reviewed source commit `1b1f2aff` was pushed to the existing `origin/main`.
