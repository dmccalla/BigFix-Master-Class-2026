# Master Class Diagnostics Workbench User Guide Verification

Historical record. It describes guide version 1.0 Draft as checked on 2026-10-14 and is not updated for later guide versions.

Date: 2026-10-14. Guide version: 1.0 Draft. DRAFT watermark retained.

## Scope And Data

The guide was checked against the current Master Class application and Windows
launcher. The source document supplied by Design was edited in place, with its
layout and styles retained. Aptos replaces the source heading font. The corporate
URL and inherited cover wordmark were removed because this is unofficial
attendee documentation.

The screenshots use the complete repository folder
`SampleData/BigFix Master Class 2026/Results`, copied without renaming its
subfolders to `C:\Temp\MasterClassGuide\Results` to avoid a personal username
in the figures. The initial captures using a mixture of standalone samples
were discarded and replaced.

- Run Name: `Example_Server`.
- Output Folder: `C:\Temp\MasterClassGuide\Output`.
- Client dates: 10-05-2026 to 10-06-2026, as specified for the sample in
  `Docs/Getting_Started.md`.
- Perfmon: the Results BLG, with CPU and disk counts detected by the app.
- RAM: 12 GB. Virtual machine: selected. Both supplied by Duncan.
- Capture 2: unused. No second capture was invented.
- Dark mode: switched on through the actual UI for Figure 4, then switched
  off for the remaining application figures.

The development application still displays 2.0. The guide describes dark
mode for the upcoming 2.1 release at Duncan's request. The screenshot pixels
and the application version were not altered.

## Claim Checks

Confirmed means the current source supports the guide's wording. Runtime
checks are called out separately below. File and line references identify
the implementation inspected during this work.

