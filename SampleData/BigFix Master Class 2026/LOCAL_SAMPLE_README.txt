LOCAL TEST SAMPLE - current format verified 2026-10-20

Select this folder as the data folder: SampleData\BigFix Master Class 2026
There is no nested Results folder in this local test copy.
Select the whole sample folder, rather than Client_Loop alone, so the app
can find Deployment_Information and include Evaluation Frequency.

Client Performance coverage:
- Active property evaluation intervals and their frequency bands.
- Minimum analysis interval: 1800 seconds on 1 device and 600 on 2 devices.
- Top 10 entries for site, analysis-property and retrieved-property work.
- Command polling, UDP, FastHashVerify, CPU idle settings and core counts.

These are demonstration values, not current measurements of a deployment.
The active demo captures use a synthetic June 2026 assessment period. Original
inputs are preserved in SampleData/Originals_20261024.zip. See
DEMO_SNAPSHOT.json for the date shifts and hardware context. The Platform sample uses synthetic
interval rows covering all 877 active properties. TA and Class samples
retain 244 active-property intervals and 2537 loop source rows. Their
synthetic Top 10 totals have been aligned with occurrence counts and
average times. Retrieved properties are the lab's 36 reserved and 6
default properties from 10-22-2026, plus two custom examples.

Existing local inputs were backed up before consolidation. No production
code or collection task content is changed by this sample refresh.

Validation on 2026-10-20:
The current local app generated Client Performance, PerfMon and FillDB
Performance reports from this folder. CSV/XML loop and UDP inputs agree.
Minimum analysis intervals, property evaluation intervals, client settings
and Top 10 examples are present. PerfMon has 60 sample readings and FillDB
has 24 source rows. These compact inputs demonstrate the current report
fields; the validation date is not a new collection date.
See SAMPLE_DATA_VALIDATION.json for input hashes and collector versions.
