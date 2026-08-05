"""Hatchery returns, borrowed from the sibling project that parses them.

Fish caught in a river are fish on their way to a hatchery rack, and WDFW count them
again when they arrive. Those counts are published weekly as escapement reports, and
Hatchery-Insights already parses that pile of PDFs into one table; re-parsing them
here would be the same work twice, so this reads the table that project publishes.

    https://github.com/Ethan-M2024/Hatchery-Insights

What comes back is, per facility and species, how many adults had reached the rack by
a given date. Two things fall out of that:

    run timing   which weeks of the year a run arrives in, averaged over past years
    this year    how far along this year's return is against that shape

The first says when a fishery below the hatchery should turn on. The second says
whether this year is early, late, thin or heavy — and those two together are the
closest thing to a forecast that creel data alone cannot give.
"""
import csv
import io
import gzip
import json
import os
import re
import sys
from collections import defaultdict
from datetime import date, datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import paths

REPO = 'https://raw.githubusercontent.com/Ethan-M2024/Hatchery-Insights/main/data'
RETURNS = f'{REPO}/raw.csv.gz'
FACILITIES = f'{REPO}/facility_geo.json'

#: the escapement reports name runs the way a manager does — "Fall Chinook", "Type N
#: Coho", "Winter-Late Steelhead". A creel report names the fish. These are the same
#: animal to an angler deciding where to go.
SPECIES = {
    'chinook': 'Chinook', 'coho': 'Coho', 'chum': 'Chum', 'pink': 'Pink',
    'sockeye': 'Sockeye', 'steelhead': 'Steelhead', 'kokanee': 'Kokanee',
    'cutthroat': 'Cutthroat', 'rainbow': 'Rainbow trout', 'sturgeon': 'Sturgeon',
}


def species_of(run):
    """"Winter-Late Steelhead" is steelhead; the run name is kept beside it."""
    low = (run or '').lower()
    for key, name in SPECIES.items():
        if key in low:
            return name
    return ''


#: a season is taken to start in the ninth week of the year — the first week of
#: March — and to run to the end of the following February
SEASON_START = 8
SEASON_END = 60


#: the same rack is written several ways across twenty years of reports — "COWLITZ
#: SALMON HATCH" and "COWLITZ SALMON HATCHERY", "GEORGE ADAMS HATCHRY" and
#: "GEORGE ADAMS HATCHERY". Left apart they are two racks, and adding them together
#: doubles a river's whole run.
ABBREVIATIONS = {
    'HATCHRY': 'HATCHERY', 'HATCH': 'HATCHERY', 'HTCHY': 'HATCHERY',
    'CR': 'CREEK', 'R': 'RIVER', 'LK': 'LAKE', 'SPR': 'SPRINGS',
    'FCF': 'FISH COLLECTION FACILITY', 'PDS': 'PONDS', 'PD': 'POND',
}


def canonical_facility(name):
    words = re.sub(r'[^A-Za-z ]', ' ', str(name or '').upper()).split()
    return ' '.join(ABBREVIATIONS.get(w, w) for w in words).strip()


def _week(iso_day):
    return date.fromisoformat(iso_day).isocalendar()[1]


def calendar_week(season_week):
    """Back from the season's own clock to the week of the year."""
    return season_week - 52 if season_week > 52 else season_week


def _as_date(value):
    """The reports write 10/25/18; two-digit years run back to 1998."""
    value = (value or '').strip()
    m = re.fullmatch(r'(\d{1,2})/(\d{1,2})/(\d{2}|\d{4})', value)
    if not m:
        return ''
    month, day, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if year < 100:
        year += 2000 if year < 90 else 1900
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return ''


def fetch(refresh=False, say=print):
    """The returns table and the facility positions, cached like everything else."""
    cache = os.path.join(paths.PAGE_DIR, 'hatchery_returns.csv.gz')
    geo_cache = os.path.join(paths.PAGE_DIR, 'hatchery_facilities.json')
    if refresh or not os.path.exists(cache):
        blob = common.get(RETURNS, timeout=180)
        os.makedirs(paths.PAGE_DIR, exist_ok=True)
        with open(cache, 'wb') as f:
            f.write(blob)
    if refresh or not os.path.exists(geo_cache):
        with open(geo_cache, 'wb') as f:
            f.write(common.get(FACILITIES, timeout=120))
    with gzip.open(cache, 'rt', encoding='utf-8') as f:
        rows = list(csv.DictReader(f))
    with open(geo_cache, encoding='utf-8') as f:
        facilities = json.load(f)
    say(f'   hatchery returns: {len(rows):,} rows, {len(facilities)} facilities')
    return rows, facilities


def to_int(value):
    try:
        return int(float(str(value).replace(',', '')))
    except (TypeError, ValueError):
        return 0


def run_curves(rows, say=print):
    """Cumulative adults at the rack, by facility, species, season and week.

    Each row is one stock's season-to-date total as of a report date, and a facility
    runs several stocks at once, so a week's return is the sum across stocks of the
    latest figure each had reached by then — never a sum of the rows themselves,
    which would count the same fish again every week they stood in the pond.

    Weeks one to eight belong to the season before them. A fall run counted in early
    January is the tail of that run, not the start of the next one, and filing it by
    calendar year makes every season look as though it began with a flood.
    """
    per_stock = defaultdict(dict)     # (facility, species, season, stock) -> week -> n
    for r in rows:
        day = _as_date(r.get('data_date'))
        species = species_of(r.get('species'))
        facility = canonical_facility(r.get('facility'))
        if not day or not species or not facility:
            continue
        adults = to_int(r.get('adult_total')) + to_int(r.get('jack_total'))
        if adults <= 0:
            continue
        year, week = int(day[:4]), _week(day)
        season = year - 1 if week <= SEASON_START else year
        # a season runs from March to February, so it is indexed on its own clock:
        # weeks 9 to 52 as themselves, January and February as 53 to 60. Left on the
        # calendar, a winter run's January tail sorts before its October start and
        # every curve reads as though it ran backwards.
        cell = per_stock[(facility, species, season, (r.get('stock') or '').strip())]
        index = week if week > SEASON_START else week + 52
        cell[index] = max(cell.get(index, 0), adults)

    curves = defaultdict(lambda: defaultdict(int))
    for (facility, species, season, _stock), weeks in per_stock.items():
        if not weeks:
            continue
        running, last = {}, 0
        for week in range(SEASON_START + 1, SEASON_END + 1):
            last = max(last, weeks.get(week, 0))
            running[week] = last
        first = min(weeks)
        for week in range(first, SEASON_END + 1):
            curves[(facility, species, season)][week] += running[week]
    say(f'   hatchery run curves: {len(curves):,} facility-species-seasons')
    return {k: dict(v) for k, v in curves.items()}


def load(full=False, say=print):
    rows, facilities = fetch(refresh=full, say=say)
    return run_curves(rows, say=say), facilities


if __name__ == '__main__':
    curves, geo = load()
    sample = [k for k in curves if 'COWLITZ SALMON' in k[0]][:3]
    for key in sample:
        weeks = sorted(curves[key].items())
        print(key, weeks[:3], '...', weeks[-2:])
