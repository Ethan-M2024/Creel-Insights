"""WDFW's creel database, as published on data.wa.gov.

This is the backbone of the whole dashboard: individual angler interviews and the
fish counted in them, statewide, one row per fish record rather than per summary
line. Six tables matter here.

    rpax-ahqm   interviews  — who was fishing, from where, for how long
    6y4e-8ftk   catch       — what those interviews produced, by species and fate
    nbd2-vdmz   water bodies— a centroid for every water body named above
    dpqw-kc2b   summary     — WDFW's own published totals, used only to check ours
    ui95-axtn   events      — one sampling day; used to date interviews that lack it
    6zm6-iep6   closures    — days a fishery was shut, so a zero can be read correctly

Catch and interviews are pulled whole and cached. They are the only source here that
covers eastern Washington, the Cowlitz, and every river creel outside Puget Sound, so
if a location appears nowhere else it almost certainly came from these two tables.
"""
import json
from collections import defaultdict
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common
from common import FRESH, MARINE

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import paths

BASE = 'https://data.wa.gov/resource/{}.json'
PAGE = 50000                     # Socrata's ceiling for one request

INTERVIEWS = 'rpax-ahqm'
CATCH = '6y4e-8ftk'
WATER_BODIES = 'nbd2-vdmz'
SUMMARY = 'dpqw-kc2b'
CLOSURES = '6zm6-iep6'

SOURCE = 'creel-database'

#: WDFW's own project names, mapped to the region a reader would look under
#: WDFW name their creel projects after management districts, which say nothing to a
#: reader. The names here are the waters each one actually covers, checked against
#: the rivers in the data: District 16 is the Quillayute system on the west end of
#: the Olympic Peninsula — the Hoh, Sol Duc, Bogachiel, Calawah — and calling it
#: "Southwest rivers" put the Hoh in the wrong half of the state.
PROJECT_REGION = {
    'District 11': 'South Sound rivers',
    'District 13': 'Snohomish and Stillaguamish rivers',
    'District 14': 'Skagit and Nooksack rivers',
    'District 16': 'Olympic Peninsula rivers',
    'District 17 North': 'Grays Harbor rivers',
    'District 17 South': 'Willapa Bay rivers',
    'Cowlitz': 'Cowlitz', 'R5 Steelhead': 'Southwest rivers',
    'R5 Inland Fish': 'Southwest lakes', 'CRM - Roving Creel Project': 'Columbia River',
}


def fetch_all(dataset, *, order=':id', refresh=False, say=print):
    """Page a whole Socrata table into memory, caching the result on disk.

    Socrata will happily serve 50,000 rows at a time but silently repeats rows if
    the query has no total order, so every page is ordered by the row id.
    """
    cache = os.path.join(paths.API_DIR, f'{dataset}.json')
    if os.path.exists(cache) and not refresh:
        with open(cache, encoding='utf-8') as f:
            return json.load(f)
    rows, offset = [], 0
    while True:
        q = f'?$limit={PAGE}&$offset={offset}&$order={order}'
        page = json.loads(common.get_text(BASE.format(dataset) + q, timeout=180))
        rows.extend(page)
        if len(page) < PAGE:
            break
        offset += PAGE
        say(f'   {dataset}: {len(rows):,} rows...')
    os.makedirs(paths.API_DIR, exist_ok=True)
    with open(cache, 'w', encoding='utf-8') as f:
        json.dump(rows, f)
    say(f'   {dataset}: {len(rows):,} rows')
    return rows


def _clock(value):
    """One of WDFW's time fields as hours past midnight.

    They are written "07:53:00", with no date attached, which is why reading them as
    timestamps failed on every row and left every angler-hour at zero.
    """
    parts = str(value or '').strip().split('T')[-1].split(':')
    if len(parts) < 2:
        return None
    try:
        h, m = int(parts[0]), int(parts[1])
        sec = int(float(parts[2])) if len(parts) > 2 else 0
    except ValueError:
        return None
    if not (0 <= h < 24 and 0 <= m < 60):
        return None
    return h + m / 60 + sec / 3600


