# EGN 321 — Module 6 Assignment 6.1

## History Builder: SQLite Logging and Honest Time-Series Reporting

**Student: Juan Pablo Osorio**

This submission extends the Module 5 virtual NTC temperature sensor work into a searchable SQLite history. The primary sampling interval is **1 second**, confirmed by the student. All primary timestamps are **reconstructed for classroom replay**. Missing measurements are kept unknown, rejected raw readings remain auditable, and plots do not connect across unavailable accepted values, missing records or run boundaries.

## Run the project

Use Python 3.10 or later. Extract the ZIP and open a terminal in `EGN321_Assignment6_1`:

```bash
python -m pip install -r requirements.txt
python history_builder.py
python -m unittest -v
```

The script regenerates the two databases, three window exports and plots per dataset, completeness reports, gap reports, and JSON analysis. It refreshes only its generated databases under `results/`; source CSVs are not changed. It does not require Ollama or a network connection after dependencies are installed.

The executed `Assignment6_1_History_Builder.ipynb` contains the results and can also be rerun in Jupyter or Google Colab. In Colab, run the first code cell and upload the complete ZIP when asked. This notebook is a coherent adaptation of the instructor starter: it avoids its repeated upload/overwrite blocks and applies the correct dataset-specific intervals and source column mappings.

The Word report is a completed version of the instructor's eight-section template. It is a delivered analysis document; running the pipeline regenerates the underlying evidence, not the Word file.

## Sources and provenance

- Student repository: https://github.com/juanosorio-alt/EGN321-Assignment5-2
- Primary input: `data/readings_failure_scenario.csv`, obtained from that repository.
- Comparison source: `data/readings_original.csv`, retained for provenance only. It is **not used to fill** the failure scenario's missing value.
- Sensor: virtual NTC on Arduino Uno in Velxio; original simulation: https://velxio.dev/juan-osorio/temperature-lab-correctedvlx/
- Supplemental input: the instructor attachment `module6_sample_sensor_history.csv`, copied as `data/instructor_sample_history.csv`. Temperature is selected from its five-sensor wide table; other sensor columns remain unchanged in the input file.
- The instructor Student Guide, report template and notebook guided the structure and workflow. The worked example is explanatory material, not measured evidence in this submission.
- File SHA-256 hashes are recorded in `source_manifest.json` and database metadata.

## Replay timestamps and runs

The primary input has 125 records across two runs. Run 1 has 100 samples; run 2 restarts the sample counter at 1 and has 25 samples. The sampling interval is one second. The fixed classroom start is `2026-10-01T12:00:00`, using UTC only as a replay convention. Timestamp strings are stored consistently without an offset; the convention is recorded in metadata and plot labels. These dates are not original acquisition times.

Within each run:

```text
timestamp = replay_start + (run_offset + sample_number - 1) * 1 second
run_1_offset = 0 samples
run_2_offset = 100 samples
```

The replay ends at `2026-10-01T12:02:04`. Run 2 begins at `12:01:40` only because the runs are concatenated for replay. Their actual temporal separation is unknown. Gap detection and line segments never cross a run boundary. Missing sample positions within a run are preserved rather than renumbered away.

The instructor input already supplies timestamps and has a **60-second** sampling grid. Its timestamps remain as supplied, with timezone unspecified. They are classroom dataset timestamps, not evidence of the student's acquisition times.

## Deterministic validation

For the primary data, preserve the Module 5 rule: accept finite Celsius measurements in **0–50 °C inclusive**. Values outside that range are `OUT_OF_RANGE`; empty temperatures are `MISSING`; malformed/non-finite values or wrong units are `INVALID`. Accepted values are stored separately from raw values. A change greater than 20 °C from the prior numeric Celsius sample in the same run sets `spike_flag`. In-range spikes are labeled `SUSPICIOUS` and remain accepted, as in Module 5.

Source statuses, source filter decisions, raw ADC strings and raw temperature text are retained. A rejected value has SQL `NULL` in `accepted_value`; a missing value is never changed to zero. For the instructor supplement, the provided status is authoritative for acceptance: only numeric `OK` readings are accepted. The two policies are documented separately.

## SQLite design

Each dataset has its own `module6_sensor_history.db`. The `sensor_readings` table stores:

| Fields | Purpose |
|---|---|
| `record_id`, `run_id`, `sample_number` | Preserve original identity and the counter reset. |
| `timestamp`, `timestamp_source` | Store sortable time and its provenance. |
| `sensor_name`, `unit` | Identify the sensor and Celsius units. |
| `raw_value`, `raw_text`, `raw_adc` | Preserve numeric temperature, original text and ADC counts separately. |
| `accepted_value` | Store the accepted temperature or NULL. |
| `status`, `source_status`, `source_filter_decision` | Preserve analysis and source decisions. |
| `spike_flag`, `failure_injected` | Preserve warnings and explicit simulated failure. |

`metadata` stores the source hash, interval, clock convention, analysis scope and provenance. Primary keys and uniqueness constraints prevent duplicated records. Time indexes support the history queries. Inserts use a transaction; a failed import rolls back, and repeat imports do not accumulate duplicates.

## Time windows

The last hour and last day are calculated from `MAX(timestamp)` in the relevant database, not the computer's current time. The cutoff is computed in Python and passed as a SQL parameter. Both endpoints are inclusive. The query is:

