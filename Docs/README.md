# Master Class Diagnostics Workbench Documentation

- [17 November cross-repository restart verification](Records/Service_Restart_Cross_Repo_Verification_2026-11-17.md): all three fixes, revised guides, passing local checks, nine live FillDB scenarios and a measured 22-minute shutdown.

Docs holds this file and folders. Every other file lives in the folder that matches its kind. `Tests/test_docs_layout.py` fails if a file is left loose here or a relative link in a Markdown file stops resolving.

| Folder | What belongs in it |
|---|---|
| [User Guide](User%20Guide/) | The User Guide (Word and PDF) and its screenshots. |
| [Lab Guide](Lab%20Guide/) | The Session 3 lab guide (Word and PDF). |
| [Reference](Reference/) | Living technical documents. [Getting Started](Reference/Getting_Started.md), [Data Collection](Reference/Data_Collection.md), [Guide Versions](Reference/Guide_Versions.md) and [Testing and Delivery](Reference/Testing_Delivery.md). |
| [Records](Records/) | Dated, point-in-time records such as approved exceptions. They are not updated after the date. |
| [Design](Design/) | Handoffs, source files and verification notes for the guide designers. Never shipped. |

- [2 November release validation](Records/Release_Validation_2026-11-02.md): full suite, live lab collection, tool output, Word review and package evidence.

- [FillDB score verification](Records/FillDB_Score_Verification_2026-11-02.md): live data sufficiency, score controls, date checks and recovery of the interrupted MC capture.

- [Release 2.2](Releases/2.2.md): downloads, changes and setup.

- [Windows service restarts](Reference/Service_Restarts.md): waiting, failure recovery, operator checks and live-test coverage.

The User Guide revision 1.3 and Lab Guide revision 1.2, dated
11/17/2026, clarify service restart waiting, recovery and cleanup checks.
Both PDFs were exported from Microsoft Word.
