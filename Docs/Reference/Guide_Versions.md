# Guide Versions

The published BigFix guides that the analysis thresholds and sizing figures are built against. When a new edition ships, check its values against this page, update the code and this page together, and record the change in the CHANGELOG.

The TA Health Check, the Master Class Diagnostics Workbench and the Report Builder keep the same copy of this page.

## Guides in Use

| Guide | Document version | Published | Checked on | Used by |
|---|---|---|---|---|
| BigFix Non-Functional Requirements: A Checklist Approach | 11.x.4 | 06-08-2026 | 10-19-2026 | PerfMon (all three tools), FillDB (all three tools), Client Settings Suggester (Report Builder) |
| BigFix Capacity Planning: Core Platform | 11.x.12 | 10-05-2026 | 10-19-2026 | Server Capacity and Relay Capacity (Report Builder only) |

The Capacity Planning edition and its figure numbers live in `Report Builder/Config/capacity_sizing.json`. Report text reads them through `figure_ref()` and `guide_name()`, so a new edition is one edit to that file.

## NFR Guide Values

| Check | NFR item | Page | Guide value | Code value |
|---|---|---|---|---|
| Storage queue depth | PRF-INF-01 | 14 | 1 or less per physical device | Same |
| Storage latency | PRF-INF-02 | 14 | 1 ms or less per physical device | Same |
| Storage operations | PRF-INF-03 | 14 | No flat-lining under load. 5,000 transfers per second for database storage | Same |
| CPU utilization | PRF-INF-04 | 15 | 80% or less. 50% to 80% on a virtual machine | Same |
| CPU queue length | PRF-INF-05 | 15 | 4 or less | Same |
| CPU privileged time | PRF-INF-06 | 15 | 10% or less of aggregate CPU | 10% of total CPU time, by ruling 10-19-2026 |
| Network health | PRF-INF-07 | 16 | Error and discard counters approach zero | Any increase between samples fails, by ruling 10-19-2026 |
| Memory health | PRF-INF-09 | 17 | Paging File % Usage Peak 5% or less of physical memory | Same. The counter is converted from a share of the page file |
| FillDB health check | PRF-BIG-30 | 25 | Parallel DB Update (Short Batch), Parallel DB Update, Batch Rate and Parallel Parsing rate Good or Great | Changing to follow the guide, by ruling 10-19-2026 |

The PerfMon warning levels (CPU utilization 70%, CPU queue 3, privileged time 8%, page file 4%) are not in the guide. By ruling 10-19-2026 they are being removed so that only the guide's limits apply.

## Capacity Planning Figures

| Figure | Content | Section in the data file |
|---|---|---|
| 3.1.1 | Hyperthreaded core at 30% of a physical core. 2.0 GHz per core | `basis` |
| 3.1.4 | 5,000 IOPS at 1 ms latency | `universal` |
| Figure 4 | Root server CPU, memory and storage by deployment size | `root_server` |
| Figure 5 | Web Reports and BES Explorer additions | `web_reports` |
| Figure 6 | WebUI additions per 10 concurrent users | `webui` |
| Figure 11 | Leaf relay scale by version and authentication | `relay` |
| Figure 13 | Persistent connection limits by version | `relay.persistent_connection_limit` |
| Figure 16 | Plugin Portal additions per plugin | `plugin_portal` |
| Figure 26 | Message Level Encryption additions | `message_level_encryption` |

The 11.0.7 relay ratings in Figures 11 and 13 apply to Windows, RHEL and non-DMZ relays. The capture does not say whether a relay is in a DMZ, so a DMZ relay on 11.0.7 is rated as if it were not.

## Values With No Published Source

These are house values. Neither guide states them.

| Value | Where |
|---|---|
| Client loop groups at 15, 30 and 60 minutes | Client Performance |
| ActionSite 10 MB soft warning. A 25 MB hard ceiling is being added by ruling 10-19-2026 | Client Performance, Contributing Factors |
| Subscribed sites 100, computer groups 100, Fixlets and tasks 80,000 | Client Performance, Contributing Factors |
| Analyses or properties 10,000 total or 500 active | Client Performance, Contributing Factors |
| Master operators 5, master operator open actions 25, master operator content 50 | Client Performance, Contributing Factors |
| Analysis properties every 6 hours or longer | Client Performance, Evaluation Frequency |
| Severe loops over 120 minutes | Client Performance |
| FastHashVerify 20 ms work and 60 ms sleep | Client Performance, Client Settings |
| Command polling interval plus 600 seconds | Client Performance, Notification and Polling |
