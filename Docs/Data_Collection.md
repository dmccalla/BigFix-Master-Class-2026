# Data Collection

What each module reads, where the files come from in a BigFix deployment,
and how to lay them out so the Workbench finds them on its own.

## Folder Layout

Put everything for one deployment under one folder and point the Data
Folder at it. The Workbench looks in these subfolders:

```
<Data Folder>\
    Client_Loop\              Client Performance Counters export, Top 10 and UDP captures
    Deployment_Information\   The *_Info_*.log captures from the root server
    Perfmon\                  One or two PerfMon .blg captures
    FillDB_Performance\       FillDB performance .log files, or the analyzer CSV
```

The sample capture under `SampleData\BigFix Master Class 2026` follows this
layout and is a good reference for the file names. A file that lives
somewhere else, or under another name, can always be chosen by hand with
**Change** on step 2.

## Client Performance Loop Analysis

Reviews how long clients take to evaluate their content, and why.

| Input | Required | Looks for | Source |
|---|---|---|---|
| Client Performance Counters export | Yes | `Client_Loop_*.xml`, `Client_Loop_*.csv`, `*Basic*` | The analysis export from the BigFix console, or the XML written by `Utilities\query_properties.ps1`. Use the **Basic** export. The Advanced export carries extra columns and is not supported. |
| Report Start Date and End Date | Yes | Entered on step 2 | The period the collection covers. |
| Top 10 slowest evaluations | No | `*top10-query-results*.csv`, `*top10*.csv`, `*top10*.txt`, `*top10*.xml`, and evaluation-time exports | The session relevance query in `Utilities\query_properties.ps1`, or its console export. Adds the Top 10 Most Expensive Evaluations table. |
| UDP notifications | No | `*udp-notification*.csv`, `*udp_notification*.csv`, the `.xml` forms, `*udp-ping*.csv`, `*receiving*udp*.csv` | The same script. Adds UDP coverage by relay and by subnet, and the Command Polling Review. |
| `Deployment_Information` folder | No | A folder named `Deployment_Information` | The root server information captures (`General_Info`, `Client_Settings_Info`, `Relay_Server_Info` and the rest). Adds the Contributing Factors section. |

## Perfmon Infrastructure Analysis

Scores Windows performance counters from a BigFix server against the
platform's requirements.

| Input | Required | Looks for | Source |
|---|---|---|---|
| Capture 1 `.blg` file | Yes | `*.blg` under `Perfmon` | A PerfMon data collector set on the root server or a relay, saved as a binary log. |
| Logical processors and physical disks | Detected | Read from the capture | Override only when the detected value is wrong. |
| Physical memory (GB) | Yes | Entered on step 2 | The server's RAM. A capture does not record it. |
| Virtual machine | Yes | Entered on step 2 | Whether the server is a VM. |
| Capture 2 | No | A second `.blg` | A second server, or the same server after a change. Reported side by side. |
| Collection start and end | No | Entered on step 2 | Defaults to the capture's own span. |

Parsing a large capture can take several minutes. The Workbench converts the
binary log with `relog.exe`, which ships with Windows.

## FillDB Performance Analysis

Reviews how quickly FillDB processes client reports into the database.

| Input | Required | Looks for | Source |
|---|---|---|---|
| FillDB performance log or CSV | Yes | `*FillDB*` under `FillDB_Performance`, or `Logs\FillDB_Performance` | The root server's FillDB performance logs, written when performance logging is enabled on the BES Root Server. Point the module at one log and it combines the rollover files beside it in order. An already analyzed CSV is accepted as well. |
| Collection start and end | No | Entered on step 2 | Defaults to the log's own span. |

Raw logs are analyzed with `Utilities\MXFillDBPerf.exe`, which the module
runs for you.

## Collecting From A Deployment

The captures above come from three places:

1. **The BigFix console.** Export the Client Performance Counters analysis
   (Basic) to XML or CSV.
2. **The root server.** Run the PerfMon data collector set for the collection
   period and save the `.blg`. Enable FillDB performance logging for the same
   period and copy the logs. Run `Utilities\query_properties.ps1` for the Top
   10 and UDP captures.
3. **Nothing customer-specific.** Every capture is operational telemetry:
   counter values, evaluation times, relay and subnet names. No credentials or
   content are collected.

Keep the captures for one deployment together. The Workbench never modifies
an input file.

## Master Class Lab Workflow

The live labs begin in the `Performance and Config Analysis` site in the BigFix console. Run the collection task first, then
retrieve the resulting capture and use it as the input for the matching module.
The sample data is for practicing the Workbench workflow; it does not replace
the collection task in a live lab.

| Lab | BigFix collection task | Capture to retrieve | Workbench module |
|---|---|---|---|
| Client Performance | `BigFix Master Class -- Collect Client Performance Counter Analysis Data (2.0)` | `Client_Loop_*.xml` or `Client_Loop_*.csv`; the task also produces the optional Top 10 and UDP captures | Client Performance Loop Analysis |
| PerfMon | `BigFix Master Class -- Setup and Run Perfmon Counters (2.0)` | The `.blg` file from each targeted server | Perfmon Infrastructure Analysis |
| FillDB (time permitting) | `BigFix Master Class -- Enable FillDB Performance Logging (2.0)` | `FillDBPerf.log` and its rollover files after logging is disabled | FillDB Performance Analysis |

For the Client Performance lab, confirm that the `BigFix Master Class
-- Client Performance Counters - Basic (2.0)` analysis is active before running
the collection task. The collection task runs as a one-time action from the
root server.

For the PerfMon lab, run the task against the role servers in scope and
retrieve the logs directly from those machines. PerfMon logs are large and are
not uploaded by the lab tasks. For the optional FillDB lab, disable
the performance logging after the capture period and retrieve the complete log
set, including rollover files.

When a capture window is longer than the class session, the task run can be
demonstrated live and the instructor-provided sanitized capture can be used for
the analysis portion of the exercise.
