"""MLB regular-season home games for the Yankees and Mets.

baseball-reference does not publish a start-time column on its team
schedule pages — only `D/N` (day/night). We approximate:
  D -> 13:00
  N -> 19:00
and flag the approximation in `notes`. Anomaly fingerprinting tolerates
a ±30-minute start-time error because the lead/lag windows are ±3h.

Postseason home games are NOT covered by this schedule page; they
arrive via `mlb_postseason.py` (hand-curated for 2024).
"""
from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta

import pandas as pd

from .. import config
from ..schema import Event
from .sports_reference import read_schedule_table

log = logging.getLogger(__name__)

# Day/Night → default start time when no explicit time is available.
START_TIME_BY_DN = {"D": time(13, 0), "N": time(19, 0)}


def _parse_team(team_abbr: str, year: int) -> list[Event]:
    info = config.TEAMS[team_abbr]
    url = config.URLS["mlb"][team_abbr]
    df = read_schedule_table(url, cache_name=f"mlb_{team_abbr}_{year}")

    # Drop section-header rows (the ones where 'Gm#' is a non-numeric label).
    df = df[df["Gm#"].astype(str).str.isdigit()].copy()
    df["Gm#"] = df["Gm#"].astype(int)

    # Home games only: the unnamed "@" column is NaN for home.
    away_col = "Unnamed: 4"
    df = df[df[away_col].isna() | (df[away_col].astype(str).str.strip() == "")].copy()

    # Doubleheaders are listed as "Wednesday, Aug 7 (1)" and "(2)". Extract
    # the game-of-day suffix separately so both rows parse and we can label
    # them as G1/G2 in event_name.
    pat = r"^(?P<base>.+?)(?:\s*\((?P<gn>\d)\))?$"
    extracted = df["Date"].str.extract(pat)
    df["date_parsed"] = pd.to_datetime(
        extracted["base"] + f", {year}", format="%A, %b %d, %Y", errors="coerce"
    ).dt.date
    df["gn"] = extracted["gn"]

    events: list[Event] = []
    for _, row in df.iterrows():
        if pd.isna(row["date_parsed"]):
            log.warning("[%s] could not parse date: %r", team_abbr, row["Date"])
            continue
        dn = str(row["D/N"]).strip().upper()
        start = START_TIME_BY_DN.get(dn, time(19, 0))
        end = (
            datetime.combine(row["date_parsed"], start)
            + timedelta(minutes=config.DEFAULT_DURATIONS_MIN["Sports-MLB"])
        ).time()
        att = row["Attendance"]
        gn = row.get("gn")
        name = f"{team_abbr} vs {row['Opp']}"
        notes = f"D/N={dn or '?'} (start time approximated from D/N)"
        if pd.notna(gn):
            name = f"{name} (G{gn})"
            notes = f"{notes}; game {gn} of doubleheader"
        events.append(
            Event(
                date=row["date_parsed"],
                start_time=start,
                end_time=end,
                venue_station_id=info["venue_station_id"],
                target_key=info["target_key"],
                event_name=name,
                event_type="Sports-MLB",
                expected_attendance=int(att) if pd.notna(att) and str(att).strip() else None,
                source="baseball-reference.com",
                source_url=url,
                notes=notes,
            )
        )

    log.info("[%s] %d home games parsed", team_abbr, len(events))
    return events


def collect(year: int = 2024) -> list[Event]:
    events: list[Event] = []
    for team_abbr in ("NYY", "NYM"):
        events.extend(_parse_team(team_abbr, year))
    return events
