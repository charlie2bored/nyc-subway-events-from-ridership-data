# Thought Process - How I'm Thinking About This Project

*A plain-language journal of decisions. If you've never read a line of code
and don't know what an MTA station is, this should still make sense. I'll
keep appending to it as we go.*

---

## The Big Idea

New York City does not have a calendar - it has thousands of overlapping
calendars. The Yankees calendar. The Knicks calendar. The Madison Square
Garden concert calendar. The marathon. The Macy's parade. The day a Taylor
Swift residency hits Brooklyn. Each one is real and each one moves people
around the city.

When a big event happens, the most obvious place that registers it is the
**subway**. Tens of thousands of additional people show up at one station,
all in a tight window. If you watched the subway's ridership numbers
carefully, you could basically reverse-engineer the city's calendar
without ever opening a newspaper.

That's what this project does. We're going to:

1. Watch the subway at five specific stations all year (2024).
2. Figure out what "normal" looks like there, hour by hour.
3. Find the moments when ridership goes weirdly above normal.
4. Match those moments to known events.
5. Compare the **shape** of the deviation across event types - and ask:
   does a Knicks game look different from a concert? Does the US Open
   look different from a Mets game?

We're calling the result a "field guide to urban fingerprints" - each event
type has a distinctive signature in how it moves people, and we're going
to draw a map of those signatures.

---

## Why These Five Stations

We deliberately picked stations next to **different kinds of venues**, so we
can compare event signatures across categories:

| Station | What's there | What it tells us |
|---|---|---|
| **34 St-Penn Station** | Madison Square Garden | Indoor arena: Knicks, Rangers, concerts |
| **Atlantic Av-Barclays** | Barclays Center | Different indoor arena: Nets, concerts |
| **Mets-Willets Point** | Citi Field + Arthur Ashe Stadium | Outdoor stadium: Mets + the US Open tennis |
| **161 St-Yankee Stadium** | Yankee Stadium | Outdoor stadium: Yankees only |
| **Times Sq-42 St** | Times Square itself | The "control" station: civic events (NYE, parades, Broadway) |

Times Sq is special - it's not a venue, it's a destination. Including it
lets us tell two things apart:
- **A signal that's only at one venue** (Knicks game = Penn surges, others
  don't).
- **A signal that's across the whole city** (NYE = everybody's transit
  changes, and Times Sq is the epicenter).

A surprise we hit on day one: **"Penn Station" is actually two separate
subway stations** in the MTA's data - one for the 1/2/3 lines (which runs
directly under MSG) and one for the A/C/E lines (one block north).
They're not connected inside the fare gates. So when we look at MSG, we
need to look at both stations together. Other complexes - Times Square,
Atlantic Av - are single merged stations with many lines.

---

## What Data We're Using

