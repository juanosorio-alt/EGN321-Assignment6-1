"""EGN 321 Assignment 6.1 — deterministic SQLite history and gap reporting.

Run: python history_builder.py
No network, database server, or AI model is required.
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
import sqlite3
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent
INTERVAL_SECONDS = 1  # Confirmed by the student for Module 5.
REPLAY_START = "2026-10-01T12:00:00"
FIELDS = ["record_id", "run_id", "sample_number", "timestamp", "sensor_name",
          "raw_value", "raw_text", "raw_adc", "accepted_value", "status",
          "source_status", "source_filter_decision", "spike_flag", "unit",
          "timestamp_source", "failure_injected"]
SCHEMA = """
CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sensor_readings (
 record_id INTEGER PRIMARY KEY,
 run_id INTEGER NOT NULL,
 sample_number INTEGER NOT NULL,
 timestamp TEXT NOT NULL,
 sensor_name TEXT NOT NULL,
 raw_value REAL,
 raw_text TEXT NOT NULL,
 raw_adc TEXT,
 accepted_value REAL,
 status TEXT NOT NULL,
 source_status TEXT NOT NULL,
 source_filter_decision TEXT NOT NULL,
 spike_flag INTEGER NOT NULL CHECK (spike_flag IN (0,1)),
 unit TEXT NOT NULL,
 timestamp_source TEXT NOT NULL,
 failure_injected INTEGER NOT NULL CHECK (failure_injected IN (0,1)),
 UNIQUE (sensor_name, run_id, sample_number),
 UNIQUE (sensor_name, timestamp),
 CHECK (accepted_value IS NULL OR status IN ('OK','SUSPICIOUS'))
);
CREATE INDEX IF NOT EXISTS idx_sensor_time ON sensor_readings(sensor_name,timestamp);
CREATE INDEX IF NOT EXISTS idx_time ON sensor_readings(timestamp);
"""


def parse_time(value):
    return datetime.fromisoformat(value)


def numeric(text):
    try:
        value = float(text)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def source_sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_primary(path, interval=INTERVAL_SECONDS, start=REPLAY_START):
    """Keep run/sample identity; concatenate runs only on a labeled replay clock.

    The real delay between runs is unknown. Missing sequence positions inside
    each run retain their place; rows are never renumbered to hide gaps.
    """
    if interval <= 0:
        raise ValueError("Sampling interval must be positive")
    with Path(path).open(newline="", encoding="utf-8") as stream:
        source = list(csv.DictReader(stream))
    source.sort(key=lambda r: int(r["record_id"]))
    rows, run_offsets, run_max, seen_runs = [], {}, {}, []
    for r in source:
        run = int(r["run_id"])
        if run not in run_max:
            seen_runs.append(run)
            run_max[run] = 0
        run_max[run] = max(run_max[run], int(r["sample_number"]))
    offset = 0
    for run in seen_runs:
        run_offsets[run] = offset
        offset += run_max[run]
    previous = {}
    for r in source:
        run, sample = int(r["run_id"]), int(r["sample_number"])
        if sample < 1:
            raise ValueError("Sample numbers must be positive")
        text = r["temperature_c"]
        raw = numeric(text)
        spike = raw is not None and run in previous and abs(raw - previous[run]) > 20
        if not text.strip():
            status = "MISSING"
        elif raw is None or r["unit"] != "C":
            status = "INVALID"
        elif not 0 <= raw <= 50:
            status = "OUT_OF_RANGE"
        else:
            status = "SUSPICIOUS" if spike else "OK"
        accepted = raw if status in ("OK", "SUSPICIOUS") else None
        if raw is not None and r["unit"] == "C":
            previous[run] = raw
        timestamp = parse_time(start) + timedelta(seconds=(run_offsets[run]+sample-1)*interval)
        rows.append(dict(zip(FIELDS, [int(r["record_id"]), run, sample,
            timestamp.isoformat(), "NTC_temperature", raw, text, r["raw_adc"],
            accepted, status, r["sensor_status"], r.get("filter_decision", ""),
            int(spike), r["unit"], "reconstructed_for_classroom_replay",
            int(r.get("failure_injected", "false").lower() == "true") ])))
    return rows


def read_instructor(path):
    """Supplement only: retain provided timestamps, temperature and statuses.

    The source contains five sensors; this supplementary analysis explicitly
    selects temperature. Its 60-second cadence is not the student's cadence.
    """
    rows = []
    with Path(path).open(newline="", encoding="utf-8") as stream:
        for r in csv.DictReader(stream):
            raw = numeric(r["temperature_c"])
            status = r["temperature_status"].strip().upper()
            if raw is None:
                status = "MISSING" if not r["temperature_c"].strip() else "INVALID"
            rows.append(dict(zip(FIELDS, [int(r["sample_number"]), 1,
                int(r["sample_number"]), parse_time(r["timestamp"]).isoformat(),
                "instructor_temperature", raw, r["temperature_c"], "",
                raw if status == "OK" else None, status, r["temperature_status"],
                "instructor_status_policy", 0, "C", "provided_in_instructor_csv", 0])))
    return rows


def write_database(path, rows, metadata):
    """Transactional refresh; repeated imports cannot duplicate records."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.executescript(SCHEMA)
        with conn:
            conn.execute("DELETE FROM sensor_readings")
            conn.execute("DELETE FROM metadata")
            conn.executemany("INSERT INTO metadata VALUES (?,?)",
                             [(k, json.dumps(v)) for k,v in metadata.items()])
            conn.executemany(f"INSERT INTO sensor_readings ({','.join(FIELDS)}) "
                             f"VALUES ({','.join('?' for _ in FIELDS)})",
                             [[r[k] for k in FIELDS] for r in rows])


