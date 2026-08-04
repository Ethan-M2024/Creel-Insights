"""Turn the two extracted tables into everything the dashboard draws.

The interesting question this file answers is the one the reports never state
outright: where is fishing getting better, and where has it fallen off. That is a
comparison, so it needs a fair baseline. Catch alone will not do — a river with four
anglers and two fish is not beating a bay with four hundred anglers and a hundred —
and neither will catch per angler on its own, because every fishery has a season and
July is not November anywhere.

So a place is compared against itself, at the same point in the season:

    recent      fish kept per angler over the last N days of data
    prior       the same length of window immediately before it
    seasonal    the same calendar window in each of the previous three years

A place is only scored when enough anglers were interviewed in the window to make a
rate mean something, and the counts behind every rate travel with it so a reader can
see what the number rests on.
"""
import json
import os
import re
import statistics
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'sources'))
import paths
from paths import open_text
import common
import geo

#: how many anglers must have been interviewed in a window before a catch rate is
#: reported for it. Below this the rate is noise: one lucky boat moves it by half.
MIN_ANGLERS = 30
#: how many days of history the weekly series carries; older years drop to monthly
WEEKLY_YEARS = 4
#: the windows the dashboard lets a reader switch between. Seven days is the one an
#: angler asks about — what happened this past week — and is short enough that most
#: places fall below the angler threshold and are marked thin rather than ranked.
WINDOWS = (7, 14, 28, 56)
#: how far either side of the calendar window last year's comparison may look
SEASON_SLOP = 10
#: baseline years to look back over
BASELINE_YEARS = 3


#: how far, in degrees of latitude, an area-placed dock may be drawn from its area's
#: centre. Two hundred docks stacked on thirteen centroids draw as thirteen dots, so
#: they are fanned out far enough to be distinguishable and not so far as to imply a
#: position: about four kilometres, well inside every area.
AREA_SPREAD = 0.038


def _spread_area_placed(places):
    """Fan the docks that share an area centroid around it, deterministically.

    The offset is a fixed function of the place's name, so the same dock lands in the
    same spot on every build and a reader watching the map week to week is not
    distracted by dots wandering. It is a drawing device, not a coordinate: these
    places stay labelled as area positions everywhere they appear.
    """
    import math
    grouped = defaultdict(list)
    for p in places.values():
        if p.get('precision') == 'area' and p['lat'] is not None:
            grouped[p['area']].append(p)
    for members in grouped.values():
        members.sort(key=lambda p: p['name'])
        n = len(members)
        if n < 2:
            continue
        for i, p in enumerate(members):
            angle = i * 2.399963                       # golden angle, in radians
            radius = AREA_SPREAD * math.sqrt((i + 0.5) / n)
            lat = p['lat'] + radius * math.sin(angle)
            lon = p['lon'] + radius * math.cos(angle) / max(0.3, math.cos(
                math.radians(p['lat'])))
            p['lat'], p['lon'] = round(lat, 6), round(lon, 6)


def read_rows(path):
    import csv
    if not os.path.exists(path):
        return []
    with open_text(path) as f:
        return list(csv.DictReader(f))


def to_int(v):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return 0


def to_float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def week_start(iso_day):
    d = date.fromisoformat(iso_day)
    return (d - timedelta(days=d.weekday())).isoformat()


def month_start(iso_day):
    return iso_day[:7] + '-01'