def _hours(row):
    """Angler-hours: how long the trip had been running, times the anglers on it.

    Four fifths of the interviews record both ends of the trip, and it is the only
    place in any of these reports that says how long the fishing took. Catch per
    angler cannot tell a fish an hour from a fish a day; catch per angler-hour can.

    A trip that ends before it starts ran past midnight, and is read that way only
    when the result is a plausible session — anything longer is a keying slip, and is
    left blank rather than guessed at.
    """
    t0 = _clock(row.get('fishing_start_time'))
    t1 = _clock(row.get('fishing_end_time'))
    if t0 is None or t1 is None:
        return ''
    span = t1 - t0
    if span < 0:
        span += 24
        if span > 12:
            return ''
    if not 0 < span <= 24:
        return ''
    anglers = common.num(row.get('angler_count'))
    if not isinstance(anglers, int) or anglers <= 0:
        anglers = 1
    return round(span * anglers, 2)


def _water(project, water_body):
    marine_words = ('marine area', 'puget sound', 'bay', 'strait', 'sound', 'ocean')
    wb = (water_body or '').lower()
    return MARINE if any(w in wb for w in marine_words) else FRESH


def load(refresh=False, say=print):
    """Return (catch rows, effort rows, success rows) in the shared shape."""
    interviews = fetch_all(INTERVIEWS, refresh=refresh, say=say)
    catches = fetch_all(CATCH, refresh=refresh, say=say)

    # interview id -> where and when, so catch rows inherit a place even when the
    # catch record itself carries only the event
    by_interview = {}
    effort_rows = []
    for r in interviews:
        iid = r.get('interview_id')
        wb = r.get('water_body') or ''
        proj = r.get('project_name') or ''
        d = (r.get('event_date') or '')[:10]
        if not d or not wb:
            # an interview with no water body cannot be placed, mapped or compared
            continue
        region = PROJECT_REGION.get(proj, proj or 'Statewide')
        water = _water(proj, wb)
        if iid:
            by_interview[iid] = (d, wb, proj, region, water)
        anglers = common.num(r.get('angler_count'))
        if anglers != '' and anglers < 0:
            anglers = ''          # WDFW write -1 where the count was not recorded
        effort_rows.append(common.effort(
            d, SOURCE, wb, region=region, water=water,
            interviews=1, anglers=anglers,
            boat_anglers=anglers if (r.get('angler_type') == 'Boat') else 0,
            angler_hours=_hours(r)))

    catch_rows = []
    for r in catches:
        iid = r.get('interview_id')
        d = (r.get('event_date') or '')[:10]
        wb = r.get('water_body') or ''
        proj = r.get('project_name') or ''
        if iid in by_interview:
            d0, wb0, proj0, region, water = by_interview[iid]
            d = d or d0
            wb = wb or wb0
            proj = proj or proj0
        else:
            region = PROJECT_REGION.get(proj, proj or 'Statewide')
            water = _water(proj, wb)
        if not d or not wb:
            continue
        fate = (r.get('fate') or 'Unknown').lower()
        if fate not in ('kept', 'released'):
            continue           # broodstock and unknown fates are not angler catch
        catch_rows.append(common.catch(
            d, SOURCE, wb, common.species(r.get('species')),
            common.num(r.get('fish_count')) or 1,
            fate=fate, origin=common.origin(r.get('fin_mark')),
            region=region, water=water,
            catch_area=r.get('catch_area_code') or ''))

    # How often a party caught anything, counted rather than modelled. Every
    # interview is published with an id, and every fish record carries the id of the
    # interview it came from, so the share of parties that went home with a Chinook
    # is a matter of counting ids — not of assuming catch arrives at random, which is
    # what a Poisson estimate of the same number quietly assumes.
    parties = defaultdict(set)          # (day, water body) -> interview ids
    for r in interviews:
        iid = r.get('interview_id')
        d = (r.get('event_date') or '')[:10]
        wb = r.get('water_body') or ''
        if iid and d and wb:
            parties[(d, wb)].add(iid)
    caught = defaultdict(set)           # (day, water body, species) -> interview ids
    for r in catches:
        iid = r.get('interview_id')
        if not iid or common.num(r.get('fish_count')) == 0:
            continue
        place = by_interview.get(iid)
        d = (r.get('event_date') or '')[:10] or (place[0] if place else '')
        wb = r.get('water_body') or (place[1] if place else '')
        sp = common.species(r.get('species'))
        if d and wb and sp:
            caught[(d, wb, sp)].add(iid)
    success_rows = [
        common.success(d, SOURCE, wb, sp, len(parties.get((d, wb), ())), len(ids))
        for (d, wb, sp), ids in caught.items() if parties.get((d, wb))]

    return catch_rows, effort_rows, success_rows, detail(interviews, catches,
                                                         by_interview)