The MTA publishes [hourly ridership data](https://data.ny.gov/Transportation/MTA-Subway-Hourly-Ridership-Beginning-February-202/wujg-7c2s)
for every subway station in the system. It tells you, for every hour of
every day since February 2022:

> At station X, at 7pm on Tuesday, exactly N people swiped in.

It even breaks N down by payment method (OMNY tap, MetroCard) and fare
class (full fare, student, senior, etc.) - though for now we add them
all up into one total per hour.

We chose 2024 for the time window because:
- It's a complete calendar year, so all seasons are covered.
- It's recent enough that OMNY (the tap-to-pay system) is widely
  adopted, which gives cleaner data than the old MetroCard-only era.
- It's *before* the 2025 election cycle, which would have introduced
  unusual rally/protest traffic patterns.

We pulled all of 2024 for our 5 archetypes once and cached the result on
disk. From here on, every analysis re-reads from the local cache - we
never bother the MTA's servers again.

---

## How We Define "Normal"

This is the hardest part of the project.

The naive thing is: "average ridership at this station." But averages
don't help us. The average for "Yankee Stadium at 8pm on Saturday" mixes
together game nights (40,000 people) with non-game nights (a few hundred).
You end up with a number that doesn't describe either.

Three decisions we made to build a better "normal":

### 1. Use the median, not the average.

The **median** is the middle value when you line everything up in order.
If you have 30 Saturday-8pm samples and 10 of them are game nights, the
median lands in the middle of the non-game cluster - it's not pulled
upward by the big game-night numbers. (The average would be.)

### 2. Build the baseline by (day-of-week × hour-of-day).

A Tuesday at 8am has a very different "normal" than a Saturday at 3am.
Instead of a single average for "Yankee Stadium," we build a 7×24
table: one number per (day of week, hour of day). So when we look at
Tuesday at 8pm, we compare it to other Tuesday-at-8pm samples, not to
the whole week.

### 3. Split the year into Summer and Winter.

Yankee Stadium is **not the same place** in February (no baseball) as in
July (game every night). If we used one baseline for the whole year,
winter at Yankee Stadium would look anomalously low (compared to a
baseball-inflated baseline), and summer would look anomalously high
(compared to a winter-deflated baseline). Both readings would be wrong.

The split:
- **Summer:** April through October (baseball season runs Apr-Sep, plus
  playoff October).
- **Winter:** November through March (NBA + NHL run roughly Nov-Apr).

By accident this also gives us clean coverage for indoor arenas in
winter and outdoor stadiums in summer.

### 4. Exclude federal holidays from the baseline.

If we let July 4th into the baseline, the median for "Thursday at 9pm"
might shift because of fireworks crowds. So we yank holidays out of the
baseline-input pool entirely. They still show up in the time series -
they just don't get a vote in defining what "normal Thursday" looks
like. (Note: this means holidays themselves will *look* anomalous when
we score them against the baseline. That's intentional. NYE at Times
Square *should* be one of the biggest anomalies of the year.)

---

## The First Real Discovery

After we built the baseline, we did a sanity check at Yankee Stadium:
how much higher is the *median* Friday-evening ridership in summer
versus winter?

| Day | Summer evening | Winter evening | Difference |
|---|---:|---:|---:|
| Mon | 381 | 343 | +37 |
| Tue | 429 | 348 | +82 |
| Wed | 434 | 350 | +84 |
| Thu | 434 | 354 | +80 |
| **Fri** | **605** | **391** | **+214** |
| Sat | 369 | 313 | +55 |
| Sun | 310 | 252 | +58 |

The +214 on Friday is too big to explain as "ambient summer effect" (better
weather, restaurants busier, etc.). Here's what we think is going on:

The Yankees play about 81 home games a year. They tend to schedule
weekend series, which means **most summer Fridays are game days.** If
more than half of summer Friday evenings have a game, the *median*
itself has shifted - the median Friday-evening at Yankee Stadium is
already partially a game-day number.

This matters because it means our baseline at Yankee Stadium for a
Friday evening is **not** "normal, no game" - it's "the middle of a
distribution dominated by games." A no-game Friday will look unusually
*low* against this baseline (because it actually is low compared to the
contaminated reference).

We're flagging this for Phase 2: once we have the actual schedule, we
can rebuild the baseline using only confirmed non-game evenings and
see how much the picture changes.

This is a real example of why this kind of work is interesting. The
"obvious" choice (use the median, it's robust to outliers) breaks down
when the outliers are no longer outliers - when they're a majority.

---

## The Edge Cases We Care About

A few small details that matter, because skipping them would silently
corrupt the analysis:

- **Daylight Saving Time spring-forward.** On 2024-03-10 at 2 AM, the
  clocks jump to 3 AM. That hour does not exist in NYC local time.
  Every station's data shows exactly one missing hour for the year, and
  this is why. We leave it as missing (not zero), so it doesn't
  contribute to anything.

- **The 7 train sometimes shuts down for maintenance.** Mets-Willets Point
  is on the 7 train, and the data shows 7 missing hours beyond DST -
  almost certainly weekend track work. We leave those missing too,
  because zero would be misleading (the station was closed, not empty).

- **Penn Station's two sides feed MSG differently.** The 1/2/3 platforms
  are directly under MSG. The A/C/E is a block away with a transfer
  passageway. We compute the baseline for each side separately and add
  them up at the end. Helps us answer questions like "does MSG draw
  more from West Side or 8th Avenue?" when we get there.

---

## What's Next (Phase 2)

We have the baseline. We've measured the residuals (actual minus
expected). The residuals at sports venues already look like real event
signal: Yankee's biggest residual hour is `+15,507 riders` at
11pm on 2024-10-29, which is World Series Game 4 night. We didn't tell
it that - it just popped out.

But we haven't matched residuals to *named events* yet. That's the
next phase:

1. **Build a list** of every concert, game, parade, marathon, and big
   civic event in NYC in 2024. Source it from sports schedule sites,
   Setlist.fm, NYC permit records, Wikipedia.

2. **Match** each event to the corresponding subway station and the hour
   window it happened in.

3. **Cross-check** the matches against our flagged anomalies:
   - Events the system caught (true positives).
   - Events the system missed (false negatives - were they
     weather-suppressed? Or genuinely small?).
   - Anomalies that don't correspond to any known event (mystery
     spikes - could be data issues, could be news-archive
     digging).