def build(catch_rows, effort_rows, place_geo, say=print, success_rows=()):
    as_of = max([r['date'] for r in catch_rows] + [r['date'] for r in effort_rows])
    as_of_d = date.fromisoformat(as_of)

    # ------------------------------------------------------------- places
    # A place is a source plus a name. The same river read two ways — a database
    # export and a sentence in a weekly report — is two different measurements, and
    # averaging them would hide which one a number came from.
    places = {}

    def place_id(row):
        key = (row['source'], row['location'])
        if key not in places:
            g = place_geo.get(row['location']) or {}
            places[key] = {
                'i': len(places), 'name': row['location'], 'source': row['source'],
                'region': row.get('region') or '', 'water': row.get('water') or '',
                'area': row.get('catch_area') or '',
                'lat': g.get('lat'), 'lon': g.get('lon'),
                'precision': g.get('precision'), 'matched_to': g.get('matched_to'),
            }
        return places[key]['i']

    # ------------------------------------------------------------- daily tallies
    effort_day = defaultdict(lambda: [0, 0.0, 0])       # anglers, hours, interviews
    for r in effort_rows:
        pid = place_id(r)
        cell = effort_day[(pid, r['date'])]
        cell[0] += to_int(r.get('anglers'))
        cell[1] += to_float(r.get('angler_hours'))
        cell[2] += to_int(r.get('interviews'))

    catch_day = defaultdict(lambda: [0, 0])             # kept, released
    # Where the report says whether the fish was clipped, that is kept alongside.
    # It is the difference between a fishery and a closed one under mark-selective
    # rules — an unclipped Chinook goes back — and WDFW record it on a third of the
    # fish, so it is carried rather than averaged away.
    origin_day = defaultdict(lambda: [0, 0, 0, 0])   # kept H, kept W, rel H, rel W
    species_seen = defaultdict(int)
    for r in catch_rows:
        pid = place_id(r)
        sp = r['species']
        if not sp:
            continue
        n = to_int(r.get('fish'))
        kept = r.get('fate') == 'kept'
        cell = catch_day[(pid, sp, r['date'])]
        cell[0 if kept else 1] += n
        origin = r.get('origin')
        if origin in ('hatchery', 'wild'):
            slot = (0 if kept else 2) + (0 if origin == 'hatchery' else 1)
            origin_day[(pid, sp, r['date'])][slot] += n
        species_seen[sp] += n

    # A place is sampled in whichever area the sampler was working that day, so the
    # area it belongs to is the one it is sampled in most, not the one it happened to
    # appear under first.
    area_votes = defaultdict(lambda: defaultdict(int))
    for r in effort_rows:
        num = area_key(r.get('catch_area'))
        if num:
            area_votes[(r['source'], r['location'])][num] += 1
    centroids = geo.area_centroids()
    for key, p in places.items():
        votes = area_votes.get(key)
        if votes:
            p['area'] = max(votes.items(), key=lambda kv: kv[1])[0]
        if p['lat'] is None and p.get('area') in centroids:
            # no WDFW coordinate exists for this dock; the honest position is the
            # middle of the area it reports to, said plainly rather than implied
            p['lat'], p['lon'] = centroids[p['area']]
            p['precision'] = 'area'
            p['matched_to'] = f"Marine Area {p['area']}"
    _spread_area_placed(places)

    species = [s for s, _ in sorted(species_seen.items(),
                                    key=lambda kv: (-kv[1], kv[0]))]
    sp_index = {s: i for i, s in enumerate(species)}
    say(f'   {len(places)} places, {len(species)} species, '
        f'{len(catch_day):,} place-species-days')

    # ------------------------------------------------------------- series
    weekly_from = (as_of_d - timedelta(days=365 * WEEKLY_YEARS)).isoformat()
    weekly = defaultdict(lambda: [0, 0])
    monthly = defaultdict(lambda: [0, 0])
    for (pid, sp, day), (kept, rel) in catch_day.items():
        monthly[(pid, sp_index[sp], month_start(day))][0] += kept
        monthly[(pid, sp_index[sp], month_start(day))][1] += rel
        if day >= weekly_from:
            cell = weekly[(pid, sp_index[sp], week_start(day))]
            cell[0] += kept
            cell[1] += rel

    weekly_effort = defaultdict(lambda: [0, 0.0])
    monthly_effort = defaultdict(lambda: [0, 0.0])
    for (pid, day), (anglers, hours, _) in effort_day.items():
        m = monthly_effort[(pid, month_start(day))]
        m[0] += anglers
        m[1] += hours
        if day >= weekly_from:
            w = weekly_effort[(pid, week_start(day))]
            w[0] += anglers
            w[1] += hours

    # ------------------------------------------------------- interview outcomes
    # How often a party caught one, counted from the interviews themselves. Only the
    # statewide database publishes interviews one by one, so this covers the rivers
    # and lakes in it and says nothing about the rest — which is better than
    # modelling a number for places whose interviews were never published.
    outcome_day = defaultdict(lambda: [0, 0])       # (pid, sp, day) -> parties, hits
    for r in success_rows:
        key = (r['source'], r['location'])
        if key not in places or r['species'] not in sp_index:
            continue
        cell = outcome_day[(places[key]['i'], r['species'], r['date'])]
        cell[0] += to_int(r['interviews'])
        cell[1] += to_int(r['with_fish'])
    say(f'   interview outcomes: {len(outcome_day):,} place-species-days')

    # ------------------------------------------------------------- lifetime
    # The trend windows answer "what is happening now", which by construction leaves
    # out every place that is out of season, closed, or no longer surveyed — most of
    # the record. This is the whole record instead: one row per place per species,
    # over every year it was ever sampled, so nothing WDFW counted is invisible.
    lifetime, place_span = totals(catch_day, effort_day, sp_index, say=say,
                                  origin_day=origin_day, outcome_day=outcome_day)

    # ------------------------------------------------------------- trends
    trend = trends(catch_day, effort_day, places, sp_index, as_of_d, say=say,
                   origin_day=origin_day, outcome_day=outcome_day)

    # ------------------------------------------------------------- by area
    # Two hundred of the Puget Sound ramps are marinas and city docks that appear in
    # no WDFW coordinate dataset, so they can never be a dot on the map. They all
    # carry a catch and reporting area, though, which is the unit WDFW manages the
    # fishery in — so the same arithmetic is run again over areas, and nothing that
    # cannot be placed is lost from the map, only from the point view.
    shapes = waters(say=say)
    area_catch, area_effort, area_names = by_water(
        catch_day, effort_day, places, shapes, effort_rows)
    area_trend = trends(area_catch, area_effort, area_names, sp_index, as_of_d,
                        say=say, label='area')
    # the whole record by area as well, so switching to the area view does not
    # quietly drop back to the last eight weeks
    area_lifetime, area_span = totals(area_catch, area_effort, sp_index, say=say,
                                      label='area')

    # ------------------------------------------------------------- seasonality
    season = seasonality(catch_day, effort_day, sp_index, as_of_d)

    # ------------------------------------------------------------- totals
    by_year = defaultdict(lambda: defaultdict(int))
    by_year_rel = defaultdict(lambda: defaultdict(int))
    for (pid, sp, day), (kept, rel) in catch_day.items():
        by_year[day[:4]][sp] += kept
        by_year_rel[day[:4]][sp] += rel
    effort_year = defaultdict(int)
    for (pid, day), (anglers, _h, _i) in effort_day.items():
        effort_year[day[:4]] += anglers

    payload = {
        'meta': {
            'built': datetime.now(timezone.utc).isoformat(timespec='seconds'),
            'as_of': as_of,
            'first': min(d for _, d in effort_day) if effort_day else as_of,
            'species': species,
            'headline_species': [s for s in common.HEADLINE_SPECIES if s in sp_index],
            'windows': list(WINDOWS),
            'min_anglers': MIN_ANGLERS,
            'weekly_from': weekly_from,
            'regions': sorted({p['region'] for p in places.values() if p['region']}),
            'sources': sorted({p['source'] for p in places.values()}),
            'total_fish': sum(species_seen.values()),
            'total_anglers': sum(v[0] for v in effort_day.values()),
        },
        'places': [
            dict({k: v for k, v in p.items() if k != 'i'},
                 **place_span.get(p['i'], {}))
            for p in sorted(places.values(), key=lambda p: p['i'])],
        'weekly': _pack(weekly, weekly_effort),
        'monthly': _pack(monthly, monthly_effort),
        'trend': trend,
        'lifetime': lifetime,
        'area_trend': area_trend,
        'area_places': [
            dict({k: v for k, v in a.items() if k != 'i'},
                 **area_span.get(a['i'], {}))
            for a in sorted(area_names.values(), key=lambda a: a['i'])],
        'area_lifetime': area_lifetime,
        'areas': shapes,
        'season': season,
        # every species, not just the year's biggest: the species tab lets a reader
        # pick any of the fifty-one, and a truncated list would draw them as zero
        'years': {y: {sp: n for sp, n in sorted(v.items()) if n}
                  for y, v in sorted(by_year.items())},
        # released as well as kept, so the species tab can answer what was caught
        # rather than only what was taken home
        'years_released': {y: {sp: n for sp, n in sorted(v.items()) if n}
                           for y, v in sorted(by_year_rel.items())},
        # which parts of the state are actually in here, so a reader looking for a
        # water that is missing can see whether anyone surveys it at all
        'coverage': coverage(places, catch_day, effort_day, say=say),
        # what the samplers wrote down beyond the count: how big, on what, and
        # whether the boat or the bank did better
        'detail': detail_by_place(places, sp_index, effort_day=effort_day, say=say),
        'year_anglers': dict(sorted(effort_year.items())),
    }
    return payload


