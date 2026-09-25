# Release Process

How a version of the Master Class Diagnostics Workbench is cut and recorded.
The application, the collection tasks, the sample data and the guide ship
together and carry one version number.

## Where A Version Lives

| Thing | Where | What it is |
|---|---|---|
| Declared version | `pyproject.toml`, `project.version` | The single source of truth. Read by `Lib/Core/app_version.py`. |
| Changelog | `CHANGELOG.md` | The permanent record of what changed between versions. |
| Git tag | `vMAJOR.MINOR.PATCH` on one commit | The exact code a version shipped from. |
| Release assets | GitHub Releases | The versioned zip, its `.sha256`, and the SBOM. |

Between releases the declared version carries a `-dev` suffix so a build from
`main` is never mistaken for the shipped release. `Tests/test_version.py`
fails the suite when a release version has no changelog section.

## Cutting A Release

1. Record changes under `## [Unreleased]` in `CHANGELOG.md` as they land.
2. Run the gate and resolve every **Action Required** result. A **Review
   Recommended** result needs a recorded decision before it is accepted.

   ```powershell
   .\Tools\run-code-sweep.ps1
   ```

   The sweep writes its reports and executive summary under
   `Temp\Code_Sweeps\<timestamp>\`.
3. Confirm the tree is clean and the suite passes.

   ```powershell
   git status
   .venv\Scripts\python -m pytest -q
   ```

4. Rename the Unreleased section to the version and date, open a fresh empty
   `## [Unreleased]` above it, and drop the `-dev` suffix from
   `pyproject.toml`.
5. Run the suite again. Commit the release metadata together:
   `git commit -m "Release v1.0.0"`.
6. Build and inspect the package.

   ```powershell
   .\Build\package_release.ps1
   ```

   This writes `Master-Class-Diagnostics-Workbench-1.0.0.zip` and its
   `.sha256` under `Dist\Releases`. The zip carries `START_HERE.txt`,
   `sbom.cyclonedx.json`, `THIRD_PARTY_NOTICES.md` and
   `release-manifest.json` with a SHA-256 per file. Extract it into a clean
   folder, run the launcher, and run the sample workflow.
7. Tag the commit with an annotated tag and push both.

   ```
   git tag -a v1.0.0 -m "Release v1.0.0"
   git push
   git push origin v1.0.0
   ```

8. Draft the GitHub Release against the tag, paste the changelog section as
   the body, upload the zip, the `.sha256` and the SBOM, and publish.
   Download the zip in a fresh session and verify the checksum.
9. Open the next development version: set `version` to the next `-dev` and
   commit it on its own.

## Getting It To Attendees

Attendees receive the zip, not the repository. The repository is private and
access is granted per person. Instructions name the versioned zip and its
checksum.
