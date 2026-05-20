"""NHL home games (Rangers at MSG) within calendar 2024.

Like NBA, the NHL season crosses calendar years. Pull both 2023-24 and
2024-25 schedules and filter to calendar 2024.

Note: MSG hosts both the Knicks (NBA) and Rangers (NHL). When both play
on the same date we keep both events — the residual spike on those days
will be the combined effect.
"""
from __future__ import annotations

import logging
from datetime import time

from .. import config
from ..schema import Event
from .sports_reference import parse_team_schedule

log = logging.getLogger(__name__)


# hockey-reference does not publish start times for Rangers games. Most NHL
# games at MSG start at 19:00 or 19:30 ET — we default to 19:00 with a
# note flagging the approximation.

def collect(keep_year: int = 2024) -> list[Event]:
    info = config.TEAMS["NYR"]
    events: list[Event] = []
    for season_year, url_key in ((2024, "NYR_2024"), (2025, "NYR_2025")):
        events.extend(
            parse_team_schedule(
                team_abbr="NYR",
                season_year=season_year,
                url=config.URLS["nhl"][url_key],
                target_key=info["target_key"],
                venue_station_id=info["venue_station_id"],
                event_type="Sports-NHL",
                duration_min=config.DEFAULT_DURATIONS_MIN["Sports-NHL"],
                game_col="GP",
                date_format="%Y-%m-%d",
                away_col="Unnamed: 2",
                attendance_col="Att.",
                start_time_col=None,
                default_start_time=time(19, 0),
                keep_year=keep_year,
            )
        )
    return events
