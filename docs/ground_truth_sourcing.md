# Ground Truth Sourcing Plan

*Phase 2, Step 1. Drafted before any scraping. The point of this doc is
to commit to sources, formats, and rate-limit etiquette before we start
hitting third-party sites, and to make every later decision auditable.*

---

## Output schema

Single CSV: `data/processed/ground_truth_events.csv`

| column              | type    | example                              | notes |
|---------------------|---------|--------------------------------------|-------|
| `event_id`          | string  | `mlb-NYY-2024-04-05`                 | stable hash for joins / dedup |
| `date`              | date    | `2024-04-05`                         | event date in NYC local time |
| `start_time`        | time    | `19:05`                              | scheduled first-pitch / tipoff / curtain |
| `end_time`          | time    | `22:00`                              | best-estimate end; nullable when unknown |
| `venue_station_id`  | string  | `604`                                | maps to `ingest.config` `complex_ids` |
| `target_key`        | string  | `yankee`                             | our archetype slug |
| `event_name`        | string  | `Yankees vs Orioles`                 | display label |
| `event_type`        | enum    | `Sports-MLB`                         | see enum below |
| `expected_attendance` | int    | 47532                                | nullable when not reported |
| `source`            | string  | `baseball-reference.com`             | provenance for audit |
| `source_url`        | string  | `https://...`                        | the page we pulled from |
| `notes`             | string  | `World Series Game 4`                | freeform |

**`event_type` enum** (matches the prompt):
`Sports-MLB`, `Sports-NBA`, `Sports-NHL`, `Sports-NFL-Away`,
`Concert`, `Parade`, `Civic`, `Festival`, `Other`.

We will populate a second CSV during matching:
`data/processed/unexplained_anomalies.csv`, with an empty
`manual_annotation` column for me to fill in by hand after looking at
news archives.

---

## Sources by event type

### Sports - MLB (Yankees, Mets)