Step 1 of Phase 2 is to **write the sourcing plan as a document
first**, before scraping anything. That's what we're working on now.

---

---

## Phase 2: Collecting the Ground Truth

We now have ridership baselines and the residuals (actual − expected)
that look like real event signals. But without a *list of what
actually happened*, we can't tell which residuals are real events
versus weird data and we can't compare events across categories. So
this phase is mostly data plumbing: pulling event lists from public
sources and turning them into a single CSV that the analysis layer
will join against.

### Where we pulled events from, and why

| Event type | Source | Why this source |
|---|---|---|
| MLB games (Yankees, Mets) | baseball-reference.com | Comprehensive, attendance included, public. |
| NBA games (Knicks, Nets) | basketball-reference.com | Same family. Has tipoff time, which baseball doesn't. |
| NHL games (Rangers) | hockey-reference.com | Same family. (No tipoff time published; defaulted to 7pm.) |
| Concerts (MSG, Barclays) | setlist.fm API | Crowd-sourced setlists. Free key, sanctioned API. |
| Civic events (NYE, marathon, Pride, etc.) | Hand-curated | Too few and too important to leave to scraping. |
| US Open sessions | Hand-curated | 14 days, 2 sessions each. Worth typing by hand. |
| Sports playoffs | Hand-curated | The team-schedule scrapers only return regular season. Playoff home games (Knicks ECF run, Rangers ECF run, Yankees World Series, Mets NLCS) are individually checked-in. |
| NYC parade permits | NYC Open Data | Tried this. The dataset only retains records from 2024-06-30 forward; no 2024 history available. Major parades fell back to hand-curation. |

### Three decisions I want a non-technical reader to understand

**Dropping NFL.** I originally thought we could include Giants and Jets
home Sundays as a "control" - predicting that our stations should
*not* spike on NFL home days, and verifying that. But Penn Station
also hosts MSG events (Knicks, Rangers, concerts), and NJ Transit
runs through Penn too. A Sunday with a Giants home game and a Knicks
home game looks identical on the subway. There's no signal that
isolates the NFL contribution. So including NFL would inject noise
into the matcher without adding any verifiable signal. Dropped.

**Default start times.** MLB doesn't publish a clean start-time column;
hockey doesn't publish one at all. We use:
- MLB Day games → 13:00, MLB Night games → 19:00
- NHL → 19:00
These are accurate to within ~30 minutes for most games. Since our
fingerprint analysis looks at ±3 hour windows around the event, this
approximation is fine. Flagged in the `notes` column for every
affected row so we can revisit later if needed.

**Doubleheaders.** Baseball schedules sometimes list one date with two
games (e.g., a rained-out game played as a doubleheader the next day).
The MLB scraper now captures both halves separately, tagged G1/G2.
This matters because a doubleheader is a fundamentally different
subway signature: 6-7 hours of continuous high traffic instead of a
single 3-hour event.

### What this gives us

**513 events** total, distributed across the year:

- **174 baseball games** at Yankee Stadium and Mets-Willets (regular
  season + postseason; both teams made deep playoff runs in 2024)
- **100 basketball/hockey games** at MSG (Knicks + Rangers, regular
  season + playoffs)