def query_history(path, hours=None):
    """Inclusive windows [latest-duration, latest], anchored to stored data."""
    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        latest = conn.execute("SELECT MAX(timestamp) FROM sensor_readings").fetchone()[0]
        if latest is None:
            return []
        if hours is None:
            result = conn.execute("SELECT * FROM sensor_readings ORDER BY timestamp,sensor_name")
        else:
            if hours < 0:
                raise ValueError("Window duration cannot be negative")
            cutoff = (parse_time(latest)-timedelta(hours=hours)).isoformat()
            result = conn.execute("SELECT * FROM sensor_readings WHERE timestamp >= ? "
                                  "AND timestamp <= ? ORDER BY timestamp,sensor_name",
                                  (cutoff,latest))
        return [dict(r) for r in result]


def groups(rows):
    result = defaultdict(list)
    for r in rows:
        result[(r["sensor_name"],r["run_id"])].append(r)
    return [sorted(g,key=lambda r:r["timestamp"]) for g in result.values()]


def detect_gaps(rows, interval):
    """Detect absent records within each run; reject duplicate/off-grid times.

    largest gap is the elapsed time between bounding records, not the number
    of missing positions. At 1 s cadence a 3 s separation means 2 missing slots.
    """
    if interval <= 0:
        raise ValueError("Sampling interval must be positive")
    gaps = []
    for g in groups(rows):
        for a,b in zip(g,g[1:]):
            delta = (parse_time(b["timestamp"])-parse_time(a["timestamp"])).total_seconds()
            ratio = delta/interval
            if delta <= 0 or not math.isclose(ratio,round(ratio),abs_tol=1e-7):
                raise ValueError("Timestamps must be unique and on the declared sampling grid")
            if delta > interval + 1e-7:
                gaps.append({"sensor_name":a["sensor_name"],"run_id":a["run_id"],
                    "before":a["timestamp"],"after":b["timestamp"],
                    "elapsed_seconds":delta,"missing_slots":round(ratio)-1,
                    "missing_slot_duration_seconds":(round(ratio)-1)*interval})
    return gaps


def summarize(rows, interval):
    gaps = detect_gaps(rows,interval)
    missing = sum(g["missing_slots"] for g in gaps)
    expected = len(rows)+missing
    accepted = [r["accepted_value"] for r in rows if r["accepted_value"] is not None]
    numeric_count = sum(r["raw_value"] is not None for r in rows)
    return {"received_records":len(rows),"expected_records_within_observed_runs":expected,
        "missing_records":missing,"records_with_missing_values":sum(r["status"]=="MISSING" for r in rows),
        "numeric_readings":numeric_count,"accepted_readings":len(accepted),
        "record_completeness_percent":100*len(rows)/expected if expected else None,
        "numeric_completeness_percent":100*numeric_count/expected if expected else None,
        "accepted_completeness_percent":100*len(accepted)/expected if expected else None,
        "status_counts":dict(sorted(Counter(r["status"] for r in rows).items())),
        "gap_count":len(gaps),"largest_record_gap_seconds":max((g["elapsed_seconds"] for g in gaps),default=0),
        "first_timestamp":min((r["timestamp"] for r in rows),default=None),
        "latest_timestamp":max((r["timestamp"] for r in rows),default=None),
        "accepted_min_c":min(accepted) if accepted else None,
        "accepted_max_c":max(accepted) if accepted else None,
        "accepted_median_c":statistics.median(accepted) if accepted else None}


def plot_segments(rows, interval):
    """Separate lines at missing rows, null accepted values, and run boundaries."""
    segments = []
    for g in groups(rows):
        segment = []
        previous = None
        for r in g:
            t = parse_time(r["timestamp"])
            if previous is not None and (t-previous).total_seconds() > interval+1e-7:
                if segment: segments.append(segment)
                segment = []
            if r["accepted_value"] is None:
                if segment: segments.append(segment)
                segment = []
            else:
                segment.append((t,r["accepted_value"]))
            previous = t
        if segment: segments.append(segment)
    return segments


