"""Compute seasonal hour-of-week × day-of-week median baselines per complex.

Run as a module:
    python -m baseline.build

Pipeline:
  1. Load each archetype's cached Parquet.
  2. Aggregate ridership across (payment_method, fare_class_category) splits
     so one row = one (complex_id, hour) total.
  3. Reindex to the full 2024 hourly grid so missing hours become NaN
     (DST spring-forward, plus the 7-train Mets gaps).
  4. Tag each row with season, day_of_week, hour, is_federal_holiday.
  5. Compute the baseline as the median ridership in each
     (complex_id, season, dow, hour) cell, excluding holidays and NaN
     hours. The median is robust to event spikes by design.
  6. Attach the baseline back onto the time series.

Outputs:
  data/processed/baselines.parquet
      long-format: target_key, station_complex_id, season, day_of_week,
      hour, n_observations, baseline_ridership
  data/processed/ridership_with_baseline.parquet
      every hour of 2024 per complex, with calendar tags and baseline
  data/processed/baseline_quality_report.md
      sanity checks for review
"""
from __future__ import annotations

import logging
from io import StringIO

import numpy as np
import pandas as pd

from ingest import config
from .seasons import tag_all

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("baseline.build")


FULL_GRID = pd.date_range("2024-01-01 00:00", "2024-12-31 23:00", freq="h")
DOW_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


# ---------------------------------------------------------------------------
# 1-3. Load, aggregate, reindex
# ---------------------------------------------------------------------------

def load_target_aggregated(target: config.StationArchetype) -> pd.DataFrame:
    """Read raw Parquet for `target` and aggregate to (complex_id, hour) totals.

    Reindexes each complex to the full 2024 grid so missing hours = NaN.
    Returns columns: transit_timestamp, station_complex_id, ridership.
    """
    raw = pd.read_parquet(config.raw_parquet_path(target.key))
    log.info("[%s] loaded %d raw rows", target.key, len(raw))

    out_chunks: list[pd.DataFrame] = []
    for cid in target.complex_ids:
        sub = raw.loc[raw["station_complex_id"] == cid]
        hourly = sub.groupby("transit_timestamp")["ridership"].sum()
        hourly = hourly.reindex(FULL_GRID)
        hourly.index.name = "transit_timestamp"
        chunk = hourly.reset_index()
        chunk["station_complex_id"] = cid
        out_chunks.append(chunk)

    df = pd.concat(out_chunks, ignore_index=True)
    df["station_complex_id"] = df["station_complex_id"].astype("string")
    log.info(
        "[%s] reindexed: %d rows across %d complexes; NaN hours = %d",
        target.key,
        len(df),
        len(target.complex_ids),
        int(df["ridership"].isna().sum()),
    )
    return df


# ---------------------------------------------------------------------------
# 5. Compute baselines
# ---------------------------------------------------------------------------

def compute_baselines(df: pd.DataFrame) -> pd.DataFrame:
    """Median ridership per (complex_id, season, day_of_week, hour).

    Excludes federal holidays and NaN ridership from the pool. Carries the
    sample size into the output as `n_observations` so downstream code can
    threshold on cells with too few datapoints.
    """
    pool = df.loc[~df["is_federal_holiday"] & df["ridership"].notna()].copy()
    grouped = pool.groupby(
        ["station_complex_id", "season", "day_of_week", "hour"],
        observed=True,
        as_index=False,
    )
    baseline = grouped["ridership"].agg(
        baseline_ridership="median",
        n_observations="count",
    )
    return baseline


# ---------------------------------------------------------------------------
# 6. Attach
# ---------------------------------------------------------------------------

def attach_baselines(df: pd.DataFrame, baselines: pd.DataFrame) -> pd.DataFrame:
    """Left-merge baseline_ridership onto every hourly row."""
    keys = ["station_complex_id", "season", "day_of_week", "hour"]
    merged = df.merge(
        baselines[keys + ["baseline_ridership", "n_observations"]],
        on=keys,
        how="left",
        validate="many_to_one",
    )
    merged["residual"] = merged["ridership"] - merged["baseline_ridership"]
    return merged


# ---------------------------------------------------------------------------
# 7. Reporting
# ---------------------------------------------------------------------------

def _section(buf: StringIO, title: str, level: int = 2) -> None:
    buf.write(f"\n{'#' * level} {title}\n\n")


def _md(df: pd.DataFrame, max_rows: int = 30) -> str:
    return df.head(max_rows).to_markdown(index=False)


