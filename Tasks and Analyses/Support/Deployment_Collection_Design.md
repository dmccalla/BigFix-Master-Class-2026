# Deployment Information collection design

This contract applies to Collect Deployment Information in each product repository.
Validate standalone tasks first. Where a Day 1 combined task exists, it inherits the
verified collection behavior afterward. A standalone repository does not need a new
combined task.

## Load and capture contract

- Run requests sequentially. Default the pause after each request to 5 seconds, both in
  the description UI and when an action does not supply the parameter. This reduces
  burst load across deployments with different capacities. It does not establish a
  guaranteed safe request rate. Administrators may select 1 second when the deployment
  is known to handle it. The existing 0-second override remains available.
- Generate the 113 constant headings and blank lines locally as BESAPI XML fragments.
  Keep their text, destinations, and ordering. Do not send them to `/api/query`.
  Include the schema-required Evaluation element, with Time explicitly marked
  `Not applicable: local capture` and Plurality `Singular`. Do not invent a server
  evaluation duration for locally generated data.
- Preserve all 177 real Session Relevance expressions. With all sections selected,
  pacing alone adds about 15 minutes at the default, plus request execution time.
  The two admin requests run only when the optional human readable logs are selected.
- Keep the 13 existing client relevance expressions: Actionsite Size and the 12 root
  server values. Append these answers to the appropriate XML before optional log
  conversion. XML-only collection must retain them and must not create a partial
  `Root_Server_Info` log.
- Use the CLI `--outFile` option to receive native XML without redirected-console
  encoding conversion. Stream those response-file bytes directly to their existing
  captures. Read only the newly appended response to classify it, using a streaming XML reader. Do not
  rebuild query answers or hold complete large result sets in memory.
- Preserve concatenated BESAPI documents. Captures are not single XML documents.
  Keep XML and locally collected answers even if a later request fails. Back up the
  preceding collection using the existing backup flow before a new collection starts.

## Diagnostics and failure policy

`Deployment_Information/Diagnostics/Deployment_Collector_<action ID>.csv` contains one
row per attempted request, plus initialization, login, and completion rows. Its JSON
companion records counters and the overall result. Diagnostics are always collected,
independently of the human readable data-log option.

Each row records UTC time, a stable request ID, resource, capture filename, outcome,
native CLI exit code, HTTP status when the CLI reports one, elapsed milliseconds,
server evaluation time when the XML includes it, and the availability-failure count.
Use request ID and the embedded task's `-QueryNumber` to find the original relevance.
Per-request rows exclude passwords, tokens, command arguments and returned metric
values. JSON and text summaries include only the environment allowlist below. Other
metric answers remain in their normal evidence captures.

| Case | Behavior |
|---|---|
| Initial CLI login returns nonzero | Stop. This can be authentication, TLS, connectivity, or CLI setup. Do not label every login failure as a bad password. |
| Explicit HTTP 401 during collection | Stop immediately. Do not retry with the same rejected session. |
| Explicit HTTP 403 | Record permission failure and continue. Mark the completed collection incomplete. |
| Relevance `<Error>` response | Record the query failure and continue. Mark the completed collection incomplete. |
| HTTP 408, 429 or 5xx; connection failure; timeout; unusable response | Count an availability failure. Stop at three consecutive failures. |
| Other explicit HTTP 4xx | Record request failure, continue, and finish incomplete. |
| Successful empty `<Result>` | Success. Reset the availability counter. |
| Slow successful query | Record its timing. Do not fail solely because it is slow. |
| Local helper, state, or evidence-write error | Stop immediately. |

A valid permission or query-error response also proves the server responded and resets
the availability counter. The CLI does not guarantee a machine-readable HTTP status for
every failure. An unclassified nonzero exit or unusable response is counted as an
availability failure rather than guessed to be an authentication failure.

