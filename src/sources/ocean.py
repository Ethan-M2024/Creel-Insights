"""The ocean sport salmon quota report: four coastal ports, week by week.

WDFW tracks the ocean fishery against a quota set by the Pacific Fishery Management
Council, and publishes it weekly per management area: Columbia River, Westport,
La Push and Neah Bay. Each area gets its own table of statistical weeks.

The coastwide table is deliberately skipped. It is the sum of the four areas, and
adding it in would count every ocean fish twice. The Columbia River area is kept even
though it spans the state line, because that is the unit WDFW manages and reports;
the dashboard labels it as including Oregon rather than pretending otherwise.
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common
from common import MARINE

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import paths

URL = 'https://wdfw.wa.gov/fishing/reports/creel/ocean'
ARCHIVE = 'https://wdfw.wa.gov/fishing/reports/creel/ocean/archives'
SOURCE = 'ocean-quota'
REGION = 'Pacific coast'

AREAS = {
    'columbia river area': 'Columbia River ocean area (incl. Oregon)',
    'westport': 'Westport (Marine Area 2)',
    'la push': 'La Push (Marine Area 3)',
    'neah bay': 'Neah Bay (Marine Area 4)',
}
SKIP_HEADING = re.compile(r'coastwide|total', re.I)


def area_for(headings):
    for h in reversed(headings):
        key = re.sub(r'\s+', ' ', h).strip().lower().rstrip(' :')
        for needle, label in AREAS.items():
            if key.startswith(needle):
                return label
        if SKIP_HEADING.search(key):
            return None
    return None


def week_start(text, year):
    """'Jun 22-28' or 'Jul 27-Aug 2' -> the ISO date the statistical week began."""
    t = re.sub(r'\s+', ' ', text or '').strip()
    m = re.match(r'([A-Za-z]{3,9})\.?\s*(\d{1,2})', t)
    if not m:
        return None
    return common.parse_day(f'{m.group(1)} {m.group(2)}', year)


def parse(html_text, default_year=None):
    catch_rows, effort_rows = [], []
    for headings, rows in common.heading_tables(html_text):
        area = area_for(headings)
        if not area or len(rows) < 2:
            continue
        year = default_year
        for h in headings:
            m = re.search(r'\b(20\d{2})\b', h)
            if m:
                year = m.group(1)
                break
        if not year:
            continue
        header = [h.lower() for h in rows[0]]
        i_dates = next((i for i, h in enumerate(header) if 'date' in h), None)
        i_ang = next((i for i, h in enumerate(header)
                      if 'angler' in h and 'per' not in h), None)
        species_cols = {}
        for i, h in enumerate(header):
            if 'cumulative' in h or 'percent' in h or '%' in h:
                continue          # running totals, recomputed downstream instead
            for word, sp in (('chinook', 'Chinook'), ('coho', 'Coho'),
                             ('pink', 'Pink')):
                if word in h and i != i_ang:
                    species_cols[i] = sp
        if i_dates is None:
            continue
        for cells in rows[1:]:
            if len(cells) != len(header):
                continue
            day = week_start(cells[i_dates], year)
            if not day:
                continue
            if i_ang is not None:
                effort_rows.append(common.effort(
                    day, SOURCE, area, anglers=common.num(cells[i_ang]),
                    region=REGION, water=MARINE, catch_area=area))
            for i, sp in species_cols.items():
                n = common.num(cells[i])
                if n != '':
                    catch_rows.append(common.catch(
                        day, SOURCE, area, sp, n, fate='kept',
                        region=REGION, water=MARINE, catch_area=area))
    return catch_rows, effort_rows


def load(this_year, *, full=False, say=print):
    catch_rows, effort_rows = [], []
    for url, name, age in ((URL, 'ocean.html', 0),
                           (ARCHIVE, 'ocean_archive.html', 0 if full else 24 * 7)):
        html_text = common.get_text(
            url, cache_path=os.path.join(paths.PAGE_DIR, name), max_age_h=age)
        c, e = parse(html_text, default_year=str(this_year))
        catch_rows += c
        effort_rows += e
    # the current-season page and the archive can overlap for one year; a week is
    # identified by its area and start date, so the duplicate collapses cleanly
    seen = set()
    catch_rows = [r for r in catch_rows
                  if not (k := (r['date'], r['location'], r['species'], r['fate'])) in seen
                  and not seen.add(k)]
    seen = set()
    effort_rows = [r for r in effort_rows
                   if not (k := (r['date'], r['location'])) in seen and not seen.add(k)]
    say(f'   Ocean quota report: {len(effort_rows):,} area-weeks')
    return catch_rows, effort_rows


if __name__ == '__main__':
    from datetime import date
    c, e = load(date.today().year)
    print(len(c), len(e))
    print(sorted({r['location'] for r in e}))
    print(sorted({r['date'][:4] for r in e}))