| | |
|---|---|
| Source | [baseball-reference.com](https://www.baseball-reference.com) |
| Yankees URL | `/teams/NYY/2024-schedule-scores.shtml` |
| Mets URL | `/teams/NYM/2024-schedule-scores.shtml` |
| Extraction | `pandas.read_html` on the schedule table; filter to `Home` |
| Yield | ~81 home games each → **~162 events** |
| Rate limit | Sports Reference asks for **≥ 3s** between requests; we'll use **10s**. Only two requests needed for MLB (one per team) so this is cheap. |
| ToS | Their scraping policy permits modest research-scale pulls with attribution. Attribution will go in the CSV `source` column and the project README. |
| Time window | 2024 home games include the regular season (Mar 28 – Sep 29) plus Yankees postseason (Oct ALDS/ALCS/WS). |
| Risks | Attendance is reported the day after the game; for very recent games the column may be missing. Not a problem for 2024 (already finalized). |
| Mapping | All Yankees games → `target_key="yankee"`, `venue_station_id="604"`. All Mets games → `target_key="mets"`, `venue_station_id="448"`. |
| `start_time` | Schedule table publishes local first-pitch time. |
| `end_time` | MLB games average ~3 hours under the 2023 pitch clock; we'll use `start_time + 3h00m` as the default. Extra-innings games will be longer; that's fine - small overshoot is preferable to undershoot for the lead/lag window in fingerprinting. |

### Sports - NBA (Knicks, Nets)

| | |
|---|---|
| Source | [basketball-reference.com](https://www.basketball-reference.com) |
| Knicks URLs | `/teams/NYK/2024_games.html` (2023-24 season) + `/teams/NYK/2025_games.html` (2024-25 season) |
| Nets URLs | `/teams/BRK/2024_games.html` + `/teams/BRK/2025_games.html` |
| Extraction | Same: `pandas.read_html`, filter home games, filter to **calendar year 2024** dates. |
| Yield | ~40 Knicks + ~40 Nets in 2024 calendar year → **~80 events** |
| Rate limit | Same Sports Reference family - 10s pauses. |
| Time window | NBA seasons cross calendar years. The 2023-24 season ends in April-June 2024 (regular season + playoffs); the 2024-25 season starts late October 2024. Both contribute to 2024. |
| Mapping | Knicks → `msg_penn` / `complex_ids=("318","164")`. Nets → `barclays` / `617`. |
| `start_time` | Schedule publishes local tipoff time. |
| `end_time` | NBA regulation runs ~2h15m; postseason a bit longer. Use `start_time + 2h30m`. |

### Sports - NHL (Rangers)

| | |
|---|---|
| Source | [hockey-reference.com](https://www.hockey-reference.com) |
| URLs | `/teams/NYR/2024_games.html` + `/teams/NYR/2025_games.html` |
| Extraction | `pandas.read_html`; same filter. |
| Yield | ~40 Rangers home games in 2024 → **~40 events** |
| Rate limit | 10s pauses (same family). |
| Mapping | Rangers → `msg_penn`. **Important:** MSG hosts both Knicks (NBA) and Rangers (NHL). When both play on the same day (rare but happens), we keep both rows. |
| `end_time` | NHL ~2h30m, including intermissions. |

### Sports - NFL - excluded

The Giants and Jets play at MetLife Stadium in New Jersey. No subway
line directly serves it - at best you'd see a small bleed at Penn
Station from fans transferring to NJ Transit. **Decision: drop NFL
entirely.** Penn Station carries simultaneous traffic from MSG events
(Knicks / Rangers / concerts), so any "NFL Sunday" signal would be
indistinguishable from a concurrent MSG event, and there's no signed
ground truth that NFL fans dominate the transfer flow over
arena-goers. Including NFL would inject confounded events that hurt
matching precision without adding analytical value.

### Concerts - MSG and Barclays

| | |
|---|---|
| Primary source | [setlist.fm](https://www.setlist.fm) venue pages |
| MSG URL | `/venue/madison-square-garden-new-york-ny-usa-3d639291.html` |
| Barclays URL | `/venue/barclays-center-brooklyn-ny-usa-43d6cea3.html` |
| Extraction | HTML scrape with `requests` + `beautifulsoup4`. Pages are paginated; need to walk back through 2024. |
| Yield | MSG hosts ~150 concerts/year, Barclays ~100. Setlist.fm typically captures the high-profile ones (anything with a setlist submitted by attendees). Realistic yield: **~80-120 MSG, ~50-80 Barclays.** |
| Rate limit | Setlist.fm has an [API](https://api.setlist.fm/docs/1.0/index.html) requiring a free key. **Decision:** use the API (cleaner, sanctioned) not HTML scrape. Documented rate limit: 2 req/s, 1440 req/day for free tier. We'll pace at 1 req/s. |
| Mapping | MSG concerts → `msg_penn`. Barclays concerts → `barclays`. |
| `start_time` | Concert start times not reliably published by setlist.fm. Default to **20:00** (8pm) for MSG/Barclays concerts; flag in `notes` that the time is a default. |
| `end_time` | Default `start_time + 3h00m`. |
| Attendance | Setlist.fm does not report attendance. Leave `expected_attendance` null. Cross-reference Wikipedia tour pages later for *capacity context* (sold-out vs. partial) only if it becomes essential for clustering. |
| Notes | Setlist.fm sometimes records support acts as separate entries on the same date. We dedup by `(date, venue)`, keeping the headliner (first row alphabetically is a poor proxy; use the entry with the highest `eventDate` count of submissions if available). |

### Parades

| | |
|---|---|
| Primary source | [NYC Open Data: Street Activity Permits (CECM)](https://data.cityofnewyork.us/City-Government/NYC-Permitted-Event-Information/tvpp-9vvx) |
| Dataset ID | `tvpp-9vvx` (Socrata, same client) |
| Filter | `event_type contains "parade"` OR `event_type contains "march"`; 2024 dates |
| Extraction | Reuse `ingest.socrata_client` with a different dataset_id. |
| Yield | NYC issues hundreds of "parade" permits/year. Most are tiny (block parties, religious processions). We will additionally **hand-curate a list of ~15 major parades** to ensure are tagged: Macy's Thanksgiving (Nov 28), Pride (Jun 30), West Indian Day (Sep 2), Halloween Village Parade (Oct 31), St. Patrick's (Mar 17), Veterans Day (Nov 11), Puerto Rican Day (Jun 9), Easter Parade (Mar 31), Salute to Israel (~Jun), German-American Steuben Parade (~Sep), Columbus Day (Oct 14), Greek Independence Day, Persian Day, Dominican Day. |
| Mapping | Most major parades route through midtown Manhattan → `times_sq`. Halloween Village Parade routes elsewhere - assign `Other` or skip (no ridership impact at our 5 stations). Pride ends at the West Village - modest impact at `times_sq` upstream. |
| `start_time` / `end_time` | From the permit data when available; otherwise hand-curated. |

### Civic events (NYE, marathon, fireworks)

| | |
|---|---|
| Primary source | Wikipedia + NYC.gov press archive |
| Yield | ~10 events |
| Method | **Hand-curated** in `ground_truth/civic_events.csv` (checked-in seed file). Far too small to be worth scraping. |
| Events to include | Times Square Ball Drop (Dec 31), NYC Marathon (Nov 3, 2024), Macy's 4th of July Fireworks (Jul 4), Macy's Thanksgiving Day Parade (Nov 28) - overlaps Parade category, tag as `Parade`, Pride Sunday (Jun 30) - overlaps, tag as `Parade`. |
| Mapping | NYE → `times_sq`. Marathon finish → modest impact across the city but no direct station. Fireworks (FDR Drive) → not directly on our stations but possible bleed at `times_sq`. |

### US Open

| | |
|---|---|
| Source | Wikipedia `2024 US Open (tennis)` article + USTA archives |
| Dates | 2024-08-19 (qualifying) - 2024-09-08 (men's final). Main draw: Aug 26 – Sep 8. |
| Method | Hand-curated table of (date, session, expected_attendance). The Open has day sessions (~11:00) and night sessions (~19:00) on most days. |
| Yield | ~14 days × 2 sessions = **~28 event windows**. |
| Mapping | All → `mets` / `448`. The USTA Billie Jean King Tennis Center sits next to Citi Field; the 7 train stop serves both. |
| Notes | The Open and Mets home games can overlap on the same date - when they do, the station may see compound surges. Both events stay in the table; the matcher will associate the anomaly with both. |

### Festival

Most NYC summer festivals (Governor's Ball - Randall's Island,
Electric Zoo - Randall's, SummerStage - Central Park) are not at
our stations. **Decision:** skip this category for the main analysis,
but reserve `Festival` in the enum for any future expansion. If a
festival happens to cluster around one of our stations (e.g., a Times
Square street fair), it gets `Festival` here.

---

## Estimated yield

| Category | Events | Method |
|---|---:|---|
| Sports-MLB | ~162 | scrape (read_html) |
| Sports-NBA | ~80 | scrape |
| Sports-NHL | ~40 | scrape |
| Concert | ~150 | API (setlist.fm) |
| Parade | ~15 | Socrata + hand-curate |
| Civic | ~10 | hand-curate |
| US Open | ~28 | hand-curate |
| **Total** | **~500** | |

Above the prompt's stated 200-300 target. Sports alone delivers ~300
deterministic events; concerts add 100-200. We'll keep the full set
and decide at fingerprinting time whether to downweight any sub-category
that's over-represented.

---

## Implementation order

Build in this order so each stage is independently testable:

1. **MLB schedules.** (Yankees, Mets.) Smallest, most deterministic,
   exercises `pandas.read_html` and the dedup logic.
2. **NBA + NHL schedules.** (Knicks, Nets, Rangers.) Same shape as
   MLB; verifies cross-season splice.
3. **Civic + US Open hand-curated CSVs.** Just dropdown text files we
   check in. No code.
4. **Parades from NYC Open Data.** Reuses `SocrataClient`.
5. **Concerts from setlist.fm API.** Requires the `SETLIST_FM_API_KEY`
   in `.env`.
6. **Combine** everything into `ground_truth_events.csv` with the
   `event_id` hash, deduped by `(date, venue, event_type)`.

Each step writes its own intermediate Parquet under
`data/raw/ground_truth/`, so re-runs don't re-hit any source.

---

## Rate-limit etiquette

Hard rules, all configurable in `ground_truth/config.py`:

- **Sports Reference family:** 10 seconds between requests. (Their
  ToS asks for ≥ 3s; we go conservative since one-shot research
  scripts often look bot-y.)
- **Setlist.fm API:** 1 req/s (their cap is 2/s).
- **NYC Open Data:** standard Socrata pacing; same client as MTA.
- **Wikipedia:** N/A - we don't scrape, we copy by hand into a CSV.

Every scraper uses a **User-Agent** header identifying this project
and a contact email, per common good-citizen scraping practice. Every
scraper **caches** its raw page response to disk so re-runs are free.

---

## What needs you (human) in the loop

- A Setlist.fm API key in `.env` as `SETLIST_FM_API_KEY`, before the
  concert step runs.
- Sanity-review of the hand-curated `civic_events.csv` and
  `us_open_sessions.csv` after I draft them.
- The annotation column in `unexplained_anomalies.csv` after Phase 2
  matching, so we can attribute mystery spikes.

---

*Approval requested on this plan before implementing any of it.*
