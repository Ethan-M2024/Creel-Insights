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
#: the windows the dashboard lets a reader switch between
WINDOWS = (14, 28, 56)
#: how far either side of the calendar window last year's comparison may look
SEASON_SLOP = 10
#: baseline years to look back over
BASELINE_YEARS = 3


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


def build(catch_rows, effort_rows, place_geo, say=print):
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
    species_seen = defaultdict(int)
    for r in catch_rows:
        pid = place_id(r)
        sp = r['species']
        if not sp:
            continue
        n = to_int(r.get('fish'))
        cell = catch_day[(pid, sp, r['date'])]
        cell[0 if r.get('fate') == 'kept' else 1] += n
        species_seen[sp] += n

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

    # ------------------------------------------------------------- trends
    trend = trends(catch_day, effort_day, places, sp_index, as_of_d, say=say)

    # ------------------------------------------------------------- by area
    # Two hundred of the Puget Sound ramps are marinas and city docks that appear in
    # no WDFW coordinate dataset, so they can never be a dot on the map. They all
    # carry a catch and reporting area, though, which is the unit WDFW manages the
    # fishery in — so the same arithmetic is run again over areas, and nothing that
    # cannot be placed is lost from the map, only from the point view.
    area_catch, area_effort, area_names = by_area(catch_day, effort_day, places)
    area_trend = trends(area_catch, area_effort, area_names, sp_index, as_of_d,
                        say=say, label='area')

    # ------------------------------------------------------------- seasonality
    season = seasonality(catch_day, effort_day, sp_index, as_of_d)

    # ------------------------------------------------------------- totals
    by_year = defaultdict(lambda: defaultdict(int))
    for (pid, sp, day), (kept, rel) in catch_day.items():
        by_year[day[:4]][sp] += kept
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
            {k: v for k, v in p.items() if k != 'i'}
            for p in sorted(places.values(), key=lambda p: p['i'])],
        'weekly': _pack(weekly, weekly_effort),
        'monthly': _pack(monthly, monthly_effort),
        'trend': trend,
        'area_trend': area_trend,
        'area_places': [
            {k: v for k, v in a.items() if k != 'i'}
            for a in sorted(area_names.values(), key=lambda a: a['i'])],
        'season': season,
        # every species, not just the year's biggest: the species tab lets a reader
        # pick any of the fifty-one, and a truncated list would draw them as zero
        'years': {y: {sp: n for sp, n in sorted(v.items()) if n}
                  for y, v in sorted(by_year.items())},
        'year_anglers': dict(sorted(effort_year.items())),
    }
    return payload


#: "Area 10, Seattle-Bremerton area", "Westport (Marine Area 2)", "Area 2.1" — the
#: number is the only part that identifies the water, and it is written six ways
AREA_NUMBER = re.compile(r'(?:marine\s+)?area\s*([0-9]+(?:\.[0-9]+)?)', re.I)


def area_key(text):
    m = AREA_NUMBER.search(text or '')
    return m.group(1) if m else None


def by_area(catch_day, effort_day, places):
    """Re-tally the daily figures by catch and reporting area instead of by place."""
    areas = {}
    lookup = {}
    for p in places.values():
        num = area_key(p.get('area')) or area_key(p.get('name'))
        if not num:
            continue
        if num not in areas:
            areas[num] = {'i': len(areas), 'name': f'Marine Area {num}',
                          'source': 'catch area', 'region': p.get('region') or '',
                          'water': 'marine', 'area': num,
                          'lat': None, 'lon': None, 'precision': 'area'}
        lookup[p['i']] = areas[num]['i']

    a_catch = defaultdict(lambda: [0, 0])
    a_effort = defaultdict(lambda: [0, 0.0, 0])
    for (pid, sp, day), (kept, rel) in catch_day.items():
        aid = lookup.get(pid)
        if aid is None:
            continue
        cell = a_catch[(aid, sp, day)]
        cell[0] += kept
        cell[1] += rel
    for (pid, day), (anglers, hours, interviews) in effort_day.items():
        aid = lookup.get(pid)
        if aid is None:
            continue
        cell = a_effort[(aid, day)]
        cell[0] += anglers
        cell[1] += hours
        cell[2] += interviews
    return a_catch, a_effort, areas


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
    """Fish and anglers between two dates, per place and per place-species."""
    fish = defaultdict(lambda: [0, 0])
    anglers = defaultdict(int)
    for (pid, day), (a, _h, _i) in effort_day.items():
        if start <= day <= end:
            anglers[pid] += a
    for (pid, sp, day), (kept, rel) in catch_day.items():
        if start <= day <= end:
            cell = fish[(pid, sp)]
            cell[0] += kept
            cell[1] += rel
    return fish, anglers