def build_report(baselines: pd.DataFrame, ts: pd.DataFrame) -> str:
    buf = StringIO()
    buf.write("# Baseline Quality Report — 2024\n\n")
    buf.write(
        "*Generated by `baseline.build`. Each baseline cell is the median "
        "ridership for one (complex_id × season × day_of_week × hour), "
        "computed over non-holiday hours with non-NaN ridership.*\n"
    )

    # ---------- summary per (target × complex × season) -------------------
    _section(buf, "Per (target × complex × season) summary", level=2)
    summary = (
        baselines.groupby(["target_key", "station_complex_id", "season"], observed=True)
        .agg(
            cells_filled=("baseline_ridership", "count"),
            min_baseline=("baseline_ridership", "min"),
            median_baseline=("baseline_ridership", "median"),
            max_baseline=("baseline_ridership", "max"),
            mean_n_obs=("n_observations", "mean"),
            min_n_obs=("n_observations", "min"),
        )
        .round(2)
        .reset_index()
    )
    buf.write(_md(summary, max_rows=100) + "\n")
    buf.write(
        "\n*168 = full coverage of the 7×24 hour-of-week grid. mean_n_obs ~30 "
        "for summer, ~22 for winter is the expectation.*\n"
    )

    # ---------- sample size adequacy --------------------------------------
    _section(buf, "Sample size adequacy", level=2)
    n_dist = baselines["n_observations"].describe(percentiles=[0.05, 0.25, 0.5, 0.75, 0.95]).round(2)
    buf.write("Distribution of cell-level sample sizes:\n\n")
    buf.write(n_dist.to_frame("n_observations").to_markdown() + "\n")

    low_cells = baselines.loc[baselines["n_observations"] < 5].sort_values(
        "n_observations"
    )
    buf.write(f"\nCells with n < 5: **{len(low_cells)}**\n")
    if len(low_cells):
        buf.write("\nLow-sample cells (first 20):\n\n")
        buf.write(_md(low_cells[
            ["target_key", "station_complex_id", "season", "day_of_week", "hour",
             "n_observations", "baseline_ridership"]
        ], max_rows=20) + "\n")

    # ---------- rush hour shape sanity check (Times Sq) -------------------
    _section(buf, "Sanity: rush-hour structure at Times Sq (complex 611, weekday summer)", level=2)
    tsq = baselines.loc[
        (baselines["station_complex_id"] == "611")
        & (baselines["season"] == "summer")
        & (baselines["day_of_week"] == 2)  # Wed
    ].sort_values("hour")
    if len(tsq):
        buf.write(_md(tsq[["hour", "n_observations", "baseline_ridership"]], max_rows=24) + "\n")
        buf.write(
            "\n*Expect strong rush-hour peaks at 08-09 and 17-18, deep trough at 03-04.*\n"
        )

    # ---------- summer vs winter at Yankee Stadium ------------------------
    _section(buf, "Sanity: summer vs winter delta at Yankee Stadium (complex 604, evenings)", level=2)
    yk_evenings = (
        baselines.loc[
            (baselines["station_complex_id"] == "604") & (baselines["hour"].between(18, 22))
        ]
        .groupby(["season", "day_of_week"], observed=True)["baseline_ridership"]
        .mean()
        .unstack("season")
        .round(1)
    )
    yk_evenings.index = [DOW_NAMES[i] for i in yk_evenings.index]
    yk_evenings["summer - winter"] = (yk_evenings["summer"] - yk_evenings["winter"]).round(1)
    buf.write(_md(yk_evenings.reset_index().rename(columns={"index": "dow"})) + "\n")
    buf.write(
        "\n*Median excludes individual game-day spikes by design, so the delta "
        "captures ambient baseball-season effect (transit, restaurants, foot "
        "traffic) — not the game crowds themselves. Positive summer numbers "
        "still expected.*\n"
    )

    # ---------- residual sanity -------------------------------------------
    _section(buf, "Residual distribution sanity (per target)", level=2)
    resid_summary = (
        ts.groupby("target_key", observed=True)["residual"]
        .describe(percentiles=[0.01, 0.5, 0.99])
        .round(1)
    )
    buf.write(resid_summary.to_markdown() + "\n")
    buf.write(
        "\n*99th-percentile residual is roughly the magnitude an event can add to "
        "a single hour. Sports/concert venues should have much larger tails than "
        "times_sq.*\n"
    )

    return buf.getvalue()


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def main() -> int:
    all_ts: list[pd.DataFrame] = []
    all_bl: list[pd.DataFrame] = []

    for target in config.TARGETS:
        df = load_target_aggregated(target)
        df = tag_all(df)
        baselines = compute_baselines(df)
        baselines["target_key"] = target.key

        df_with = attach_baselines(df, baselines)
        df_with["target_key"] = target.key

        log.info(
            "[%s] baseline cells: %d; ts rows: %d; ts NaN ridership: %d; "
            "ts NaN baseline (likely low-sample cells): %d",
            target.key,
            len(baselines),
            len(df_with),
            int(df_with["ridership"].isna().sum()),
            int(df_with["baseline_ridership"].isna().sum()),
        )
        all_ts.append(df_with)
        all_bl.append(baselines)

    combined_ts = pd.concat(all_ts, ignore_index=True)
    combined_bl = pd.concat(all_bl, ignore_index=True)

    ts_out = config.DATA_PROCESSED / "ridership_with_baseline.parquet"
    bl_out = config.DATA_PROCESSED / "baselines.parquet"
    combined_ts.to_parquet(ts_out, index=False)
    combined_bl.to_parquet(bl_out, index=False)
    log.info("Wrote %s (%d rows)", ts_out, len(combined_ts))
    log.info("Wrote %s (%d rows)", bl_out, len(combined_bl))

    report = build_report(combined_bl, combined_ts)
    report_path = config.DATA_PROCESSED / "baseline_quality_report.md"
    report_path.write_text(report)
    log.info("Wrote %s", report_path)
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
