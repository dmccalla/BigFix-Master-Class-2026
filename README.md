# Master Class Diagnostics Workbench

Repo for my Master Class presentation on the Automation of BigFix Performance and Configuration Analysis.

Automated performance and configuration analysis for BigFix. The Workbench
runs three analysis modules against data collected from a BigFix deployment
and writes each module's Mini Report, Infographic, and Excel outputs to one
run folder.

| Module | Input | Outputs |
|---|---|---|
| Client Performance Loop Analysis | Agent Performance Counters export (XML or CSV), plus optional Top 10 evaluation and UDP notification captures | Mini Report, Infographic, Excel |
| Perfmon Infrastructure Analysis | PerfMon `.blg` capture | Mini Report, Infographic, Excel |
| FillDB Performance Analysis | FillDB performance log or its analyzed CSV | Mini Report, Infographic |

Windows only. PerfMon analysis uses `relog.exe`, which ships with Windows.

## Layout

| Folder | Contents |
|---|---|
| `App/` | The desktop UI and the run engine (`run_diagnostics.py`) |
| `Get/` | The three analysis modules |
| `Inject/` | The PerfMon chart injector that assembles the PerfMon Mini Report |
| `Lib/` | Shared code: input handling, chart and workbook themes, design system |
| `Assets/` | Chart template for the Infographic outputs |
| `Fonts/` | Bundled open-source fonts (Inter, Roboto) |
| `Templates/` | Word style template the Mini Reports clone their styles from |
| `SampleData/` | A fictional sample capture so the Workbench runs without a deployment |
| `Tasks and Analyses/` | The BigFix tasks and analysis that collect the input data |
| `Utilities/` | Standalone helpers used by the collection tasks |
| `Tests/` | Test suite (`python -m pytest`) |

## Running

Double-click `Launchers\Run Diagnostics Workbench.cmd`. The launcher finds
Python 3.11 or newer, creates a private `.venv` for the Workbench, installs
its packages there, and opens the app.

To run the engine without the UI:

```
python App\run_diagnostics.py --config <config.json> --yes
```

The config format is documented at the top of `App/run_diagnostics.py`.

## License

MIT. See `LICENSE` and `NOTICE`.