#: how far back the day-by-day slice runs. The whole-record summaries answer "what
#: is this place like"; the slice answers "what has it been like lately", and 120
#: days covers every trend window the dashboard offers with room to spare.
RECENT_DAYS = 120


def _recent(interviews, catches, by_interview, band_of, target_of, status_of):
    """The same field notes, kept day by day for the recent past.

    A reader who has asked for the last seven days should be told about the last
    seven days, not handed a fifty-year average with the same heading. Only the
    recent slice is carried at this resolution — the whole record at day level would
    be most of the payload, and nobody is asking what gear worked in 1994.
    """
    from datetime import date, timedelta
    days = [(r.get('event_date') or '')[:10] for r in interviews]
    latest = max((d for d in days if d), default='')
    if not latest:
        return {}
    cutoff = (date.fromisoformat(latest) - timedelta(days=RECENT_DAYS)).isoformat()

    size = defaultdict(list)
    gear = defaultdict(lambda: defaultdict(int))
    hour_parties = defaultdict(lambda: defaultdict(int))     # water|day -> band
    hour_hits = defaultdict(lambda: defaultdict(int))        # water|species|day
    seat = defaultdict(lambda: defaultdict(lambda: [0, 0]))
    trips = defaultdict(lambda: [0, 0])
    target = defaultdict(lambda: [0, 0])
    seat_of = {}

    for r in interviews:
        day = (r.get('event_date') or '')[:10]
        wb = r.get('water_body') or ''
        iid = r.get('interview_id')
        if not iid or not wb or day < cutoff:
            continue
        kind = (r.get('angler_type') or '').strip()
        if kind in ('Bank', 'Boat'):
            seat_of[iid] = kind
            seat[f'{wb}|{day}'][kind][0] += 1
        if iid in status_of:
            trips[f'{wb}|{day}'][0 if status_of[iid] == 'complete' else 1] += 1
        if iid in target_of:
            cell = target[f'{wb}|{common.species(target_of[iid])}|{day}']
            cell[0] += 1
            cell[1] += max(0, common.num(r.get('angler_count')) or 0)
        if iid in band_of:
            hour_parties[f'{wb}|{day}'][band_of[iid]] += 1

    hit_species, hit_seat = set(), set()
    for r in catches:
        iid = r.get('interview_id')
        day = (r.get('event_date') or '')[:10]
        place = by_interview.get(iid)
        wb = r.get('water_body') or (place[1] if place else '')
        sp = common.species(r.get('species'))
        if not wb or not sp or day < cutoff:
            continue
        cm = r.get('fork_length_cm')
        if cm:
            try:
                value = float(cm)
            except ValueError:
                value = 0
            if 5 <= value <= 200:
                size[f'{wb}|{sp}|{day}'].append(round(value, 1))
        kind = (r.get('gear_type') or '').strip()
        if kind and kind.lower() not in ('unk', 'na', 'unknown'):
            gear[f'{wb}|{sp}|{day}'][kind] += common.num(r.get('fish_count')) or 1
        if iid in band_of and (iid, sp) not in hit_species:
            hit_species.add((iid, sp))
            hour_hits[f'{wb}|{sp}|{day}'][band_of[iid]] += 1
        if iid in seat_of and (iid, wb) not in hit_seat:
            hit_seat.add((iid, wb))
            seat[f'{wb}|{day}'][seat_of[iid]][1] += 1

    return {
        'from': cutoff,
        'size': dict(size),
        'gear': {k: dict(v) for k, v in gear.items()},
        # parties are per water and band, whatever anyone was fishing for; the fish
        # are per species, so the two are kept in separate tables and divided later
        'hour_parties': {k: dict(v) for k, v in hour_parties.items()},
        'hour_hits': {k: dict(v) for k, v in hour_hits.items()},
        'seat': {k: {b: v for b, v in kinds.items()} for k, kinds in seat.items()},
        'trips': dict(trips),
        'target': dict(target),
    }


