# Master Class Diagnostics Workbench: User Guide Design Handoff

Status: Historical. This design handoff is complete and the guide has shipped. Use the existing user guide as the document master.

## Assignment

Create **Master Class Diagnostics Workbench User Guide** using the same
design as the existing main user guide. Reuse its Word document as the
design master and adapt the relevant content for the Master Class application.
The result should look like another guide in the same document family.

The supplied design master is:

`Docs/User Guide/Source_User_Guide_2.0.docx`

This is an unchanged copy of the main user guide, renamed for the handoff.
It is reference material, not the finished Master Class guide. Start from
a working copy to retain its actual styles and layouts, then remove the
source body content and figures. Write the new body from the Master Class
content requirements below, using the source's formatting.

Audience: a BigFix practitioner using the application for the first time.
Explain how to launch the application, configure a run, analyze collected
files, and open the results. Use short numbered procedures, the exact
on-screen labels, and screenshots of the Master Class application.

Save the editable Word guide and its matching PDF under `Docs/User Guide/`.
The guide must be usable on its own, without a separate lab guide. Classroom
exercises, collection task walkthroughs, and lesson timing are outside scope.

The design instructions, source-file lists, reuse map, and exclusions in
this handoff are notes for Design. They do not belong in the finished user
guide. The original source document is an authoring reference and is not
part of the attendee-facing guide deliverables.

## Required Design

Preserve these elements from `Source_User_Guide_2.0.docx`:

| Element | Instruction |
|---|---|
| Cover | Retain the cover composition, title hierarchy, alignment, and spacing. Replace the product title with Master Class Diagnostics Workbench and retain User Guide as the document type. |
| Page setup | Retain the source's US Letter portrait pages, margins, section layouts, and header/footer positioning. |
| Typography | Use Aptos throughout. Retain the source's sizes, weights, colors, paragraph spacing, and heading hierarchy. Update the existing Word styles. |
| Section openings | Retain the source's section-number treatment, heading placement, and page-break approach. Renumber the shortened guide consistently. |
| Body copy and procedures | Retain body text, numbered-step, bullet, inline emphasis, and path formatting. |
| Tables | Retain the source's table styles, header treatments, cell spacing, borders, and text hierarchy. |
| Screenshots and figures | Retain screenshot placement, sizing conventions, caption treatment, figure numbering, and any applicable annotations. Replace application screenshots with current Master Class screens. |
| Headers and footers | Retain layout and page-number treatment. Update product-specific wording and remove the corporate website URL. This is not official vendor documentation. |
| Contents and references | Retain the source's navigation and cross-reference treatment where used. Update fields, numbering, and references after editing. |

The actual Word document controls the design. Its inspected styles include
Aptos 11 pt body text, 24 pt first-level headings, 18 pt second-level headings,
and dark blue heading colors. These details help identify the reference;
they are not a replacement for using its complete styles, theme, and layouts.
Use Aptos for the headings as well as the body text.

Replace the source product name with **Master Class Diagnostics Workbench**
in the new guide, including the cover, running text, headers, and footers.
Remove source-specific organization and service wording, website links,
customer-delivery instructions, and obsolete figure references. Check text
boxes, hyperlinks, document properties, comments, and tracked changes as
well as the visible pages. Preserve the design of these elements where
applicable, and use only wording relevant to the Master Class guide.
Reuse the visual design while updating the application-specific content.
Do not introduce a different cover, palette, type system, or table design.

Use the same document design for the shorter scope. Do not pad the guide
with sections belonging to the source application's larger workflow.

## Sources For The Writer

The following files exist in the Master Class repository and were reviewed
for this brief:

| File | Use |
|---|---|
| `Docs/User Guide/Source_User_Guide_2.0.docx` | Required visual master and source of reusable content. |
| `Docs/Getting_Started.md` | Existing launch, workflow, output, and troubleshooting copy. |
| `Docs/Data_Collection.md` | Input descriptions and collected-data folder layout. |
| `README.md` | Product overview and supported environment. |
| `Launchers/Run Diagnostics Workbench.cmd` | Actual first-launch behavior and package installation. |
| `App/diagnostics_workbench_ui.py` | Current labels, required fields, status changes, and Cancel behavior. |
| `App/run_diagnostics.py` | Supported input formats, output names, and run-folder layout. |

