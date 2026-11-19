# Cross-Repository Service Restart Verification, 2026-11-17

The controller correction is present in all three repositories. Local and live
verification completed on BFROOT1 in the BigFix Workbench Test site. All nine
FillDB scenarios and the actual 22-minute delayed-service test passed.

## Scope

| Repository | Changed task files | Inline service commands |
| --- | ---: | ---: |
| Platform | 29 | 118 |
| TA | 3 | 8 |
| Master Class | 3 | 8 |

The commands request nonblocking stops, observe the actual Windows service
state, and keep waiting while the service is stopping or starting. Progress
is recorded every 30 seconds. Errors preserve failure status and attempt to
restore Running after an outstanding stop. A service remaining pending needs
operator investigation. Cancellation still requires a service-state check.
See [Windows service restarts](../Reference/Service_Restarts.md).

## Local checks

| Repository | Completed suite | Additional final checks |
| --- | --- | --- |
| Platform | 740 focused checks passed, 1 release-only check skipped | Restart controller, native PowerShell exit codes, task contracts, lab harness, guides, links, layout and text rules. |
| TA | Full suite: 1,079 passed, 36 skipped | 46 final task, guide, naming and lab-path checks passed after the guide and scenario updates. |
| Master Class | Full suite: 1,112 passed, 37 skipped | 60 final task, guide and naming checks passed after the guide and scenario updates. |

All 67 task definitions validated against their own repository helpers:
48 Platform, 7 TA and 12 Master Class. Regeneration does not change the
controller copies. Product log folders retain their own names.

Final documentation checks passed four link/text checks in Platform and
four link/naming checks in each other repository. The additional Platform
documentation-location guard flags an existing generated customer report
under outputs/omr, outside Docs. That output was preserved. This unrelated
guard failure does not affect the service tests or the nine live scenarios.

Native PowerShell tests cover a 22-minute virtual shutdown, startup longer
than five minutes, late-stop recovery, failed recovery and nonzero process
exit after successful recovery. These are simulated services. The real-service
fixture compiled successfully and its no-execution guard passed locally.
The fixture executable was not run locally.

## Documentation

| Guide | Revision | Pages |
| --- | --- | ---: |
| Platform User Guide | 2.7 | 45 |
| Platform Procedural Guide | 2.7 | 39 |
| Customer Briefing and Prerequisites | 1.1 | 3 |
| TA User Guide | 1.1 | 21 |
| TA Lab Guide | 1.3 | 28 |
| Master Class User Guide | 1.3 | 21 |
| Master Class Lab Guide | 1.2 | 28 |

All revisions are dated 11/17/2026. The seven Word guides and their PDFs were
updated with Microsoft Word. Page counts remain unchanged at 185 total.
Revised instructions and revision records were inspected at readable size,
with complete page overviews. All embedded image contents are unchanged.
Existing lab Version Control histories retain their established sequences.
The Platform guide-claims ledger's restart entries were corrected after live
validation. Nine cells changed. All other values and workbook package parts,
including its filter, were preserved. Only the affected row heights and one
status fill changed to fit and match existing formatting.

The briefing no longer gives a fixed 25-minute allowance. Troubleshooting
does not treat every Failed action as a timeout or assume cleanup is absent.
Collection, test and maintenance references describe state waiting, recovery,
operator checks and the correct product log paths. The active presentation
was checked for restart timing claims. Its restart and cleanup guidance
needed no correction. The lab exercise's unrelated 20-minute estimate remains.

## Live validation

BFROOT1 was identified by name and allowlisted computer ID 8317784 before
execution. Temporary test copies used the checked-in task scripts. Source
hashes in the scenario reports still match the current definitions.

| Repository | Scenario | Parent action IDs | Generated cleanup action |
| --- | --- | --- | --- |
| Platform | filldb-performance-manual-lifecycle | 2137, 2139 | None expected |
| Platform | filldb-performance-generated-disable | 2141 | 2142 |
| Platform | filldb-performance-defaults-reset | 2144, 2146 | None expected |
| TA | filldb-performance-manual-lifecycle | 2148, 2150 | None expected |
| TA | filldb-performance-generated-disable | 2152 | 2153 |
| TA | filldb-performance-defaults-reset | 2155, 2157 | None expected |
| Master Class | filldb-performance-manual-lifecycle | 2159, 2161 | None expected |
| Master Class | filldb-performance-generated-disable | 2163 | 2164 |
| Master Class | filldb-performance-defaults-reset | 2166, 2168 | None expected |

All scenarios passed their action-state and client assertions. Manual
enable/disable, generated cleanup and defaults reset each finished with FillDB
Running. Logging and temporary collection settings were restored.

The disposable service's measured shutdown took
1320.86 seconds (22.01 minutes).
Windows continued to report StopPending beyond 20 minutes, and the service
then restarted successfully. A real stop request followed by an injected command
error recovered to Running in 6.45 seconds and preserved
the original failure. The disposable service was stopped and deleted.
Launcher action 2135 completed. The fixture's final
result, rather than launcher completion, establishes success.

Final independent checks at 2026-11-17T18:38:36.933912+00:00 confirmed root server and
FillDB Running, performance logging disabled, collection paths inactive,
temporary markers absent and the disposable service absent. Temporary test
tasks and completed actions remain in the lab as action-history evidence.

Live coverage used the shared Windows controller through the FillDB task
lifecycles in each repository. Other component roles and combined day tasks
were covered by local contracts and decoded-command behavior tests, rather
than individual live restarts of every role.

See [machine-readable live evidence](Service_Restart_Live_2026-11-17.json).
The [controller transition log](Service_Restart_Transitions_2026-11-17.log)
and [delayed-service log](Service_Restart_Probe_2026-11-17.log) retain the
actual state progression and recovery messages.

Imported tasks and previously issued cleanup actions are not rewritten by
repository edits. Review them before using the corrected definitions.
