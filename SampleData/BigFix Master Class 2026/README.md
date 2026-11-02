# Shared demonstration assessment

All three workbenches use this complete dataset, identified as
`shared-demo-2026-11-02`. It contains 2,537 client records, 24 relays,
25 subnets and 244 active property intervals for 1-14 June 2026.
Each workbench uses the inputs for the modules it supports.

Select the complete demo folder in the application:

| Workbench | Folder |
|---|---|
| Main | `SampleData/BigFix_Inc` |
| TA | `SampleData/TA Health Check` |
| MC | `SampleData/BigFix Master Class 2026` |

There is no nested Results folder. Select the whole folder so Client
Performance can find the deployment reference inputs and property intervals.

The shared assessment includes Client Performance, deployment reference,
FillDB and PerfMon evidence. The same folder also carries dashboards, SQL,
server and relay capacity, server logs and saved Release Intelligence for
the full report. Datasets with more than ten groups exercise report previews
and the corresponding workbook references.

These are demonstration values, not a live collection. The PerfMon binary
and counters are unchanged: 60 readings on 14 June 2026, 20:17 to 21:16,
with four logical processors and 12 GB RAM. FillDB covers 37 hours on
13-14 June. SQL exports and server logs remain representative evidence;
they are not measurements of a newly collected 2,537-device deployment.
Relay capacity is a synthetic set of 24 hosts derived from the original
capacity examples. Unknown installation paths remain Not collected.

The saved Release Intelligence example was filtered for 11.0.6.137. It
contains no later releases and retains its original August capture date.
It is an offline example, not current release guidance.

See `DEMO_SNAPSHOT.json` for sources and transformations, `Originals/` for
preserved source archives, and `SAMPLE_DATA_VALIDATION.json` for input hashes.
The original smaller main demonstration remains available in Git history.
