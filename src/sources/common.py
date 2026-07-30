"""What every creel source has in common: the row shape, and how to speak WDFW.

WDFW publishes creel data in half a dozen unrelated shapes — a database export, five
different HTML tables, two runs of PDFs — and each one names the same fish, the same
ramp and the same date differently. Every parser in this folder ends by handing back
the two records defined here, so the rest of the pipeline never has to know which
report a number came from.

    CatchRow    one date x place x species x fate x origin, and how many fish
    EffortRow   one date x place, and how much fishing produced those fish

Effort is kept apart from catch on purpose. A creel interview counts anglers once and
their fish once per species, so folding the two together would multiply the anglers by
however many species they caught, and every catch-per-angler figure downstream would
be wrong.
"""
import os
import re
import sys
import time
from datetime import date, datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import safety

UA = 'Mozilla/5.0 (compatible; wdfw-creel-dashboard/1.0)'

CATCH_FIELDS = ('date', 'source', 'region', 'water', 'location', 'catch_area',
                'species', 'fate', 'origin', 'fish')
EFFORT_FIELDS = ('date', 'source', 'region', 'water', 'location', 'catch_area',
                 'interviews', 'anglers', 'boat_anglers', 'boats', 'angler_hours')

#: marine or fresh, per source; the dashboard splits salt from rivers because
#: catch-per-angler means something different in each
MARINE = 'marine'
FRESH = 'fresh'


def catch(date_, source, location, species, fish, *, fate='kept', origin='unknown',
          region='', water=MARINE, catch_area=''):
    """One species line. *fish* may be zero — a zero is evidence, not a gap."""
    return {'date': as_date(date_), 'source': source, 'region': region,
            'water': water, 'location': (location or '').strip(),
            'catch_area': (catch_area or '').strip(),
            'species': species, 'fate': fate, 'origin': origin,
            'fish': int(round(float(fish)))}


def effort(date_, source, location, *, interviews=None, anglers=None,
           boat_anglers=None, boats=None, angler_hours=None, region='',
           water=MARINE, catch_area=''):
    return {'date': as_date(date_), 'source': source, 'region': region,
            'water': water, 'location': (location or '').strip(),
            'catch_area': (catch_area or '').strip(),
            'interviews': num(interviews), 'anglers': num(anglers),
            'boat_anglers': num(boat_anglers), 'boats': num(boats),
            'angler_hours': num(angler_hours)}


def num(v):
    """Blank stays blank. A count that was never reported is not a zero."""
    if v is None or v == '':
        return ''
    if isinstance(v, str):
        v = v.replace(',', '').replace('%', '').strip()
        if v in ('', '-', '--', 'n/a', 'N/A', 'NA'):
            return ''
    try:
        f = float(v)
    except ValueError:
        return ''
    return int(f) if f == int(f) else round(f, 2)


def as_date(v):
    if isinstance(v, datetime):
        return v.date().isoformat()
    if isinstance(v, date):
        return v.isoformat()
    return str(v)[:10]


