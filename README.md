# NYC Subway Events from Ridership Data

Recover NYC's 2024 event calendar — Mets/Yankees/Knicks/Rangers home games,
MSG and Barclays concerts, the US Open, parades, NYE — from MTA hourly
subway ridership alone, then describe what each event type looks like at
the turnstile.

Every number in this README comes from a file in `data/processed/` that the
pipeline wrote. Citations are in brackets, e.g. `[matching_report_v2.md]`.

---

## Pipeline

```
ingest/         Pull 2024 hourly ridership for 5 station archetypes from
                MTA Socrata dataset wujg-7c2s. Cache to Parquet, write a
                data-quality report.
                                                  [data_quality_report.md]

baseline/       Median ridership per (complex_id × season × day-of-week ×
                hour). 168-cell grids per (complex × season). Federal
                holidays excluded.
                                              [baseline_quality_report.md]
                Refit (v2) additionally excludes ±3h around every known
                event window.
                                                [baseline_refit_report.md]

anomaly/        Two flags per hour:
                  ratio  = ridership / baseline ≥ 1.5
                  z      = ≥ 3.0 over the prior four same-hour-of-week
                           observations (28-day rolling window)
                Either flag → "anomalous hour".
                                                    [anomaly_report_v2.md]

ground_truth/   513 events scraped or curated for 2024:
                  174 MLB, 168 concerts, 88 NBA, 50 NHL,
                  24 US Open sessions, 5 parades, 4 civic
                  [ground_truth_events.csv]
                Sources: baseball/basketball/hockey schedules from the
                sports-reference family, MSG + Barclays concerts via the
                setlist.fm API, civic events / US Open / playoffs by
                hand. NOAA Central Park weather joined for the
                false-negative explainer.
                                                    [matching_report_v2.md]

fingerprint/    Five features per matched event:
                  peak_intensity (log-transformed), lead_time_h,
                  lag_time_h, asymmetry_ratio, decay_half_life_h
                                                    [fingerprint_report.md]

                k-means with silhouette sweep over k ∈ {2..8}.
                Hierarchical (Ward) reported as a dendrogram. UMAP for
                viz only.
                                                        [cluster_report.md]
```

The five stations: `msg_penn` (complexes 318 + 164), `barclays` (617),
`mets` Willets-Pt (448), `yankee` (604), `times_sq` (611).
[`ingest/config.py`]

---

## Detection results

**Overall recall: 495 / 513 = 96.5%** with the event-aware (v2) baseline.
The naive (v1) baseline got 477 / 513 = 93.0%.
[`matching_report.md`, `matching_report_v2.md`]

Per (station × event type):

| station   | event type | events | matched | recall |
| :-------- | :--------- | -----: | ------: | -----: |
| yankee    | MLB        |     88 |      88 | 100%   |
| mets      | MLB        |     86 |      86 | 100%   |
| mets      | US Open    |     24 |      24 | 100%   |
| barclays  | NBA        |     38 |      38 | 100%   |
| barclays  | Parade     |      1 |       1 | 100%   |
| barclays  | Concert    |     60 |      59 | 98.3%  |
| msg_penn  | NBA        |     50 |      47 | 94.0%  |
| msg_penn  | Concert    |    108 |     100 | 92.6%  |
| msg_penn  | NHL        |     50 |      46 | 92.0%  |
| times_sq  | Civic      |      4 |       3 | 75.0%  |
| times_sq  | Parade     |      4 |       3 | 75.0%  |

[`matching_report_v2.md`]

The 18 false negatives are concentrated at MSG (15 of 18: Knicks, Rangers,
and concerts) and at Times Sq (Veterans Day Parade, NYE 2024). The MSG
misses cluster in January (rolling-z lacks same-hour-of-week history) and
on residency artists (Billy Joel, Phish — the artist plays so often the
baseline absorbs them even after the refit).
[`matching_report_v2.md` rows 33-50]

---

## What the detector found cold

The largest single hour at Yankee Stadium in 2024 by raw ridership was
**2024-10-29 23:00**, with 15,664 riders against a Tuesday baseline of
124.5 — a residual of ~15,540 above normal.
[`data_quality_report.md` line 333; `anomaly_report_v2.md` line 106]

That hour matches **World Series Game 4 (Yankees vs Dodgers)** in the
independently scraped ground truth.
[`ground_truth_events.csv`]

By the rolling-z anomaly score the top Yankee hour is actually
**2024-10-31 00:00** (post-Game 5 spillover) at z = 4,531.
[`anomaly_report_v2.md` line 105]

---

## Fingerprint clustering

495 matched events; one 5-D feature vector per event. Z-scored, then
k-means.

**Silhouette picked k = 2** (score 0.5456). The two clusters split as:

| cluster | n   | profile                                                  |
| ------: | --: | :------------------------------------------------------- |
|       0 | 415 | small peak, short lead, short lag, symmetric, fast decay |
|       1 |  80 | big peak, long lead (~2σ), long lag, front-loaded        |

Cluster 1 is heavily Mets-Willets: **all 24 US Open sessions** and
**31 of 86 Mets games** land in it, plus a few outliers from every other
venue. [`cluster_report.md` lines 17-42]