#: "Area 10, Seattle-Bremerton area", "Westport (Marine Area 2)", "Area 2.1" — the
#: number is the only part that identifies the water, and it is written six ways
AREA_NUMBER = re.compile(r'(?:marine\s+)?area\s*([0-9]+(?:\.[0-9]+)?)', re.I)


def area_key(text):
    m = AREA_NUMBER.search(text or '')
    return m.group(1) if m else None


def waters(say=print):
    """Every shape the map can shade: marine areas, ocean bands, river basins.

    Between them they cover the whole state, which is the point. A map of dots asks
    the reader to find the fishing; a map of filled water tells them, and a basin
    with no creel in it is grey rather than absent.
    """
    shapes = []
    for a in geo.catch_areas(say=say):
        code = re.match(r'(\d+(?:\.\d+)?)', a.get('code') or '')
        if not code:
            continue
        shapes.append({'name': f'Marine Area {code.group(1)}', 'code': code.group(1),
                       'kind': 'marine', 'rings': a['rings']})
    shapes.extend(geo.ocean_areas())
    for b in geo.basins(say=say):
        shapes.append({'name': b['name'], 'code': 'wria-' + b['code'],
                       'kind': 'basin', 'rings': b['rings']})
    # several polygons make up one reporting area (10, 10A, 10E); they are one water
    merged = {}
    for shape in shapes:
        key = (shape['kind'], shape['code'])
        if key in merged:
            merged[key]['rings'].extend(shape['rings'])
        else:
            merged[key] = dict(shape, rings=list(shape['rings']))
    out = list(merged.values())
    say(f'   waters on the map: {len(out)}')
    return out