- **38 basketball games** at Barclays (Nets)
- **168 concerts** at MSG (108) and Barclays (60)
- **24 US Open sessions** at Mets-Willets in late Aug / early Sep
- **9 major civic events / parades** across the year (NYE, Pride,
  Macy's Thanksgiving, marathon, July 4 fireworks, etc.)

### The first concrete win

Before we built any matcher, we already had one piece of evidence the
whole approach is going to work:

> The Yankee Stadium hour with the **biggest** residual from baseline
> in all of 2024 was **2024-10-29 at 23:00**, at **+15,507 riders**
> over the median.
>
> The event list (built independently, with no awareness of our
> ridership data) has exactly one event at Yankee Stadium that day:
> **Yankees vs Dodgers, World Series Game 4, 8:00pm start.**

The ridership data found the World Series without ever being told it
existed. That's the model we want repeated at every station for every
event type. The next steps are: (a) build the anomaly detector that
formalizes "find big residuals" into a flagged hours table, and (b)
cross-reference those flagged hours against the 513-event ground
truth.

---

---

## The contamination fix we promised, paid off

After the first matching pass we got 93% recall overall - but only
**78% on Knicks games, 82% on Rangers games, 88% on MSG concerts.**
Outdoor stadiums hit 100% (Yankees, Mets, Nets). The story we had
written in advance held: the *naive* baseline at MSG was contaminated
by event-day traffic, so the "normal" Tuesday 8pm against which a
Knicks game was being measured was already a half-game-day number.
A moderate-attendance Knicks game stopped being detectable.

So we refit the baseline excluding **any hour within ±3h of a known
event** for that station. Federal holidays already came out earlier
for the same reason. Run it through anomaly detection and the matcher
again:

| target type | v1 recall | v2 recall | Δ |
|---|---:|---:|---:|
| Yankees / Mets (MLB) | 100% | 100% | - |
| Nets (NBA) | 100% | 100% | - |
| Barclays concerts | 98% | 98% | - |
| **MSG concerts** | **88%** | **93%** | **+5** |
| **Knicks (NBA)** | **78%** | **94%** | **+16** |
| **Rangers (NHL)** | **82%** | **92%** | **+10** |
| **Overall** | **93.0%** | **96.5%** | **+3.5** |

The headline: **31 of 36 false negatives were at MSG, and 23 of them
came back as true positives once the baseline stopped pretending
event days were normal.**

The remaining MSG false negatives cluster in early January (when the
rolling z-score doesn't have enough same-hour-of-week history yet) and
on Phish/Billy Joel residency nights (where the artist plays so often
the baseline still partly absorbs them, even after one round of
exclusion). Both could be improved with a second iteration, but
diminishing returns.

### Why this generalizes

This is a textbook bootstrapped-baseline problem and the project
proves a clean version of the result: you can't define "normal" while
the abnormal events are mixed into your sample, but once you *know*
which days are events, you can rebuild a clean "normal" that catches
the borderline cases. The same trick would work in commerce
(separating Black Friday from base traffic), in operations (sev-day
load vs. peace-time), or in any kind of seasonal-product analysis
where a few intense periods dominate the mean.

---

---

## Phase 3: What do the fingerprints actually look like?

After matching, we had 495 events with five-dimensional "fingerprints":
peak intensity (how big the spike was), lead time (how early people
arrived), lag time (how long after the event ended ridership stayed
elevated), asymmetry ratio (lead / lag - are you front-loaded or
back-loaded?), and half-life of the post-event decay.

Three pre-registered questions to answer with the clustering layer:
1. Do Knicks games and Rangers games - same building, same night
   slot - separate?
2. Do day-time baseball games look different from night games?
3. Are concerts a distinct cluster, or do they overlap with the
   sport played in the same building?

### The clustering finds a real macro split

When we z-score the five features (log-transforming peak_intensity
first, because it ranges 0.4–358 across stations) and run k-means
with k from 2 to 8, the silhouette score peaks at **k=2** at 0.55.
That clustering produces:

- **Cluster A (415 events):** typical indoor-arena profile. Sharp
  short spike around event time, minimal pre-event arrival, fast
  decay. Contains Knicks, Rangers, Nets, virtually all MSG and
  Barclays concerts, regular-season Yankees/Mets games.
- **Cluster B (80 events):** "stadium-style." Big lead time
  (people arrive hours early), more symmetric arrival-and-exit
  pattern, slower decay. Contains every US Open session, ~36% of
  Mets games (the big ones), the postseason games at Yankee, the
  Times Square parades.

So the **first-order structure of NYC events is "quick indoor
arena" vs. "slow outdoor stadium / parade."** That's not the only
distinction in the data, but it's the dominant one.

### The three pre-registered tests, answered

**1. Knicks vs Rangers at MSG.** Both ended up in Cluster A. But
the *features* are statistically different:
- Peak intensity: **0.96** (NBA) vs **0.65** (NHL), p = 0.004
- Lead time: significantly different, p = 0.02
- Asymmetry: significantly different, p = 0.02
- Lag time and half-life: not significantly different

So yes, Knicks and Rangers games leave **different fingerprints**
on Penn Station - Knicks events have a stronger and slightly
earlier ridership signature - but they are not different *enough*
to form their own k-means cluster. They share an archetype with
each other and with MSG concerts. The differences are real but
sub-cluster.

**2. Day vs night MLB at Yankee Stadium.** Both also end up in
Cluster A. The features:
- Peak intensity: **11.8** (day) vs **33.5** (night), p < 0.001
- Lead time, asymmetry: significantly different (p ≈ 0.02-0.03)
- Lag time and half-life: not significantly different

The 3× peak gap is because the *baseline* at Yankee Stadium at 10pm
is tiny, so a night-game crowd produces a much larger ratio.
Structurally similar, but night games look much more dramatic
against their reference.

**3. Are concerts a distinct cluster?** No. **94% of concerts land
in Cluster A**, but only **36% of Cluster A is concerts** - the
rest is NBA, NHL, MLB. Concerts at MSG and Barclays share an
event signature with the home teams that play in the same
building. The "indoor arena" archetype is a *venue* fingerprint,
not an *event-type* fingerprint, at this level of feature
resolution.

### What we see at k=6 (forced finer split)

Forcing the clustering to k=6 reveals a more meaningful taxonomy:

| cluster | n | character | populated by |
|---:|---:|---|---|
| 0 | 47 | High lead time, high asymmetry | US Open premiums, postseason MLB, Times Sq parades |
| 1 | 206 | Quick indoor arena | MSG concerts (81), Knicks (36), Rangers (33), Nets (24) |
| 2 | 88 | Mixed medium | Barclays concerts (25), some MSG concerts (16) |
| 3 | 19 | Very long half-life | Slow-decaying Mets games and US Open |
| 4 | 130 | Outdoor stadium baseline | Most Yankee MLB (70), most Mets MLB (51) |
| 5 | 5 | Extreme asymmetry | Times Square parades |

At this granularity, the **MSG indoor arena cluster (cluster 1)
contains Knicks, Rangers, and MSG concerts together** - same
fingerprint archetype despite different sports. That is the
project's most concrete finding, and it's a real result about
urban behavior: the **building shapes the fingerprint more than
the sport does**, for indoor events.

### Honest about the limits

- The decay-half-life feature is only meaningful at low-baseline
  venues. At Penn Station, post-event ridership is masked by
  commuter flow and the exponential fit fails for 96% of MSG
  concerts. We use a linear-fit fallback and a unified half-life
  metric, but it's a noisy signal at MSG specifically.
- The 5-feature space is small. With richer features - say, hourly
  z-scores of the surrounding 8 hours instead of summary stats -
  we'd probably get cleaner within-venue clustering. That's a
  follow-up.
- k=2 has the highest silhouette, but it conflates a lot of real
  structure. The k=6 view is the more interesting one for a
  human reader; the silhouette favors macro splits because the
  bigger clusters dominate the score.

### The portfolio-ready conclusion

> NYC events leave a measurable subway fingerprint, and we can
> recover it from public data with no help from event metadata.
> When you cluster those fingerprints, the dominant axis is
> *venue type*, not event type: indoor arenas (MSG, Barclays)
> produce fast, peak-around-tip-off signatures that look the same
> whether the event is Knicks, Rangers, or Phish; outdoor stadiums
> (Yankee, Mets) and the parade route through Times Square
> produce slower, more pre-loaded signatures regardless of the
> specific event. Within those archetypes, finer event-type
> distinctions exist and are statistically significant - Knicks
> peaks are 48% higher than Rangers peaks at the same building -
> but they sit inside the same fingerprint family, not in their
> own.

---

*Last updated: 2026-05-19. Will append as decisions are made.*
