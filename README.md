# Master Class Diagnostics Workbench

Automated performance and configuration analysis for BigFix.

The Workbench takes data collected from a BigFix deployment, runs three
analysis modules against it, and writes each module's Mini Report,
Infographic and Excel workbook into one run folder. It was built for the
2026 BigFix Master Class so that attendees can run the same analysis on
their own deployments after the session.

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
- Python 3.11 or newer, installed with "Add Python to PATH".
- Microsoft Edge or Google Chrome. The Infographic is rendered by the
  installed browser in the background.

The Workbench installs its own packages into a private `.venv` folder next
to the code. Your Python installation is not changed.

## Quick Start

1. Extract the release zip to a folder you can write to.
2. Double-click `Launchers\Run Diagnostics Workbench.cmd`. The first run
   creates the private environment and installs the packages, which takes
   about a minute.
3. On **Folders**, set the Data Folder to `SampleData\BigFix Master Class
   2026`, choose an Output Folder and enter a Run Name.
4. On **Modules**, keep all three modules selected. Open **Details** on the
   Client Performance Loop Analysis row and enter the Report Start and End
   dates.
5. On **Build**, press **Build**. When the three modules read Done, press
   **Open Output**.

[Getting Started](Docs/Getting_Started.md) walks through each step and
explains the outputs. [Data Collection](Docs/Data_Collection.md) describes
the files each module needs and where they come from.

## Layout

| Folder | Contents |
|---|---|
| `App/` | The desktop app and the engine that runs the modules |
| `Get/` | The three analysis modules |
| `Inject/` | The chart injector that assembles the PerfMon Mini Report |
| `Lib/` | Shared code: input handling, analysis helpers, chart and workbook themes |
| `Assets/` | The Infographic chart template and the app icon |
| `Fonts/` | Bundled open-source fonts (Inter, Roboto) |
| `Templates/` | The Word style template the Mini Reports take their styles from |
| `SampleData/` | The fictional sample capture |
| `Utilities/` | Helpers the data collection uses: `MXFillDBPerf.exe` and `query_properties.ps1` |
| `Launchers/` | The Windows launcher |
| `Docs/` | Guides for attendees and for maintaining the project |
| `Tests/` | The test suite |
| `Build/` | Developer tooling: code sweep, packaging, release notices. Not shipped. |

## Development

```powershell
.venv\Scripts\python -m pytest -q      # the suite
.\Build\run-code-sweep.ps1             # lint, tests, security, licenses, SBOM
.\Build\package_release.ps1            # the release zip, checksum and SBOM
```

See [Testing](Docs/Testing.md), [Security](Docs/Security.md) and the
[Release Process](Docs/Release_Process.md). Changes are recorded in
[CHANGELOG.md](CHANGELOG.md).

## License

MIT. See [LICENSE](LICENSE) and [NOTICE](NOTICE). The bundled fonts keep
their own licenses, listed in NOTICE. Third-party package licenses ship with
each release as `THIRD_PARTY_NOTICES.md`.