```sql
SELECT * FROM sensor_readings
WHERE timestamp >= ? AND timestamp <= ?
ORDER BY timestamp, sensor_name;
```

Full history uses the same ordering without a cutoff. Primary last-hour, last-day and full-history views all contain 125 records because the entire primary replay is only 124 elapsed seconds long. A nominal hour/day window does not create evidence for the unobserved earlier time.

## Gap and completeness definitions

For each sensor and run, consecutive timestamps are compared against the expected sampling interval. A separation larger than that interval is a gap. Regular-grid validation rejects duplicate or off-grid timestamps rather than hiding them in a rounded estimate.

```text
missing positions between two records = elapsed_seconds / interval_seconds - 1
expected positions = received records + absent positions
record completeness = received records / expected positions * 100
numeric completeness = numeric measurements / expected positions * 100
accepted-value completeness = accepted measurements / expected positions * 100
```

The denominator is bounded by the first and last observed record in each run, including both endpoints. Leading/trailing absence outside those bounds and unknown delays between runs cannot be quantified. `largest_record_gap_seconds` is the separation between the records bounding a gap, not the duration assigned to missing sample slots. The CSV separately records both quantities.

## Verified primary results

| Metric | Result |
|---|---:|
| Expected positions within observed runs | 125 |
| Received/stored records | 125 |
| Absent records | 0 |
| Logged rows with a missing measurement | 1 |
| Numeric measurements | 124 |
| Accepted measurements | 105 |
| Record completeness | 100% |
| Numeric completeness | 99.2% |
| Accepted-value completeness | 84% |
| Largest absent-record gap | 0 seconds |
| Accepted minimum / maximum / median | 14 / 36 / 27 °C |

Status counts are **103 OK, 2 SUSPICIOUS, 19 OUT_OF_RANGE, 1 MISSING**. The absent temperature is record 110, run 2, sample 10, reconstructed time `12:01:49`. Adjacent numeric measurements at `12:01:48` and `12:01:50` are separated by 2 seconds around one missing measurement slot. The row is present, so it is not a missing record. The two nearby values of 27 °C do not establish the unknown value between them.

## Instructor supplement results

The temperature history covers 30 hours. This longer provided dataset demonstrates absent-record gaps without altering the student's evidence.

| Window | Expected | Received | Absent | Record completeness | Largest gap |
|---|---:|---:|---:|---:|---:|
| Last hour | 61 | 61 | 0 | 100% | 0 seconds |
| Last day | 1,441 | 1,421 | 20 | 98.61% | 1,260 seconds |
| Full history | 1,801 | 1,756 | 45 | 97.50% | 1,560 seconds |

Full-history statuses: 1,753 OK and 3 OUT_OF_RANGE. Accepted minimum/maximum/median: 19.29 / 24.62 / 22.57 °C. Last-day statuses: 1,419 OK and 2 OUT_OF_RANGE. Last-hour statuses: 61 OK. The inclusive endpoint convention explains 61 expected minute positions in an hour.

The two gaps are:

- October 1, 13:09 to 13:35: 26-minute separation; 25 absent minute positions.
- October 2, 05:59 to 06:20: 21-minute separation; 20 absent minute positions.

## Honest plots and interpretation

`plot_segments()` starts a new line after each absent interval, NULL accepted value or run boundary. It never bridges a gap. Rejected numeric temperatures are shown as separate orange crosses. The primary missing value is highlighted and enlarged in `missing_value_detail.png`; supplemental missing record intervals appear as gray bands.

The primary graph describes changes in recorded simulated values and the validation decisions. It does not establish a continuous-hour/day trend, a physical cause, sensor calibration, original acquisition times or the delay between runs. The supplemental graph shows changing recorded temperatures on each side of missing intervals; it cannot establish what happened inside them. No interpolation, imputation, smoothing or average across gaps is used. Min/max/median summarize accepted observed samples only.

## Tests and reproducibility

`python -m unittest -v` passed **12 tests**. Tests check exact SQLite round trips including NULL/raw/identity fields, repeat imports, transactional rollback, missing-slot counts, absence of false gaps at normal cadence, missing values versus absent rows, off-grid/duplicate time rejection, separation of runs, broken plot segments, latest-data query boundaries and the known instructor missing counts. Synthetic test fixtures remain isolated in temporary databases and are never used as assignment evidence.

The notebook has also been executed from start to finish; code cell outputs are retained. The original Module 5 integration log was used as a cross-check of accepted values. `results/test_results.txt` contains the automated test output.

## Deliverables

- `Assignment6_1_Report_Juan_Pablo_Osorio.docx`: completed instructor report template.
- `Assignment6_1_History_Builder.ipynb`: executed notebook with results and plots.
- `history_builder.py`: reproducible pipeline.
- `test_history_builder.py`: automated verification.
- `data/`: primary, original comparison and instructor input files.
- `results/primary/`: SQLite database, three history CSVs/plots, missing-value detail, gap/completeness CSVs and JSON evidence.
- `results/instructor_supplement/`: separate database, three history CSVs/plots and gap/completeness evidence.
- `source_manifest.json`, `requirements.txt`, `.gitignore`: provenance and setup.

Module 6 repository: https://github.com/juanosorio-alt/EGN321-Assignment6-1

## AI use

AI assistance was used to develop the implementation, notebook, tests and report. Numerical results were generated and checked by deterministic Python/SQLite code. Ollama was not run; its instructor lab is optional. No missing reading or physical explanation was supplied by AI as evidence.
