"""Validate the cached 2024 ridership Parquets and emit a Markdown DQ report.

Run as a module:
    python -m ingest.data_quality

Checks performed per target:
  * Row count, column dtypes
  * Date range covered vs expected 2024-01-01 .. 2024-12-31
  * Missing hours (in the (station_complex_id x hour) grid)
  * Duplicate (timestamp, complex_id, payment_method, fare_class) rows
  * Negative or null ridership
  * Per-station, per-payment-method aggregates
  * Top 10 hours by ridership (gut-check that big-event hours look plausible)

Writes data/processed/data_quality_report.md.
"""
from __future__ import annotations

import logging
import sys
from io import StringIO
from pathlib import Path

import pandas as pd

from . import config

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("data_quality")


EXPECTED_START = pd.Timestamp("2024-01-01 00:00:00")
EXPECTED_END = pd.Timestamp("2024-12-31 23:00:00")  # inclusive last hour


def _section(buf: StringIO, title: str, level: int = 2) -> None:
    buf.write(f"\n{'#' * level} {title}\n\n")


def _df_to_md(df: pd.DataFrame, max_rows: int = 20) -> str:
    if len(df) > max_rows:
        df = df.head(max_rows)
    return df.to_markdown(index=False)


def check_target(buf: StringIO, target: config.StationArchetype) -> dict[str, object]:
    path = config.raw_parquet_path(target.key)
    _section(buf, f"`{target.key}` — {target.label}", level=2)
    buf.write(f"*Archetype:* {target.archetype}\n\n")
    buf.write(f"*Source file:* `{path.relative_to(config.PROJECT_ROOT)}`\n\n")

    if not path.exists():
        buf.write("**MISSING PARQUET.** Run `python -m ingest.pull_2024` first.\n")
        return {"target": target.key, "ok": False, "reason": "missing_parquet"}

    df = pd.read_parquet(path)
    stats: dict[str, object] = {
        "target": target.key,
        "rows": len(df),
        "complex_ids_in_data": sorted(df["station_complex_id"].dropna().unique().tolist()),
        "configured_complex_ids": list(target.complex_ids),
    }

    # --- row count + schema -----------------------------------------------
    _section(buf, "Schema & counts", level=3)
    buf.write(f"- Rows: **{len(df):,}**\n")
    buf.write(f"- Configured complex_ids: `{list(target.complex_ids)}`\n")
    buf.write(f"- Complex_ids actually present: `{stats['complex_ids_in_data']}`\n")
    dtypes = pd.DataFrame({"column": df.columns, "dtype": df.dtypes.astype(str).values})
    buf.write("\n" + _df_to_md(dtypes) + "\n")

    if not df["station_complex_id"].dropna().isin(target.complex_ids).all():
        buf.write("\n**WARNING:** rows present whose `station_complex_id` is not in the target config.\n")

    # --- date range --------------------------------------------------------
    _section(buf, "Date range", level=3)
    ts = df["transit_timestamp"]
    actual_min, actual_max = ts.min(), ts.max()
    buf.write(f"- Expected: `{EXPECTED_START}` .. `{EXPECTED_END}`\n")
    buf.write(f"- Observed: `{actual_min}` .. `{actual_max}`\n")
    stats["min_ts"] = str(actual_min)
    stats["max_ts"] = str(actual_max)
    if actual_min > EXPECTED_START:
        buf.write(f"- **GAP at start:** {actual_min - EXPECTED_START} late.\n")
    if actual_max < EXPECTED_END:
        buf.write(f"- **GAP at end:** {EXPECTED_END - actual_max} early.\n")

    # --- missing hours per complex ----------------------------------------
    _section(buf, "Missing hours per complex_id", level=3)
    full_hours = pd.date_range(EXPECTED_START, EXPECTED_END, freq="h")
    missing_rows = []
    for cid in target.complex_ids:
        cid_hours = pd.DatetimeIndex(
            sorted(df.loc[df["station_complex_id"] == cid, "transit_timestamp"].unique())
        )
        missing = full_hours.difference(cid_hours)
        missing_rows.append(
            {"complex_id": cid, "expected": len(full_hours), "observed": len(cid_hours), "missing": len(missing)}
        )
    missing_df = pd.DataFrame(missing_rows)
    buf.write(_df_to_md(missing_df) + "\n")
    stats["missing_hours"] = missing_df.to_dict(orient="records")

    # --- duplicates -------------------------------------------------------
    _section(buf, "Duplicate rows", level=3)
    dup_keys = ["transit_timestamp", "station_complex_id", "payment_method", "fare_class_category"]
    dup_mask = df.duplicated(subset=dup_keys, keep=False)
    n_dups = int(dup_mask.sum())
    buf.write(f"- Duplicate rows on `{dup_keys}`: **{n_dups:,}**\n")
    stats["duplicates"] = n_dups
    if n_dups:
        sample = df.loc[dup_mask].sort_values(dup_keys).head(10)
        buf.write("\nSample of duplicates:\n\n" + _df_to_md(sample) + "\n")

    # --- negatives / nulls -------------------------------------------------
    _section(buf, "Ridership sanity", level=3)
    null_rides = int(df["ridership"].isna().sum())
    neg_rides = int((df["ridership"] < 0).sum())
    buf.write(f"- Null `ridership`: **{null_rides:,}**\n")
    buf.write(f"- Negative `ridership`: **{neg_rides:,}**\n")
    buf.write(f"- Min ridership: {df['ridership'].min()}\n")
    buf.write(f"- Max ridership: {df['ridership'].max()}\n")
    buf.write(f"- Median (non-zero) ridership: {df.loc[df['ridership'] > 0, 'ridership'].median()}\n")
    stats["null_ridership"] = null_rides
    stats["neg_ridership"] = neg_rides

    # --- payment method breakdown -----------------------------------------
    _section(buf, "Payment method × fare class", level=3)
    pm = (
        df.groupby(["payment_method", "fare_class_category"], dropna=False)["ridership"]
        .agg(["count", "sum", "mean"])
        .round(2)
        .reset_index()
        .sort_values("sum", ascending=False)
    )
    buf.write(_df_to_md(pm, max_rows=30) + "\n")

    # --- top 10 hours (gut-check the event signal exists) -----------------
    _section(buf, "Top 10 hours by total ridership (gut-check)", level=3)
    hourly = (
        df.groupby(["transit_timestamp", "station_complex_id"])["ridership"]
        .sum()
        .reset_index()
        .sort_values("ridership", ascending=False)
        .head(10)
    )
    buf.write(_df_to_md(hourly) + "\n")

    stats["ok"] = (
        null_rides == 0
        and neg_rides == 0
        and n_dups == 0
        and actual_min <= EXPECTED_START
        and actual_max >= EXPECTED_END
    )
    return stats


