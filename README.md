# Master Class Diagnostics Workbench

Automated performance and configuration analysis for BigFix.

The Workbench takes data collected from a BigFix deployment, runs the three
Master Class analysis modules against it, and writes each module's Mini Report,
Infographic and Excel workbook into one run folder.

| Module | What it needs | What it writes |
|---|---|---|
| Client Performance Loop Analysis | An Agent Performance Counters export (XML or CSV). Optional: the Top 10 evaluation capture, the UDP notification capture and a `Deployment_Information` folder. | Mini Report, Infographic, Excel |
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
- Microsoft Word and Excel are the preferred and tested applications for
  opening the Mini Reports and Excel workbooks. LibreOffice and other
  compatible applications may work, but they have not been fully vetted.

The Workbench installs its own packages into a private `.venv` folder next
to the code. Your Python installation is not changed.

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
| `Build/` | The release and template builders, including `build_lab_guide.py` for the Student Lab Guide |
| `Templates/` | The Word style template the Mini Reports take their styles from, and the lab guide template |
| `SampleData/` | The fictional sample capture |
| `Utilities/` | Helpers the data collection uses: `MXFillDBPerf.exe` and `query_properties.ps1`. The lab guide screenshot capture scripts |
| `Launchers/` | The Windows launcher |
| `Docs/` | Guides for attendees and the live lab collection workflow. `Lab_Guide_Assets/` holds the lab guide screenshots |

## Class Materials

- [Getting Started](Docs/Getting_Started.md) explains the Workbench workflow.
- [Data Collection](Docs/Data_Collection.md) explains the live collection tasks
  and the files each module reads.
- [Student Lab Guide](Docs/Master_Class_Lab_Guide.docx) contains the three
  standalone exercises for the Master Class.

## License

MIT. See [LICENSE](LICENSE) and [NOTICE](NOTICE). The bundled fonts keep
their own licenses, listed in NOTICE.
