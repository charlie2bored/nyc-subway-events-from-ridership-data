"""Shared helpers for parsing sports-reference.com family schedule pages.

baseball-reference, basketball-reference, hockey-reference share a layout:
one big HTML table on the team-season page with one row per game. The
schedule table is *not* in an HTML comment on these pages (unlike some of
the advanced-stats tables on the site), so `pandas.read_html` works
directly.

The schemas differ slightly between sports — see callers in mlb.py,
nba.py, nhl.py.
"""
from __future__ import annotations

import logging
from io import StringIO

import pandas as pd

from .. import config
from ._http import fetch_text

log = logging.getLogger(__name__)


def fetch_schedule_html(url: str, cache_name: str) -> str:
    cache_path = config.GT_RAW / "sports_reference" / f"{cache_name}.html"
    return fetch_text(
        url=url,
        cache_path=cache_path,
        delay=config.SPORTS_REFERENCE_DELAY,
    )


def read_schedule_table(url: str, cache_name: str) -> pd.DataFrame:
    html = fetch_schedule_html(url, cache_name)
    tables = pd.read_html(StringIO(html))
    if not tables:
        raise RuntimeError(f"No tables found in {url}")
    # The schedule table is always the first one on the page across
    # all three reference sites.
    return tables[0]


def parse_short_time(t) -> "pd.Timestamp.time | None":
    """Parse basketball/hockey-reference time strings like '7:00p', '1:00p'."""
    from datetime import datetime
    import pandas as pd

    if pd.isna(t):
        return None
    s = str(t).strip().lower()
    if s.endswith("p"):
        s = s[:-1] + "pm"
    elif s.endswith("a"):
        s = s[:-1] + "am"
    try:
        return datetime.strptime(s, "%I:%M%p").time()
    except ValueError:
        return None


def parse_team_schedule(
    *,
    team_abbr: str,
    season_year: int,                # e.g., 2024 for the "2023-24" season
    url: str,
    target_key: str,
    venue_station_id: str,
    event_type: str,
    duration_min: int,
    game_col: str,                   # "G" (basketball) or "GP" (hockey)
    date_format: str,                # "%a, %b %d, %Y" or "%Y-%m-%d"
    away_col: str,                   # "Unnamed: 5" or "Unnamed: 2"
    attendance_col: str,             # "Attend." or "Att."
    start_time_col: str | None,      # "Start (ET)" or None
    default_start_time,              # datetime.time used when start_time_col is None or NaN
    keep_year: int = 2024,
) -> list:
    """Generic team-schedule parser. Used by NBA and NHL callers."""
    import logging
    from datetime import datetime, timedelta

    import pandas as pd

    from ..schema import Event

    log = logging.getLogger(__name__)

    df = read_schedule_table(url, cache_name=f"{event_type.lower()}_{team_abbr}_{season_year}")

    # Drop interstitial header rows where game_col is non-numeric.
    df = df[df[game_col].astype(str).str.isdigit()].copy()

    # Home games: the @ column is NaN/blank for home.
    df = df[df[away_col].isna() | (df[away_col].astype(str).str.strip() == "")].copy()

    df["date_parsed"] = pd.to_datetime(df["Date"], format=date_format, errors="coerce").dt.date

    if start_time_col is not None:
        df["start_parsed"] = df[start_time_col].apply(parse_short_time)
    else:
        df["start_parsed"] = None

    events: list[Event] = []
    for _, row in df.iterrows():
        if pd.isna(row["date_parsed"]) or row["date_parsed"].year != keep_year:
            continue
        start = row["start_parsed"]
        if start is None:
            start = default_start_time
            note_fallback = f"; start time fallback ({start.strftime('%H:%M')})"
        else:
            note_fallback = ""
        end = (
            datetime.combine(row["date_parsed"], start)
            + timedelta(minutes=duration_min)
        ).time()
        att = row[attendance_col]
        events.append(
            Event(
                date=row["date_parsed"],
                start_time=start,
                end_time=end,
                venue_station_id=venue_station_id,
                target_key=target_key,
                event_name=f"{team_abbr} vs {row['Opponent']}",
                event_type=event_type,
                expected_attendance=int(att) if pd.notna(att) and str(att).strip() else None,
                source=url.split("/")[2],
                source_url=url,
                notes=f"season={season_year-1}-{str(season_year)[-2:]}{note_fallback}",
            )
        )

    log.info("[%s/%s] %d home games in calendar %d", event_type, team_abbr, len(events), keep_year)
    return events
