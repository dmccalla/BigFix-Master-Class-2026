# Release Package Rules

The GitHub Release ZIP is the student download. Apply these rules to every new
Master Class release and check the finished ZIP, not just the source tree.

- The ZIP opens at the Workbench root. Put `App/`, `Launchers/`, `Docs/`,
  and the other required product folders directly at its top level. Do not
  add a version-named enclosing folder. Preserve required internal folders.
- Include only finished PDF files under `Docs/`. Keep the editable user-guide
  source, loose screenshots, design notes, and other documentation sources in
  git, outside the ZIP. Runtime report templates under `Templates/` remain.
- Include no `.md` files anywhere in the ZIP. Use `START_HERE.txt` for
  in-package directions, and publish the changelog on the release page.
- Put a direct link to that release's PDF user guide at the top of the release
  notes. Encourage students to read it before running the Workbench. Do not
  link to a moving `main` version.
- Verify the ZIP entry list, root layout, PDF-only docs, exclusions, manifest
  hashes, and `.sha256` file. Extract into a clean folder and test the
  launcher. After upload, download the published ZIP and checksum and confirm
  they match the verified build.

`Build/package_release.ps1` and `Tests/test_package_release.py` enforce the
archive layout and file exclusions. Review both when changing the package.

## Separate Large Perfmon Download

The release packager also builds `Sample-Data-Perfmon-Large-<version>.zip`
and its `.sha256` file. Upload these alongside the main application ZIP and
checksum on that same release. No upload is performed by the packaging script.
The ZIP has a `sample-manifest.json` with the source commit, version, file
sizes and SHA-256 hashes. The BLGs remain outside git and the main application
download. The small default sample remains in the application package.

Put the large `.blg` files directly in `LocalSamples/Large_Perfmon` under the
application root, set `BIGFIX_LARGE_PERFMON_SAMPLE_DIR` to an existing source
folder, or pass `-LargePerfmonSamplePath <folder>` to `package_release.ps1`.
The explicit parameter takes priority over the environment variable and default
folder. Use the retained original large lab capture, not the small `server.blg`.
Each release builder must have a copy of the source BLGs; a git clone alone
does not contain them. Do not use a temporary backup folder as the permanent
release source.

The default build fails early if the source is missing or has no nonempty BLGs,
so a release cannot silently omit its companion download. `-ValidateOnly`
checks the inputs without creating archives. `-SkipLargePerfmonSamples` is an
explicit way to build or validate only the main application package when the
optional data is unavailable. Do not describe that build as containing the large
sample download.

To use the companion, extract it into the application package's extraction
folder. The BLGs go into `SampleData/Large_Perfmon` under the application root.
Select a BLG directly in the Perfmon module when testing that larger capture;
do not replace or mix it into the default multi-module sample folder. Check
the archive checksum and the per-file manifest before publishing.
