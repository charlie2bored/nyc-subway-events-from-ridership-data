"""Match ground-truth events against flagged anomalies.

Run as a module:
    python -m ground_truth.match

Logic:
  For every event in `ground_truth_events.csv`, build a symmetric ±3h
  window around its declared [start_time, end_time] on the event date.
  Look at every flagged hour in `flagged_anomalies.parquet` whose
  station_complex_id belongs to the event's target archetype and whose
  transit_timestamp falls within that window.
    - At least one flagged hour → matched (true positive).
    - No flagged hour          → unmatched (false negative).
  Counts an event as a single match even if 3-4 consecutive hours
  flagged within its window — the per-hour detail stays in
  `flagged_anomalies.parquet` for fingerprinting.

  Every flagged hour that does NOT fall in any event window for its
  target_key becomes an "unexplained anomaly," written to
  `unexplained_anomalies.csv` with an empty `manual_annotation` column.

  False-negative rows are joined to NOAA Central Park daily weather so
  blizzards/floods get tagged separately from genuinely-missed events.

Outputs:
  data/processed/event_matches.csv
  data/processed/unexplained_anomalies.csv
  data/processed/matching_report.md
"""
from __future__ import annotations

import logging
from datetime import datetime, time, timedelta
from io import StringIO

import pandas as pd

from ingest.config import DATA_PROCESSED, TARGETS
from anomaly.detect import detect  # not used directly; importing keeps lineage clear

from . import config
from .weather import annotate as annotate_weather
from .weather import fetch_central_park

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("ground_truth.match")


WINDOW_HOURS = 3            # ±3h symmetric around event window
MIN_EVENT_DURATION = timedelta(hours=1)   # if start==end, pad to 1h


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _target_to_complex_ids() -> dict[str, list[str]]:
    return {t.key: list(t.complex_ids) for t in TARGETS}


def _build_event_windows(events: pd.DataFrame) -> pd.DataFrame:
    """Add `window_start` and `window_end` datetimes per event row.

    Symmetric ±WINDOW_HOURS around [start_time, end_time]. Events without
    a start_time default to 18:00; missing end_time defaults to start+1h.
    """
    out = events.copy()
    out["date"] = pd.to_datetime(out["date"]).dt.date

    def to_dt(d, t_str, fallback: time) -> datetime:
        if pd.isna(t_str):
            t = fallback
        else:
            t = datetime.strptime(str(t_str), "%H:%M").time()
        return datetime.combine(d, t)

    starts = [to_dt(d, s, time(18, 0)) for d, s in zip(out["date"], out["start_time"])]
    ends = []
    for d, e, st in zip(out["date"], out["end_time"], starts):
        ends.append(to_dt(d, e, (st + MIN_EVENT_DURATION).time()))

    out["event_start_dt"] = starts
    out["event_end_dt"] = ends
    out["window_start"] = [s - timedelta(hours=WINDOW_HOURS) for s in starts]
    out["window_end"] = [e + timedelta(hours=WINDOW_HOURS) for e in ends]
    return out


# ---------------------------------------------------------------------------
# matching
# ---------------------------------------------------------------------------

def match_events(events: pd.DataFrame, anomalies: pd.DataFrame) -> pd.DataFrame:
    """One row per event with match status and peak-hour metadata."""
    targets_to_complexes = _target_to_complex_ids()

    # Pre-index anomalies by target_key for cheap lookups.
    by_target: dict[str, pd.DataFrame] = {
        tk: anomalies.loc[anomalies["target_key"] == tk].copy()
        for tk in anomalies["target_key"].unique()
    }
    for df in by_target.values():
        df["transit_timestamp"] = pd.to_datetime(df["transit_timestamp"])

    events_w = _build_event_windows(events)

    rows: list[dict] = []
    for _, ev in events_w.iterrows():
        tk = ev["target_key"]
        complex_ids = targets_to_complexes.get(tk, [])
        sub = by_target.get(tk)
        if sub is None or sub.empty or not complex_ids:
            rows.append(_no_match_row(ev))
            continue
        # Filter to the event's window and the target's complexes.
        m = (
            sub["station_complex_id"].isin(complex_ids)
            & (sub["transit_timestamp"] >= ev["window_start"])
            & (sub["transit_timestamp"] <= ev["window_end"])
        )
        hits = sub.loc[m]
        if hits.empty:
            rows.append(_no_match_row(ev))
            continue
        # Peak hour = highest anomaly_ratio in window
        peak = hits.loc[hits["anomaly_ratio"].idxmax()]
        rows.append({
            **_base_row(ev),
            "matched": True,
            "n_flagged_hours_in_window": int(len(hits)),
            "peak_hour": peak["transit_timestamp"],
            "peak_ridership": float(peak["ridership"]),
            "peak_baseline": float(peak["baseline_ridership"]),
            "peak_anomaly_ratio": float(peak["anomaly_ratio"]),
            "peak_z_score": float(peak["z_score"]) if pd.notna(peak["z_score"]) else None,
            "peak_flag_method": (
                "both" if bool(peak["flag_ratio"]) and bool(peak["flag_z"])
                else "ratio" if bool(peak["flag_ratio"])
                else "z"
            ),
        })

    return pd.DataFrame(rows)


