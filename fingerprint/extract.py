"""Extract the five fingerprint features per matched ground-truth event.

For every event that the v2 matcher tagged as `matched=True`, we read
ridership in a window [start − 6h, end + 12h], aggregate across the
target's complexes, and compute:

  peak_intensity     : max((actual − baseline) / baseline) over
                       [start − 3h, end + 3h].
  peak_hour_offset   : hours of peak relative to event_start.
  lead_time_h        : hours before event_start when (actual/baseline)
                       first crosses 1.5x. 0 if no pre-event spike.
  lag_time_h         : hours after event_end when (actual/baseline)
                       first drops back to ≤ 1.2x. Capped at 12h.
  asymmetry_ratio    : lead_time_h / lag_time_h. NaN if lag is 0.
  decay_lambda       : best-fit λ in `ridership(t) = baseline + A·e^(-λt)`
                       over the post-event window.
  decay_half_life_h  : ln(2) / λ.
  decay_r2           : goodness-of-fit. If r² < 0.7 we fall back to a
                       linear slope and flag the event as non-exponential.
  decay_linear_slope : Δ riders / h, only set when the exponential fit
                       failed the r² gate.

Run as a module:
    python -m fingerprint.extract

Outputs:
    data/processed/event_features.parquet
    data/processed/fingerprint_report.md
"""
from __future__ import annotations

import logging
from datetime import datetime, time, timedelta
from io import StringIO

import numpy as np
import pandas as pd
from scipy.optimize import curve_fit

from ingest.config import DATA_PROCESSED
from ground_truth import config as gt_config

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("fingerprint.extract")


WINDOW_PRE_HOURS = 6
WINDOW_POST_HOURS = 12
PEAK_BUFFER_HOURS = 3              # ± 3h around the declared event window
LEAD_TRIGGER = 1.5                 # ratio at which lead-time clock starts
LAG_RETURN = 1.2                   # ratio at which lag-time clock stops
DECAY_R2_GATE = 0.7
MIN_EVENT_DURATION = timedelta(hours=1)


# ---------------------------------------------------------------------------
# event time helpers (consistent with match.py)
# ---------------------------------------------------------------------------

def _to_dt(d: datetime, t_str, fallback: time) -> datetime:
    if pd.isna(t_str):
        t = fallback
    else:
        t = datetime.strptime(str(t_str), "%H:%M").time()
    return datetime.combine(d, t)


def _attach_event_times(events: pd.DataFrame) -> pd.DataFrame:
    out = events.copy()
    out["date"] = pd.to_datetime(out["date"]).dt.date
    starts = [_to_dt(d, s, time(18, 0)) for d, s in zip(out["date"], out["start_time"])]
    ends = [
        _to_dt(d, e, (st + MIN_EVENT_DURATION).time())
        for d, e, st in zip(out["date"], out["end_time"], starts)
    ]
    out["event_start_dt"] = starts
    out["event_end_dt"] = ends
    return out


# ---------------------------------------------------------------------------
# feature extraction per event
# ---------------------------------------------------------------------------

def _aggregate_window(
    ridership: pd.DataFrame,
    target_key: str,
    start_dt: datetime,
    end_dt: datetime,
) -> pd.DataFrame:
    sub = ridership.loc[
        (ridership["target_key"] == target_key)
        & (ridership["transit_timestamp"] >= start_dt)
        & (ridership["transit_timestamp"] <= end_dt)
    ]
    if sub.empty:
        return pd.DataFrame()
    hourly = (
        sub.groupby("transit_timestamp", as_index=True)[["ridership", "baseline_ridership"]]
        .sum()
        .sort_index()
    )
    # Avoid divide-by-zero in ratio/pct calcs.
    safe_base = hourly["baseline_ridership"].where(hourly["baseline_ridership"] > 0, np.nan)
    hourly["pct_dev"] = (hourly["ridership"] - safe_base) / safe_base
    hourly["ratio"] = hourly["ridership"] / safe_base
    return hourly


