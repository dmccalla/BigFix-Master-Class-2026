# Master Class Diagnostics Workbench 2.0.0

## Initial Distribution

This is the initial distribution of the Master Class Diagnostics Workbench for
the classroom and practice lab. It is a Windows desktop application that turns
collected BigFix evidence into focused diagnostic outputs.

## Included Analysis Modules

- **Client Performance Analysis** reads the Client Performance Counters export
  and can use optional Top 10 evaluation, UDP notification, and Deployment
  Information data.
- **Perfmon Infrastructure Analysis** reads a BigFix server PerfMon `.blg`
  capture. A second capture can be compared when available.
- **FillDB Performance Analysis** reads FillDB performance logs or the
  analyzer CSV.

Each module writes its applicable Mini Report, Infographic, and Excel output
into one named run folder.

## Included Content

The package includes the Windows launcher, required runtime code, the Master
Class BigFix collection tasks and analyses, and fictional sample data. Class
instructions, collection procedures, and lab exercises are supplied
separately.

## Requirements

- Windows 10 or 11.
- Python 3.12 or newer, installed with "Add Python to PATH" selected.
- Microsoft Edge or Google Chrome for background Infographic rendering.
- Microsoft Word and Excel are the preferred and tested applications for Mini
  Reports and workbooks. LibreOffice and other compatible applications may
  work, but they have not been fully vetted.

## Integrity And Security

Verify the archive against its accompanying `.sha256` file before use. The
package also contains `release-manifest.json` with a SHA-256 hash for every
packaged file, `sbom.cyclonedx.json`, and `THIRD_PARTY_NOTICES.md`.

To report an issue, include the Workbench version shown in the title bar and
the steps that reproduce it.
