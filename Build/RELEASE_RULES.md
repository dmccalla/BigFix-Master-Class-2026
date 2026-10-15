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
