# Washington Creel Report Insights

Every creel report Washington publishes — who fished, where, and what they caught —
parsed out of WDFW's pages, PDFs and databases, reconciled, and turned into a map of
**where fishing is picking up and where it has fallen off, species by species**.

**[▶ Open the live dashboard](https://ethan-m2024.github.io/Creel-Insights/)**

WDFW publishes creel data in seven places and four formats. A Drupal table for Puget
Sound ramps. A weekly PDF written in sentences for the Columbia. A quota report for
the ocean ports. A fixed-width PDF for the pikeminnow reward fishery. An
interview-level database on data.wa.gov. Read one at a time they answer one question
each: how did last weekend go at that ramp. Read together they answer the question
anglers actually ask — where are fish being caught right now, and is that better or
worse than this water usually does at this point in the season.

This repository holds all of it, parsed and checked, and rebuilds itself daily.
Nothing is hand-entered and no figure is estimated: every number traces to a
published WDFW report, and the harvest is checked against WDFW's own published creel
summary before it ships. See [Accuracy](#accuracy).

---

## One command

Same command on macOS and Windows, whichever you prefer:

```
python3 run.py              # macOS / Linux — open the dashboard
py run.py                   # Windows — open the dashboard

python3 run.py --update     # fetch the newest WDFW reports, rebuild, then open
python3 run.py --check      # re-run the accuracy audit on the data already here
python3 run.py --help       # every option
```

Opening needs **no install and no internet**. The built page ships in this repository
and carries its own data. Only `--update` needs the PDF library, and `run.py` sets it
up by itself the first time you ask for it, in a private `.venv` that touches nothing
else on your machine.

If you would rather not use a terminal, double-click instead:

| | macOS | Windows |
|---|---|---|
| **Just look at it** | `Open Dashboard (Mac).command` | `Open Dashboard (Windows).bat` |
| **Pull in new reports** | `Update Dashboard (Mac).command` | `Update Dashboard (Windows).bat` |

You can also open `docs/index.html` directly — one self-contained file you can email,
put on a shared drive, or keep on a USB stick.

---

## What the dashboard answers

**Where is it getting good?** The heat map colours every place by how its catch per
angler compares with the same weeks in previous years, so a fishery that always fires
in August is not flagged as news every August. Dot size is how many anglers were
interviewed, so a red dot with a big footprint is a real signal and a small one is a
hint.

**Where has it cooled off?** The same comparison, run the other way, with the places
that have dropped furthest listed beside the map. A place is only scored when at
least 30 anglers were interviewed in the window — below that a catch rate is one
lucky boat.

**Is this week different from last?** Switch the comparison to the fortnight just
past and the map answers a shorter question: what changed since the last report.

**When does this water usually produce?** Every species has a week-by-week seasonality
curve built from the last five years, and every place has its own weekly history.

**Where do the numbers come from?** The sources tab lists every report read, its date
range, how many places it covers, and the result of every accuracy check on the build
you are looking at.

---

## The sources

| Source | Format | Covers | What it gives |
|---|---|---|---|
| WDFW creel database (`data.wa.gov`) | JSON API | statewide, 1973 to now | angler interviews and individual fish, by species, fate and fin mark |
| Puget Sound ramp creel | HTML, paginated | 2013 to now | every sampled ramp-day: interviews, anglers, and catch by species |
| Buoy 10 | HTML | 2014 to now | daily boats, anglers, Chinook and coho kept at the Columbia mouth |
| Willapa Bay | HTML | 2018 to now | management-week interviews and catch, clipped and unmarked kept apart |
| Ocean sport salmon quota report | HTML | 2016 to now | weekly anglers and salmon for Columbia, Westport, La Push, Neah Bay |
| Columbia River and tributary report | PDF prose | 2019 to now | weekly bank and boat effort and catch, by river section |
| Northern pikeminnow sport reward | PDF table | 2019 to now | weekly registered anglers and fish per check station |

Two of these need explaining.

**The Columbia report is prose, not a table.** WDFW writes it out in sentences:
*"Section 6 (Kalama) — 110 bank anglers kept eight steelhead and released four
steelhead."* Every number in that paragraph is a creel figure and there is nowhere
else to get it, so `src/sources/southwest.py` reads it. The parsing is deliberately
narrow: a sentence must match the shape WDFW actually writes before anything is taken
from it, and a paragraph that does not match contributes nothing rather than a guess.

**The ocean report publishes a coastwide total as well as the four port tables.** The
total is skipped. It is the sum of the four, and including it would count every ocean
fish twice.

---

## How a catch rate is worked out

Catch alone cannot be compared between places: a river with four anglers and two fish
is not out-fishing a bay with four hundred anglers and a hundred. Catch per angler
alone cannot be compared across the calendar: every fishery has a season, and July is
not November anywhere.

So each place is compared **against itself, at the same point in the season**:

| | |
|---|---|
| **recent** | fish kept per angler over the last 14, 28 or 56 days of data |
| **prior** | the same length of window immediately before it |
| **seasonal** | the median of the same calendar window in each of the last three years |

Effort and catch live in separate tables (`data/creel_effort.csv.gz` and
`data/creel_rows.csv.gz`) because one interview counts anglers once and their fish
once per species. Joining them into a single row and summing would multiply anglers
by however many species they caught, and every rate downstream would be wrong.

The counts behind every rate travel with it — kept, released, anglers, and how many
past years the seasonal baseline had to work with — so you can see what any number
rests on rather than taking it on faith.

---

## Accuracy

Every build runs an audit and refuses to publish if it fails.

**Against WDFW.** WDFW publish a summarised creel table of their own
(`dpqw-kc2b`: anglers, harvest and release by day, water body and species). The
pipeline rebuilds those totals from the interview-level records it parsed, and
compares them row by row. Agreement has to hold on at least 90% of shared rows,
within 2% or three fish.

**Against itself.** No catch dated in the future. No negative counts. No catch row
without a species and a place. No fish without effort recorded alongside it. No
location placed at coordinates outside Washington. No source that has silently
stopped producing rows.

Run it yourself against the data already in the repository, with no network access:

```
python3 run.py --check
```

Where a location cannot be matched to WDFW coordinates it is left off the map rather
than placed approximately, and the dashboard names it. The one deliberate exception is
a short list of fixed places that exist in no WDFW point dataset — the ocean
management areas, the Columbia's fishery sections, the pikeminnow check stations.
Those are hand-placed once, in `src/geo.py`, and every one is labelled *approximate*
wherever it is shown.

---

## Layout

```
run.py                  the only entry point; sets up its own environment
src/pipeline.py         fetch every source, write two tables, rebuild, check
src/sources/            one module per WDFW publication
    common.py           the shared row shape, species names, fetching
    socrata.py          the statewide interview database
    puget.py            Puget Sound ramp creel
    buoy10.py           Buoy 10
    willapa.py          Willapa Bay
    ocean.py            ocean sport salmon quota report
    southwest.py        the Columbia report, read out of prose
    pikeminnow.py       the sport-reward fishery
src/geo.py              placing locations, and how confident that placement is
src/build_data.py       the trend arithmetic and the dashboard payload
src/validate.py         the audit
src/template.html       the dashboard, one self-contained page
data/                   extracted rows, payload, geography, manifest
docs/index.html         the built page, served by GitHub Pages
```

Downloaded reports and API pulls are cached under `.cache/` and are not tracked; a
fresh clone rebuilds them on the first `--update`.

---

## Data and licence

The underlying reports are published by the Washington Department of Fish and
Wildlife. This repository's code is MIT licensed (see `LICENSE`). WDFW describe the
in-season figures as preliminary and subject to their own quality control, and so
does the dashboard.