There are no automatic request retries. The helper waits for the current IEM process;
it does not introduce a new process-kill timeout or launch a replacement query in
parallel. A client-side timeout does not prove the server-side relevance stopped.
After a stop, review the diagnostics and retained XML, resolve the cause, and rerun
manually when appropriate. Failed queries also append the established
`ERROR: Query line N failed:` marker so evidence consumers can detect incomplete data.

## Readable diagnostics and environment context

Every run writes `Diagnostics/Deployment_Collector_<action ID>_Summary.txt`, even
when optional data logs are off. The existing JSON state is schema version 2 and
retains its original counters and exit code. CSV columns and row counts are unchanged.
The summary is refreshed as requests complete, on normal completion, and on a
collector-controlled stop. A Running snapshot is not proof of completion. An external
action interruption or inaccessible diagnostic storage can leave the last snapshot.

The summary includes selected sections, planned/attempted requests, pacing and log
settings, UTC start/update/end, collection-window duration, summed request wall time,
section totals, up to ten slowest query IDs and twenty failure examples. The CSV
retains every request. Scheduled pacing is an estimate, not a measured duration;
the next pause might not execute if an action is interrupted. Request wall time
excludes PowerShell startup, response classification, pacing and data-log conversion.
The diagnostic window starts at initialization and excludes earlier backup/setup.
In Day 1 it can include selected dashboard modules; their selection is recorded. A
separate Deployment Information window starts at its first API request and includes
later pacing, local captures and log conversion, excluding earlier initialization,
login and dashboard modules. Until a request starts, that window is unavailable. Returned server evaluation durations are converted
only when their units are recognized. Report parsed/unrecognized counts; do not treat
an absent duration as a zero-duration query.

Reuse successful answers from DI-014/015/016 for computer, active-computer and relay
counts; DI-020 or DI-030 for server version counts; DI-033/034/035 for reported root
CPU, RAM and OS. Record the source ID. Reject a partial Result accompanied by Error.
Missing, skipped, blank or failed answers remain null/Unavailable; a real zero remains
zero. Root values can describe multiple root servers in a deployment.