def water_of(place, shapes):
    """Which shape a place sits in: its reporting area first, then the map.

    A marine place states the area it was sampled in, and that is better than any
    coordinate. Everything else is placed by where it is — a river creel falls in one
    basin, and that basin is the ground the reader is looking at.
    """
    area = area_key(place.get('area'))
    if area:
        for i, shape in enumerate(shapes):
            if shape['kind'] in ('marine', 'ocean') and shape['code'] == area:
                return i
    lat, lon = place.get('lat'), place.get('lon')
    if lat is None or lon is None:
        return None
    marine_first = place.get('water') == 'marine'
    order = ('marine', 'ocean', 'basin') if marine_first else ('basin', 'marine', 'ocean')
    for kind in order:
        for i, shape in enumerate(shapes):
            if shape['kind'] == kind and geo.point_in_rings(lon, lat, shape['rings']):
                return i
    return None


def by_water(catch_day, effort_day, places, shapes, effort_rows):
    """Re-tally the daily figures by water rather than by place.

    Marine days are filed by the area the sampler recorded that day, not by the place
    they came from: a Sekiu dock reports Area 5 one day and Area 4 the next, and
    pinning it to one of them leaves the other looking empty. Days with no area on
    them, and all of fresh water, fall back to the shape the place itself sits in.
    """
    waters_ = {}
    marine_index = {shape['code']: i for i, shape in enumerate(shapes)
                    if shape['kind'] in ('marine', 'ocean')}
    place_shape = {p['i']: water_of(p, shapes) for p in places.values()}
    where = {(p['source'], p['name']): p['i'] for p in places.values()}

    # (place, day) -> shape, from the area written on that day's rows
    day_shape = {}
    for r in effort_rows:
        num = area_key(r.get('catch_area'))
        pid = where.get((r['source'], r['location']))
        if num in marine_index and pid is not None:
            day_shape[(pid, r['date'])] = marine_index[num]

    def water_id(index):
        shape = shapes[index]
        if index not in waters_:
            waters_[index] = {
                'i': len(waters_), 'name': shape['name'], 'source': 'water',
                'region': '', 'kind': shape['kind'], 'shape': index,
                'water': 'fresh' if shape['kind'] == 'basin' else 'marine',
                'area': shape['code'], 'lat': None, 'lon': None,
                'precision': 'area'}
        return waters_[index]['i']

    def shape_for(pid, day):
        return day_shape.get((pid, day), place_shape.get(pid))

    a_catch = defaultdict(lambda: [0, 0])
    a_effort = defaultdict(lambda: [0, 0.0, 0])
    for (pid, day), (anglers, hours, interviews) in effort_day.items():
        index = shape_for(pid, day)
        if index is None:
            continue
        cell = a_effort[(water_id(index), day)]
        cell[0] += anglers
        cell[1] += hours
        cell[2] += interviews
    for (pid, sp, day), (kept, rel) in catch_day.items():
        index = shape_for(pid, day)
        if index is None:
            continue
        cell = a_catch[(water_id(index), sp, day)]
        cell[0] += kept
        cell[1] += rel
    return a_catch, a_effort, waters_


def by_area(catch_rows, effort_rows):
    """Re-tally the daily figures by catch and reporting area instead of by place.

    Read from the rows rather than from the places: a ramp is sampled for several
    areas over a season — a Sekiu dock reports Area 5 one day and Area 4 the next —
    so pinning each place to the first area it happened to appear under would file a
    week of Area 11 fishing under whichever area that ramp was first seen in, and
    leave Area 11 looking empty.
    """
    areas = {}

    def area_id(row):
        num = area_key(row.get('catch_area'))
        if not num:
            return None
        if num not in areas:
            areas[num] = {'i': len(areas), 'name': f'Marine Area {num}',
                          'source': 'catch area', 'region': row.get('region') or '',
                          'water': row.get('water') or 'marine', 'area': num,
                          'lat': None, 'lon': None, 'precision': 'area'}
        return areas[num]['i']

    a_catch = defaultdict(lambda: [0, 0])
    a_effort = defaultdict(lambda: [0, 0.0, 0])
    for r in effort_rows:
        aid = area_id(r)
        if aid is None:
            continue
        cell = a_effort[(aid, r['date'])]
        cell[0] += to_int(r.get('anglers'))
        cell[1] += to_float(r.get('angler_hours'))
        cell[2] += to_int(r.get('interviews'))
    for r in catch_rows:
        aid = area_id(r)
        if aid is None or not r['species']:
            continue
        cell = a_catch[(aid, r['species'], r['date'])]
        cell[0 if r.get('fate') == 'kept' else 1] += to_int(r.get('fish'))
    return a_catch, a_effort, areas


