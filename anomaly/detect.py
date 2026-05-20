"""Two complementary anomaly flags per (timestamp, complex_id).

Both work on `ridership_with_baseline.parquet`. We compute both because
they answer different questions:

  ratio flag    : "is this hour at least Nx the long-run baseline?"
                  Stable but blind to drift — a station that quietly
                  trended upward all year still uses last-spring's
                  baseline as a reference.

  rolling z     : "is this hour many sigma above what was typical for
                  the SAME hour-of-week in the recent past?" Robust to
                  slow drift; sensitive to abrupt change. Matched on
                  hour-of-week so morning rush doesn't pollute evening
                  z-scores.

We emit both flags and let the analysis layer compare.
"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)


def add_ratio_score(df: pd.DataFrame) -> pd.DataFrame:
    """Add `anomaly_ratio` = actual / baseline and `anomaly_score` = ratio - 1.

    NaN-safe. Where baseline is 0 or NaN, both columns are NaN (not inf).
    """
    out = df.copy()
    baseline = out["baseline_ridership"]
    out["anomaly_ratio"] = np.where(
        (baseline.notna()) & (baseline > 0),
        out["ridership"] / baseline,
        np.nan,
    )
    out["anomaly_score"] = out["anomaly_ratio"] - 1.0
    return out


def add_rolling_zscore(
    df: pd.DataFrame,
    window_occurrences: int = 4,
    min_history: int = 2,
) -> pd.DataFrame:
    """Per-(complex_id, day_of_week, hour) rolling z-score.

    Each (dow, hour) cell occurs once per week. A 28-day window therefore
    equals `window_occurrences=4` prior same-hour-of-week observations.

    The rolling stats use `.shift(1)` so the current hour is never part
    of its own reference distribution.
    """
    out = df.sort_values(
        ["station_complex_id", "day_of_week", "hour", "transit_timestamp"]
    ).reset_index(drop=True)
    g = out.groupby(["station_complex_id", "day_of_week", "hour"], sort=False)

    out["rolling_mean"] = g["ridership"].transform(
        lambda s: s.rolling(window=window_occurrences, min_periods=min_history).mean().shift(1)
    )
    out["rolling_std"] = g["ridership"].transform(
        lambda s: s.rolling(window=window_occurrences, min_periods=min_history).std().shift(1)
    )
    out["z_score"] = np.where(
        (out["rolling_std"].notna()) & (out["rolling_std"] > 0),
        (out["ridership"] - out["rolling_mean"]) / out["rolling_std"],
        np.nan,
    )
    return out


def add_flags(
    df: pd.DataFrame,
    ratio_threshold: float = 1.5,
    z_threshold: float = 3.0,
) -> pd.DataFrame:
    """Boolean flag columns. NaN inputs → False (no flag)."""
    out = df.copy()
    out["flag_ratio"] = out["anomaly_ratio"].fillna(0) >= ratio_threshold
    out["flag_z"] = out["z_score"].fillna(0) >= z_threshold
    out["flag_either"] = out["flag_ratio"] | out["flag_z"]
    out["flag_both"] = out["flag_ratio"] & out["flag_z"]
    return out


def detect(
    df: pd.DataFrame,
    *,
    ratio_threshold: float = 1.5,
    z_threshold: float = 3.0,
    window_occurrences: int = 4,
) -> pd.DataFrame:
    """End-to-end: ratio score + rolling z + flags."""
    out = add_ratio_score(df)
    out = add_rolling_zscore(out, window_occurrences=window_occurrences)
    out = add_flags(out, ratio_threshold=ratio_threshold, z_threshold=z_threshold)
    return out
