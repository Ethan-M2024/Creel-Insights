"""Pacific halibut: the weekly landings summary, by coastal subarea.

The halibut fishery is run against a quota set by the International Pacific Halibut
Commission, and WDFW publishes the season's progress week by week for four subareas —
Puget Sound, the north coast, the south coast, and the Columbia River. Each row is a
week of open days: halibut landed, anglers who landed them, and the average weight.

This is the only source here that gives a weight, and the only one where a season can
end mid-week because the quota ran out — so the days a subarea was actually open are
kept with the row, and a week with no open days contributes nothing.
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common
from common import MARINE

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import paths

URL = 'https://wdfw.wa.gov/fishing/regulations/halibut/seasons-quotas'
SOURCE = 'halibut'
REGION = 'Pacific coast'
SPECIES = 'Halibut'

#: the heading above each table names the subarea and its quota
SUBAREA = re.compile(
    r'^(Puget Sound|North Coast|South Coast|Columbia River[^-]*)\s*-\s*Quota', re.I)
LANDINGS_YEAR = re.compile(r'(20\d{2})\s+Pacific halibut landings', re.I)

NAMES = {
    'puget sound': 'Puget Sound halibut',
    'north coast': 'North coast halibut (Neah Bay, La Push)',
    'south coast': 'South coast halibut (Westport)',
    'columbia river': 'Columbia River halibut (incl. Oregon)',
}


def subarea(headings):
    for h in reversed(headings):
        m = SUBAREA.match(h.strip())
        if m:
            key = m.group(1).strip().lower()
            for needle, label in NAMES.items():
                if key.startswith(needle):
                    return label
            return m.group(1).strip()
    return None


def week_start(text, year):
    """'Apr 2-5' and 'Apr 30; May 1-2' both begin on the first day named."""
    m = re.match(r'\s*([A-Za-z]{3,9})\.?\s*(\d{1,2})', str(text or ''))
    if not m:
        return None
    return common.parse_day(f'{m.group(1)} {m.group(2)}', year)


def parse(html_text):
    year = None
    ym = LANDINGS_YEAR.search(common.strip_tags(html_text))
    if ym:
        year = ym.group(1)
    catch_rows, effort_rows = [], []
    for headings, rows in common.heading_tables(html_text):
        area = subarea(headings)
        if not area or len(rows) < 3:
            continue
        # the header spans two rows — "Week | Dates open | Weekly | Cumulative" over
        # the columns themselves — so the data rows are found by shape instead
        for cells in rows[2:]:
            if len(cells) < 5:
                continue
            day = week_start(cells[1], year)
            fish = common.num(cells[2])
            anglers = common.num(cells[3])
            if not day or fish == '' or anglers == '':
                continue
            effort_rows.append(common.effort(
                day, SOURCE, area, anglers=anglers, region=REGION, water=MARINE,
                catch_area=area))
            catch_rows.append(common.catch(
                day, SOURCE, area, SPECIES, fish, fate='kept',
                region=REGION, water=MARINE, catch_area=area))
    return catch_rows, effort_rows


def load(*, full=False, say=print):
    html_text = common.get_text(
        URL, cache_path=os.path.join(paths.PAGE_DIR, 'halibut.html'), max_age_h=0)
    c, e = parse(html_text)
    say(f'   halibut: {len(e):,} subarea-weeks')
    return c, e


if __name__ == '__main__':
    c, e = load()
    print(len(c), len(e))
    print(sorted({r['location'] for r in e}))
    print(e[:2])