def main() -> int:
    buf = StringIO()
    buf.write("# Data Quality Report — 2024 MTA Hourly Ridership\n")
    buf.write(f"\n*Generated by `ingest.data_quality` from cached Parquets in `data/raw/`.*\n")

    summary_rows = []
    for target in config.TARGETS:
        stats = check_target(buf, target)
        summary_rows.append(stats)

    # Move the summary table to the top of the report.
    sumdf = pd.DataFrame(
        [
            {
                "target": s["target"],
                "rows": s.get("rows", 0),
                "complex_ids": s.get("configured_complex_ids", []),
                "duplicates": s.get("duplicates", "—"),
                "null_ridership": s.get("null_ridership", "—"),
                "neg_ridership": s.get("neg_ridership", "—"),
                "ok": s.get("ok", False),
            }
            for s in summary_rows
        ]
    )
    header = StringIO()
    header.write("# Data Quality Report — 2024 MTA Hourly Ridership\n")
    header.write(f"\n*Generated by `ingest.data_quality` from cached Parquets in `data/raw/`.*\n")
    header.write("\n## Summary\n\n")
    header.write(sumdf.to_markdown(index=False) + "\n")
    # Drop the duplicate H1 from `buf` (the first line) before appending.
    rest = "\n".join(buf.getvalue().splitlines()[2:])
    full = header.getvalue() + "\n" + rest

    out = config.DATA_PROCESSED / "data_quality_report.md"
    out.write_text(full)
    log.info("Wrote report -> %s", out)

    all_ok = all(s.get("ok", False) for s in summary_rows)
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