def totals(catch_day, effort_day, sp_index, say=print, label='place',
           origin_day=None, outcome_day=None):
    """Every place and species over the whole record, however long ago it was fished.

    Returns the per-place-species totals and, separately, each place's span and
    lifetime effort — the second is what lets the map show a place that has not been
    surveyed since 2015 without pretending it is current.
    """
    per_place = defaultdict(lambda: {'anglers': 0, 'hours': 0.0, 'days': 0,
                                     'first': '9999', 'last': ''})
    for (pid, day), (anglers, hours, _interviews) in effort_day.items():
        cell = per_place[pid]
        cell['anglers'] += anglers
        cell['hours'] += hours
        cell['days'] += 1
        cell['first'] = min(cell['first'], day)
        cell['last'] = max(cell['last'], day)

    per_species = defaultdict(lambda: [0, 0, '9999', ''])
    for (pid, sp, day), (kept, rel) in catch_day.items():
        cell = per_species[(pid, sp_index[sp])]
        cell[0] += kept
        cell[1] += rel
        cell[2] = min(cell[2], day)
        cell[3] = max(cell[3], day)

    outcomes_by_name = _outcome_totals(outcome_day, '0000', '9999')
    lifetime_outcomes = {(pid, sp_index[name]): v
                         for (pid, name), v in outcomes_by_name.items()
                         if name in sp_index}
    by_name = _origin_totals(origin_day, '0000', '9999')
    marks = {(pid, sp_index[name]): v for (pid, name), v in by_name.items()
             if name in sp_index}
    rows = []
    for (pid, sp), (k, r, first, last) in sorted(per_species.items()):
        row = {'p': pid, 's': sp, 'kept': k, 'rel': r, 'first': first, 'last': last}
        found = marks.get((pid, sp))
        if found:
            row.update({'kept_h': found[0], 'kept_w': found[1],
                        'rel_h': found[2], 'rel_w': found[3]})
        parties = lifetime_outcomes.get((pid, sp))
        if parties and parties[0] >= 10:
            row.update({'parties': parties[0], 'parties_hit': parties[1]})
        rows.append(row)

    span = {}
    for pid, cell in per_place.items():
        span[pid] = {
            'anglers': cell['anglers'], 'days': cell['days'],
            'hours': round(cell['hours'], 1),
            'first': cell['first'] if cell['first'] != '9999' else '',
            'last': cell['last'],
        }
    say(f'   whole record: {len(rows):,} {label}-species totals across '
        f'{len(span)} {label}s')
    return rows, span


def _pack(catch, effort):
    """Column arrays: they compress far better than a list of objects."""
    keys = sorted(catch)
    periods = sorted({k[2] for k in keys} | {k[1] for k in effort})
    p_index = {p: i for i, p in enumerate(periods)}
    return {
        'periods': periods,
        'place': [k[0] for k in keys],
        'species': [k[1] for k in keys],
        'period': [p_index[k[2]] for k in keys],
        'kept': [catch[k][0] for k in keys],
        'released': [catch[k][1] for k in keys],
        'effort': [[pid, p_index[per], anglers, round(hours, 1)]
                   for (pid, per), (anglers, hours) in sorted(effort.items())],
    }


def _window_totals(catch_day, effort_day, start, end):
    """Fish, anglers and angler-hours between two dates, per place and species."""
    fish = defaultdict(lambda: [0, 0])
    anglers = defaultdict(int)
    hours = defaultdict(float)
    for (pid, day), (a, h, _i) in effort_day.items():
        if start <= day <= end:
            anglers[pid] += a
            hours[pid] += h
    for (pid, sp, day), (kept, rel) in catch_day.items():
        if start <= day <= end:
            cell = fish[(pid, sp)]
            cell[0] += kept
            cell[1] += rel
    return fish, anglers, hours


#: how many angler-hours a place must have behind it before a per-hour rate is
#: reported. Only the interview database times its trips, so a place fed by the
#: weekly reports alone has none of these and is left blank rather than divided by
#: an hour count that is really a zero.
MIN_HOURS = 20


def _outcome_totals(outcome_day, start, end):
    """Parties interviewed and parties that caught one, between two dates."""
    out = defaultdict(lambda: [0, 0])
    for (pid, sp, day), (parties, hits) in (outcome_day or {}).items():
        if start <= day <= end:
            cell = out[(pid, sp)]
            cell[0] += parties
            cell[1] += hits
    return {k: v for k, v in out.items() if v[0]}


