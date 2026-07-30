"""Willapa Bay, Marine Area 2.1: the salmon fishery summarised by management week.

Each season gets a table keyed by management week — WDFW's statistical week, which
runs Monday to Sunday — with the week's dates written out beside it. The week's
dates are read rather than the week number converted, because the season's first and
last weeks are usually partial and the printed range says so.

This is one of only two sources that separates a clipped Chinook from an unmarked
one on the same line, so the origin split here is real data, not an assumption.
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common
from common import MARINE

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import paths

URL = 'https://wdfw.wa.gov/fishing/reports/creel/willapa-bay'
SOURCE = 'willapa'
REGION = 'Willapa Bay'
LOCATION = 'Willapa Bay (Area 2.1)'

#: header phrase -> (species, fate, origin)
CATCH_COLUMNS = (
    (re.compile(r'ad.?clip.*chinook.*retain', re.I), ('Chinook', 'kept', 'hatchery')),
    (re.compile(r'unmark.*chinook.*retain', re.I), ('Chinook', 'kept', 'wild')),
    (re.compile(r'coho.*retain', re.I), ('Coho', 'kept', 'unknown')),
    (re.compile(r'unmark.*chinook.*releas', re.I), ('Chinook', 'released', 'wild')),
    (re.compile(r'chinook.*releas', re.I), ('Chinook', 'released', 'unknown')),
    (re.compile(r'coho.*releas', re.I), ('Coho', 'released', 'unknown')),
    (re.compile(r'chum.*retain', re.I), ('Chum', 'kept', 'unknown')),
)


def week_start(text, year):
    """'8/12-8/18' or 'Aug 7 -13' -> the ISO date the week began."""
    t = re.sub(r'\s+', ' ', text or '').strip()
    m = re.match(r'(\d{1,2})/(\d{1,2})', t)
    if m:
        try:
            from datetime import date
            return date(int(year), int(m.group(1)), int(m.group(2))).isoformat()
        except ValueError:
            return None
    return common.parse_day(t, year)


def parse(html_text):
    catch_rows, effort_rows = [], []
    for headings, rows in common.heading_tables(html_text):
        year = None
        for h in reversed(headings):
            m = re.search(r'\b(20\d{2})\b', h)
            if m:
                year = m.group(1)
                break
        if not year or len(rows) < 2:
            continue
        header = rows[0]
        i_dates = next((i for i, h in enumerate(header)
                        if re.search(r'date', h, re.I)), None)
        i_int = next((i for i, h in enumerate(header)
                      if re.search(r'interview', h, re.I)), None)
        i_ang = next((i for i, h in enumerate(header)
                      if re.search(r'angler', h, re.I)), None)
        if i_dates is None:
            continue
        for cells in rows[1:]:
            if len(cells) != len(header):
                continue
            day = week_start(cells[i_dates], year)
            if not day:
                continue
            get = lambda i: (common.num(cells[i]) if i is not None else '')
            effort_rows.append(common.effort(
                day, SOURCE, LOCATION, interviews=get(i_int), anglers=get(i_ang),
                region=REGION, water=MARINE, catch_area='Area 2.1'))
            for i, head in enumerate(header):
                for pattern, (sp, fate, origin) in CATCH_COLUMNS:
                    if pattern.search(head):
                        n = common.num(cells[i])
                        if n != '':
                            catch_rows.append(common.catch(
                                day, SOURCE, LOCATION, sp, n, fate=fate,
                                origin=origin, region=REGION, water=MARINE,
                                catch_area='Area 2.1'))
                        break
    return catch_rows, effort_rows


def load(*, full=False, say=print):
    html_text = common.get_text(
        URL, cache_path=os.path.join(paths.PAGE_DIR, 'willapa.html'), max_age_h=0)
    c, e = parse(html_text)
    say(f'   Willapa Bay: {len(e):,} management weeks')
    return c, e


if __name__ == '__main__':
    c, e = load()
    print(len(c), len(e), c[:3], e[:2])