def _base_row(ev: pd.Series) -> dict:
    return {
        "event_id": ev["event_id"],
        "date": ev["date"],
        "target_key": ev["target_key"],
        "event_name": ev["event_name"],
        "event_type": ev["event_type"],
        "window_start": ev["window_start"],
        "window_end": ev["window_end"],
    }


def _no_match_row(ev: pd.Series) -> dict:
    return {
        **_base_row(ev),
        "matched": False,
        "n_flagged_hours_in_window": 0,
        "peak_hour": None,
        "peak_ridership": None,
        "peak_baseline": None,
        "peak_anomaly_ratio": None,
        "peak_z_score": None,
        "peak_flag_method": None,
    }


# ---------------------------------------------------------------------------
# unexplained anomalies
# ---------------------------------------------------------------------------

def find_unexplained(anomalies: pd.DataFrame, events: pd.DataFrame) -> pd.DataFrame:
    """Flagged hours that do not fall inside any event window."""
    events_w = _build_event_windows(events)
    # Build per-target sorted window lists for fast scan.
    windows_by_tk: dict[str, list[tuple[datetime, datetime]]] = {}
    for tk, sub in events_w.groupby("target_key", observed=True):
        wins = sorted(
            zip(sub["window_start"], sub["window_end"]), key=lambda w: w[0]
        )
        windows_by_tk[tk] = wins

    anomalies = anomalies.copy()
    anomalies["transit_timestamp"] = pd.to_datetime(anomalies["transit_timestamp"])

    keep: list[int] = []
    for idx, row in anomalies.iterrows():
        tk = row["target_key"]
        ts = row["transit_timestamp"]
        wins = windows_by_tk.get(tk, [])
        # Linear scan is fine at this size; sorted lets us break early.
        explained = False
        for ws, we in wins:
            if ts < ws:
                break
            if ws <= ts <= we:
                explained = True
                break
        if not explained:
            keep.append(idx)

    cols = [
        "transit_timestamp", "target_key", "station_complex_id",
        "ridership", "baseline_ridership", "anomaly_ratio", "z_score",
        "flag_ratio", "flag_z", "day_of_week", "hour", "season",
        "is_federal_holiday", "holiday_name",
    ]
    out = anomalies.loc[keep, cols].copy()
    out["manual_annotation"] = ""
    return out.sort_values("transit_timestamp").reset_index(drop=True)


# ---------------------------------------------------------------------------
# report
# ---------------------------------------------------------------------------