def make_plot(rows, interval, path, title, clock_label, zoom=False):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    fig,ax = plt.subplots(figsize=(11,4.2),layout="constrained")
    if zoom:
        missing = next(r for r in rows if r["status"] == "MISSING")
        mid = parse_time(missing["timestamp"])
        rows = [r for r in rows if abs((parse_time(r["timestamp"])-mid).total_seconds()) <= 6*interval]
    segments = plot_segments(rows,interval)
    for i,seg in enumerate(segments):
        ax.plot([p[0] for p in seg],[p[1] for p in seg],color="#175b86",
                marker=".",ms=4,lw=1.2,label="Accepted temperature" if i==0 else None)
    rejected = [r for r in rows if r["raw_value"] is not None and r["accepted_value"] is None]
    if rejected:
        ax.scatter([parse_time(r["timestamp"]) for r in rejected],
                   [r["raw_value"] for r in rejected],marker="x",s=25,color="#b54922",label="Rejected raw temperature")
    for i,gap in enumerate(detect_gaps(rows,interval)):
        ax.axvspan(parse_time(gap["before"])+timedelta(seconds=interval/2),
                   parse_time(gap["after"])-timedelta(seconds=interval/2),
                   color="#d4d7dc",alpha=.7,label="Absent records" if i==0 else None)
    nulls = [r for r in rows if r["status"] == "MISSING"]
    for i,r in enumerate(nulls):
        mid = parse_time(r["timestamp"])
        ax.axvspan(mid-timedelta(seconds=interval/2),mid+timedelta(seconds=interval/2),
                   color="#e9bd60",alpha=.5,label="Logged missing value" if i==0 else None)
    run_groups = groups(rows)
    for g in run_groups[1:]:
        ax.axvline(parse_time(g[0]["timestamp"]),color="#777",ls=":",lw=1,label="Run boundary (real delay unknown)")
    ax.set(title=title,xlabel=clock_label,ylabel="Temperature (°C)")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M:%S" if interval==1 else "%m-%d %H:%M"))
    ax.grid(alpha=.2)
    ax.legend(loc="best",fontsize=8)
    fig.savefig(path,dpi=180)
    plt.close(fig)


def export_csv(path, rows, fields):
    with Path(path).open("w",newline="",encoding="utf-8") as f:
        w=csv.DictWriter(f,fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def build_dataset(name, rows, interval, source, output_root, metadata):
    out = Path(output_root)/name
    out.mkdir(parents=True,exist_ok=True)
    metadata.update({"expected_interval_seconds":interval,"source_file":str(Path(source).name),
                     "source_sha256":source_sha(source),"window_boundaries":"inclusive",
                     "completeness_scope":"first through last stored record within each run"})
    db = out/"module6_sensor_history.db"
    write_database(db,rows,metadata)
    summaries={}
    for window,hours in [("last_hour",1),("last_day",24),("full_history",None)]:
        selected=query_history(db,hours)
        export_csv(out/f"{window}_report.csv",selected,FIELDS)
        summaries[window]=summarize(selected,interval)
        make_plot(selected,interval,out/f"{window}.png",f"{name.replace('_',' ').title()} — {window.replace('_',' ')}",
                  metadata["clock_label"])
    gaps=detect_gaps(query_history(db),interval)
    gap_fields=["sensor_name","run_id","before","after","elapsed_seconds","missing_slots","missing_slot_duration_seconds"]
    export_csv(out/"gaps.csv",gaps,gap_fields)
    summary_fields=[k for k in summaries["full_history"] if k!="status_counts"]
    export_csv(out/"gap_completeness_report.csv",[{"window":k,**{f:v[f] for f in summary_fields}} for k,v in summaries.items()],["window"]+summary_fields)
    if name=="primary":
        make_plot(rows,interval,out/"missing_value_detail.png","Primary history — missing measurement at record 110",
                  metadata["clock_label"],zoom=True)
    result={"metadata":metadata,"windows":summaries,"gaps":gaps}
    (out/"analysis.json").write_text(json.dumps(result,indent=2)+"\n")
    return result


def main(output_root=None):
    output_root=Path(output_root) if output_root else ROOT/"results"
    primary=ROOT/"data/readings_failure_scenario.csv"
    instructor=ROOT/"data/instructor_sample_history.csv"
    a=build_dataset("primary",read_primary(primary),1,primary,output_root,{
        "student":"Juan Pablo Osorio","timestamp_source":"reconstructed_for_classroom_replay",
        "replay_start":REPLAY_START,"clock_label":"Reconstructed replay clock (UTC convention), 2026-10-01",
        "interval_basis":"1 second, confirmed by the student",
        "run_boundary":"Runs concatenated for replay only; actual inter-run delay unknown",
        "validation":"0–50 °C inclusive; >20 °C jumps flagged but not automatically rejected"})
    b=build_dataset("instructor_supplement",read_instructor(instructor),60,instructor,output_root,{
        "timestamp_source":"provided_in_instructor_csv","clock_label":"Provided classroom timestamps (timezone unspecified)",
        "interval_basis":"60 seconds, matching provided sample numbers and timestamps",
        "scope":"Instructor practice dataset; temperature only; separate from student evidence",
        "validation":"Accept only numeric readings labeled OK in the instructor CSV"})
    print(json.dumps({"primary":a["windows"]["full_history"],
                      "instructor_supplement":b["windows"]["full_history"]},indent=2))
    return a,b


if __name__=="__main__":
    main()