| Claim | Verdict | Source | Result / Change |
|---|---|---|---|
| 1.1 | Confirmed | `App/run_diagnostics.py:1602` | Three module names match the UI. |
| 1.2 | Confirmed | `App/run_diagnostics.py:1689` | Timestamped run folder and module outputs match. |
| 1.3 | Confirmed | `App/diagnostics_workbench_ui.py:161` | Module descriptions match. |
| 1.4 | Unverified | `Build/package_release.ps1:67` | File exists and packaging includes tracked Docs files. A published release archive was not inspected. |
| 1.5 | Confirmed | `README.md:34`, `Launchers/Run Diagnostics Workbench.cmd:70` | Documented environment and launcher requirements match. |
| 2.1 | Confirmed | `Launchers/Run Diagnostics Workbench.cmd:70` | Python floor is 3.12. |
| 2.2 | Confirmed | `Launchers/Run Diagnostics Workbench.cmd:47` | Launcher checks py first, then python. |
| 2.3 | Confirmed | `Launchers/Run Diagnostics Workbench.cmd:1` | Launcher exists and was used for the screenshot session. |
| 2.4 | Confirmed | `Launchers/Run Diagnostics Workbench.cmd:53` | Missing-environment path displays a notice and pauses. |
| 2.5 | Confirmed | `Launchers/Run Diagnostics Workbench.cmd:27`, `Launchers/Run Diagnostics Workbench.cmd:77` | Private environment and requirements installation match. |
| 2.6 | Confirmed | `Launchers/Run Diagnostics Workbench.cmd:63` | Existing runnable environment is reused. |
| 2.7 | Confirmed | `App/diagnostics_workbench_ui.py:781` | Starts on Folders. Observed during launch. |
| 2.8 | Confirmed | `Launchers/Run Diagnostics Workbench.cmd:72` | Missing environment is created again. |
| 3.1 | Confirmed | `App/diagnostics_workbench_ui.py:216` | Folders, Modules, Build. |
| 3.2 | Confirmed | `App/diagnostics_workbench_ui.py:2196`, `App/diagnostics_workbench_ui.py:5081` | Button names match the actual screenshots. |
| 3.3 | Confirmed | `App/diagnostics_workbench_ui.py:4775` | Run Details is present on Build. |
| 4.1 | Confirmed | `App/diagnostics_workbench_ui.py:2822` | Data Folder, Output Folder, Run Name. The selected folder is named Results. |
| 4.2 | Confirmed | `App/diagnostics_workbench_ui.py:4538` | Data Folder optional, other two fields required. |
| 4.3 | Confirmed | `App/run_diagnostics.py:1682` | Run name is normalized for filenames, then timestamped. |
| 4.4 | Confirmed | `App/diagnostics_workbench_ui.py:3011` | Three-input scan summary observed. |
| 5.1 | Confirmed | `App/diagnostics_workbench_ui.py:3312` | All Available selects found inputs. Clear deselects. |
| 5.2 | Confirmed | `App/diagnostics_workbench_ui.py:3901` | Choose / Change are selected from input state. |
| 5.3 | Confirmed | `App/diagnostics_workbench_ui.py:3903` | Folder-specific labels match. |
| 5.4 | Confirmed | `App/diagnostics_workbench_ui.py:4203` | Capture panels use Browse. |
| 5.5 | Confirmed | `App/diagnostics_workbench_ui.py:4560` | At least one selected module required. |
| 5.6 | Confirmed | `App/diagnostics_workbench_ui.py:4000`, `App/diagnostics_workbench_ui.py:4625` | Calendar and documented date formats are supported. |
| 5.7 | Confirmed | `App/diagnostics_workbench_ui.py:131`, `App/diagnostics_workbench_ui.py:3180` | Status wording and automatic review completion match. |
| 5.8 | Confirmed | `App/diagnostics_workbench_ui.py:2953`, `App/diagnostics_workbench_ui.py:3137` | Scan and manual-input guidance fits the code. |
| 5.9 | Confirmed | `App/run_diagnostics.py:1393`, `App/run_diagnostics.py:1626` | Primary extensions and Basic-export guidance match. |
| 5.10 | Confirmed | `App/run_diagnostics.py:1403` | Report date labels match. |
| 5.11 | Confirmed | `App/run_diagnostics.py:1413` | Optional input labels match. |
| 5.12 | Confirmed | `App/diagnostics_workbench_ui.py:4167`, `App/diagnostics_workbench_ui.py:4225` | Both capture headings match. |
| 5.13 | Confirmed | `App/diagnostics_workbench_ui.py:4423`, `App/diagnostics_workbench_ui.py:4494` | Positive hardware values and automatic CPU/disk detection match. |
| 5.14 | Confirmed | `App/diagnostics_workbench_ui.py:4335`, `App/run_diagnostics.py:1290` | Checkbox label and VM flag match. |
| 5.15 | Confirmed | `App/diagnostics_workbench_ui.py:4582` | Separate capture file and hardware fields are checked. |
| 5.16 | Confirmed | `App/run_diagnostics.py:1144` | Collection dates are optional. |
| 5.17 | Confirmed | `App/diagnostics_workbench_ui.py:4270`, `App/diagnostics_workbench_ui.py:4404`, `App/diagnostics_workbench_ui.py:4444` | Re-detect, Browse, and Remove callbacks confirm the descriptions. |
| 5.18 | Confirmed | `App/run_diagnostics.py:1033` | Perfmon detection/conversion uses the Windows tool. |
| 5.19 | Confirmed | `Lib/Analysis/filldb_perf_log.py:375`, `App/run_diagnostics.py:1525` | Raw-log conversion, CSV passthrough, and optional dates match. |
| 6.1 | Confirmed | `App/run_diagnostics.py:1953` | Module execution is sequential. |
| 6.2 | Confirmed | `App/diagnostics_workbench_ui.py:5279`, `App/diagnostics_workbench_ui.py:5542` | Log view and output-folder opening match. |
| 6.3 | Confirmed | `App/diagnostics_workbench_ui.py:5531` | Cancel terminates the engine. Guide warns about incomplete outputs. |
| 6.4 | Confirmed | `App/run_diagnostics.py:1689` | Actual folder name matches the guide description. |
| 6.5 | Confirmed | `App/run_diagnostics.py:1602`, `App/run_diagnostics.py:1261` | Subfolders and optional second-capture outputs match. |
| 6.6 | Confirmed | `App/run_diagnostics.py:1548` | FillDB produces DOCX and PNG, with no Excel workbook promised. |
| 6.7 | Confirmed | `App/run_diagnostics.py:1837`, `App/run_diagnostics.py:1983` | Manifest and run-log paths match. |
| 7.1 | Confirmed | `Launchers/Run Diagnostics Workbench.cmd:98`, `App/diagnostics_workbench_ui.py:4538` | Troubleshooting rows correspond to startup and validation paths. |
| 7.2 | Confirmed | `App/run_diagnostics.py:1862`, `App/diagnostics_workbench_ui.py:5505` | Both diagnostics filename patterns match. |
| 8.1 | Confirmed | `App/run_diagnostics.py:1930`, `Tests/test_security_guardrails.py:90` | Guide describes local file analysis. No runtime network-monitor claim is made. |
| 8.2 | Confirmed | `Launchers/Run Diagnostics Workbench.cmd:72` | Packages are installed using the private interpreter. |