At initialization, read a local allowlist of OS-reported CPU model/socket/core/thread
counts, RAM GiB, manufacturer/model and OS caption/version/architecture. A VM describes
its assigned resources. This uses three local
[`Get-CimInstance` reads](https://learn.microsoft.com/en-us/powershell/module/cimcmdlets/get-ciminstance?view=powershell-5.1),
each with a three-second operation timeout. There are no new BigFix API requests.
Missing local context adds a context note, not a collection failure. Never copy entire
CIM objects, hardware-analysis results, host identities, serial/processor IDs, license
information, credentials or arbitrary metric answers into the new JSON context or
text summary. Existing CSV capture filenames retain their established naming.
Review deployment context before sharing it outside its authorized audience.

Store the normalized helper SHA-256, shipped query-contract SHA-256, client version
and observed server-version counts for repeated measurements. Engine identity/version,
database/storage performance, concurrent load and cache state are explicitly unknown;
do not infer them. These diagnostics support runtime estimates and later comparisons
with matching versions, query sets, sections, pacing and log settings. The shipped
query fingerprint describes the tested task; custom ActionScript edits need their
own comparison identity. They do not
establish deployment rankings. Automatic aggregation or uploading is not added.

## BigFix action results

These are collector-defined codes, not platform-wide error-code assignments:

| Code | Meaning |
|---|---|
| 0 | Selected collection completed without recorded request failures. |
| 24001 | Initial CLI login or setup failed. |
| 24002 | Authentication rejected during collection. |
| 24003 | Three consecutive availability failures. |
| 24004 | Collection finished with incomplete evidence. |
| 24005 | Local collector, helper, or diagnostic file failure. |

Read a subprocess exit code immediately, before another `wait` command overwrites it.
The ActionScript uses `exit {exit code of action}` immediately when a helper returns
nonzero. Its success criterion is RunToCompletion. The lab verifies that an early
nonzero exit reports Failed and preserves the collector code. A final ping or successful cleanup must not hide it.
Verify both the code and Failed/Completed status on the lab server.

The BigFix [`exit` command](https://developer.bigfix.com/action-script/reference/flow-control/exit.html)
sets the action exit code. The
[`continue if` command](https://developer.bigfix.com/action-script/reference/flow-control/continue-if.html)
stops execution when its condition is false. Consult the action's success criteria
when interpreting its displayed status.

## Query engine compatibility

The root server's normal `/api/query` route selects an available Explorer before
falling back to Web Reports. See the [query API reference](https://developer.bigfix.com/rest-api/api/query.html).
The collector keeps that routing and the existing relevance expressions. A running
engine can still reject an operation that it does not support.

On the controlled BFROOT1 lab run of 2026-10-19, Explorer at `192.168.4.7` rejected
the existing administered-computer count operations in requests `DI-107`, `DI-108`,
and `DI-109`: the non-master-operator average and the operator minimum and maximum.
The CLI returned exit code 0 while its XML contained `<Error>`. These are query
failures, not availability failures. The collector retains the response, records
the missing evidence, continues the remaining requests, and finishes with 24004.
The 177 original expressions and their output labels remain unchanged.

Full no-error lab scenarios deliberately flag this compatibility condition. A
correctly reported incomplete collection is not proof that all requested data was
available. Review engine support before treating the operator statistics as complete.
The collection changes do not alter engine registrations, priorities, or services.
Recheck these three queries after an Explorer upgrade before carrying this lab
limitation forward. Support can differ between engine versions and deployments.

## Operator guidance and verification

After an expected root-server service restart, a console session that has not
reauthenticated promptly can show transient errors. Reauthenticate, then clear those
messages and continue. Errors that persist or recur require investigation. Collection
does not require a server restart.

Avoid overlapping collection runs against the same deployment, including runs from
different product versions. Sequential requests within one run do not limit requests
from another independently started run. The collector does not claim a deployment-wide
lock; check running actions and coordinate collection.

Offline tests preserve literal order and real queries, XML/log compatibility, helper
embedding, pacing, classification, counter reset, no retries, and exit-code outcomes.
The controlled lab plan is `.github/deployment-collection-lab.example.json`. Target
only the approved lab root, test every section with logs off and on, retain action IDs
and capture evidence, and verify standalone success before updating combined content.
Use harmless negative probes to verify BigFix status and exit-code propagation.

The lab harness uses standard form-encoded Session Relevance requests for preflight,
matching normal engine selection for the collector. It does not force the optional
Explorer-only JSON request mode. A preflight transport failure must be distinguished
from a failure in an executed collection action.

## Validation record, 2026-10-19

The controlled target was BFROOT1, computer ID 8317784. Runs were sequential.
One-second pacing was an explicit lab override where shown; the default remains
five seconds. Action numbers identify retained lab evidence, not release versions.

| Action | Coverage | Result |
|---|---|---|
| 1705 | Platform standalone, General section, default 5 seconds, logs off | Completed, code 0. All 26 requests succeeded. Actionsite Size remained in XML; no data log was created. |
| 1707 | Platform standalone, every section, 1-second override, logs on | Finished incomplete, code 24004. All 179 requests were attempted. Only DI-107/108/109 failed with the engine limitation above. Retained 10 XML captures, 10 logs and 183 CSV lines including the header. |
| 1709 | TA standalone, Root section, 1-second override, logs off | Completed, code 0. Eight requests succeeded. Root client values remained in XML; no partial Root log was created. All seven retained-capture assertions passed after correcting the assertion's CSV-field matching. |
| 1711 | Class standalone, Root section, 1-second override, logs on | Completed, code 0. Eight requests succeeded. Root XML and its readable log were retained. All seven assertions passed. |
| 1713 | Platform Day 1 combined, Deployment Information only, 1-second override, logs off | Finished incomplete, code 24004. All 177 requests were attempted. Only DI-107/108/109 failed. Retained 10 XML captures, no data logs, and 181 CSV lines including the header. Actionsite, root client values, and the property evaluation interval block remained in XML. |

Harmless native exit probes 1697 and 1703 confirmed Failed status with exit codes
24002 and 24003. A development run also exercised the three-unusable-response
gate before the CLI native-output correction; it stopped with 24003. Those probes
do not claim a production authentication or availability outage was induced.

The full offline suites passed: Platform 2,277 tests, TA 639 tests, and Class 633
tests, with their environment-dependent skips. Ruff lint and format checks passed
in all three repositories. Native Windows helper tests cover failure classification,
counter reset, partial Result plus Error, Unicode and large response preservation.
Consumer compatibility tests compare the existing Get parsing and generated
reference-table XML before and after collection changes, including diagnostics
alongside evidence. Get and Inject production scripts were not changed.

Normalized standalone action bodies match across all three repositories. Frozen
contracts preserve the 177 query expressions, 113 constant fragments, and all 13
client relevance expressions. The combined task reuses that collection and retains
its 104 existing dashboard query commands. Combined live coverage selects Deployment
Information only; it does not claim a new dashboard runtime validation.

These results verify the collector and retained output contract. They do not remove
the three existing query-engine limitations or establish production capacity.
Readable summaries and environment context are included. Cross-deployment aggregation
and benchmarking remain separate work.

## Diagnostics follow-up validation, 2026-10-19 Eastern

Standalone validation preceded the combined update, on the same allowlisted BFROOT1
target. No collection actions overlapped. One second was an explicit lab override;
the shipped five-second default and the original request/capture contracts remain.

| Action | Coverage | Result |
|---|---|---|
| 1715 | Platform standalone, General and Root, five-second pacing, data logs off | Completed, code 0. All 34 requests succeeded; 38 CSV lines. Counts, server versions, root hardware, readable summary and XML client values verified. This first run preceded the separate first-request window refinement. |
| 1717 | TA standalone, Root only, one-second pacing, data logs off | Completed, code 0. Eight requests and 12 CSV lines; root values retained, zero data logs. Summary and schema 2 checks passed. Node count remained Unavailable with General skipped; separate diagnostic/request windows verified. |
| 1719 | Class standalone, Root only, one-second pacing, data logs on | Completed, code 0. Eight requests and 12 CSV lines; one root data log. Summary and schema 2 checks passed. Retained summary helper fingerprint matches the shipped source. |
| 1721 | Platform Day 1 combined, Deployment Information only, one-second pacing, data logs off | Finished incomplete, code 24004. The failing query IDs were DI-107, DI-108. Verified against CSV outcomes, XML errors and error markers; no other failures were hidden. All 177 requests were attempted; 10 XML captures, zero data logs, 181 CSV lines and 126 local XML fragments. Verified all ten section totals, ten slowest requests, context/source IDs, helper identity and retained summary. |

Before integrating the concurrent loop-health update, offline suites passed: Platform 2,289 tests (82 skips), TA 650 (31 skips), and
Class 644 (33 skips). Ruff lint and formatting passed in all three. Native helper
coverage is 27 tests, including missing versus zero counts, rejected partial answers,
allowlisted context, unavailable local discovery, explicit timing units, bounded
slowest/failure lists, helper identity and the first-request timing window. The
existing consumer compatibility test includes the new summary alongside diagnostics.
After rebasing onto the concurrent loop-health fixes, integration checks passed
(Platform 24, TA 16, Class 16) and all lint/format checks still passed. The slowest
request test compares measured CSV durations rather than assuming a fixed process
startup time, so normal runner scheduling does not change its expected result.

The three normalized standalone action bodies match, as do the helper sources.
Normalized helper SHA-256 is
`33b40e34cde423ea9e3bd628750f5e1f6dd7bd3fd43627d070343d524d1e5c5a`.
The preserved query/literal/client-value contracts remain 177/113/13, with no added
BigFix API queries. All 104 combined dashboard query commands remain unchanged.
Get, Inject, customer report prose, templates and client-performance code were not
changed by this follow-up.
