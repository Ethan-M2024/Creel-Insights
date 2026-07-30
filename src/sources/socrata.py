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
PROJECT_REGION = {
    'District 11': 'South Sound rivers', 'District 13': 'Olympic Peninsula rivers',
    'District 14': 'North Sound rivers', 'District 16': 'Southwest rivers',
    'District 17 North': 'North coast rivers', 'District 17 South': 'South coast rivers',
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


def _hours(row):
    """Hours fished, when the interview recorded both ends of the trip."""
    a, b = row.get('fishing_start_time'), row.get('fishing_end_time')
    if not a or not b:
        return ''
    try:
        t0 = datetime.fromisoformat(a.replace('Z', ''))
        t1 = datetime.fromisoformat(b.replace('Z', ''))
    except ValueError:
        return ''
    h = (t1 - t0).total_seconds() / 3600
    # a negative or absurd span is a data-entry slip, not a 30-hour trip
    return round(h, 2) if 0 < h <= 24 else ''


def _water(project, water_body):
    marine_words = ('marine area', 'puget sound', 'bay', 'strait', 'sound', 'ocean')
    wb = (water_body or '').lower()
    return MARINE if any(w in wb for w in marine_words) else FRESH


def load(refresh=False, say=print):
    """Return (catch rows, effort rows) in the shared shape."""
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
    return catch_rows, effort_rows


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