# ------------------------------------------------------------------ species
#: Anything WDFW writes for a species, reduced to one name the dashboard uses.
#: Unmapped species are kept under their own cleaned-up name rather than dropped,
#: so a new one appears in the data instead of vanishing from it.
SPECIES_ALIAS = {
    'chinook': 'Chinook', 'king': 'Chinook', 'chinook salmon': 'Chinook',
    'chinook jack': 'Chinook', 'jack chinook': 'Chinook',
    'coho': 'Coho', 'silver': 'Coho', 'coho salmon': 'Coho',
    'coho jack': 'Coho', 'jack coho': 'Coho',
    'chum': 'Chum', 'chum salmon': 'Chum', 'pink': 'Pink', 'pink salmon': 'Pink',
    'sockeye': 'Sockeye', 'sockeye salmon': 'Sockeye', 'kokanee': 'Kokanee',
    'steelhead': 'Steelhead', 'summer steelhead': 'Steelhead',
    'winter steelhead': 'Steelhead', 'steelhead trout': 'Steelhead',
    'rainbow trout': 'Rainbow trout', 'rainbow': 'Rainbow trout',
    'cutthroat': 'Cutthroat', 'sea-run cutthroat': 'Cutthroat',
    'cutthroat trout': 'Cutthroat', 'coastal cutthroat': 'Cutthroat',
    'halibut': 'Halibut', 'pacific halibut': 'Halibut',
    'lingcod': 'Lingcod', 'ling cod': 'Lingcod',
    'white sturgeon': 'Sturgeon', 'sturgeon': 'Sturgeon',
    'walleye': 'Walleye', 'smallmouth bass': 'Smallmouth bass',
    'northern pikeminnow': 'Northern pikeminnow', 'pikeminnow': 'Northern pikeminnow',
    'shad': 'Shad', 'american shad': 'Shad',
    'atlantic salmon': 'Atlantic salmon', 'bull trout': 'Bull trout',
    'brown trout': 'Brown trout', 'burbot': 'Burbot', 'tiger musky': 'Tiger musky',
    'yellow perch': 'Yellow perch', 'crappie': 'Crappie', 'bluegill': 'Bluegill',
    'largemouth bass': 'Largemouth bass', 'channel catfish': 'Channel catfish',
    'rockfish': 'Rockfish', 'cabezon': 'Cabezon', 'sole': 'Sole',
    'flounder': 'Flounder', 'dungeness crab': 'Dungeness crab',
}

#: the eight the dashboard leads with; everything else is still there, just behind
#: the "all species" control
HEADLINE_SPECIES = ('Chinook', 'Coho', 'Chum', 'Pink', 'Sockeye', 'Steelhead',
                    'Halibut', 'Lingcod')


def species(raw):
    s = re.sub(r'\s+', ' ', str(raw or '')).strip()
    if not s:
        return ''
    key = s.lower().rstrip('s') if s.lower() not in SPECIES_ALIAS else s.lower()
    return SPECIES_ALIAS.get(s.lower()) or SPECIES_ALIAS.get(key) or s[:1].upper() + s[1:]


#: WDFW marks a hatchery fish by its clipped adipose fin; the reports say so in a
#: dozen ways, and the distinction matters — most wild fish must be released
ORIGIN_ALIAS = {
    'ad': 'hatchery', 'adclipped': 'hatchery', 'ad clipped': 'hatchery',
    'ad-clipped': 'hatchery', 'clipped': 'hatchery', 'marked': 'hatchery',
    'hatchery': 'hatchery', 'ad_present': 'wild', 'unclipped': 'wild',
    'unmarked': 'wild', 'wild': 'wild', 'not clipped': 'wild', 'nc': 'wild',
    'um': 'wild', 'ad+lv': 'hatchery', 'ad+rv': 'hatchery', 'sd+um': 'wild',
    'unknown': 'unknown', 'ut': 'unknown', 'na': 'unknown', '': 'unknown',
}


def origin(raw):
    return ORIGIN_ALIAS.get(re.sub(r'\s+', ' ', str(raw or '')).strip().lower(),
                            'unknown')


# ------------------------------------------------------------------ network
def get(url, *, timeout=90, cache_path=None, max_age_h=None):
    """Fetch through the safety module, optionally serving from a local cache.

    *max_age_h* lets a page that changes every week be re-read on a rebuild without
    re-downloading fifteen years of pages that cannot change again.
    """
    if cache_path and os.path.exists(cache_path):
        fresh = max_age_h is None or (
            time.time() - os.path.getmtime(cache_path) < max_age_h * 3600)
        if fresh:
            with open(cache_path, 'rb') as f:
                return f.read()
    blob = safety.fetch(url, timeout=timeout, user_agent=UA)
    if cache_path:
        os.makedirs(os.path.dirname(cache_path), exist_ok=True)
        with open(cache_path, 'wb') as f:
            f.write(blob)
    return blob


def get_text(url, **kw):
    return get(url, **kw).decode('utf-8', 'replace')


