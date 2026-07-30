"""The Northern Pikeminnow Sport-Reward Fishery, station by station, week by week.

Anglers are paid per pikeminnow removed from the Columbia and Snake, and every week
of the season WDFW publishes a one-page field report: registered anglers, fish
turned in, and catch per angler at each of about twenty check stations.

The page holds every weekly report back to 2019, in two layouts. Through 2024 it is a
fixed-width text table, read off the line — pdfplumber's table finder merges those
columns into a single cell. From 2025 the columns were reordered and a rotated
watermark was laid over them, which breaks "154" into "1 54" in the extracted text,
so those seasons are read from the position of every word on the page instead and
checked against the report's own catch-per-angler figure.
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common
from common import FRESH

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import paths
import safety

URL = 'https://wdfw.wa.gov/fishing/reports/creel/pikeminnow'
ORIGIN = 'https://wdfw.wa.gov'
SOURCE = 'pikeminnow'
REGION = 'Columbia River'
SPECIES = 'Northern pikeminnow'

#: station, then five weekly figures and five year-to-date ones. Only the weekly
#: half is stored: the year-to-date column is a running sum of it, and keeping both
#: would let a reader add the same fish twice.
ROW = re.compile(
    r'^(?P<station>[A-Za-z][A-Za-z .\'\-]+?)\s+'
    r'(?P<effort>[\d,]+)\s+(?P<tags>[\d,]+)\s+(?P<npm>[\d,]+)\s+'
    r'(?P<total>[\d,]+)\s+(?P<cpue>[\d.]+)\s+'
    r'(?P<yeffort>[\d,]+)\s+(?P<ytags>[\d,]+)\s+(?P<ynpm>[\d,]+)\s+'
    r'(?P<ytotal>[\d,]+)\s+(?P<ycpue>[\d.]+)\s*$')

PERIOD = re.compile(
    r'([A-Z][a-z]{2,8})\.?\s+(\d{1,2})\s*[-–]\s*(?:([A-Z][a-z]{2,8})\.?\s+)?'
    r'(\d{1,2}),?\s*(\d{4})')


def discover(say=print):
    html_text = common.get_text(
        URL, cache_path=os.path.join(paths.PAGE_DIR, 'pikeminnow.html'), max_age_h=0)
    # the page mixes relative and absolute links to the same file store
    links = sorted({m for m in re.findall(
        r'href="(?:https://wdfw\.wa\.gov)?(/sites/default/files/[^"\s]+?\.pdf)"',
        html_text, re.I)})
    say(f'   pikeminnow: {len(links)} weekly reports listed')
    return links


def parse(text):
    """Return (catch rows, effort rows) for one weekly report."""
    m = PERIOD.search(text)
    if not m:
        return [], []
    start = common.parse_day(f'{m.group(1)} {m.group(2)}', m.group(5))
    if not start:
        return [], []
    catch_rows, effort_rows = [], []
    for line in text.splitlines():
        hit = ROW.match(line.strip())
        if not hit:
            continue
        station = hit.group('station').strip()
        if station.lower().startswith('total'):
            continue              # the report's own sum, recomputed downstream
        effort_rows.append(common.effort(
            start, SOURCE, station, anglers=common.num(hit.group('effort')),
            region=REGION, water=FRESH))
        catch_rows.append(common.catch(
            start, SOURCE, station, SPECIES, common.num(hit.group('total')),
            fate='kept', region=REGION, water=FRESH))
    return catch_rows, effort_rows


def read_pdf(path):
    import pdfplumber
    with pdfplumber.open(path) as pdf:
        return '\n'.join((page.extract_text() or '') for page in pdf.pages)


#: 2025 and 2026 use a different table: a column of opening dates, weekly and
#: year-to-date figures interleaved rather than in two blocks, and a rotated
#: watermark whose letters land inside the numbers. Reading the text lines of one of
#: those gives "1 54" where the report says 154, so those two seasons are read from
#: the position of every word on the page instead.
WEEK_OF = re.compile(
    r'Week\s+of\s+([A-Z][a-z]{2,8})\.?\s*(\d{1,2})\s*(?:thru|through|-|–)', re.I)
YEAR = re.compile(r'Sport-?Reward Fishery\s*(20\d{2})', re.I)


def word_rows(path, tolerance=4):
    """Every line of the page as x-ordered words, with split numbers rejoined."""
    import pdfplumber
    out = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            lines = {}
            for w in page.extract_words():
                lines.setdefault(round(w['top'] / tolerance), []).append(w)
            for key in sorted(lines):
                words = sorted(lines[key], key=lambda w: w['x0'])
                merged = []
                for w in words:
                    if merged and w['x0'] - merged[-1]['x1'] < 2.5:
                        merged[-1] = {'text': merged[-1]['text'] + w['text'],
                                      'x0': merged[-1]['x0'], 'x1': w['x1']}
                    else:
                        merged.append({'text': w['text'], 'x0': w['x0'], 'x1': w['x1']})
                out.append(merged)
    return out


def _number(token):
    t = token.replace(',', '')
    try:
        return float(t)
    except ValueError:
        return None


def parse_positional(path):
    """Read the newer layout, using the report's own catch-per-angler as a check.

    Which column is which moved between seasons, but the relationship between them
    did not: CPUE is the week's fish divided by the week's anglers. So the effort and
    the fish are the pair on the row that reproduces the printed CPUE, and a row
    where no pair does is left out rather than guessed at.
    """
    rows = word_rows(path)
    flat = ' '.join(w['text'] for row in rows for w in row)
    ym = YEAR.search(flat)
    wm = WEEK_OF.search(flat)
    if not ym or not wm:
        return [], []
    start = common.parse_day(f'{wm.group(1)} {wm.group(2)}', ym.group(1))
    if not start:
        return [], []

    catch_rows, effort_rows = [], []
    for row in rows:
        name = ' '.join(w['text'] for w in row
                        if w['x0'] < 200 and len(w['text']) > 1).strip()
        if not name or name.lower().startswith(('station', 'total', 'week', 'gear',
                                                'definition', 'for the')):
            continue
        numbers = [(_number(w['text']), w['text']) for w in row if w['x0'] >= 200]
        numbers = [(v, t) for v, t in numbers if v is not None]
        if not numbers:
            continue
        # the opening date parses as a number only if it is written 5/1/2026, which
        # it is not — but drop anything with a slash to be sure
        numbers = [(v, t) for v, t in numbers if '/' not in t]
        cpue = next((v for v, t in numbers if '.' in t), None)
        ints = [int(v) for v, t in numbers if '.' not in t]
        if cpue is None or not ints:
            continue
        effort = ints[0]
        if effort <= 0:
            continue
        fish = next((n for n in ints[1:]
                     if cpue and abs(n / effort - cpue) <= max(0.05, cpue * 0.02)),
                    None)
        if fish is None:
            continue
        effort_rows.append(common.effort(start, SOURCE, name, anglers=effort,
                                         region=REGION, water=FRESH))
        catch_rows.append(common.catch(start, SOURCE, name, SPECIES, fish,
                                       fate='kept', region=REGION, water=FRESH))
    return catch_rows, effort_rows


def load(*, full=False, say=print):
    catch_rows, effort_rows = [], []
    reports = 0
    for link in discover(say=say):
        dest = common.fetch_pdf(link, 'pm', origin=ORIGIN, full=full, say=say)
        if not dest:
            continue
        try:
            c, e = parse(read_pdf(dest))
            if not e:
                c, e = parse_positional(dest)
        except Exception as exc:
            say(f'!! could not read {os.path.basename(dest)}: {exc}')
            continue
        if e:
            reports += 1
        catch_rows += c
        effort_rows += e
    say(f'   pikeminnow: {reports} reports read, {len(effort_rows):,} station-weeks')
    return catch_rows, effort_rows


if __name__ == '__main__':
    c, e = load()
    print(len(c), len(e))
    print(sorted({r['date'][:4] for r in e}))
    print(sorted({r['location'] for r in e})[:25])