Use the supplied content requirements below to resolve differences between
the existing Markdown documents and the current application. Do not copy
claims about class materials or release contents from the README into the
user guide.

## Reuse From The Existing User Guide

Use `Docs/User Guide/Source_User_Guide_2.0.docx` for both the design and the
sections identified below. Preserve the formatting of retained content and
edit its instructions to match the Master Class application.

| Source section | Reuse instruction |
|---|---|
| Before You Start / 1.1 Requirements | Reuse the introductory structure and requirements table format. Use the Master Class requirements below. |
| Setting Up / 2.1 Install Python | Adapt the Windows Python instructions. Omit macOS and uv installation instructions. |
| 2.2 Launch The Workbench | Reuse the portable-folder and first-launch explanation. Replace the launcher and package installation details. |
| 2.3 If Setup Fails | Adapt the Python, write-access, and incomplete-environment troubleshooting. |
| Run Individual Modules / 4.2 Run One Or More Modules | Reuse the sequence: select folders, select modules, resolve missing inputs, build, open outputs. Rewrite the fields and controls. |
| Step 1: Folders And Run Details | Use Data Folder, Output Folder, and Run Name. |
| Step 2: Modules / 6.4 Statuses | Adapt the module selection and status explanations to the current application. |
| 7.1 Output Terms / 7.2 Build Progress | Reuse the output definitions and progress explanation, with the Master Class outputs below. |
| Troubleshooting | Use a short problem/action table for the issues listed below. |
| 12.1 Local Processing / 12.2 The Private Python Environment / 12.3 Data Handling Rules | Adapt the explanation of local analysis, isolated packages, and confidential handling. Describe this launcher's pip installation accurately. |

Exclude the source application's combined-report workflow, run-mode
selection, scoring-workbook review, validation step, Update Run procedure,
delivery gates, unrelated modules, and service-specific policies or branding.

## Guide Structure And Content

Retain the source's section organization for the material that applies:

1. Before You Start, including requirements and the three-module overview.
2. Setting Up, including Python, launch, and setup troubleshooting.
3. Workbench Workflow, with the Folders, Modules, Build, and Open Output sequence.
4. Step 1: Folders And Run Details.
5. Step 2: Modules, including statuses and the three module Details views.
6. Step 3: Build, including progress, logs, and output definitions.
7. Troubleshooting.
8. Security And Data Handling.

The content blocks below supply the facts to write into those sections.
Their labels organize this brief; they do not replace the source guide's
heading styles or section-opening design. Put module-specific input and
output tables in Step 2 and Step 3 respectively. A separate module-reference
appendix is unnecessary for this basic guide.

### 1. What The Workbench Does

Suggested opening copy:

> The Master Class Diagnostics Workbench analyzes files collected from a
> BigFix deployment. Select one or more analysis modules to create Mini
> Reports, Infographics, and supporting Excel workbooks in a timestamped
> run folder.

List the three modules using these exact names:

- **Client Performance Analysis**: client evaluation performance,
  notification coverage, and client CPU and hashing settings.
- **Perfmon Infrastructure Analysis**: Windows performance counters
  assessed against BigFix requirements.
- **FillDB Performance Analysis**: FillDB processing performance.

Explain that users need collected files before running an analysis. For
input collection details, direct them to `Docs/Data_Collection.md`.

### 2. Requirements And Launch

Include these requirements:

- Windows 11, the documented environment for this application.
- Python 3.12 or newer, available through the Python launcher or PATH.
- Microsoft Edge or Google Chrome for rendering Infographics.
- Microsoft Word and Excel as the preferred applications for opening outputs.
- A writable application folder and output location.
- Input files for the selected module.

Use this launch procedure:

1. Place the supplied application folder in a writable local location.
2. Keep its folder structure intact.
3. Open `Launchers` and double-click **Run Diagnostics Workbench.cmd**.
4. On first launch, acknowledge the notice and allow package installation
   to finish.
