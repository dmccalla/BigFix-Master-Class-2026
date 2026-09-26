# Getting Started

This guide takes you from the release zip to your first set of outputs. It
uses the sample capture that ships with the Workbench, so no BigFix
deployment is needed to follow it.

## Before You Start

- Windows 10 or 11.
- Python 3.11 or newer. Install it from python.org and tick **Add Python to
  PATH** during setup.
- Microsoft Edge or Google Chrome. Edge is already on Windows.

## Install

1. Extract the zip to a folder you can write to, such as `Documents`. Keep
   the folder structure as it is.
2. Open `Launchers` and double-click **Run Diagnostics Workbench.cmd**.
3. The first run explains that the Workbench keeps its packages in its own
   private environment, a `.venv` folder next to the code. Press a key to
   continue. Creating the environment and installing the packages takes
   about a minute. Later runs skip this and open the app straight away.

If the launcher reports that Python was not found or is too old, install
Python 3.11 or newer and run the launcher again. If an install fails part
way through, delete the `.venv` folder and run the launcher again.

## Step 1: Folders

**Data Folder** is where the collected data lives. For the sample run, browse
to `SampleData\BigFix Master Class 2026`. The Workbench scans the folder and
reports how many of the three modules found their input. The field is
optional: leave it blank to pick each module's input by hand on step 2.

**Output Folder** is where the run folder is created. Every build makes a new
folder there, named after the run and the time of the build.

**Run Name** is required. It names the run folder and prefixes every output
file, so use something you will recognise later, such as the customer or
server name.

## Step 2: Modules

Each row is one module. The pill on the right shows its state:

- **Found**: the input was found and the module is ready.
- **Needs A File**: nothing matched. Open Details and choose the file.
- **Needs Review**: the input was found but a required value is still blank.

Open **Details** on a row to see what the module does, which files it looks
for and which it selected. **Change** replaces a selected file with one you
choose.

The Client Performance Loop Analysis needs the **Report Start Date** and
**Report End Date**. They bound the period the report describes. For the
sample data, any range that includes 14 June 2026 works.

The Perfmon Infrastructure Analysis reads the processor and disk counts from
the capture. Physical memory cannot be read from a capture, so enter it when
you know it. A second capture is optional.

Use **All Available** to select every module with an input and **Clear** to
deselect them all. A module you leave unselected is skipped.

## Step 3: Build

The Run Details strip repeats the run name, the selected modules and the
output folder. Press **Build**. Each module runs in turn and its status pill
moves from Queued to Running to Done. Parsing a large PerfMon capture can take
several minutes.

**View Logs** opens the engine log as it is written. **Open Output** opens the
run folder once the build finishes. **Cancel** stops the build after the
current module.

## The Outputs

The run folder holds one subfolder per module, plus the run log and a
manifest listing every file the build wrote.

| Module | Files |
|---|---|
| Client Performance Loop Analysis | Mini Report (`.docx`), Infographic (`.png`), Excel workbook (`.xlsx`) |
| Perfmon Infrastructure Analysis | Mini Report (`.docx`), Excel workbook (`.xlsx`), and a `_Perfmon_Charts` folder holding the scorecard Infographic and one chart per counter |
| FillDB Performance Analysis | Mini Report (`.docx`), Infographic (`.png`) |

The Mini Report is the narrative: the score, how it was calculated, the
findings and the tables behind them. The Infographic is the one-page visual
of the same result. The Excel workbook carries the source data and the
per-item detail for anyone who wants to go deeper.

## Running Your Own Data

Collect the files described in [Data Collection](Data_Collection.md), put
them in a folder that follows the layout shown there, and point the Data
Folder at it. Everything else is the same as the sample run.

## If Something Goes Wrong

- The build reports a failed module: open **View Logs**. The log names the
  input and the reason.
- No Infographic was written: the Workbench needs Edge or Chrome installed to
  render it. The Mini Report and workbook are still produced.
- A module shows **Needs A File** even though the data is there: check the
  file names against the patterns in Data Collection. Files with other names
  can still be chosen by hand with **Change**.
- The app does not start after a Python upgrade: delete the `.venv` folder
  and run the launcher again.