def _origin_totals(origin_day, start, end):
    """Clipped and unclipped fish between two dates, per place and species."""
    out = defaultdict(lambda: [0, 0, 0, 0])
    for (pid, sp, day), counts in (origin_day or {}).items():
        if start <= day <= end:
            cell = out[(pid, sp)]
            for i, n in enumerate(counts):
                cell[i] += n
    return {k: v for k, v in out.items() if any(v)}


def trends(catch_day, effort_day, places, sp_index, as_of_d, say=print,
           label='place', origin_day=None, outcome_day=None):
    """Score every place and species for whether it is picking up or falling off."""
    out = []
    for window in WINDOWS:
        recent_start = (as_of_d - timedelta(days=window - 1)).isoformat()
        recent_end = as_of_d.isoformat()
        prior_start = (as_of_d - timedelta(days=2 * window - 1)).isoformat()
        prior_end = (as_of_d - timedelta(days=window)).isoformat()

        r_fish, r_ang, r_hrs = _window_totals(
            catch_day, effort_day, recent_start, recent_end)
        r_origin = _origin_totals(origin_day, recent_start, recent_end)
        r_outcome = _outcome_totals(outcome_day, recent_start, recent_end)
        p_fish, p_ang, p_hrs = _window_totals(
            catch_day, effort_day, prior_start, prior_end)

        # the same calendar window in each of the previous few years
        season_fish, season_ang, season_hrs = [], [], []
        for back in range(1, BASELINE_YEARS + 1):
            try:
                anchor = as_of_d.replace(year=as_of_d.year - back)
            except ValueError:                      # 29 February
                anchor = as_of_d.replace(year=as_of_d.year - back, day=28)
            s = (anchor - timedelta(days=window - 1 + SEASON_SLOP)).isoformat()
            e = (anchor + timedelta(days=SEASON_SLOP)).isoformat()
            f, a, h = _window_totals(catch_day, effort_day, s, e)
            season_fish.append(f)
            season_ang.append(a)
            season_hrs.append(h)

        for (pid, sp), (kept, rel) in sorted(r_fish.items()):
            anglers = r_ang.get(pid, 0)
            if anglers < 1:
                continue
            hours = r_hrs.get(pid, 0.0)
            # Kept and released are carried through the comparisons separately, not
            # summed here: on a river running catch-and-release the released fish are
            # the whole fishery, and a reader who asks for them must get a baseline
            # measured the same way rather than one built out of the kept column.
            # The same goes for the two ways of measuring effort: an angler-hour and
            # an angler are different denominators, and mixing them across a
            # comparison would put a change in one down to the other.
            def rate(fish_at, effort_at, floor):
                """The four rates for one window: kept and released, per unit."""
                if effort_at < floor:
                    return None, None
                pair = fish_at.get((pid, sp), [0, 0])
                return pair[0] / effort_at, pair[1] / effort_at

            enough_anglers = max(MIN_ANGLERS // 3, 5)
            prior, prior_rel = rate(p_fish, p_ang.get(pid, 0), enough_anglers)
            prior_h, prior_hr = rate(p_fish, p_hrs.get(pid, 0.0), MIN_HOURS)

            rates, rates_rel, rates_h, rates_hr = [], [], [], []
            for f, a, h in zip(season_fish, season_ang, season_hrs):
                # the seasonal window is widened by the slop on both sides, so its
                # rate is the same shape as the recent one, just measured wider
                k, r = rate(f, a.get(pid, 0), enough_anglers)
                if k is not None:
                    rates.append(k)
                    rates_rel.append(r)
                kh, rh = rate(f, h.get(pid, 0.0), MIN_HOURS)
                if kh is not None:
                    rates_h.append(kh)
                    rates_hr.append(rh)

            def median_or_none(values):
                return round(statistics.median(values), 4) if values else None

            row = {
                'w': window, 'p': pid, 's': sp_index[sp],
                # a rate off a handful of anglers is a rumour, not a measurement:
                # it is shown, but marked, and never ranked
                'thin': 1 if anglers < MIN_ANGLERS else 0,
                'kept': kept, 'rel': rel, 'anglers': anglers,
                'cpue': round(kept / anglers, 4),
                'cpue_r': round(rel / anglers, 4),
                'prior': None if prior is None else round(prior, 4),
                'prior_r': None if prior_rel is None else round(prior_rel, 4),
                'season': median_or_none(rates),
                'season_r': median_or_none(rates_rel),
                'season_years': len(rates),
            }
            parties = r_outcome.get((pid, sp))
            if parties and parties[0] >= 10:
                # under ten interviews the share is a coin toss dressed as a rate
                row.update({'parties': parties[0], 'parties_hit': parties[1]})
            marks = r_origin.get((pid, sp))
            if marks:
                # clipped and unclipped, as counted; the rest of the fish simply
                # were not checked, and are left out rather than assumed either way
                row.update({'kept_h': marks[0], 'kept_w': marks[1],
                            'rel_h': marks[2], 'rel_w': marks[3]})
            if hours >= MIN_HOURS:
                # only the interview database times its trips, so most places have
                # no hours at all and simply carry none of these
                row.update({
                    'hours': round(hours, 1),
                    'cph': round(kept / hours, 4),
                    'cph_r': round(rel / hours, 4),
                    'prior_h': None if prior_h is None else round(prior_h, 4),
                    'prior_hr': None if prior_hr is None else round(prior_hr, 4),
                    'season_h': median_or_none(rates_h),
                    'season_hr': median_or_none(rates_hr),
                    'season_years_h': len(rates_h),
                })
            out.append(row)
    say(f'   scored {len(out):,} {label}-species-window trends')
    return out


#: the Cascade crest, roughly: everything east of this line is eastern Washington
CREST = -120.7


def detail_by_place(places, sp_index, effort_day=None, say=print):
    """Re-key the size, gear and bank-or-boat summaries onto place and species ids.

    They are gathered by water body name, because that is what the interviews carry;
    the dashboard works in place ids, and a place is a source plus a name, so the
    same water read by two sources keeps its own row.
    """
    if not os.path.exists(paths.DETAIL):
        return {}
    with open(paths.DETAIL, encoding='utf-8') as f:
        raw = json.load(f)
    by_name = defaultdict(list)
    for p in places.values():
        by_name[p['name']].append(p['i'])

    size, gear, seat = {}, {}, {}
    for key, value in (raw.get('size') or {}).items():
        name, _, species = key.partition('|')
        if species in sp_index:
            for pid in by_name.get(name, ()):
                size[f'{pid}|{sp_index[species]}'] = value
    for key, value in (raw.get('gear') or {}).items():
        name, _, species = key.partition('|')
        if species in sp_index:
            for pid in by_name.get(name, ()):
                gear[f'{pid}|{sp_index[species]}'] = value
    for name, value in (raw.get('seat') or {}).items():
        for pid in by_name.get(name, ()):
            seat[str(pid)] = value
    hour, target, trips = {}, {}, {}
    for key, value in (raw.get('hour') or {}).items():
        name, _, species = key.partition('|')
        if species in sp_index:
            for pid in by_name.get(name, ()):
                hour[f'{pid}|{sp_index[species]}'] = value
    for key, value in (raw.get('target') or {}).items():
        name, _, species = key.partition('|')
        if species in sp_index:
            for pid in by_name.get(name, ()):
                target[f'{pid}|{sp_index[species]}'] = value
    for name, value in (raw.get('trips') or {}).items():
        for pid in by_name.get(name, ()):
            trips[str(pid)] = value

    # which days of the week the fishing happens on, from every source rather than
    # only the interviews: a ramp that is a Saturday scrum is worth knowing about
    weekday = defaultdict(lambda: [0] * 7)
    for (pid, day), (anglers, _h, _i) in (effort_day or {}).items():
        weekday[pid][date.fromisoformat(day).weekday()] += anglers
    crowd = {str(pid): counts for pid, counts in weekday.items() if sum(counts) >= 200}

    # the same notes day by day for the recent past, so a reader who asks for the
    # last seven days is answered about the last seven days
    recent = {'from': (raw.get('recent') or {}).get('from', '')}
    for table in ('size', 'gear', 'hour_hits', 'target'):
        moved = {}
        for key, value in ((raw.get('recent') or {}).get(table) or {}).items():
            name, species, day = key.split('|')
            if species in sp_index:
                for pid in by_name.get(name, ()):
                    moved[f'{pid}|{sp_index[species]}|{day}'] = value
        recent[table] = moved
    for table in ('hour_parties', 'seat', 'trips'):
        moved = {}
        for key, value in ((raw.get('recent') or {}).get(table) or {}).items():
            name, day = key.split('|')
            for pid in by_name.get(name, ()):
                moved[f'{pid}|{day}'] = value
        recent[table] = moved

    say(f'   detail: {len(size)} size, {len(gear)} gear, {len(seat)} bank-or-boat, '
        f'{len(hour)} by time of day, {len(target)} directed effort, '
        f'{len(crowd)} weekday profiles, day by day since {recent.get("from") or "—"}')
    return {'size': size, 'gear': gear, 'seat': seat, 'hour': hour,
            'target': target, 'trips': trips, 'crowd': crowd, 'recent': recent}


def coverage(places, catch_day, effort_day, say=print):
    """What each region contributes, and which side of the mountains it is on.

    WDFW publish creel interviews for ten survey projects, all of them west of the
    Cascades or on the Columbia. Nothing is published for the eastern districts, and
    a reader who cannot find Banks Lake deserves to be told that rather than left to
    conclude the fishing there is bad.
    """
    rows = defaultdict(lambda: {'places': 0, 'anglers': 0, 'fish': 0,
                                'first': '9999', 'last': '', 'east': 0})
    by_pid = {}
    for p in places.values():
        cell = rows[p['region'] or 'Unassigned']
        cell['places'] += 1
        if p.get('lon') is not None and p['lon'] > CREST:
            cell['east'] += 1
        by_pid[p['i']] = p['region'] or 'Unassigned'
    for (pid, day), (anglers, _h, _i) in effort_day.items():
        cell = rows[by_pid.get(pid, 'Unassigned')]
        cell['anglers'] += anglers
        cell['first'] = min(cell['first'], day)
        cell['last'] = max(cell['last'], day)
    for (pid, _sp, _day), (kept, rel) in catch_day.items():
        rows[by_pid.get(pid, 'Unassigned')]['fish'] += kept + rel
    out = [dict(v, region=k, first=v['first'] if v['first'] != '9999' else '')
           for k, v in sorted(rows.items(), key=lambda kv: -kv[1]['anglers'])]
    say(f'   coverage: {len(out)} regions, '
        f"{sum(r['east'] for r in out)} places east of the Cascades")
    return out


def seasonality(catch_day, effort_day, sp_index, as_of_d, years=5):
    """When in the year each species is actually caught, statewide.

    Built from the last few years only: a run's timing shifts, and a median that
    includes 2013 answers a question about 2013.
    """
    since = (as_of_d - timedelta(days=365 * years)).isoformat()
    kept = defaultdict(int)
    anglers = defaultdict(int)
    for (pid, day), (a, _h, _i) in effort_day.items():
        if day >= since:
            anglers[_isoweek(day)] += a
    released = defaultdict(int)
    for (pid, sp, day), (k, r) in catch_day.items():
        if day >= since:
            kept[(sp_index[sp], _isoweek(day))] += k
            released[(sp_index[sp], _isoweek(day))] += r
    out = defaultdict(lambda: [0] * 53)
    out_rel = defaultdict(lambda: [0] * 53)
    for (sp, wk), n in kept.items():
        if 1 <= wk <= 53:
            out[sp][wk - 1] = n
    for (sp, wk), n in released.items():
        if 1 <= wk <= 53:
            out_rel[sp][wk - 1] = n
    return {'weeks': list(range(1, 54)),
            'kept': {str(sp): v for sp, v in out.items()},
            'released': {str(sp): v for sp, v in out_rel.items()},
            'anglers': [anglers.get(w, 0) for w in range(1, 54)]}


def _isoweek(iso_day):
    return date.fromisoformat(iso_day).isocalendar()[1]


def main(say=print):
    catch_rows = read_rows(paths.RAW)
    effort_rows = read_rows(paths.EFFORT)
    if not catch_rows:
        raise SystemExit('no extracted rows found; run the update first')

    names = {r['location'] for r in catch_rows} | {r['location'] for r in effort_rows}
    import socrata
    water_bodies = socrata.water_body_geo(say=say)
    # which region each name was reported from, so a dock cannot borrow a position
    # from a namesake two hundred miles away
    regions = {}
    for r in catch_rows + effort_rows:
        regions.setdefault(r['location'], r.get('region') or '')
    placed, unplaced = geo.build(names, water_bodies=water_bodies, regions=regions,
                                 say=say)
    with open(paths.PLACE_GEO, 'w', encoding='utf-8') as f:
        json.dump({'placed': placed, 'unplaced': sorted(unplaced)}, f, indent=0)

    success_rows = read_rows(paths.SUCCESS)
    payload = build(catch_rows, effort_rows, placed, say=say,
                    success_rows=success_rows)
    # what the reader cares about is which places are missing from the map, not
    # which names failed the first matching pass — most of those are later placed
    # from their catch area
    payload['unplaced'] = sorted(
        p['name'] for p in payload['places'] if p.get('lat') is None)
    if os.path.exists(paths.OUTLINE):
        with open(paths.OUTLINE, encoding='utf-8') as f:
            payload['outline'] = json.load(f)
    if os.path.exists(paths.QUOTAS):
        with open(paths.QUOTAS, encoding='utf-8') as f:
            payload['quotas'] = json.load(f)
    if os.path.exists(paths.MANIFEST):
        with open(paths.MANIFEST, encoding='utf-8') as f:
            payload['manifest'] = json.load(f)
    write_payload(payload, say=say)
    return payload


def write_payload(payload, audit=None, say=print):
    """Write the payload, optionally with the audit that has since been run.

    The audit reads the same two tables the payload is built from, so it can only
    run after the build. Writing twice is cheap and keeps the page's accuracy panel
    describing this build rather than the last one.
    """
    if audit is not None:
        payload['audit'] = audit
    with open_text(paths.PAYLOAD, 'w') as f:
        json.dump(payload, f, separators=(',', ':'))
    say(f'   dashboard payload: {os.path.getsize(paths.PAYLOAD) / 1024:.0f} KB')
    return payload


if __name__ == '__main__':
    main()
