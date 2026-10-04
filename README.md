# Master Class Diagnostics Workbench

Automated performance and configuration analysis for BigFix.

The Workbench takes data collected from a BigFix deployment, runs the three
Master Class analysis modules against it, and writes each module's Mini Report,
Infographic and Excel workbook into one run folder.

| Module | What it needs | What it writes |
|---|---|---|
| Client Performance Analysis | A Client Performance Counters export (XML or CSV). Optional: the Top 10 evaluation capture, the UDP notification capture and a `Deployment_Information` folder. | Mini Report, Infographic, Excel |
| Perfmon Infrastructure Analysis | A PerfMon `.blg` capture from a BigFix server, with a second capture optional. | Mini Report, Infographic, Excel |
| FillDB Performance Analysis | The FillDB performance logs, or the analyzer's CSV. | Mini Report, Infographic |

A fictional sample capture ships under `SampleData`, so the Workbench runs
end to end before any data is collected.

## Requirements

- Windows 10 or 11. PerfMon analysis uses `relog.exe`, which ships with
  Windows.
- Python 3.12 or newer, installed with "Add Python to PATH".
- Microsoft Edge or Google Chrome. The Infographic is rendered by the
  installed browser in the background.
- Microsoft Word and Excel are the preferred and most extensively tested
  applications for opening the Mini Reports and Excel workbooks. LibreOffice
  has been tested successfully as an alternative, but it has received less
  compatibility coverage than Word and Excel.

The Workbench installs its own packages into a private `.venv` folder next
to the code. Your Python installation is not changed. Every package version
is pinned and at least seven days old.

## Using The Workbench

See [Getting Started](Docs/Getting_Started.md) for the application workflow
and outputs. [Data Collection](Docs/Data_Collection.md) describes the files
each module needs, where they come from, and how the live labs run the
corresponding BigFix collection tasks first.

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
| `SampleData/` | The fictional sample capture |
| `Utilities/` | Helpers the data collection uses: `MXFillDBPerf.exe` and `query_properties.ps1` |
| `Launchers/` | The Windows launcher |
| `Docs/` | Guides for attendees, the Student Lab Guide, and the live lab collection workflow |

## Class Materials

- [Getting Started](Docs/Getting_Started.md) explains the Workbench workflow.
- [Data Collection](Docs/Data_Collection.md) explains the live collection tasks
  and the files each module reads.
- [Student Lab Guide](Docs/MC_Denver_2026_Performance_Configuration_Analysis_Lab_Guide_1032026.docx)
  walks through the 20 minute lab: collect the data in the BigFix console, run
  the Workbench, and read the Client Performance and Perfmon outputs. FillDB is
  a bonus round in the appendix.

## License

MIT. See [LICENSE](LICENSE) and [NOTICE](NOTICE). The bundled fonts keep
their own licenses, listed in NOTICE.