def trends(catch_day, effort_day, places, sp_index, as_of_d, say=print,
           label='place'):
    """Score every place and species for whether it is picking up or falling off."""
    out = []
    for window in WINDOWS:
        recent_start = (as_of_d - timedelta(days=window - 1)).isoformat()
        recent_end = as_of_d.isoformat()
        prior_start = (as_of_d - timedelta(days=2 * window - 1)).isoformat()
        prior_end = (as_of_d - timedelta(days=window)).isoformat()

        r_fish, r_ang = _window_totals(catch_day, effort_day, recent_start, recent_end)
        p_fish, p_ang = _window_totals(catch_day, effort_day, prior_start, prior_end)

        # the same calendar window in each of the previous few years
        season_fish, season_ang = [], []
        for back in range(1, BASELINE_YEARS + 1):
            try:
                anchor = as_of_d.replace(year=as_of_d.year - back)
            except ValueError:                      # 29 February
                anchor = as_of_d.replace(year=as_of_d.year - back, day=28)
            s = (anchor - timedelta(days=window - 1 + SEASON_SLOP)).isoformat()
            e = (anchor + timedelta(days=SEASON_SLOP)).isoformat()
            f, a = _window_totals(catch_day, effort_day, s, e)
            season_fish.append(f)
            season_ang.append(a)

        for (pid, sp), (kept, rel) in sorted(r_fish.items()):
            anglers = r_ang.get(pid, 0)
            if anglers < MIN_ANGLERS:
                continue
            recent_cpue = kept / anglers
            prior = None
            if p_ang.get(pid, 0) >= MIN_ANGLERS:
                prior = p_fish.get((pid, sp), [0, 0])[0] / p_ang[pid]
            rates = []
            for f, a in zip(season_fish, season_ang):
                if a.get(pid, 0) >= MIN_ANGLERS:
                    # the seasonal window is widened by the slop on both sides, so
                    # its rate is scaled back to the same number of days
                    rates.append(f.get((pid, sp), [0, 0])[0] / a[pid])
            seasonal = statistics.median(rates) if rates else None
            out.append({
                'w': window, 'p': pid, 's': sp_index[sp],
                'kept': kept, 'rel': rel, 'anglers': anglers,
                'cpue': round(recent_cpue, 4),
                'prior': None if prior is None else round(prior, 4),
                'season': None if seasonal is None else round(seasonal, 4),
                'season_years': len(rates),
            })
    say(f'   scored {len(out):,} {label}-species-window trends')
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
    for (pid, sp, day), (k, _r) in catch_day.items():
        if day >= since:
            kept[(sp_index[sp], _isoweek(day))] += k
    out = defaultdict(lambda: [0] * 53)
    for (sp, wk), n in kept.items():
        if 1 <= wk <= 53:
            out[sp][wk - 1] = n
    return {'weeks': list(range(1, 54)),
            'kept': {str(sp): v for sp, v in out.items()},
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
    placed, unplaced = geo.build(names, water_bodies=water_bodies, say=say)
    with open(paths.PLACE_GEO, 'w', encoding='utf-8') as f:
        json.dump({'placed': placed, 'unplaced': sorted(unplaced)}, f, indent=0)

    payload = build(catch_rows, effort_rows, placed, say=say)
    payload['areas'] = geo.catch_areas(say=say)
    payload['unplaced'] = sorted(unplaced)
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
