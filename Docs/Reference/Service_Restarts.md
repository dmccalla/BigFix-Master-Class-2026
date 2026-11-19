# Windows Service Restarts

Logging enablement, disablement and reset tasks can restart their related
Windows service. Agree the restart window with the server owner. Duration
depends on the service and environment. There is no fixed 20-minute shutdown
or 5-minute startup deadline.

The controller requests a nonblocking stop and waits for the actual service
state. It keeps waiting while Windows reports StopPending or StartPending.
A 22-minute stop can finish normally before the task applies its logging
changes and starts the service. Status is recorded every 30 seconds in
`%ProgramData%\MasterClassWorkbench\ServiceTransitions.log`.

## Failures and recovery

A command error or an unexpected service state fails the action. If shutdown
has already begun when an error occurs, the controller waits for Stopped and
attempts to restore Running. Recovery does not turn the failed action into a
success. A failed recovery explicitly requires operator intervention.

A service that remains pending needs investigation. The task does not kill
the service. After a failure, cancellation or interruption, check the actual
service state before rerunning the task. A Failed task does not prove whether
its cleanup action was created. Check both the service and the cleanup action.
If logging remains enabled and cleanup is missing or failed, restore the
service as needed and use the matching WARNING task to disable logging.

## Maintaining the task definitions

The readable source is `Utilities/health_check_service_transition.ps1`.
Regenerate its inline copies from the application directory with
`python Utilities/service_transition_commands.py`. Each BES task is self-contained.
Generated cleanup actions embed the same controller. Import corrected task
definitions before new executions and review previously issued cleanup
actions separately. Repository edits do not rewrite existing action scripts.

## Verification

Run these checks from the application directory.

```powershell
python -m pytest Tests/test_task_service_restarts.py Tests/test_service_transition_behavior.py
```
The behavior tests run native PowerShell against fake services and a virtual
clock. They cover a 22-minute stop, a start longer than five minutes, late-stop
recovery, failed recovery, and failure exit codes after successful recovery.
Both direct and generated action commands are exercised.

In the lab, verify the target identity and initial service and logging state.
Exercise enablement, manual disablement, reset and generated cleanup. Confirm
Running after each restart, restored logging settings after cleanup, action
status, and controller log entries. A simulated long transition is not a
measured lab restart. Retain real timings separately.

The [17 November lab verification](../Records/Service_Restart_Cross_Repo_Verification_2026-11-17.md) records nine passing FillDB lifecycle scenarios and the measured 22-minute shutdown.