## Added And Omitted Controls

Dark mode guidance was added at Duncan's explicit request. The actual control
is in `App/diagnostics_workbench_ui.py:2261`, the callback at line 2283, and
the build-time disabling at line 2523. Figure 4 shows the actual dark view.

The app also has Back, Start over, and a diagnostics keyboard shortcut. The
guide describes the main analysis workflow without expanding into a
diagnostics manual. No application features were added or changed.

## Checks And Limits

### Final Document Status

Following Duncan's approval, the document version is now 1.0, without Draft.
The Draft prefix in the document-control notes and the DRAFT watermark were
removed. Word and PDF were saved again. A scan of Word content, headers,
footers, and document properties found no remaining draft references. The
exported document-control page was visually checked, and the guide remains
16 pages. This changes documentation status only; it does not change the
application version or publish a GitHub release. Earlier draft-stage checks
below describe the state when those checks were originally performed.

### Class Purpose And Project Status

At Duncan's request, Section 1.1 now explains that the Workbench is a completed,
purpose-built class demonstration, not an application under ongoing active
development. It encourages class members to add modules and extend their own
copy or fork, including continued AI-assisted development. It identifies the
GitHub repository as read-only for class members and links to the repository
and its Issues tab for problems and enhancement requests. Further work is
considered in response to those requests; no ongoing roadmap is promised.
The repository URL was taken from the Master Class repository's origin remote.

The README uses the same purpose and status wording. Its setup, FillDB input
and output descriptions, dependency cooldown terminology, dark mode note,
and guide links were also aligned with the current user guide. Word and PDF
were refreshed; the purpose note and contents were visually checked. The
guide remains 16 pages. No commit, push, or repository-permission change was
made; the README update is local until published.

The purpose note was subsequently moved out of Document Control into Before
You Start as Section 1.1; Requirements is now Section 1.2. The existing workflow
graphic and its caption were moved into Section 3. The first-launch graphic is
now Figure 1 and the workflow graphic Figure 2, maintaining reading order.
Contents, figure captions, and PDF were refreshed. The contents, introduction,
and workflow pages were visually checked after these changes. Existing purpose
wording, repository/Issues hyperlinks, screenshots, and dark mode guidance
were retained. The guide still has 16 pages.

### Terminology Review

Reviewed the complete guide text, including the contents, tables, captions,
and Word headers/footers, against the Master Class application, collection
task definitions, launcher, build scripts, and presentation security slide.
The following writer-introduced wording was corrected:

| Previous wording | Corrected wording | Basis |
|---|---|---|
| Dependency Controls | Dependency Cooldowns | Duncan's terminology, presentation's Dependency cooldown, and `Build/refresh-lockfile.ps1` |
| Code Sweeps And Release Checks | Code Sweeps | Duncan's terminology and `Build/run_code_sweep.py` |
| BigFix NFR requirements | BigFix requirements | Perfmon description in `App/diagnostics_workbench_ui.py` |

The dependency paragraph now explicitly uses dependency cooldowns. The
private Python environment wording is supported by the launcher's `.venv`
setup and the presentation; it was not renamed. Module names, navigation,
buttons, status labels, date and hardware fields, optional-input labels,
task names, utility names/switches, and output names were checked against
their corresponding source definitions. No additional invented control
names were identified in that review. No application code was changed.
Contents fields and the Word PDF export were refreshed after the edits.

### Security Section Update

Section 8 was expanded using the presentation's "Built to Be Safe to Run"
backup slide (slide XML 43, displayed slide 42) and the Master Class
implementation. It now covers air-gapped analysis after setup, private
packages, dependency pinning and the seven-day cooldown, code sweeps,
SBOMs, license notices, and SHA-256 checksums.

| Added content | Basis |
|---|---|
| Offline analysis and separate package setup | `Tests/test_security_guardrails.py`, `Launchers/Run Diagnostics Workbench.cmd` |
| Pinned runtime packages and seven-day update cooldown | `requirements.txt`, `pyproject.toml`, `Build/refresh-lockfile.ps1` |
| Automated code sweeps and supported secret scanning | `Build/run_code_sweep.py` |
| Runtime SBOM, third-party notices, manifest, and checksums | `Build/package_release.ps1` |
| Source inspection under the MIT license | `LICENSE` |

The existing security guardrail tests passed (2 tests). No new full code
sweep was run for this documentation edit. The guide describes the
workflow, without claiming a fresh clean scan or guaranteed risk removal.
Setup or rebuilding the environment still requires package-source access.
The guide remains 16 pages after updating its fields and Word PDF export.

### Installation And Collection Update

At Duncan's request, Section 2 now includes uv installation immediately
after Python, using `winget install --id=astral-sh.uv -e`, followed by
reopening PowerShell and checking `uv --version`. The Windows command was
verified against [Astral's installation instructions](https://docs.astral.sh/uv/getting-started/installation/).
The earlier note saying no separate uv installation was needed was removed.
The launcher description still reflects its actual pip-based setup.

Section 2.5 adds a brief collection table for the three modules, with exact
task names, prerequisites, capture highlights, and the FillDB restart and
automatic-disable warning. Names and behavior were checked against the
Master Class `.bes` definitions under `Tasks and Analyses`,
`Docs/Data_Collection.md`, and the Session 3 lab guide in `Docs/Lab Guide`.
The lab guide remains the source for collection screenshots and detailed
console instructions. The Results folder name and structure are retained.

These additions were made in the open Word document to preserve existing
unsaved edits. The contents and requirements table were updated, and the
PDF was refreshed. Visual checks of pages 3 through 6 confirmed that the
new material fits without table splits or overlaps. The guide is 16 pages.

### Earlier Guide Checks

- Read the complete guide text and checked the listed claims against source.
- Launched the actual application through its Windows launcher.
- Captured Figures 3 to 8 from the real application and File Explorer.
- Kept PNG captures at native resolution and at least 1440 pixels wide.
- Used the full Results dataset and the supplied RAM/VM values.
- Retained the editable guide's styles, version, and watermark.
- Updated Word fields and exported the PDF with Microsoft Word.
- Rendered all PDF pages using Windows' PDF renderer for visual inspection.
- Checked the final DOCX for placeholder descriptions, the removed URL, and
  the rejected font.
- Word's built-in Placeholder Text style metadata was retained. No visible
  placeholder copy or screenshot placeholder descriptions remain.
- No fresh dependency installation, raw-log analyzer run, second-capture
  build, cancellation interruption, or published-release inspection was
  performed. Those behaviors were checked in source where relevant.
- No commits or pushes were made.
