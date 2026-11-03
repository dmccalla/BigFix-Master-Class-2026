# FillDB score verification

## Normal shipped test data

Regenerated Main, TA and MC FillDB reports using each application's normal
`SampleData` FillDB analysis CSV. All three inputs have the same SHA-256 and
contain 1,496,466 parsed messages. Each report shows Healthy, 100 of 100,
with three of the four guide checks assessed. Parallel DB Update has zero
captured messages and remains excluded from the score.

The delivered CSV values, Word table cells, chart payload and embedded chart
were checked. Corresponding chart images match across all three applications.
Microsoft Word exported each report to three pages. All nine pages were
visually reviewed, including the numeric score, coverage explanation and tables.
No scoring formula or customer-facing prose changed.

Current report evidence is in `Temp/FillDB_Normal_Data_20261102`, including
the three reports, `verification.json`, `word-exports.json` and
`pdf-verification.json`. Use these normal-data reports for scored output
verification. The short live captures below verify the insufficient-data path.

## Live capture coverage

The live lab reports correctly show Not Assessed. Their analyzer output has no
recognized health result for any of the four scored guide checks. The dates
match 2 November 2026. No date filter removed otherwise scoreable FillDB data.

| Live capture | Analyzer lines | Capture duration | Short-batch count | Assessed guide checks |
|---|---:|---|---:|---:|
| Main | 1,273 | 26 minutes 15 seconds | 42 | 0 of 4 |
| TA | 456 | 10 minutes 41 seconds | 15 | 0 of 4 |

Both captures have zero long-batch messages. The analyzer labels all four guide
checks Not enough data. A successful report build verifies processing, but does
not establish a FillDB health score or sufficient customer assessment coverage.
The previously built shared sample does exercise a numeric score: 100, with
three guide checks assessed and the fourth explicitly excluded for missing data.

## Additional verification

- Added ten permanent regression cases in each repository. They cover scores
  of 100, 75, 50 and 0, partial assessment, no assessed guide checks and unrelated
  object ratings. Three cases invoke the real bundled Windows analyzer on
  synthetic raw logs with sparse, healthy and poor processing.
- The focused checks passed: Main 37, TA 36 and MC 36. The Main selection also
  includes full-report injection checks. These are focused results, not a new
  full-suite count.
- Generated five real charts and Word reports per application. The known
  results were Healthy 100, Critical 0, Needs Attention 75, partial Healthy 100
  and Not Assessed. Source CSV values matched Word tables. Each document embedded
  the verified chart. Corresponding chart images were identical in all three
  applications.
- Microsoft Word exported the five Main control reports to 15 PDF pages.
  The displayed scores, coverage explanations, tables and pagination were
  inspected. The control inputs are synthetic test evidence, not lab measurements.
- The live-output check now verifies the score, assessed-check count, capture
  dates, table values and delivered chart against the analyzer CSV. It also
  rejects an empty selected PerfMon file.

## Interrupted MC capture

The laptop crash also restarted BFROOT1. The original MC PerfMon collector was
stopped and its BLG was empty. The failed stop action and collector-state output
are retained. A separate restart of the existing collector began a fresh capture.
Its completion, tool output and Word review are recorded in the release
validation record. An empty or interrupted capture does not count as a passed
live report test.

## Separate analyzer limit

An extremely small synthetic raw log exposed a statistics error in the bundled
analyzer. Six-line inputs failed with division by zero, including one with
separated timestamps. Adding normal mapping lines allowed the same operations
to be analyzed. This does not explain the live Not Assessed reports, which
were analyzed successfully. The application reports the analyzer failure.
The reproducer is retained in `filldb-score-review/analyzer-edge`. No analyzer
binary or application behavior was changed for this separate issue.

Local evidence is in the main application's
`Temp/Release_Validation_20261102`: the three
`filldb-score-regression.xml` results, `filldb-score-review` controls and Word
exports, and each product's `filldb-live-checks.json`. MC's recovery receipts
are in `mc/lab`. No score formula or customer-facing report prose changed.