#: when a trip started, grouped the way anyone talks about a fishing day
HOUR_BANDS = (('first light', 0, 7), ('morning', 7, 10), ('midday', 10, 14),
              ('afternoon', 14, 18), ('evening', 18, 24))


def _band(hour):
    for name, low, high in HOUR_BANDS:
        if low <= hour < high:
            return name
    return None


def detail(interviews, catches, by_interview):
    """Everything the samplers write down beyond the count.

    How big the fish run, what caught them, whether the boat beat the bank, what time
    of day the parties that caught fish had started, what they were fishing for, and
    whether they had finished their trip when they were asked. WDFW record a fork
    length on about a third of the fish, gear on three quarters, boat-or-bank on four
    interviews in ten, a start time on effectively all of them, a target species on
    six in seven, and whether the trip was complete on nine in ten. None of it is
    summarised anywhere, and all of it is what an angler wants to know before
    deciding how and when to fish a place.
    """
    lengths = defaultdict(list)
    gear = defaultdict(lambda: defaultdict(int))
    for r in catches:
        place = by_interview.get(r.get('interview_id'))
        wb = r.get('water_body') or (place[1] if place else '')
        sp = common.species(r.get('species'))
        if not wb or not sp:
            continue
        cm = r.get('fork_length_cm')
        if cm:
            try:
                value = float(cm)
            except ValueError:
                value = 0
            # a hand-keyed length in the hundreds is a millimetre reading or a slip
            if 5 <= value <= 200:
                lengths[(wb, sp)].append(value)
        kind = (r.get('gear_type') or '').strip()
        if kind and kind.lower() not in ('unk', 'na', 'unknown'):
            gear[(wb, sp)][kind] += common.num(r.get('fish_count')) or 1

    # bank against boat, counted the same way as the party success rate
    seats = defaultdict(lambda: [0, 0])            # (water, kind) -> parties, with fish
    kind_of = {}
    for r in interviews:
        kind = (r.get('angler_type') or '').strip()
        if kind in ('Bank', 'Boat') and r.get('interview_id'):
            kind_of[r['interview_id']] = kind
            wb = r.get('water_body') or ''
            if wb:
                seats[(wb, kind)][0] += 1
    hit = set()
    for r in catches:
        iid = r.get('interview_id')
        if iid in kind_of and (common.num(r.get('fish_count')) or 1) > 0:
            place = by_interview.get(iid)
            wb = r.get('water_body') or (place[1] if place else '')
            if wb and (iid, wb) not in hit:
                hit.add((iid, wb))
                seats[(wb, kind_of[iid])][1] += 1

    # what time the fishing was done, and how it paid — a party is counted in the
    # band it started in, which is the only clock the interview carries
    hours = defaultdict(lambda: [0, 0])            # (water, species, band) -> parties, hits
    band_of, target_of, status_of = {}, {}, {}
    directed = defaultdict(lambda: [0, 0])         # (water, target) -> parties, anglers
    trips = defaultdict(lambda: [0, 0])            # water -> complete, incomplete
    for r in interviews:
        iid = r.get('interview_id')
        wb = r.get('water_body') or ''
        if not iid or not wb:
            continue
        start = _clock(r.get('fishing_start_time'))
        band = _band(int(start)) if start is not None else None
        if band:
            band_of[iid] = band
        target = (r.get('target_species') or '').strip()
        # "Target species not asked" is a record of the question, not an answer
        if (target and target.lower() not in ('unk', 'unknown', 'na')
                and 'not asked' not in target.lower()):
            target_of[iid] = target
            cell = directed[(wb, common.species(target))]
            cell[0] += 1
            cell[1] += max(0, common.num(r.get('angler_count')) or 0)
        status = (r.get('trip_status') or '').strip().lower()
        if status in ('complete', 'incomplete'):
            status_of[iid] = status
            trips[wb][0 if status == 'complete' else 1] += 1

    seen_band, seen_species = set(), defaultdict(set)
    for r in catches:
        iid = r.get('interview_id')
        place = by_interview.get(iid)
        wb = r.get('water_body') or (place[1] if place else '')
        sp = common.species(r.get('species'))
        if not wb or not sp or iid not in band_of:
            continue
        key = (wb, sp, band_of[iid])
        if (iid, sp) not in seen_band:
            seen_band.add((iid, sp))
            hours[key][1] += 1
    # every party that fished a band, whether or not it caught the species
    parties_by_band = defaultdict(int)
    for iid, band in band_of.items():
        place = by_interview.get(iid)
        if place:
            parties_by_band[(place[1], band)] += 1
    for (wb, sp, band), cell in hours.items():
        cell[0] = parties_by_band.get((wb, band), 0)

    def quantile(values, q):
        values = sorted(values)
        return round(values[min(len(values) - 1, int(q * len(values)))], 1)

    out = {'size': {}, 'gear': {}, 'seat': {}, 'hour': {}, 'target': {},
           'trips': {}, 'recent': _recent(interviews, catches, by_interview,
                                          band_of, target_of, status_of)}
    for (wb, sp, band), (parties, hits) in hours.items():
        if parties >= 20:
            out['hour'].setdefault(f'{wb}|{sp}', {})[band] = {
                'parties': parties, 'with_fish': hits}
    for (wb, sp), (parties, anglers) in directed.items():
        if parties >= 20:
            out['target'][f'{wb}|{sp}'] = {'parties': parties, 'anglers': anglers}
    for wb, (complete, incomplete) in trips.items():
        if complete + incomplete >= 20:
            out['trips'][wb] = {'complete': complete, 'incomplete': incomplete}
    for (wb, sp), values in lengths.items():
        if len(values) >= 20:                      # fewer than twenty says nothing
            out['size'][f'{wb}|{sp}'] = {
                'n': len(values), 'mean': round(sum(values) / len(values), 1),
                'p25': quantile(values, 0.25), 'p50': quantile(values, 0.5),
                'p75': quantile(values, 0.75), 'max': round(max(values), 1)}
    for (wb, sp), kinds in gear.items():
        total = sum(kinds.values())
        if total >= 20:
            out['gear'][f'{wb}|{sp}'] = dict(sorted(
                kinds.items(), key=lambda kv: -kv[1])[:6])
    for (wb, kind), (parties, with_fish) in seats.items():
        if parties >= 20:
            out['seat'].setdefault(wb, {})[kind] = {'parties': parties,
                                                    'with_fish': with_fish}
    return out


def water_body_geo(refresh=False, say=print):
    """water body name -> centroid, straight from WDFW's own table."""
    out = {}
    for r in fetch_all(WATER_BODIES, refresh=refresh, say=say):
        lat, lon = r.get('centroid_lat'), r.get('centroid_lon')
        name = (r.get('water_body_desc') or '').strip()
        if not name or not lat or not lon:
            continue
        try:
            out[name] = {'lat': round(float(lat), 6), 'lon': round(float(lon), 6),
                         'source': 'wdfw water body table'}
        except ValueError:
            continue
    say(f'   water body centroids: {len(out)}')
    return out


def published_summary(refresh=False, say=print):
    """WDFW's own summarised creel counts, for the accuracy audit only.

    Nothing on the dashboard is built from this table. It exists so the numbers the
    dashboard *does* build can be held against a total WDFW published themselves.
    """
    return fetch_all(SUMMARY, refresh=refresh, say=say)


def closures(refresh=False, say=print):
    return fetch_all(CLOSURES, refresh=refresh, say=say)


if __name__ == '__main__':
    c, e = load()
    print(f'{len(c):,} catch rows, {len(e):,} effort rows')
    print(c[:2])
    print(e[:2])
