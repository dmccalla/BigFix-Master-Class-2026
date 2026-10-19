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
Do not log passwords, tokens, command arguments, or returned metric values in these
diagnostic files. Metric answers remain in their normal evidence captures.

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