5. Continue when the application opens at **Folders**.

Explain that the launcher creates a private `.venv` folder and installs
packages from `requirements.txt` using pip. The first setup needs access to
the package source. Later launches use the existing environment. No separate
uv setup is required by this launcher.

Avoid a guaranteed setup time. It depends on the computer and package access.

### 3. Step 1: Folders

| On-screen label | Explain |
|---|---|
| Data Folder | Optional. Select the folder containing the collected files to scan for module inputs. Leave it blank to choose inputs individually on Step 2. |
| Output Folder | Required. Select a writable location for the run folders. |
| Run Name | Required. Enter a recognizable name. It is used in the run-folder name and output filenames. Names over 60 characters are shortened and a warning shows. |

Tell the user to select **Next** after completing the required fields.
Explain that the scan summary reports inputs found for the three modules.
An input missing for an unselected module does not need to be supplied.

Use a clearly identified example run name, such as `Example_Server`.
Use a folder the reader selects. Do not prescribe a sample-data path or
fixed collection dates as prerequisites for using the application.

### 4. Step 2: Modules

Use this procedure:

1. Select the checkbox for each module to run.
2. Open **Details** for each selected module.
3. Check the selected input and complete the required values.
4. Resolve **Needs A File** and **Needs Review** for selected modules.
5. Select **Next**.

Explain **All Available** and **Clear**. All Available selects modules with
available inputs. Clear deselects all modules. Unselected modules are skipped.

For the Client Performance and FillDB input tables, the action is **Choose**
when no valid input is selected and **Change** when an input is already found.
Folder inputs use **Choose folder** or **Change folder**. Perfmon capture
panels use **Browse**.

| Status | Explanation |
|---|---|
| Found | The input was found. A selected module has its required review values filled in. |
| Needs A File | A usable required input has not been selected. Choose the input in Details. |
| Needs Review | Required values are incomplete. Fill them in through Details. The status updates automatically. |
| Scanning | Input detection is in progress. |
| Not Scanned | Inputs have not yet been scanned. Select a Data Folder or choose the input manually. |

There is no run-mode selection or Mark Reviewed button in this application.

Tell users to select at least one module. For date fields, use the calendar
control or enter `MM-DD-YYYY`. Where a time is needed, use
`MM-DD-YYYY HH:MM`. A Found status indicates that the required review values
are present. Next and Build also validate their formats.

### 5. Module Details

Keep this to a short subsection or table for each module.

| Module | Required input and values | Optional inputs |
|---|---|---|
| Client Performance Analysis | Client Loop XML/CSV capture or Client Performance Counters Basic export. Supported primary file extensions are `.xml`, `.csv`, `.xlsx`, `.xlsm`, and `.xls`. Enter Report Start Date and Report End Date for the collection being analyzed. The Advanced export is unsupported. | Deployment_Information folder, Top 10 slowest evaluations, and UDP notifications. |
| Perfmon Infrastructure Analysis | Capture 1 `.blg` file. CPUs, Disks, and RAM must contain positive whole numbers. CPUs and disks are detected from the capture. Enter RAM in GB manually and set Virtual machine to match the server. | Capture 2 `.blg`, with its own positive CPU, disk, and RAM values. Collection start/end can be left blank. |
| FillDB Performance Analysis | A FillDB performance log or analyzed CSV. Keep raw rollover logs together so the analyzer can combine them. | Collection start/end. |

For Perfmon, use the visible capture headings **Capture 1 - BigFix Root
Server** and **Capture 2 - SQL Server host**. Explain **Re-detect**, **Browse**,
and **Remove** for the second capture when present. Capture 2 must be a
different file from Capture 1. An unchecked Virtual machine checkbox means
the capture is being treated as a physical server.

Explain that Perfmon analysis requires Windows `relog.exe`. Raw FillDB logs
are processed using the bundled `Utilities/MXFillDBPerf.exe`. An analyzed
FillDB CSV does not need that conversion.

### 6. Step 3: Build