def _fit_decay(post: pd.DataFrame, event_end: datetime) -> dict:
    """Fit exp decay to the post-event ridership; fall back to linear if R² < gate."""
    nans = {
        "decay_lambda": np.nan,
        "decay_half_life_h": np.nan,
        "decay_r2": np.nan,
        "decay_fallback_linear": np.nan,
        "decay_linear_slope": np.nan,
    }
    if len(post) < 4 or post["ridership"].isna().any():
        return nans

    t = np.array([(idx - event_end).total_seconds() / 3600 for idx in post.index], dtype=float)
    y = post["ridership"].to_numpy(dtype=float)
    baseline = float(post["baseline_ridership"].median())
    if not np.isfinite(baseline):
        baseline = float(y.min())

    A0 = max(y[0] - baseline, 1.0)
    try:
        popt, _ = curve_fit(
            lambda tt, A, lam: baseline + A * np.exp(-lam * tt),
            t, y,
            p0=[A0, 0.3],
            maxfev=4000,
            bounds=([0, 0.001], [np.inf, 10.0]),
        )
        A_fit, lam_fit = popt
        y_pred = baseline + A_fit * np.exp(-lam_fit * t)
        ss_res = float(np.sum((y - y_pred) ** 2))
        ss_tot = float(np.sum((y - y.mean()) ** 2))
        r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0
        if r2 >= DECAY_R2_GATE and lam_fit > 0:
            return {
                "decay_lambda": float(lam_fit),
                "decay_half_life_h": float(np.log(2) / lam_fit),
                "decay_r2": r2,
                "decay_fallback_linear": False,
                "decay_linear_slope": np.nan,
            }
    except (RuntimeError, ValueError):
        r2 = np.nan

    # Linear fallback
    try:
        slope = float(np.polyfit(t, y, 1)[0])
    except Exception:
        slope = np.nan
    return {
        "decay_lambda": np.nan,
        "decay_half_life_h": np.nan,
        "decay_r2": r2 if "r2" in locals() else np.nan,
        "decay_fallback_linear": True,
        "decay_linear_slope": slope,
    }


def _extract_one(event: pd.Series, ridership: pd.DataFrame) -> dict:
    base = {
        "event_id": event["event_id"],
        "target_key": event["target_key"],
        "event_type": event["event_type"],
        "event_name": event["event_name"],
        "date": event["event_start_dt"].date(),
        "event_start_dt": event["event_start_dt"],
        "event_end_dt": event["event_end_dt"],
    }

    window_start = event["event_start_dt"] - timedelta(hours=WINDOW_PRE_HOURS)
    window_end = event["event_end_dt"] + timedelta(hours=WINDOW_POST_HOURS)
    hourly = _aggregate_window(ridership, event["target_key"], window_start, window_end)
    if hourly.empty:
        return {**base, "status": "empty_window"}

    # --- peak intensity & timing ----------------------------------------
    peak_start = event["event_start_dt"] - timedelta(hours=PEAK_BUFFER_HOURS)
    peak_end = event["event_end_dt"] + timedelta(hours=PEAK_BUFFER_HOURS)
    peak_data = hourly.loc[(hourly.index >= peak_start) & (hourly.index <= peak_end)]
    if peak_data.empty or peak_data["pct_dev"].isna().all():
        return {**base, "status": "empty_peak"}
    peak_idx = peak_data["pct_dev"].idxmax()
    peak_intensity = float(peak_data.loc[peak_idx, "pct_dev"])
    peak_hour_offset = (peak_idx - event["event_start_dt"]).total_seconds() / 3600

    # --- lead time -------------------------------------------------------
    pre = hourly.loc[hourly.index < event["event_start_dt"]]
    pre_trigger = pre.index[pre["ratio"] >= LEAD_TRIGGER]
    if len(pre_trigger):
        lead_time_h = max(0.0, (event["event_start_dt"] - pre_trigger[0]).total_seconds() / 3600)
    else:
        lead_time_h = 0.0

    # --- lag time --------------------------------------------------------
    post = hourly.loc[hourly.index > event["event_end_dt"]].copy()
    post_return = post.index[post["ratio"] <= LAG_RETURN]
    if len(post_return):
        lag_time_h = (post_return[0] - event["event_end_dt"]).total_seconds() / 3600
    else:
        lag_time_h = float(WINDOW_POST_HOURS)         # capped

    # --- asymmetry -------------------------------------------------------
    asymmetry = lead_time_h / lag_time_h if lag_time_h > 0 else np.nan

    # --- decay -----------------------------------------------------------
    decay = _fit_decay(post, event["event_end_dt"])

    return {
        **base,
        "status": "ok",
        "peak_intensity": peak_intensity,
        "peak_hour_offset_h": peak_hour_offset,
        "lead_time_h": lead_time_h,
        "lag_time_h": lag_time_h,
        "asymmetry_ratio": asymmetry,
        **decay,
    }


def extract(events: pd.DataFrame, ridership: pd.DataFrame) -> pd.DataFrame:
    events_t = _attach_event_times(events)
    rows = [_extract_one(ev, ridership) for _, ev in events_t.iterrows()]
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# report
# ---------------------------------------------------------------------------