def fetch_pdf(link, prefix, *, origin='https://wdfw.wa.gov', full=False, say=print):
    """Download one linked report into the PDF cache, returning its local path.

    A link on a page WDFW edits by hand is not a promise that a file is there: some
    point at documents that have since been withdrawn. One 404 must not end a run
    that has three hundred other reports to read, so a failure here is reported and
    skipped rather than raised.
    """
    import paths
    import safety
    name = safety.safe_filename(f'{prefix}__' + link.rsplit('/', 1)[-1])
    dest = safety.resolve_within(paths.PDF_DIR, name)
    if os.path.exists(dest) and not full:
        return dest
    try:
        blob = get(origin + link if link.startswith('/') else link, timeout=120)
    except Exception as exc:
        say(f'!! could not fetch {link}: {exc}')
        return None
    if not blob.startswith(b'%PDF'):
        say(f'!! not a PDF, skipped: {link}')
        return None
    os.makedirs(paths.PDF_DIR, exist_ok=True)
    with open(dest, 'wb') as f:
        f.write(blob)
    return dest


# ------------------------------------------------------------------ HTML
_TAG = re.compile(r'<[^>]+>')


def strip_tags(html_fragment):
    import html as _html
    txt = _TAG.sub(' ', html_fragment)
    return re.sub(r'\s+', ' ', _html.unescape(txt)).strip()


def tables(html_text):
    """Every <table> on a page, as lists of rows of already-cleaned cell text."""
    out = []
    for tb in re.findall(r'<table[^>]*>.*?</table>', html_text, re.S):
        rows = []
        for tr in re.findall(r'<tr[^>]*>(.*?)</tr>', tb, re.S):
            cells = re.findall(r'<t[dh][^>]*>(.*?)</t[dh]>', tr, re.S)
            if cells:
                rows.append([strip_tags(c) for c in cells])
        if rows:
            out.append(rows)
    return out


def heading_tables(html_text, levels='2-4'):
    """Walk a page in document order, pairing each table with the headings above it.

    Three of these pages stack a year's tables under a year heading and say nothing
    inside the table about which year it is, so the heading is the only place the
    year exists. Yielding the whole heading stack, rather than just the nearest one,
    lets a caller find the year on an outer heading and the place on an inner one.
    """
    pat = re.compile(rf'<h([{levels}])[^>]*>(.*?)</h\1>|<table[^>]*>.*?</table>', re.S)
    stack = {}
    for m in pat.finditer(html_text):
        if m.group(1):
            level = int(m.group(1))
            stack = {k: v for k, v in stack.items() if k < level}
            stack[level] = strip_tags(m.group(2))
        else:
            rows = tables(m.group(0))
            if rows:
                yield [stack[k] for k in sorted(stack)], rows[0]


MONTHS = {m.lower(): i for i, m in enumerate(
    ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
     'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'], 1)}


def parse_day(text, year):
    """Read the many ways these pages write a day: 'Aug. 1', '1-Aug', 'August 1'.

    Returns an ISO date or None. None is the right answer for a footnote row; the
    caller drops it rather than guessing at a date that was never given.
    """
    t = re.sub(r'\s+', ' ', str(text or '')).strip().strip('*').rstrip('.')
    if not t:
        return None
    m = re.fullmatch(r'(\d{4})-(\d{2})-(\d{2})', t)
    if m:
        return t
    m = re.match(r'([A-Za-z]{3,9})\.?\s+(\d{1,2})', t)
    if not m:
        m = re.match(r'(\d{1,2})\s*[-/ ]\s*([A-Za-z]{3,9})', t)
        if m:
            m = re.match(r'(?P<mon>[A-Za-z]{3,9})', m.group(2)), m.group(1)
            mon, day = m[0].group('mon'), m[1]
        else:
            return None
    else:
        mon, day = m.group(1), m.group(2)
    mi = MONTHS.get(mon[:3].lower())
    if not mi:
        return None
    try:
        return date(int(year), mi, int(day)).isoformat()
    except ValueError:
        return None
