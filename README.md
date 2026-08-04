# Washington Creel Report Insights

Every creel report Washington publishes — who fished, where, and what they caught —
parsed out of WDFW's pages, PDFs and databases, reconciled, and turned into a map of
**where fishing is picking up and where it has fallen off, species by species**.

**[▶ Open the live dashboard](https://ethan-m2024.github.io/Creel-Insights/)**

WDFW publishes creel data in eleven places and four formats. A Drupal table for Puget
Sound ramps. A weekly PDF written in sentences for the Columbia. Quota reports for the
ocean ports and the halibut subareas. A fixed-width PDF for the pikeminnow reward
fishery. An interview-level database on data.wa.gov. Read one at a time they answer
one question each: how did last weekend go at that ramp. Read together they answer the
question anglers actually ask — where are fish being caught right now, and is that
better or worse than this water usually does at this point in the season.

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

The window control also has a **whole record** setting. The other settings answer
"what is happening now", which by construction leaves out every place that is out of
season, closed, or no longer surveyed — most of the record. Whole record puts all of
it on the map at once: every place WDFW have ever counted that species at, back to
1973, sized by lifetime anglers and coloured by fish per angler, with the years each
place was sampled on hover. For Chinook that is 232 places rather than 56.

Every place that reported fishing in the window is on the map — not only the ones
with a solid sample. A rate resting on fewer than 30 anglers is drawn faded and
labelled thin, and is never ranked in the lists beside the map, because at that
sample size one lucky boat moves it by half. Docks that appear in no WDFW coordinate
dataset — most of the Puget Sound marinas — are drawn as rings inside the catch area
they report to, spread around its centre so they can be told apart, and every one of
them says so on hover. Rings are areas; filled dots are surveyed positions.

**Where has it cooled off?** The same comparison, run the other way, with the places
that have dropped furthest listed beside the map.

**Is this week different from last?** Switch the comparison to the fortnight just
past and the map answers a shorter question: what changed since the last report.

**When does this water usually produce?** Every species has a week-by-week seasonality
curve built from the last five years, and every place has its own weekly history.

**How much of the quota is gone?** The quotas tab covers every fishery WDFW run
against a ceiling, not only the Chinook ones: Puget Sound Chinook encounters against
their guideline, ocean Chinook and coho by port, Pacific halibut in pounds by subarea,
and Columbia white sturgeon by pool — each as a count and a percentage, with the date
WDFW say the estimate runs through, because that date, not the date the page was
built, is how current the figure is.

Chinook and coho are tracked separately at the same port because they run out at
different times. Halibut is the one quota counted in pounds rather than fish. Where
WDFW publish the share used but not the ceiling it is a share of, the ceiling is
worked back out of their own two figures and rounded, and the panel says so.

An area can run two guideline fisheries in one season, so each is listed under the day
it opened: Area 11 has used 54% of the quota for the fishery that opened 1 June and
15% of the one that opened 23 July. Only areas with a quota appear. This is a measure
of quota used, not a statement about whether water is open — that is set by the
[sport fishing rules](https://wdfw.wa.gov/fishing/regulations/sport-fishing).

A figure WDFW publish that cannot be right — an estimate dated a year out — is shown
as published and marked, not quietly corrected.

**Where do the numbers come from?** The sources tab lists every report read, its date
range, how many places it covers, and the result of every accuracy check on the build
you are looking at.

---

## The sources

WDFW's creel index lists eleven things. Nine of them carry data, and all nine are
read here.

| Source | Format | Covers | What it gives |
|---|---|---|---|
| WDFW creel database (`data.wa.gov`) | JSON API | statewide, 1973 to now | angler interviews and individual fish, by species, fate and fin mark |
| Puget Sound creel reports | HTML, paginated | 2013 to now | every sampled ramp-day: interviews, anglers, and catch by species |
| North coast creel surveys | JSON API | 2020 to now | Olympic Peninsula river creel, inside the same database |
| Southwest Washington fishing reports | PDF prose | 2019 to now | weekly bank and boat effort and catch, by Columbia river section |
| Buoy 10 fishing reports | HTML | 2014 to now | daily boats, anglers, Chinook and coho kept at the Columbia mouth |
| Willapa Bay (Marine Area 2.1) | HTML | 2018 to now | management-week interviews and catch, clipped and unmarked kept apart |
| Ocean sport quota report | HTML | 2016 to now | weekly anglers and salmon for Columbia, Westport, La Push, Neah Bay |
| Recreational bottomfish and halibut | HTML | current season | weekly halibut, anglers and average weight for four coastal subareas |
| Pikeminnow Sport-Reward Fishery | PDF tables | 2014 to now | weekly registered anglers, pikeminnow, and the incidental catch of six other species per check station |
| Seasonal salmon guidelines and quotas | HTML | current seasons | Puget Sound Chinook encounters against the guideline that closes each area |
| White sturgeon | HTML | current season | Columbia pool harvest against its guideline |

The last two are not creel catch — an encounter is not a fish kept, and a pool's
harvest estimate is not an interview — so they are kept in their own table
(`data/quotas.json`) and shown on their own tab rather than mixed into the catch
figures.

The one index entry with nothing to read is **Sport catch reports**: annual
catch-record-card publications, the most recent for 2021, which summarise a year
rather than track a season. They are listed in the dashboard's sources tab as
unread, with the reason.

Two sources need explaining.

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
| **recent** | fish per angler over the last 7, 14, 28 or 56 days of data, or the whole record |
| **prior** | the same length of window immediately before it |
| **seasonal** | the median of the same calendar window in each of the last three years |

**How often anyone catches anything** is counted, not modelled. WDFW publish the
statewide creel one interview at a time, and every fish record names the interview it
came from, so the share of parties that went home with a fish is a matter of counting
interview ids: 3,334 of 7,262 parties at Drano Lake, 46%. Dashboards that only have
the daily totals estimate the same number from a Poisson model, which assumes fish
arrive independently of one another — they do not, and that assumption reads high on
slow days and low on good ones. Where the interviews were never published the column
says so rather than guessing.

Where a report says whether a fish was fin-clipped, that is carried through as well
— 74,792 fish across the record. Hatchery and wild are not the same animal to a
biologist, and under mark-selective rules they are not the same fish to an angler
either, so the clipped share travels with the count in the tooltips, the tables and
the export rather than being averaged into one number.

Rates are measured two ways. **Per angler** covers every source. **Per angler-hour**
divides by the time those anglers were actually fishing, which is the honest
denominator — an angler who fished forty minutes and one who fished all day are not
the same measurement — and comes from the start and end times on the interviews. Four
fifths of the interview database records them; the weekly reports never do, so those
places are drawn grey on that basis and say why rather than reading as zero.

The map opens on **whole waters**: every marine catch area, the four ocean bands,
and each of the state's 62 river basins, shaded by the fishing inside it — bright
where the catch rate is high, pale where nobody creeled it in that window. It is the
view that answers "where should I go" without asking anyone to read a scatter of
dots. **Single places** switches back to the individual ramps and rivers.

Two of those shapes are drawn rather than published: WDFW define the ocean areas by
latitude lines running out from named points on the coast, and no service publishes
them as polygons, so they are laid out from those latitudes and marked approximate.
The marine areas and the basins are the published boundaries.

A **Happening window** tab puts all five side by side, one row per place, so a run
building or fading shows up as a row that climbs or falls from left to right rather
than as a leaderboard that rearranges itself when you change a filter.

Kept and released are carried through all three windows separately, and a **Count**
switch picks which one the map, the lists and the charts are reading: what anglers took
home, what they put back, or everything they caught. It matters more than it sounds.
A catch-and-release steelhead river reports almost nothing in the kept column, and
read on kept alone it looks dead — statewide, steelhead over the whole record are
24,224 kept against 16,178 released.

Effort and catch live in separate tables (`data/creel_effort.csv.gz` and
`data/creel_rows.csv.gz`) because one interview counts anglers once and their fish
once per species. Joining them into a single row and summing would multiply anglers
by however many species they caught, and every rate downstream would be wrong.

The counts behind every rate travel with it — kept, released, anglers, and how many
past years the seasonal baseline had to work with — so you can see what any number
rests on rather than taking it on faith.

---

## One place, one name

WDFW's wording drifts between seasons, and taking it literally splits a place's
history in half. The Columbia weekly report has written the same water as *Sec 6
(Kalama)*, *Section 6 (Kalama)* and once *Section 6 Section 6 (Kalama)*; the
pikeminnow report writes *Bingen* on the weeks the station is open and *Bingen
Closed* on the weeks it is not. Each spelling was becoming a separate place with its
own partial record.

Names are now canonicalised at the parser: a mainstem section is identified by its
number, a tributary by its river. Reaches are kept apart — above and below the I-5
bridge on the Cowlitz are genuinely different fishing, and merging them would be the
opposite mistake.

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

Where a location cannot be matched to WDFW coordinates but does report a catch and
reporting area, it is drawn inside that area and marked as an area position — never
as a surveyed point. Where it has neither, it stays off the map, and the dashboard
names it. The one deliberate exception is
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
    halibut.py          the Pacific halibut landings summary
    quotas.py           encounter guidelines and harvest quotas
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
