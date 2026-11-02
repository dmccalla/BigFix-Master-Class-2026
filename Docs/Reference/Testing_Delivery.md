# Delivery validation

Delivery checks run locally or when a maintainer explicitly starts the manual
workflow. Pushes and pull requests do not start the checked-in workflows.
The known-answer Client Performance fixture includes
the 15-, 30- and 60-minute group boundaries, missing/error results, evaluation
intervals, and the Top 10 Interval column. The real report job checks the Word tables,
Excel rows and chart values together, and saves build logs, chart HTML and PNGs.

The same fixture and expected answers are checked in all three products.
The primary repository also has a manual **Cross-product delivery comparison**
workflow. Configure `CROSS_REPO_READ_TOKEN` there with read access to the three
repositories; the default workflow token cannot read sibling private repositories.
Each manually started CI job independently checks the same known answers.
The root workflows are **CI**, **Delivery and release validation**, and
**Controlled BigFix lab**. Platform also provides **Cross-product delivery comparison**.

Run `.github/compare_delivery.py` with the three `delivery-summary.json` paths
and `--output comparison.json` to compare the actual product results. From an
application subdirectory, the helper path starts with `../.github`.

## Local report checks

Run from this application's repository root. Use the frozen development
environment. Set
`WORKBENCH_RUN_DELIVERY=1` and `WORKBENCH_DELIVERY_OUTPUT` to a short writable
folder, then run `uv run --frozen python -m pytest -q Tests/test_client_delivery.py`.
Without the setting, the fast known-answer checks still run; browser builds
are explicitly skipped. Production Get, workbook, Word and chart code is used.

## FillDB score checks

`Tests/test_filldb_guide_checks.py` checks known scores for Healthy, Needs
Attention, Critical, partially assessed and unassessed inputs. Unrated guide
checks stay out of the denominator. Unrelated object ratings cannot change the
score. On Windows, the bundled analyzer also processes synthetic raw logs with
sparse activity, healthy throughput and poor throughput.

A short live lab run verifies capture and processing. If the analyzer returns
Not enough data on every guide check, the expected score is Not Assessed.
Such a run does not exercise a numeric score or establish customer assessment
coverage. Verify the source dates, assessed-check count, chart score and delivered
Word tables together. Retain scored controls separately from live lab evidence.

## Before a release

Manually run **Delivery and release validation** in GitHub Actions. It builds
the real ZIP, verifies its checksum, commit and complete file manifest, installs
only its runtime requirements in a new environment, constructs its hidden UI,
and generates a report using the extracted application. The following Linux
job currently renders the report with LibreOffice/PDFium. Its page images and
layout findings do not count as document verification.

For the required visual check, open the report in Microsoft Word, update its
table of contents, export to PDF from Word, and inspect the affected pages at
delivery size. Retain that PDF and the review result. If Word export fails,
the check is incomplete. Do not substitute LibreOffice pagination.

No workflow publishes a release. Packaging and PDF dependencies are in the
`validation` dependency group and uv.lock; they are not runtime dependencies.

## Controlled lab

**Controlled BigFix lab** is manual. Plan runs on GitHub's Windows runner.
Check and run require a Windows runner labeled `bigfix-lab` that can reach the
lab server. Configure `BIGFIX_LAB_TOKEN`, or the
`BIGFIX_LAB_USERNAME` and `BIGFIX_LAB_PASSWORD` secrets. The server URL, test site
and single allowed target ID are configurable. The current default server is
`https://BFROOT1.dmc.lab:52311`; the default target is the previously used root
server computer ID 8317784. Check its identity before execution.

The plan command validates task XML without network access. Check verifies
target identity and prerequisites. Run additionally requires the execute
checkbox and exact hostname confirmation. It uses the existing FillDB
Performance manual and generated-disable scenarios, including restoration
assertions. These actions restart FillDB and must run in the controlled lab.
Lab content and actions are retained for diagnosis by default.

Repository-site SSH access delivers content. Lab REST credentials run and verify
tests; these are separate connections. A repository site does not replace this
test runner. No lab actions run during ordinary CI or on pull requests.