A forced **k = 6** (silhouette local max 0.4519) reveals finer structure
that the headline k = 2 collapses. At k = 6, Knicks games concentrate in
cluster 1 (36 of 47); Rangers in cluster 1 (33 of 46); MSG concerts in
cluster 1 (81 of 100). So "MSG events form a shared cluster" is true at
k = 6 but not the model's automatic choice.
[`cluster_report.md` lines 44-73]

### Pre-registered statistical tests

**Knicks vs Rangers at MSG, peak intensity:**
n = 47 Knicks, 46 Rangers. Median peak 0.957× vs 0.648× baseline.
Mann-Whitney U two-sided **p = 0.0041**; Welch's t p = 0.0079.
[`cluster_report.md` line 95]

**Yankees day vs night games, peak intensity:**
n = 31 day, 57 night. Median peak 11.84× vs 33.51× baseline
(night is ~2.83× day). MWU **p < 0.001**.
[`cluster_report.md` line 121]

**Are concerts a distinct cluster?**
At k = 2: 94.3% of concerts (150/159) land in cluster 0, but cluster 0 is
the catch-all — concerts are only 36.1% of its members. The answer is no:
indoor concerts share the cluster with NBA, NHL, and indoor-arena events
generally. [`cluster_report.md` lines 128-135]

---

## Event-aware refit: what it actually does

The v2 baseline excludes ±3h around every known event window, plus
federal holidays. Exclusion rates: MSG 25.1% of all hours, Mets 14.4%,
Barclays 13.6%, Yankee 12.5%, Times Sq 3.7%.
[`baseline_refit_report.md` lines 7-13]

Aggregate median baselines barely budge (0 to -2% across most cells).
The lift comes from specific (hour-of-week × season) cells where event
days dominated the input pool. The clearest example — MSG complex 318,
winter Tuesday evenings, v1 → v2:

| hour | v1 baseline | v2 baseline | Δ%      |
| ---: | ----------: | ----------: | ------: |
|   18 |        3480 |        4180 | +20.1%  |
|   19 |        2189 |        2553 | +16.6%  |
|   20 |        1643 |        1765 |  +7.4%  |
|   21 |        2139 |        1630 | -23.8%  |
|   22 |        1564 |        1176 | -24.8%  |

Pre-game commute hours rise (real commuter floor was understated because
post-game crashes pulled the median down); late-evening hours fall
(event-day exits inflated v1). The detector's gain came from the late-
evening drop unmasking moderate-attendance games. [`baseline_refit_report.md`
lines 34-47]

Net recall change: +18 events (477 → 495). The big sub-totals: Knicks
78% → 94%, Rangers 82% → 92%, MSG concerts 88% → 92.6%.
[`matching_report.md`, `matching_report_v2.md`]

---

## Honest limits

- **2024 only.** 8,784 hours per complex. Seasonal claims can't be
  cross-validated against another year.
- **3,940 flagged hours remain unexplained** (no ground-truth event
  within ±3h for the right station). Top of the list is Mets-Willets
  summer nights — consistent with the known gap that the scraper walks
  MSG and Barclays but not Citi Field concerts.
  [`matching_report_v2.md` line 54]
- **Times Sq sample sizes are tiny** (4 civic + 4 parade events). The
  75% recall and "parades are asymmetric" claim rest on 3-of-4 detections
  in each category and one cluster of 5 events at k = 6.
  [`fingerprint_report.md` line 22]
- **k = 2 is the model's pick.** The interesting Knicks/Rangers/MSG-
  concerts grouping requires forcing k = 6. The finer structure is real
  but secondary.
- **Penn Station aggregates two complexes** (164 and 318). Baselines are
  per-complex; anomalies are reported per-complex but matched at the
  archetype level. [`anomaly_report_v2.md` lines 17-24]
- **Rolling-z needs history.** January events have ≤3 prior same-hour-of-
  week observations and are more likely to slip through (visible in the
  Jan-cluster of MSG false negatives).

---

## Reproducing

```bash
# Python 3.11+, ~2 GB free disk, ~20 min runtime.
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Optional: SETLIST_FM_API_KEY in .env for full MSG/Barclays concert pulls.

python -m ingest.resolve_stations
python -m ingest.pull_2024
python -m ingest.data_quality

python -m baseline.build
python -m anomaly.build
python -m ground_truth.build
python -m ground_truth.match

python -m baseline.refit
python -m anomaly.build --suffix _v2
python -m ground_truth.match --suffix _v2

python -m fingerprint.extract
python -m fingerprint.cluster

python -m viz.build_all
```

Each stage writes a Markdown report into `data/processed/`. External
fetches are cached, so re-runs are idempotent.

---

## Repo layout

```
ingest/         Socrata client, station resolver, 2024 puller, DQ checks
baseline/       Hour-of-week median baselines + event-aware refit
anomaly/        Ratio + rolling-z detection
ground_truth/   Schedule scrapers, hand-curated events, matcher, NOAA join
fingerprint/    Feature extraction + clustering
viz/            Style sheet + portfolio charts
data/raw/       Cached external pulls (gitignored)
data/processed/ Outputs + Markdown reports (committed)
figures/        PNG + SVG chart outputs
```

---

*Built by Charlie Vargas. See [charlie2bored.com](https://charlie2bored.com).*
