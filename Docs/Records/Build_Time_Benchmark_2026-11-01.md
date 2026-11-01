# Build Time and Memory Benchmark, 2026-11-01

Product measured: TA Health Check 1.0, source commit `dfa027a`.

Scope: measured with TA Health Check and reused for Master Class Diagnostics Workbench, which shares the same Client Performance, PerfMon and FillDB code. Master Class was not run separately. Reassess if its processing, dependencies or packaging diverge from TA.

This record supports section 6.3, Estimated Build Time and Memory, in the user guide. It replaces the 2026-10-20 measurement, which used a synthetic six-hour PerfMon capture.

## Method

- One timed build per size, run one after another on one workstation: Lenovo 21DDS1XW00 laptop, Intel Core i9-12900H (14 cores, 20 logical processors), 64 GB RAM, local NVMe SSD, Windows 11 Enterprise, AC power, Balanced power plan.
- Client Performance, PerfMon and FillDB were selected. The production report engine ran in a fresh process with a fresh copy of the input.
- Timing covers input discovery, analysis, charts and Excel and Word output. It excludes copying the input, a 15-second baseline, module selection, review pauses, output checks and opening Word.
- Memory is the Windows job peak committed memory for the engine and every process it started, including chart renderers.
- Client data was synthetic and scaled from 50,000 to 300,000 endpoints, with about 2% of endpoints not reporting. Every size used the same real PerfMon capture. The synthetic data came from a seeded generator (seed 42).
- Each build was checked for the expected Word, Excel and chart files and for the expected number of reporting rows in the Client Performance workbook.

## PerfMon capture used

A server capture of about 21 hours, called a 24-hour capture in the guide. It came from a virtual machine and holds about 1,250 readings, one a minute.

| Item | In the capture |
| --- | --- |
| Logical processors | 12 |
| Physical disks | 5 |
| CPU use | Average 8%, peak 54% |
| Disk latency | Average 0.5 ms |
| Disk queue length | Average 0.15 across all disks |
| Total RAM | Not recorded in the capture |

The customer is not named in this record or in the guide, and the capture is not stored in the repository.

## Results

| Managed endpoints | Build time | Peak report memory (GiB) | Client Performance (sec) | PerfMon (sec) | FillDB (sec) | Reporting rows |
| --- | --- | --- | --- | --- | --- | --- |
| 50,000 | 2 min 30 sec | 1.98 | 125.7 | 17.5 | 2.5 | 49,030 |
| 100,000 | 4 min 41 sec | 2.71 | 256.8 | 17.3 | 2.6 | 97,978 |
| 150,000 | 6 min 15 sec | 3.51 | 350.3 | 17.3 | 2.5 | 146,988 |
| 200,000 | 8 min 08 sec | 4.20 | 463.7 | 17.7 | 2.6 | 195,969 |
| 250,000 | 10 min 04 sec | 4.97 | 579.8 | 17.5 | 2.6 | 244,968 |
| 300,000 | 11 min 48 sec | 5.79 | 684.5 | 17.5 | 2.5 | 293,975 |

Client Performance is about 97% of the build at every size. PerfMon time does not change with endpoint count.

The guide table rounds memory to one decimal place. The memory advice in the guide is 1.5 times the 300,000 peak (5.79 GiB), rounded up to 9 GiB. It is planning headroom, not a tested minimum.

## Compared with 2026-10-20

| Managed endpoints | 2026-10-20 time | 2026-11-01 time | 2026-10-20 memory (GiB) | 2026-11-01 memory (GiB) |
| --- | --- | --- | --- | --- |
| 50,000 | 2 min 16 sec | 2 min 30 sec | 1.68 | 1.98 |
| 100,000 | 4 min 19 sec | 4 min 41 sec | 2.65 | 2.71 |
| 150,000 | 6 min 12 sec | 6 min 15 sec | 3.68 | 3.51 |
| 200,000 | 8 min 15 sec | 8 min 08 sec | 4.59 | 4.20 |
| 250,000 | 10 min 16 sec | 10 min 04 sec | 5.46 | 4.97 |
| 300,000 | 12 min 07 sec | 11 min 48 sec | 6.66 | 5.79 |

The larger capture added about 5 seconds to PerfMon. Later code changes made the larger sizes slightly faster and lighter.

## Limits

- One pass per size on one workstation. Repeat runs were not measured.
- The first 50,000 run took 2 min 49 sec because the capture was read cold from disk. It was rerun and the second result is used.
- Other applications were open. Available RAM before each build was 27 to 29 GiB, against 36 GiB on 2026-10-20. Peak committed memory is not affected by that.
- Network shares, cold reads and the packaged desktop application were not measured. The results are not a minimum computer specification.
