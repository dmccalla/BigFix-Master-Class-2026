# Testing

Run from the repository root with the private environment the launcher
creates.

```powershell
.venv\Scripts\python -m pytest -q
```

The suite covers the engine's input discovery and validation, the three
modules' parsers and chart rules, the Word and Excel theme helpers, the
version and changelog agreement, the network and shell guardrails, the
em-dash ban, and the banned-strings guard that keeps this tree free of
references to any other project.

## Before A Release

The full gate, which also runs the suite:

```powershell
.\Tools\run-code-sweep.ps1
```

## Checking The App By Hand

Launch the app, point the Data Folder at `SampleData\BigFix Master Class
2026`, press Next, open each module's Details, press Next again and Build. All
three modules should finish with a green Done pill and Open Output should
show three module folders.
