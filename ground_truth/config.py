"""Ground-truth source configuration.

URLs, rate limits, and the mapping from team/venue → archetype.
Centralized so the per-source scrapers stay narrow.
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

from ingest.config import PROJECT_ROOT

load_dotenv()

# Storage --------------------------------------------------------------------

GT_RAW = PROJECT_ROOT / "data" / "raw" / "ground_truth"
GT_RAW.mkdir(parents=True, exist_ok=True)

EVENTS_CSV = PROJECT_ROOT / "data" / "processed" / "ground_truth_events.csv"

# Politeness -----------------------------------------------------------------

USER_AGENT = (
    "nyc-urban-fingerprints/0.1 (portfolio research; contact via "
    "github.com/charlie2bored - one-shot scrape, cached locally)"
)

SPORTS_REFERENCE_DELAY = 10.0    # seconds between requests
SETLIST_FM_DELAY = 1.0
DEFAULT_TIMEOUT = 30

# Setlist.fm API key (optional; required only for the concert step)
SETLIST_FM_API_KEY = os.environ.get("SETLIST_FM_API_KEY", "").strip() or None

# Team → archetype mapping --------------------------------------------------

# venue_station_id chosen as the *primary* feeder complex when a target has
# multiple. For msg_penn we use 318 (the IRT 1/2/3 platforms that sit
# directly beneath MSG); the IND side (164) is included in the archetype
# but is not the canonical event-venue ID.

TEAMS = {
    # MLB
    "NYY": {"target_key": "yankee",   "venue_station_id": "604", "event_type": "Sports-MLB"},
    "NYM": {"target_key": "mets",     "venue_station_id": "448", "event_type": "Sports-MLB"},
    # NBA
    "NYK": {"target_key": "msg_penn", "venue_station_id": "318", "event_type": "Sports-NBA"},
    "BRK": {"target_key": "barclays", "venue_station_id": "617", "event_type": "Sports-NBA"},
    # NHL
    "NYR": {"target_key": "msg_penn", "venue_station_id": "318", "event_type": "Sports-NHL"},
}

VENUES = {
    "MSG":      {"target_key": "msg_penn", "venue_station_id": "318"},
    "BARCLAYS": {"target_key": "barclays", "venue_station_id": "617"},
    "USTA":     {"target_key": "mets",     "venue_station_id": "448"},
    "TIMES_SQ": {"target_key": "times_sq", "venue_station_id": "611"},
}

# Source URLs ---------------------------------------------------------------

URLS = {
    "mlb": {
        "NYY": "https://www.baseball-reference.com/teams/NYY/2024-schedule-scores.shtml",
        "NYM": "https://www.baseball-reference.com/teams/NYM/2024-schedule-scores.shtml",
    },
    "nba": {
        "NYK_2024": "https://www.basketball-reference.com/teams/NYK/2024_games.html",
        "NYK_2025": "https://www.basketball-reference.com/teams/NYK/2025_games.html",
        "BRK_2024": "https://www.basketball-reference.com/teams/BRK/2024_games.html",
        "BRK_2025": "https://www.basketball-reference.com/teams/BRK/2025_games.html",
    },
    "nhl": {
        "NYR_2024": "https://www.hockey-reference.com/teams/NYR/2024_games.html",
        "NYR_2025": "https://www.hockey-reference.com/teams/NYR/2025_games.html",
    },
    "setlist_fm": {
        "base": "https://api.setlist.fm/rest/1.0",
        # IDs resolved via /search/venues against the live API on
        # 2026-05-19; the prior URL-slug guesses were wrong.
        "msg_venue_id": "23d63cc7",       # Madison Square Garden (main arena)
        "barclays_venue_id": "2bd77066",  # Barclays Center, Brooklyn
    },
    "nyc_open_data": {
        "dataset_id": "tvpp-9vvx",  # NYC Permitted Event Information
    },
}

# Default event durations when source doesn't specify ----------------------

DEFAULT_DURATIONS_MIN = {
    "Sports-MLB":   180,    # 3 hours
    "Sports-NBA":   150,    # 2h30m
    "Sports-NHL":   150,    # 2h30m
    "Concert":      180,    # 3 hours (default 20:00 start)
    "Parade":       240,    # 4 hours
    "Civic":        180,
    "Festival":     360,
    "Other":        180,
}
