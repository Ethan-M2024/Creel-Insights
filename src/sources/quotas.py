"""The two pages that track a fishery against its ceiling rather than counting catch.

    seasonal   Puget Sound Chinook: encounters against the guideline that closes the
               fishery when it is reached, by marine area, summer and winter
    sturgeon   the Columbia pools: estimated harvest against the season's guideline

Neither is creel catch, and neither is forced into the catch table — an encounter is
not a fish kept, and a pool's harvest estimate is not an interview. They are kept as
their own record because they answer a question the catch data cannot: whether the
water you are looking at is about to close.

Each record carries the date WDFW says the estimate is valid through, because that
date, not the date the page was fetched, is how current the number really is.
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import paths

SEASONAL_URL = 'https://wdfw.wa.gov/fishing/reports/creel/seasonal'
STURGEON_URL = 'https://wdfw.wa.gov/fishing/reports/creel/sturgeon'

FIELDS = ('fishery', 'area', 'criteria', 'limit', 'taken', 'percent',
          'valid_through', 'status', 'season', 'opening', 'kind', 'source_page')


def record(fishery, area, **kw):
    r = {k: '' for k in FIELDS}
    r['kind'] = 'fishery'
    r.update(fishery=fishery, area=str(area).strip(), **kw)
    return r


def _percent(text, *, taken='', limit=''):
    """The share of the quota used.

    WDFW print it on most rows and leave it off a few. Where it is missing it is
    worked out from their own two numbers rather than left blank, because a quota
    without a percentage is the one thing this table exists to show.
    """
    m = re.search(r'(\d+(?:\.\d+)?)\s*%', str(text or ''))
    if m:
        return float(m.group(1)) / 100
    if taken != '' and limit not in ('', 0):
        return round(float(taken) / float(limit), 4)
    return ''


def _valid_through(text):
    """The date WDFW say the estimate runs to, written two ways across the tables:
    'July 26, 2026' in the summer table, '04/11/26' in the winter one."""
    t = str(text or '')
    m = re.search(r'([A-Z][a-z]{2,8})\.?\s+(\d{1,2}),?\s+(20\d{2})', t)
    if m:
        return common.parse_day(f'{m.group(1)} {m.group(2)}', m.group(3))
    m = re.search(r'(\d{1,2})/(\d{1,2})/(\d{2,4})', t)
    if m:
        year = int(m.group(3))
        year += 2000 if year < 100 else 0
        try:
            from datetime import date
            return date(year, int(m.group(1)), int(m.group(2))).isoformat()
        except ValueError:
            return ''
    return ''


class Columns:
    """Resolve header text to column positions, without letting two fields share one.

    These tables put the guideline and the running total in adjacent columns whose
    headings share every important word — "Encounters Guideline /Harvest Quota" and
    "Encounters /Harvest" — so a first-match-wins search silently reads the same
    column twice and reports a fishery as exactly 100% of its own limit. Each field
    claims its column and no other field may take it.
    """

    def __init__(self, header):
        self.header = [re.sub(r'\s+', ' ', h).strip().lower() for h in header]
        self.taken = set()

    def find(self, *patterns, exact=None):
        if exact:
            for i, h in enumerate(self.header):
                if i not in self.taken and h == exact.lower():
                    self.taken.add(i)
                    return i
        for pattern in patterns:
            for i, h in enumerate(self.header):
                if i not in self.taken and re.search(pattern, h):
                    self.taken.add(i)
                    return i
        return None


#: a row that begins with an area — a number, or a named terminal fishery. Anything
#: else ("Total Sublegal Encounters") is a sub-total of the row above it, written in
#: a different set of columns, and is not read as a fishery of its own.
AREA_CELL = re.compile(r'^\s*\d+[A-Za-z]?\s*$|terminal|tulalip|sound|bay', re.I)


def parse_seasonal(html_text):
    """Puget Sound Chinook encounter guidelines, summer and winter."""
    out = []
    seen_blocks = set()
    for headings, rows in common.heading_tables(html_text):
        season = next((h for h in reversed(headings)
                       if re.search(r'chinook fishery guidelines', h, re.I)), '')
        if not season or len(rows) < 2:
            continue
        col = Columns(rows[0])
        i_area = col.find(r'area')
        i_open = col.find(r'opening|season dates|dates')
        i_crit = col.find(r'criteria')
        # order matters: the guideline column is claimed before the running total,
        # because the running total's heading is a prefix of the guideline's
        i_limit = col.find(r'guideline|quota')
        i_taken = col.find(r'encounters|harvest')
        i_valid = col.find(r'valid|^date')
        i_pct = col.find(r'percent')
        i_status = col.find(r'status')
        if i_area is None:
            continue
        for cells in rows[1:]:
            if len(cells) != len(rows[0]) or not AREA_CELL.match(cells[i_area] or ''):
                continue
            get = lambda i: (cells[i] if i is not None and i < len(cells) else '')
            area = cells[i_area].strip()
            label = f'Marine Area {area}' if re.fullmatch(r'\d+[A-Za-z]?', area) else area
            closed = re.search(r'closed', ' '.join(cells), re.I)
            criteria = get(i_crit)
            opening = get(i_open)
            # An area's block is one fishery followed by extra measures of the same
            # fishery — unmarked encounters, sublegal encounters. Which line comes
            # first differs between the summer and winter tables, so the first line
            # of a block is the fishery and the rest are its sub-measures, rather
            # than guessing from the wording.
            block = (label, opening)
            kind = 'fishery' if block not in seen_blocks else 'sub'
            seen_blocks.add(block)
            no_fishery = (common.num(get(i_limit)) == ''
                          and common.num(get(i_taken)) == '')
            if no_fishery:
                # "Closed for the 2025-2026 winter season" is written across every
                # cell of the row. There is no guideline to track, only a season
                # that was not run — which is not the same as the area being shut,
                # and is worded so nobody reads it that way
                criteria, opening = '', ''
            limit, taken = common.num(get(i_limit)), common.num(get(i_taken))
            out.append(record(
                'Puget Sound Chinook', label,
                criteria=criteria, limit=limit, taken=taken,
                percent=_percent(get(i_pct), taken=taken, limit=limit),
                valid_through=_valid_through(get(i_valid)),
                status=('No such fishery this season' if no_fishery else
                        (get(i_status) or ('Closed' if closed else ''))),
                season=re.sub(r'\s*fishery guidelines\s*', '', season, flags=re.I),
                opening=opening, kind=kind,
                source_page=SEASONAL_URL))
    return out


def parse_sturgeon(html_text):
    """White sturgeon retention, pool by pool, against the season's guideline."""
    out = []
    for headings, rows in common.heading_tables(html_text):
        header = [h.lower() for h in rows[0]] if rows else []
        if not any('guideline' in h for h in header):
            continue
        col = Columns(rows[0])
        i_area = col.find(r'area|pool')
        i_status = col.find(r'status')
        i_season = col.find(r'season')
        i_taken = col.find(r'harvest')
        i_pct = col.find(r'%|percent')
        i_limit = col.find(r'guideline', exact='guideline')
        if i_area is None:
            i_area = 0
        for cells in rows[1:]:
            if len(cells) < 3 or not cells[i_area].strip():
                continue
            get = lambda i: (cells[i] if i is not None and i < len(cells) else '')
            limit, taken = common.num(get(i_limit)), common.num(get(i_taken))
            out.append(record(
                'Columbia River white sturgeon', cells[i_area],
                criteria='Retention harvest', limit=limit, taken=taken,
                opening=get(i_season),
                percent=_percent(get(i_pct), taken=taken, limit=limit),
                status=get(i_status), season=get(i_season),
                source_page=STURGEON_URL))
    return out


def load(*, full=False, say=print):
    seasonal = parse_seasonal(common.get_text(
        SEASONAL_URL, cache_path=os.path.join(paths.PAGE_DIR, 'seasonal.html'),
        max_age_h=0))
    sturgeon = parse_sturgeon(common.get_text(
        STURGEON_URL, cache_path=os.path.join(paths.PAGE_DIR, 'sturgeon.html'),
        max_age_h=0))
    say(f'   quota trackers: {len(seasonal)} Chinook guidelines, '
        f'{len(sturgeon)} sturgeon pools')
    return seasonal + sturgeon


if __name__ == '__main__':
    for r in load():
        print(r)
