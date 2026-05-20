"""Season + federal-holiday tagging.

Two categorical axes are attached to every hourly observation:

  season ∈ {"summer", "winter"}
    summer = April .. October  (months 4..10)
    winter = November .. March (months 11, 12, 1, 2, 3)
    Picked to keep baseball season (Apr-Oct) and NBA/NHL season (Nov-Mar)
    on opposite sides — neither contaminates the other's baseline.

  is_federal_holiday : bool
    Holidays are removed from the baseline-input pool but still kept in
    the time series (with NaN ridership during the baseline computation
    step and full value at attach time). This lets holiday days light up
    as anomalies (NYE at Times Sq, July 4 fireworks, parades) instead of
    being absorbed into the reference.
"""
from __future__ import annotations

import functools

import holidays
import numpy as np
import pandas as pd

SUMMER_MONTHS = frozenset({4, 5, 6, 7, 8, 9, 10})


def tag_season(ts: pd.Series) -> pd.Series:
    """Map a datetime Series to {'summer', 'winter'} per the SUMMER_MONTHS rule."""
    is_summer = ts.dt.month.isin(SUMMER_MONTHS)
    return pd.Series(np.where(is_summer, "summer", "winter"), index=ts.index, dtype="string")


@functools.lru_cache(maxsize=4)
def _holiday_calendar(year: int) -> holidays.HolidayBase:
    return holidays.country_holidays("US", years=year)


def tag_holiday(ts: pd.Series) -> pd.DataFrame:
    """Return a 2-column DataFrame: is_federal_holiday (bool), holiday_name (str|None)."""
    dates = ts.dt.date
    years = {d.year for d in dates.dropna().unique()}
    cal = {}
    for y in years:
        cal.update(dict(_holiday_calendar(y)))
    names = dates.map(lambda d: cal.get(d) if d is not None else None)
    return pd.DataFrame(
        {
            "is_federal_holiday": names.notna(),
            "holiday_name": names.astype("string"),
        },
        index=ts.index,
    )


def tag_all(df: pd.DataFrame, ts_col: str = "transit_timestamp") -> pd.DataFrame:
    """Attach season, day_of_week, hour, and holiday columns."""
    out = df.copy()
    ts = out[ts_col]
    out["season"] = tag_season(ts)
    out["day_of_week"] = ts.dt.dayofweek.astype("int8")        # 0=Mon .. 6=Sun
    out["hour"] = ts.dt.hour.astype("int8")
    out = out.join(tag_holiday(ts))
    return out