def build_report(feats: pd.DataFrame) -> str:
    buf = StringIO()
    buf.write("# Fingerprint Feature Extraction Report — 2024\n\n")
    buf.write(
        "*Generated by `fingerprint.extract`. One row per matched event. "
        "All five fingerprint dimensions in a single tidy frame for the "
        "clustering layer.*\n"
    )
    buf.write(f"\nTotal events processed: **{len(feats)}**\n")
    n_ok = int((feats["status"] == "ok").sum())
    buf.write(f"Successful extractions: **{n_ok}**\n")
    if n_ok < len(feats):
        bad = feats[feats["status"] != "ok"]
        buf.write("\nFailures by reason:\n\n")
        buf.write(bad["status"].value_counts().to_frame("count").to_markdown() + "\n")

    ok = feats.loc[feats["status"] == "ok"].copy()

    # --- summary by event type ------------------------------------------
    buf.write("\n## Median feature values by event type\n\n")
    cols = ["peak_intensity", "lead_time_h", "lag_time_h", "asymmetry_ratio",
            "decay_half_life_h", "decay_r2"]
    by_type = ok.groupby(["target_key", "event_type"], observed=True)[cols].median().round(2)
    buf.write(by_type.to_markdown() + "\n")

    # --- decay fit success rate ----------------------------------------
    buf.write("\n## Exponential decay fit success\n\n")
    fit_summary = (
        ok.groupby(["target_key", "event_type"], observed=True)["decay_fallback_linear"]
        .agg(
            n="count",
            n_linear_fallback=lambda s: int((s == True).sum()),
            n_exp_fit=lambda s: int((s == False).sum()),
        )
    )
    fit_summary["pct_exp"] = (fit_summary["n_exp_fit"] / fit_summary["n"] * 100).round(1)
    buf.write(fit_summary.to_markdown() + "\n")

    # --- distinguishing the marquee questions --------------------------
    buf.write("\n## Knicks vs Rangers at MSG — feature comparison\n\n")
    msg = ok[(ok["target_key"] == "msg_penn") & ok["event_type"].isin(["Sports-NBA", "Sports-NHL"])]
    if not msg.empty:
        cmp = msg.groupby("event_type", observed=True)[cols].agg(["median", "std"]).round(2)
        buf.write(cmp.to_markdown() + "\n")

    buf.write("\n## MLB day vs night games at Yankee Stadium\n\n")
    yk = ok[(ok["target_key"] == "yankee") & (ok["event_type"] == "Sports-MLB")].copy()
    yk["dn"] = yk["event_start_dt"].apply(
        lambda dt: "day" if dt.hour < 17 else "night"
    )
    cmp_yk = yk.groupby("dn", observed=True)[cols].agg(["median", "std"]).round(2)
    buf.write(cmp_yk.to_markdown() + "\n")

    # --- top / extreme events ------------------------------------------
    buf.write("\n## Top 10 events by peak_intensity (sanity check)\n\n")
    top = ok.nlargest(10, "peak_intensity")[
        ["date", "target_key", "event_type", "event_name", "peak_intensity",
         "lead_time_h", "lag_time_h", "asymmetry_ratio", "decay_half_life_h", "decay_r2"]
    ].round(2)
    buf.write(top.to_markdown(index=False) + "\n")

    return buf.getvalue()


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--suffix",
        default="_v2",
        help="Which baseline+match version to feed from (default '_v2').",
    )
    args = parser.parse_args(argv)
    suf = args.suffix

    ridership_path = DATA_PROCESSED / f"ridership_with_baseline{suf}.parquet"
    matches_path = DATA_PROCESSED / f"event_matches{suf}.csv"
    events_path = gt_config.EVENTS_CSV

    log.info("Loading ridership: %s", ridership_path)
    ridership = pd.read_parquet(ridership_path)
    ridership["transit_timestamp"] = pd.to_datetime(ridership["transit_timestamp"])
    log.info("Loaded %d rows", len(ridership))

    log.info("Loading matches: %s", matches_path)
    matches = pd.read_csv(matches_path)
    matched_ids = matches.loc[matches["matched"].astype(bool), "event_id"].tolist()
    log.info("Matched events: %d", len(matched_ids))

    log.info("Loading events: %s", events_path)
    events = pd.read_csv(events_path)
    events = events[events["event_id"].isin(matched_ids)].copy()
    log.info("Filtered to %d matched events", len(events))

    log.info("Extracting features ...")
    feats = extract(events, ridership)
    log.info("Done: %d feature rows; %d ok",
             len(feats), int((feats["status"] == "ok").sum()))

    out_path = DATA_PROCESSED / "event_features.parquet"
    feats.to_parquet(out_path, index=False)
    log.info("Wrote %s", out_path)

    report = build_report(feats)
    report_path = DATA_PROCESSED / "fingerprint_report.md"
    report_path.write_text(report)
    log.info("Wrote %s", report_path)
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
