"""NOAA daily weather for NYC (Central Park) — confound control for matching.

A blizzard or a flood-day will suppress ridership even when an event is
on the schedule. Without weather context, those days look like false
negatives (event happened, anomaly didn't trigger). We pull Central
Park's daily summary so the matcher can tag weather-suppressed
false negatives separately from genuinely-unexplained ones.

Source: NCEI Access Services API (no token required).
Station: USW00094728 (Central Park, NYC).
"""
from __future__ import annotations

import logging
from io import StringIO

import pandas as pd
import requests

from .config import GT_RAW, USER_AGENT

log = logging.getLogger(__name__)


CENTRAL_PARK_STATION = "USW00094728"
# NCEI access service was hanging (slow/unreliable). The static GHCN-Daily
# "access" CSV file for a single station is much faster: ~18MB for the
# full history of Central Park, served from a regular HTTP file endpoint.
GHCN_STATION_URL = (
    "https://www.ncei.noaa.gov/data/global-historical-climatology-network-daily/"
    f"access/{CENTRAL_PARK_STATION}.csv"
)

# Snow/precip/temp thresholds for "weather-suppressed" classification.
# Sources: rough rules-of-thumb that the matcher can override.
HEAVY_RAIN_INCHES = 1.0     # NWS heavy-rain advisory begins ~1" / 24h
HEAVY_SNOW_INCHES = 1.0     # 1" of snow is enough to deter casual ridership
COLD_DEGREES_F = 20.0       # below 20°F suppresses outdoor event attendance


def fetch_central_park(year: int = 2024, force: bool = False) -> pd.DataFrame:
    """Pull and cache one year of Central Park daily summaries.

    Returns a tidy DataFrame keyed by date with columns:
      date, prcp_in, snow_in, snow_depth_in, tmax_f, tmin_f
    """
    cache_path = GT_RAW / "weather" / f"central_park_{year}.csv"
    cache_path.parent.mkdir(parents=True, exist_ok=True)

    if cache_path.exists() and not force:
        log.info("[weather] cache hit: %s", cache_path)
        return pd.read_csv(cache_path, parse_dates=["date"])

    log.info("[weather] GET %s", GHCN_STATION_URL)
    r = requests.get(
        GHCN_STATION_URL,
        headers={"User-Agent": USER_AGENT},
        timeout=120,
    )
    r.raise_for_status()
    raw = pd.read_csv(StringIO(r.text))

    # GHCN-Daily access CSVs are wide-format. Standard columns: STATION,
    # DATE, plus per-element columns (PRCP, SNOW, SNWD, TMAX, TMIN, ...).
    # PRCP / SNOW / SNWD are in tenths of mm; TMAX / TMIN in tenths of °C.
    raw["DATE"] = pd.to_datetime(raw["DATE"])
    raw_year = raw[raw["DATE"].dt.year == year].copy()

    out = pd.DataFrame({"date": raw_year["DATE"]})
    # Convert tenths-of-mm to inches: × 0.1 mm / 25.4 mm/in = × 0.003937
    MM_PER_TENTH = 0.1
    IN_PER_MM = 1 / 25.4
    out["prcp_in"] = pd.to_numeric(raw_year.get("PRCP"), errors="coerce") * MM_PER_TENTH * IN_PER_MM
    out["snow_in"] = pd.to_numeric(raw_year.get("SNOW"), errors="coerce") * IN_PER_MM
    # SNWD is recorded in mm directly (not tenths).
    out["snow_depth_in"] = pd.to_numeric(raw_year.get("SNWD"), errors="coerce") * IN_PER_MM
    # Tenths of °C → °F.
    tmax_c = pd.to_numeric(raw_year.get("TMAX"), errors="coerce") * 0.1
    tmin_c = pd.to_numeric(raw_year.get("TMIN"), errors="coerce") * 0.1
    out["tmax_f"] = tmax_c * 9 / 5 + 32
    out["tmin_f"] = tmin_c * 9 / 5 + 32

    out.to_csv(cache_path, index=False)
    log.info("[weather] cached %d days to %s", len(out), cache_path)
    return out


def is_weather_suppressed(row: pd.Series) -> bool:
    """Heuristic: did weather plausibly suppress ridership on this date?"""
    if pd.notna(row.get("prcp_in")) and row["prcp_in"] >= HEAVY_RAIN_INCHES:
        return True
    if pd.notna(row.get("snow_in")) and row["snow_in"] >= HEAVY_SNOW_INCHES:
        return True
    if pd.notna(row.get("snow_depth_in")) and row["snow_depth_in"] >= 3.0:
        return True
    if pd.notna(row.get("tmax_f")) and row["tmax_f"] <= COLD_DEGREES_F:
        return True
    return False


def annotate(weather_df: pd.DataFrame) -> pd.DataFrame:
    out = weather_df.copy()
    out["weather_suppressed"] = out.apply(is_weather_suppressed, axis=1)
    return out