1. Check the run name, selected modules, and output folder in **Run Details**.
2. Select **Build**.
3. Monitor the module statuses. Modules run sequentially. Large Perfmon
   captures can take several minutes.
4. Use **View Logs** to inspect progress or errors.
5. Select **Open Output** to open the run folder.

Describe **Cancel** as requesting cancellation of the running build. The
current UI terminates the engine process. Do not promise that the current
module finishes or that canceled outputs are complete.
The engine-process detail explains the behavior for the writer. The finished
guide only needs to explain cancellation and potentially incomplete outputs.

### 7. Outputs

Explain that each build creates a folder named from the run name and a
timestamp. The selected modules write into these subfolders:

| Module | Subfolder | Main outputs |
|---|---|---|
| Client Performance Analysis | `Client_Loop` | Mini Report (`.docx`), Infographic (`.png`), Excel workbook (`.xlsx`). |
| Perfmon Infrastructure Analysis | `Perfmon` | Mini Report (`.docx`), Excel workbook (`.xlsx`), and a `_Perfmon_Charts` folder with the scorecard and counter charts. A second capture adds its own workbook and chart folder. |
| FillDB Performance Analysis | `FillDB_Performance` | Mini Report (`.docx`) and Infographic (`.png`). |

Use short definitions: Mini Report is the narrative analysis, Infographic
is the visual summary, and Excel contains supporting data and detail.

A successful run also writes a run log and manifest. For troubleshooting a
slow or unresponsive run, retain the log and any generated
`*_Run_Diagnostics.json` and `*_UI_Diagnostics.json` files. Do not imply that
failed or canceled runs contain every expected file.

### 8. Troubleshooting And Data Handling

| Problem | Action to include |
|---|---|
| Launcher cannot find a supported Python version | Install Python 3.12 or newer and make it available through the Python launcher or PATH. |
| First setup fails | Read the launcher error. Check write access and package access. For incomplete setup, close the application, remove its `.venv` folder, and launch again. |
| Needs A File | Select the module, open Details, and choose a supported input. |
| Needs Review | Enter Client Performance report dates or complete Perfmon CPU, disk, and RAM values. |
| Build reports an error | Open View Logs and inspect the reported input or processing error. |
| Infographic is missing | Confirm that Edge or Chrome is installed and inspect View Logs. |
| Perfmon input cannot be processed | Confirm Windows, a valid `.blg`, and complete hardware values. |

State that analysis reads collected files locally. Collection is a separate
activity. Treat captures and generated files as confidential, and use
sanitized examples in screenshots. Avoid claims about customer-account
requirements, approved delivery policies, or guaranteed absence of sensitive
information in all inputs.

## Screenshots

Capture screenshots from the current Master Class application to replace
the corresponding source figures. The supplied Word reference provides
their design treatment, not the current application images. Capture:

1. Folders with the three fields populated.
2. Modules with the three current module names.
3. Client Performance Details showing the input and report dates.
4. Perfmon Details showing the capture and hardware controls.
5. Build after a successful run.
6. One generated run folder and representative output.

Use one consistent example throughout, with dates and hardware values from
the capture used for screenshots. Follow the source guide's caption style,
numbering, and placement. Keep field labels readable and use sanitized data.

## Acceptance Criteria

- The cover and representative interior pages match the supplied source
  guide's design when compared side by side.
- Typography, section openings, tables, screenshots, captions, headers,
  footers, and page numbering follow the document master.
- Product wording identifies the Master Class Diagnostics Workbench.
- Instructions match the current Master Class application and cover only
  its three modules and three-step workflow.
- No source-only pages, procedures, figures, service wording, website links,
  or authoring notes remain in the finished guide.
- Figures show the current application and use one consistent example.
- Word and PDF versions have matching layout, current page references,
  readable figures, and no clipped text or unfinished placeholders.
- The guide can be followed without a separate lab guide.

Before release, walk through the guide using the application package being
distributed. Confirm every label, required field, input, and output against
that package, and compare the finished guide with the supplied design master.

The functional instructions in this handoff have been checked against the
current source code and launcher. This does not replace a walkthrough of the
finished guide against the distributed application or a visual review of the
finished Word and PDF files.
