# Master Class Diagnostics Workbench

Automated performance and configuration analysis for BigFix.

The Workbench takes data collected from a BigFix deployment, runs the selected
Master Class analysis modules, and writes Mini Reports, Infographics, and
supporting Excel workbooks where applicable into a timestamped run folder.

## Purpose And Project Status

Built for the Master Class, the Workbench is a completed class demonstration,
not an application under ongoing active development. It is intended to inspire
class members and showcase the possibilities of automation.

Class members are encouraged to add their own modules and extend the Workbench.
Much of the application was built with AI assistance, and you can continue
using AI to develop your own extensions to the framework.

Class members have read-only access to the GitHub repository:
[https://github.com/dmccalla/BigFix-Master-Class-2026](https://github.com/dmccalla/BigFix-Master-Class-2026).
Make changes in your own copy or fork. Report issues and request enhancements
through the repository's [Issues tab](https://github.com/dmccalla/BigFix-Master-Class-2026/issues).
Further work on the class version will be considered
in response to those requests.

## Analysis Modules

| Module | What it needs | What it writes |
|---|---|---|
| Client Performance Analysis | A Client Performance Counters export (XML or CSV). Optional: the Top 10 evaluation capture, the UDP notification capture and a `Deployment_Information` folder. | Mini Report, Infographic, Excel |
| Perfmon Infrastructure Analysis | A PerfMon `.blg` capture from a BigFix server, with a second capture optional. | Mini Report, Infographic, Excel |
| FillDB Performance Analysis | The FillDB performance logs, or the analyzer's CSV. | Mini Report, Infographic |

For FillDB, keep raw logs and their rollover files together in one folder.
Select any log in the set; the Workbench combines the related logs in
chronological order and runs `MXFillDBPerf` automatically. An existing CSV
must have been generated with `--healthcheck`. The analyzed data is included
in the Mini Report; no Excel workbook is needed because `MXFillDBPerf` does
not produce a separate dataset for sorting or filtering.

The repository ships small FillDB and Perfmon samples under `SampleData`.

The lab sample data the Student Lab Guide uses, including the Client
Performance capture, is in `SampleData\BigFix Master Class 2026\Results`.
It is too large for the repository. It ships inside the release zip and as `Sample-Data-Results.zip`
on the repository's v2.0 release. To add it to a clone, extract
`Sample-Data-Results.zip` into the Workbench folder.

## Requirements

- Windows 11. PerfMon analysis uses `relog.exe`, which ships with Windows.
  FillDB analysis of raw FillDB performance logs runs `MXFillDBPerf.exe` from
  the BigFix Performance Toolkit, which ships in `Utilities`. An analyzer CSV
  needs no extra tool.
- Python 3.12 or newer, installed with "Add Python to PATH".
- uv, installed after Python. In PowerShell, run
  `winget install --id=astral-sh.uv -e`, reopen PowerShell, and check
  `uv --version`.
- Microsoft Edge or Google Chrome. The Infographic is rendered by the
  installed browser in the background.
- Microsoft Word and Excel are the preferred and most extensively tested
  applications for opening the Mini Reports and Excel workbooks. LibreOffice
  has been tested successfully as an alternative, but it has received less
  compatibility coverage than Word and Excel.

The Workbench installs its own packages into a private `.venv` folder next
to the code. Your Python installation is not changed. Runtime dependencies
are pinned. Dependency cooldowns hold back new package versions for at least
seven days before routine updates use them.

## Using The Workbench

The [User Guide (Word)](Docs/User%20Guide/Master_Class_Diagnostics_Workbench_User_Guide.docx)
and [User Guide (PDF)](Docs/User%20Guide/Master_Class_Diagnostics_Workbench_User_Guide.pdf)
cover setup, data collection, the three-step workflow, and outputs.

See [Getting Started](Docs/Getting_Started.md) for the application workflow
and outputs. [Data Collection](Docs/Data_Collection.md) describes the files
each module needs, where they come from, and how the live labs run the
corresponding BigFix collection tasks first.

### Unblock the Windows launcher

Windows may block the `.cmd` launcher because it was downloaded from the Internet. If it will not run, right-click the `.cmd` file and select **Properties**. On the **General** tab, tick the **Unblock** box at the bottom, then click **OK**. Run the launcher again. If **Unblock** is not shown, no change is needed.

![Windows launcher file Properties with the Unblock checkbox selected](Docs/User%20Guide/windows-launcher-unblock.png)

*The screenshot uses Run Diagnostics Workbench.cmd as an example. The same steps apply to this tool's `.cmd` launcher.*

Version 2.1 adds the **Dark mode** switch for light and dark appearance.
The switch is unavailable while a build is running.

## Layout

| Folder | Contents |
|---|---|
| `App/` | The desktop app and the engine that runs the modules |
| `Get/` | The three analysis modules |
| `Inject/` | The chart injector that assembles the PerfMon Mini Report |
| `Lib/` | Shared code: input handling, analysis helpers, chart and workbook themes |
| `Assets/` | The Infographic chart template and the app icon |
| `Fonts/` | Bundled open-source fonts (Inter, Roboto) |
| `Build/` | The release and template builders |
| `Templates/` | The Word style template the Mini Reports take their styles from |
| `SampleData/` | Small FillDB and Perfmon samples, and the lab sample data in the release |
| `Utilities/` | Helpers the data collection uses: `MXFillDBPerf.exe` and `query_properties.ps1` |
| `Launchers/` | The Windows launcher |
| `Docs/` | Guides for attendees and the live lab collection workflow |

## Class Materials

- [Getting Started](Docs/Getting_Started.md) explains the Workbench workflow.
- [Data Collection](Docs/Data_Collection.md) explains the live collection tasks
  and the files each module reads.

Attendees take home a package with three parts: the Workbench with its lab
sample data, the class presentation, and the Student Lab Guide, "Session 3 -
Duncan McCalla - Automated Performance and Configuration Analysis FINAL.docx".
The guide walks through the 20 minute lab: collect the data in the BigFix
console, run the Workbench, and read the Client Performance and Perfmon
outputs. FillDB is a bonus round in the appendix. The guide and the
presentation are provided separately from the Workbench because they are
updated between classes.

## License

MIT. See [LICENSE](LICENSE) and [NOTICE](NOTICE). The bundled fonts keep
their own licenses, listed in NOTICE.
