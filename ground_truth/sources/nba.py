"""NBA home games (Knicks at MSG, Nets at Barclays) within calendar 2024.

NBA seasons cross calendar years. To get all 2024 dates we pull two URLs
per team — the 2023-24 season (page named 2024_games.html) and the
2024-25 season (2025_games.html) — and filter to calendar 2024 dates.

Regular season only; playoff supplements live in `nba_postseason.py`.
"""
from __future__ import annotations

import logging
from datetime import time

from .. import config
from ..schema import Event
from .sports_reference import parse_team_schedule

log = logging.getLogger(__name__)


def collect(keep_year: int = 2024) -> list[Event]:
    events: list[Event] = []
    for team_abbr in ("NYK", "BRK"):
        info = config.TEAMS[team_abbr]
        for season_year, url_key in ((2024, f"{team_abbr}_2024"), (2025, f"{team_abbr}_2025")):
            events.extend(
                parse_team_schedule(
                    team_abbr=team_abbr,
                    season_year=season_year,
                    url=config.URLS["nba"][url_key],
                    target_key=info["target_key"],
                    venue_station_id=info["venue_station_id"],
                    event_type="Sports-NBA",
                    duration_min=config.DEFAULT_DURATIONS_MIN["Sports-NBA"],
                    game_col="G",
                    date_format="%a, %b %d, %Y",
                    away_col="Unnamed: 5",
                    attendance_col="Attend.",
                    start_time_col="Start (ET)",
                    default_start_time=time(19, 30),
                    keep_year=keep_year,
                )
            )
    return events
