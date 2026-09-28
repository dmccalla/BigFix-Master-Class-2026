# Master Class Design Fact Sheet

## Working Title

**Automated Performance and Configuration Analysis**

Master Class 2026 Denver

## Purpose

This is a practical, instructor-led BigFix Master Class experience. Attendees
collect operational data from a BigFix deployment, run the matching Workbench
module, and use the resulting Mini Report to understand the condition of the
environment.

The presentation and lab guide should make the workflow feel concrete:

```text
BigFix deployment -> collection task -> captured data -> Workbench module -> Mini Report
```

## Class Shape

| Item | Direction |
|---|---|
| Session length | 90 minutes |
| Audience | BigFix practitioners attending the Master Class |
| Experience | Guided demonstration followed by individual lab modules |
| Core lab path | Agent Performance and Perfmon Infrastructure |
| Optional lab | FillDB Performance, if time remains |
| Primary artifact | Mini Report |
| Lab site | `Performance and Config Analysis` |

The three modules are run individually. The class does not require all three
modules to be completed in one session.

## Module Inventory

| Module | What attendees collect | What the Workbench produces | Priority |
|---|---|---|---|
| Client Performance Loop Analysis | Agent Performance Counters analysis export. Optional Top 10 evaluation, UDP notification, and deployment captures add context. | Mini Report, Infographic, and supporting Excel workbook. | Core |
| Perfmon Infrastructure Analysis | A Windows PerfMon `.blg` capture from a BigFix server. | Mini Report, Infographic, and supporting Excel workbook. | Core |
| FillDB Performance Analysis | FillDB performance logs or the analyzer CSV. | Mini Report and Infographic. | Time permitting |

The Mini Report is the primary teaching artifact. There is no scoring workbook
for the Master Class.

## Live Lab Workflow

The lab begins in the BigFix console. Collection tasks are run first, then the
resulting files are retrieved and supplied to the matching Workbench module.

The current content is published to the custom site **Performance and Config
Analysis**:

1. Activate `BigFix Master Class -- Agent Performance Counters - Basic (2.0)`.
2. Run `BigFix Master Class -- Collect Agent Performance Counter Analysis Data (2.0)`.
3. Run `BigFix Master Class -- Setup and Run Perfmon Counters (2.0)` for the
   server in scope and retrieve the `.blg` file directly from that machine.
4. If time permits, run `BigFix Master Class -- Enable FillDB Performance
   Logging (2.0)`, collect the logs, disable logging, and retrieve the complete
   log set.
5. Run the selected Workbench module and open its Mini Report.

When a live collection window is longer than the class session, the instructor
may demonstrate the collection task and use a sanitized field capture or the
provided sample data for the analysis portion.

## Message To Convey

The Workbench turns familiar BigFix operational data into a repeatable analysis
workflow. The value is the connection between collection and interpretation:

- Agent evaluation data shows where client processing time is going.
- PerfMon data puts server resource behavior in infrastructure context.
- FillDB performance data shows how quickly client reports are processed.
- The Mini Report gives the attendee a compact, reviewable result rather than
  leaving the collected data as a pile of raw files.

## Presentation Content Needed

The deck should support these beats without becoming a product tour:

1. The operational question: where is the BigFix environment spending time or
   capacity?
2. The collection-to-analysis workflow.
3. The three modules and when each is useful.
4. A short walkthrough of the Agent Performance lab.
5. A short walkthrough of the Perfmon lab.
6. The optional FillDB path.
7. A Mini Report example and how to read it.
8. The transition from live collection to attendee lab work.

Use the supplied Master Class presentation template. The supplied lab-guide
template remains the source for the exercise layout.

## Visual Direction

- Practical and technical, with the BigFix console, collected files, and Mini
  Report as the visual anchors.
- Show the transformation from raw operational evidence to an interpretable
  result.
- Favor real screenshots and report excerpts from the sanitized or sample
  data over decorative illustrations.
- Keep the experience focused on repeated operational use, not a marketing
  funnel or a feature catalog.
- Treat the three modules as distinct work surfaces so attendees can understand
  what each one collects and produces.

## Fixed Constraints

- The class covers only the three Workbench modules listed above.
- Modules are run individually; the first two are the planned core exercises.
- The FillDB exercise is optional when time permits.
- The primary report is the Mini Report. Do not introduce full-report mode.
- Do not introduce a scoring workbook for the class.
- Microsoft Word and Excel are the preferred and tested applications for the
  Mini Reports and supporting workbooks. LibreOffice or other compatible tools
  may work, but they have not been fully vetted.
- PerfMon logs can be large and are retrieved directly from the target machine;
  they are not treated as normal upload content.
- The lab site name is exactly `Performance and Config Analysis`.

## Still To Supply

- Final speaker and session metadata.
- Sanitized field capture, when available.
- Final decision on whether FillDB is run live or shown as an optional demo.
- Final screenshots from the approved sample or sanitized data.