def build_report(
    matches: pd.DataFrame,
    unexplained: pd.DataFrame,
    weather: pd.DataFrame | None,
) -> str:
    buf = StringIO()
    buf.write("# Event ↔ Anomaly Matching Report — 2024\n\n")
    buf.write(
        f"*Generated by `ground_truth.match`. Event windows: symmetric ±{WINDOW_HOURS}h "
        f"around the listed [start_time, end_time]. Multi-hour flags within a single "
        f"window count as one matched event.*\n"
    )

    # ---- recall / matching rate -----------------------------------------
    buf.write("\n## Recall per event type\n\n")
    rec = (
        matches.groupby(["target_key", "event_type"])
        .agg(events=("event_id", "size"), matched=("matched", "sum"))
        .reset_index()
    )
    rec["recall_pct"] = (rec["matched"] / rec["events"] * 100).round(1)
    buf.write(rec.to_markdown(index=False) + "\n")

    total_events = len(matches)
    total_matched = int(matches["matched"].sum())
    buf.write(
        f"\n**Overall recall:** {total_matched} / {total_events} = "
        f"{100 * total_matched / total_events:.1f}%\n"
    )

    # ---- false negatives + weather -------------------------------------
    buf.write("\n## False negatives (known events with no anomaly)\n\n")
    fn = matches.loc[~matches["matched"]].copy()
    fn["date"] = pd.to_datetime(fn["date"]).dt.date
    if weather is not None and not weather.empty:
        w = weather.copy()
        w["date"] = pd.to_datetime(w["date"]).dt.date
        fn = fn.merge(w[["date", "prcp_in", "snow_in", "tmax_f", "weather_suppressed"]],
                      on="date", how="left")

    buf.write(f"**Total false negatives:** {len(fn)}\n")
    if weather is not None and "weather_suppressed" in fn.columns:
        suppressed = int(fn["weather_suppressed"].fillna(False).sum())
        unexplained_fn = len(fn) - suppressed
        buf.write(f"- Weather-explained: **{suppressed}**\n")
        buf.write(f"- Genuinely unexplained: **{unexplained_fn}**\n")

    if not fn.empty:
        buf.write("\nFirst 25 false negatives:\n\n")
        cols = ["date", "target_key", "event_type", "event_name"]
        if "weather_suppressed" in fn.columns:
            cols += ["prcp_in", "snow_in", "tmax_f", "weather_suppressed"]
        buf.write(fn[cols].head(25).to_markdown(index=False) + "\n")

    # ---- unexplained anomalies ----------------------------------------
    buf.write("\n## Unexplained flagged anomalies\n\n")
    buf.write(
        f"**Total unexplained hours:** {len(unexplained)}\n\n"
        f"These are flagged hours with no overlapping event window for "
        f"their target_key. Top 20 by anomaly_ratio:\n\n"
    )
    if not unexplained.empty:
        top = (
            unexplained.sort_values("anomaly_ratio", ascending=False)
            .head(20)
            [["transit_timestamp", "target_key", "station_complex_id",
              "ridership", "baseline_ridership", "anomaly_ratio", "z_score"]]
            .round(2)
        )
        buf.write(top.to_markdown(index=False) + "\n")

    return buf.getvalue()


# ---------------------------------------------------------------------------
# orchestrator
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--suffix",
        default="",
        help="If set (e.g. '_v2'), reads flagged_anomalies{suffix}.parquet and "
             "writes event_matches{suffix}.csv etc.",
    )
    args = parser.parse_args(argv)
    suf = args.suffix

    events_csv = config.EVENTS_CSV
    flagged_parquet = DATA_PROCESSED / f"flagged_anomalies{suf}.parquet"

    log.info("Loading events: %s", events_csv)
    events = pd.read_csv(events_csv)
    log.info("Loaded %d events", len(events))

    log.info("Loading flagged anomalies: %s", flagged_parquet)
    anomalies = pd.read_parquet(flagged_parquet)
    log.info("Loaded %d flagged hours", len(anomalies))

    # NOAA weather (best-effort: continue without it on failure)
    weather = None
    try:
        log.info("Fetching NOAA Central Park weather ...")
        weather = annotate_weather(fetch_central_park(2024))
        log.info("Got %d weather days", len(weather))
    except Exception as e:
        log.warning("Weather fetch failed; FNs will not be tagged. (%s)", e)

    log.info("Matching events to anomalies ...")
    matches = match_events(events, anomalies)
    log.info(
        "Matches: %d / %d = %.1f%%",
        int(matches["matched"].sum()), len(matches),
        100 * matches["matched"].mean(),
    )

    log.info("Identifying unexplained anomalies ...")
    unexplained = find_unexplained(anomalies, events)
    log.info("Unexplained flagged hours: %d", len(unexplained))

    matches_out = DATA_PROCESSED / f"event_matches{suf}.csv"
    unexplained_out = DATA_PROCESSED / f"unexplained_anomalies{suf}.csv"
    matches.to_csv(matches_out, index=False)
    unexplained.to_csv(unexplained_out, index=False)
    log.info("Wrote %s", matches_out)
    log.info("Wrote %s", unexplained_out)

    report = build_report(matches, unexplained, weather)
    report_path = DATA_PROCESSED / f"matching_report{suf}.md"
    report_path.write_text(report)
    log.info("Wrote %s", report_path)
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
