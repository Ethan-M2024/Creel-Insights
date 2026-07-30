"""Puget Sound ramp creel: every sampled day at every ramp, 2013 to now.

WDFW publishes this as a paginated Drupal table, fifty rows to a page, one small
table per sampled date. A row is one ramp on one day: how many anglers were
interviewed and how many of each species they had. Catch area was only added to the
page in July 2017, so rows before that legitimately have none.

Nothing about the layout is promised to stay put, so the columns are read from the
table's own header rather than by position: a new species column appears in the data
instead of shifting every number one place to the left.
"""
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common
from common import MARINE

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import paths

URL = 'https://wdfw.wa.gov/fishing/reports/creel/puget-annual'
SOURCE = 'puget-ramp'
REGION = 'Puget Sound'

#: the page's year filter is an opaque index — 1 is the current year, counting back
FIRST_YEAR = 2013

#: header text -> what the column actually is
COUNT_COLUMNS = {
    'ramp/site': 'location', 'ramp': 'location', 'site': 'location',
    'catch area': 'catch_area',
    '# interviews (boat or shore)': 'interviews', '# interviews': 'interviews',
    'interviews': 'interviews', 'anglers': 'anglers',
}
#: anything else with a species name in it is a species column; the per-angler
#: column is derived and deliberately not stored — the dashboard recomputes it
SKIP = re.compile(r'per angler|\(per', re.I)


def year_index(year, this_year):
    return this_year - year + 1


def page_url(index, page):
    return f'{URL}?sample_date={index}&page={page}'


def _cache(index, page):
    return os.path.join(paths.PAGE_DIR, f'puget_{index:02d}_{page:04d}.html')


def _day_tables(html_text):
    """Split the page into (date caption, header, rows) groups."""
    out = []
    for block in re.findall(r'<table[^>]*>.*?</table>', html_text, re.S):
        cap = re.search(r'<caption[^>]*>(.*?)</caption>', block, re.S)
        day = common.strip_tags(cap.group(1)) if cap else ''
        rows = []
        header = []
        for tr in re.findall(r'<tr[^>]*>(.*?)</tr>', block, re.S):
            th = re.findall(r'<th[^>]*>(.*?)</th>', tr, re.S)
            td = re.findall(r'<td[^>]*>(.*?)</td>', tr, re.S)
            if th and not td:
                header = [common.strip_tags(c).lower() for c in th]
            elif td:
                rows.append([common.strip_tags(c) for c in td])
        if header and rows:
            out.append((day, header, rows))
    return out


def _iso(caption):
    """'Jul 30, 2026' -> '2026-07-30'."""
    m = re.match(r'([A-Za-z]{3,9})\.?\s+(\d{1,2}),?\s+(\d{4})', caption.strip())
    if not m:
        return None
    return common.parse_day(f'{m.group(1)} {m.group(2)}', m.group(3))


def parse_page(html_text):
    catch_rows, effort_rows = [], []
    for caption, header, rows in _day_tables(html_text):
        day = _iso(caption)
        if not day:
            continue
        for cells in rows:
            if len(cells) != len(header):
                continue          # a footnote row, not data
            rec = dict(zip(header, cells))
            location = ''
            catch_area = ''
            interviews = anglers = ''
            species_counts = []
            for head, value in rec.items():
                role = COUNT_COLUMNS.get(head.strip())
                if role == 'location':
                    location = re.sub(r'\s*\(\*?\d+\)\*?', '', value).strip(' *')
                elif role == 'catch_area':
                    # before July 2017 the column exists but is filled with N/A
                    catch_area = '' if value.strip().upper() in ('N/A', 'NA') else value
                elif role == 'interviews':
                    interviews = common.num(value)
                elif role == 'anglers':
                    anglers = common.num(value)
                elif SKIP.search(head):
                    continue
                else:
                    sp = common.species(head)
                    if sp:
                        species_counts.append((sp, common.num(value)))
            if not location:
                continue
            effort_rows.append(common.effort(
                day, SOURCE, location, interviews=interviews, anglers=anglers,
                region=REGION, water=MARINE, catch_area=catch_area))
            for sp, n in species_counts:
                if n == '':
                    continue
                catch_rows.append(common.catch(
                    day, SOURCE, location, sp, n, fate='kept',
                    region=REGION, water=MARINE, catch_area=catch_area))
    return catch_rows, effort_rows


def load(this_year, *, refresh_current=True, full=False, say=print, pause=0.3):
    """Walk every year back to 2013, following each year's pager to its end.

    Old years cannot change, so their pages are read from the cache after the first
    run. The current year is re-fetched every time.
    """
    catch_rows, effort_rows = [], []
    for year in range(this_year, FIRST_YEAR - 1, -1):
        idx = year_index(year, this_year)
        page, seen = 0, 0
        while True:
            cache = _cache(idx, page)
            stale = full or (refresh_current and year >= this_year - 1)
            html_text = common.get_text(
                page_url(idx, page), cache_path=cache,
                max_age_h=0 if stale else None)
            c, e = parse_page(html_text)
            if not e:
                break
            catch_rows += c
            effort_rows += e
            seen += len(e)
            page += 1
            if page > 400:
                say(f'!! {year}: stopping at 400 pages, the pager looks unbounded')
                break
            if stale or not os.path.exists(cache):
                time.sleep(pause)
        say(f'   Puget {year}: {seen:,} ramp-days across {page} pages')
    return catch_rows, effort_rows


if __name__ == '__main__':
    from datetime import date
    c, e = load(date.today().year, full=False)
    print(f'{len(c):,} catch rows, {len(e):,} effort rows')
    print(c[:3])
