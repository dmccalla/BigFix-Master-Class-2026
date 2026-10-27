# Dependency Cooldown Exception, 2026-10-26

Product: Master Class Diagnostics Workbench.

Approver: Duncan McCalla, explicit approval in the Codex conversation on 2026-10-26.

The routine seven-day cutoff is `2026-10-19T00:00:00Z`. The certifi security fixes were released after that cutoff. The approved package-specific cutoff is `2026-10-21T00:00:00Z` for `certifi`. The global cutoff still applies to every other package.

| Exception package | Previous lock | Updated lock | Advisory |
| --- | --- | --- | --- |
| certifi | 2026.7.22 | 2026.10.19 | GHSA-6q48-6c7w-9gw2 |

The advisory reports compromised intermediate CA keys beneath an emSign root. The affected trust bundles could allow an on-path attacker to impersonate HTTPS sites. The security updates remove the affected trust root.

The same lock refresh updates `filelock` 4.0.3 to 4.2.2 and Pillow 12.3.0 to 13.0.0. Both are allowed by the routine cutoff and required to clear the installed-environment audit. `pip-audit` reported no known vulnerabilities after syncing this lock.

Remove the package-specific override at the next routine refresh after the global seven-day cutoff admits these security releases, then regenerate the lock and requirements mirror.
