"""Buoy 10: the Columbia River mouth fishery, counted day by day since 2014.

One table per season, one row per day: boats, anglers, Chinook kept, coho kept, and a
comment saying what was legal to keep that day. The comment matters — a zero on a day
marked "Closed" is not a slow day, and the dashboard reads that distinction out of
this column rather than pretending the fishery was open all season.
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common
from common import MARINE

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import paths

URL = 'https://wdfw.wa.gov/fishing/reports/creel/buoy10'
SOURCE = 'buoy10'
REGION = 'Columbia River'
LOCATION = 'Buoy 10'

CLOSED = re.compile(r'\bclosed\b|no fishing|not open', re.I)


def _column(header, *words):
    for i, h in enumerate(header):
        low = h.lower()
        if all(w in low for w in words):
            return i
    return None


def parse(html_text):
    catch_rows, effort_rows = [], []
    for headings, rows in common.heading_tables(html_text):
        year = next((h for h in reversed(headings)
                     if re.fullmatch(r'(19|20)\d{2}', h.strip())), None)
        if not year or len(rows) < 2:
            continue
        header = [h.lower() for h in rows[0]]
        i_date = _column(header, 'date')
        i_boats = _column(header, 'boat')
        i_anglers = _column(header, 'angler')
        i_chin = _column(header, 'chinook')
        i_coho = _column(header, 'coho')
        i_note = _column(header, 'comment')
        if i_date is None:
            continue
        for cells in rows[1:]:
            if len(cells) <= i_date:
                continue
            day = common.parse_day(cells[i_date], year)
            if not day:
                continue
            note = cells[i_note] if i_note is not None and len(cells) > i_note else ''
            if CLOSED.search(note):
                continue          # the fishery was shut; there is no catch to record
            get = lambda i: (common.num(cells[i])
                             if i is not None and len(cells) > i else '')
            effort_rows.append(common.effort(
                day, SOURCE, LOCATION, anglers=get(i_anglers),
                boat_anglers=get(i_anglers), boats=get(i_boats),
                region=REGION, water=MARINE, catch_area='Buoy 10'))
            for species, idx in (('Chinook', i_chin), ('Coho', i_coho)):
                n = get(idx)
                if n != '':
                    catch_rows.append(common.catch(
                        day, SOURCE, LOCATION, species, n, fate='kept',
                        region=REGION, water=MARINE, catch_area='Buoy 10'))
    return catch_rows, effort_rows


def load(*, full=False, say=print):
    html_text = common.get_text(
        URL, cache_path=os.path.join(paths.PAGE_DIR, 'buoy10.html'), max_age_h=0)
    c, e = parse(html_text)
    say(f'   Buoy 10: {len(e):,} fishing days')
    return c, e


if __name__ == '__main__':
    c, e = load()
    print(len(c), len(e), c[:2], e[:2])
