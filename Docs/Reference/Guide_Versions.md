# Guide Versions

The published BigFix guide that the analysis thresholds are built against. When a new edition ships, check its values against this page, update the code and this page together, and record the change in the CHANGELOG.

Shared module thresholds and guide editions stay aligned across the three
products. Platform-only capacity figures and modules are documented in the
Platform copy. Published guidance and house values remain distinct.

## Guides in Use

| Guide | Document version | Published | Checked on | Used by |
|---|---|---|---|---|
| BigFix Non-Functional Requirements: A Checklist Approach | 11.x.4 | 06-08-2026 | 10-19-2026 | PerfMon, FillDB |

The Capacity Planning guide (11.x.12, 10-05-2026) has none of the values these tools check, so it is not listed.

## NFR Guide Values

| Check | NFR item | Page | Guide value | Code value |
|---|---|---|---|---|
| Storage queue depth | PRF-INF-01 | 14 | 1 or less per physical device | Same |
| Storage latency | PRF-INF-02 | 14 | 1 ms or less per physical device | Same |
| Storage operations | PRF-INF-03 | 14 | No flat-lining under load. 5,000 transfers per second for database storage | Informational. No pass/fail limit is applied. The 5,000 transfers/sec value is reference context. Under-load flat-lining requires consultant review. |
| CPU utilization | PRF-INF-04 | 15 | 80% or less. 50% to 80% on a virtual machine | Same |
| CPU queue length | PRF-INF-05 | 15 | 4 or less | Same |
| CPU privileged time | PRF-INF-06 | 15 | 10% or less of aggregate CPU | 10% of total CPU time, by ruling 10-19-2026 |
| Network health | PRF-INF-07 | 16 | Error and discard counters approach zero | Any increase between samples fails, by ruling 10-19-2026 |
| Memory health | PRF-INF-09 | 17 | Paging File % Usage Peak 5% or less of physical memory | Same. The counter is converted from a share of the page file |
| FillDB health check | PRF-BIG-30 | 25 | Parallel DB Update (Short Batch), Parallel DB Update, Batch Rate and Parallel Parsing rate Good or Great | Scored on these four only. Good or Great earns 100, Poor earns 0, by ruling 10-19-2026 |

PerfMon applies only the guide's limits. The warning levels it once used (CPU utilization 70%, CPU queue 3, privileged time 8%, page file 4%) are not in the guide and were removed by ruling 10-19-2026.

## Values With No Published Source

These are house values. Neither guide states them.

| Value | Where |
|---|---|
| Client loop groups at 15, 30 and 60 minutes | Client Performance |
| Score cut-offs 90 and 70 | Client Performance, PerfMon, FillDB |
| ActionSite 10 MB soft warning (Needs Attention) and 25 MB hard ceiling (Critical), by ruling 10-19-2026 | Client Performance, Contributing Factors |
| Subscribed sites 100, computer groups 100, Fixlets and tasks 80,000 | Client Performance, Contributing Factors |
| Analyses or properties 10,000 total or 500 active | Client Performance, Contributing Factors |
| Master operators 5, master operator open actions 25, master operator content 50 | Client Performance, Contributing Factors |
| Analysis properties every 6 hours or longer | Client Performance, Evaluation Frequency |
| Severe loops over 120 minutes | Client Performance |
| FastHashVerify 20 ms work and 60 ms sleep | Client Performance, Client Settings |
| Command polling interval plus 600 seconds | Client Performance, Notification and Polling |
