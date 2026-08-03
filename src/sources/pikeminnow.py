"""The Northern Pikeminnow Sport-Reward Fishery, station by station, week by week.

Anglers are paid per pikeminnow removed from the Columbia and Snake, and every week
of the season WDFW publishes a one-page field report: registered anglers, fish
turned in, and catch per angler at each of about twenty check stations.

The page holds every weekly report back to 2014, and seventeen different column
layouts across those years: four numbers a row or ten, an opening-date column that
comes and goes, and six seasons that also count the incidental catch — smallmouth
bass, walleye, catfish, shad, sturgeon, perch — beside the pikeminnow.

Matching a layout to a year was never going to hold, so no row is read by position.
Every report states catch per angler, and that figure is the check: the effort and
the fish are whichever pair of columns divide into it. A row that cannot be made to
agree with the report's own arithmetic is left out rather than guessed at.

From 2025 a rotated watermark sits over the table, which breaks "154" into "1 54" in
the extracted text, so those seasons are read from the position of every word on the
page instead — checked the same way.
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

#: a data line: a station name, then the week's figures and the year-to-date ones.
#: Only the weekly half is kept — the year-to-date column is a running sum of it, and
#: storing both would let a reader add the same fish twice.
DATA_LINE = re.compile(r'^(?P<station>[A-Za-z][A-Za-z0-9 ./\'\(\)\-]*?)\s+(?P<rest>[\d,.\-$ ]+)$')

#: the incidental catch columns, which six of the seasons print beside the
#: pikeminnow. The report gives a count and not a fate, so these are recorded as
#: caught rather than claimed to have been taken home.
#: The names are the ones the rest of the data already uses — "Shad", not "American
#: shad"; "Sturgeon", not "White sturgeon" — so a species picked on the dashboard
#: gathers every report of it rather than splitting into near-duplicates.
INCIDENTAL = {
    'SMB': 'Smallmouth bass', 'LMB': 'Largemouth bass', 'WAL': 'Walleye',
    'YP': 'Yellow perch', 'WS': 'Sturgeon', 'AMS': 'Shad',
    'CC/CF/BH': 'Catfish', 'CC/CF': 'Catfish', 'CC': 'Channel catfish',
}

#: "May 1 - May 4, 2014", "June 24 - June 30 , 2024", and — for the weeks a season
#: opened mid-week — the bare "May 1, 2016". The stray space before the comma is
#: WDFW's, and cost eight reports until it was allowed for.
PERIOD = re.compile(
    r'([A-Z][a-z]{2,8})\.?\s+(\d{1,2})\s*[-–]\s*(?:([A-Z][a-z]{2,8})\.?\s+)?'
    r'(\d{1,2})\s*,?\s*(\d{4})')
SINGLE_DAY = re.compile(r'^\s*([A-Z][a-z]{2,8})\.?\s+(\d{1,2})\s*,?\s*(20\d{2})\b', re.M)


def discover(say=print):
    html_text = common.get_text(
        URL, cache_path=os.path.join(paths.PAGE_DIR, 'pikeminnow.html'), max_age_h=0)
    # the page mixes relative and absolute links to the same file store
    links = sorted({m for m in re.findall(
        r'href="(?:https://wdfw\.wa\.gov)?(/sites/default/files/[^"\s]+?\.pdf)"',
        html_text, re.I)})
    say(f'   pikeminnow: {len(links)} weekly reports listed')
    return links


def incidental_codes(text):
    """The incidental-catch column headings, in the order the report prints them."""
    for line in text.splitlines():
        if line.strip().startswith('Station') and 'CPUE' in line:
            tail = line.strip().split('CPUE')[-1].split()
            return [t for t in tail if t in INCIDENTAL]
    return []


def read_numbers(rest):
    """The numbers on a data line, as (value, was_decimal) pairs.

    A dash stands for a column with nothing in it, and is dropped rather than read as
    a zero: the two mean different things and only one of them is in the report. Each
    number carries how many decimal places it was printed to, which is what tells the
    row reader how exact the report's own rate is.
    """
    out = []
    for token in rest.split():
        if token in ('-', '--', '–', '$'):
            continue
        try:
            clean = token.replace(',', '').replace('$', '')
            decimals = len(clean.split('.')[1]) if '.' in clean else 0
            out.append((float(clean), '.' in clean, decimals))
        except ValueError:
            return []
    return out


def split_row(numbers):
    """Effort and fish for the week, found by dividing into the reported rate.

    The first decimal on the line is the week's catch per angler, and the columns to
    its left are that week's counts in some order that changed five times in eleven
    years. Effort is the first of them; the fish are whichever column divides into the
    rate. If nothing does, the line is not returned at all.
    """
    first_rate = next((i for i, (_v, dec, _d) in enumerate(numbers) if dec), None)
    if first_rate is None or first_rate < 2:
        return None
    cpue, decimals = numbers[first_rate][0], numbers[first_rate][2]
    ints = [v for v, dec, _d in numbers[:first_rate] if not dec]
    if len(ints) < 2:
        return None
    effort = int(ints[0])
    if effort <= 0:
        return None
    for value in reversed(ints[1:]):
        if matches_rate(value / effort, cpue, decimals):
            return effort, int(value), first_rate
    return None


def matches_rate(computed, printed, decimals):
    """Does this column, over the effort, give the rate the report printed?

    Some seasons round the rate and others cut it short — 60 fish to 41 anglers is
    printed 1.4 in 2014 and would be 1.5 in 2024 — so both readings are accepted, at
    the precision the report actually used. Anything looser starts matching the tag
    column by accident.
    """
    scale = 10 ** decimals
    rounded = round(computed, decimals)
    truncated = int(computed * scale) / scale
    eps = 1e-9
    return abs(rounded - printed) < eps or abs(truncated - printed) < eps


def parse(text):
    """Return (catch rows, effort rows) for one weekly report."""
    m = PERIOD.search(text)
    if m:
        start = common.parse_day(f'{m.group(1)} {m.group(2)}', m.group(5))
    else:
        one = SINGLE_DAY.search(text)
        start = common.parse_day(f'{one.group(1)} {one.group(2)}',
                                 one.group(3)) if one else None
    if not start:
        return [], []
    codes = incidental_codes(text)
    catch_rows, effort_rows = [], []
    for line in text.splitlines():
        hit = DATA_LINE.match(line.strip())
        if not hit:
            continue
        station = clean_station(hit.group('station'))
        if not station or station.lower().startswith(('total', 'week', 'grand')):
            continue              # the report's own sum, recomputed downstream
        numbers = read_numbers(hit.group('rest'))
        found = split_row(numbers)
        if not found:
            continue
        effort, fish, rate_at = found
        effort_rows.append(common.effort(
            start, SOURCE, station, anglers=effort, region=REGION, water=FRESH))
        catch_rows.append(common.catch(
            start, SOURCE, station, SPECIES, fish,
            fate='kept', region=REGION, water=FRESH))
        # the year-to-date block repeats the weekly one and ends in its own rate;
        # anything past that is the incidental catch, in heading order
        if codes:
            after = [v for v, dec, _d in numbers[rate_at + 1:] if not dec]
            tail = after[-len(codes):] if len(after) >= len(codes) else []
            for code, count in zip(codes, tail):
                if count:
                    catch_rows.append(common.catch(
                        start, SOURCE, station, INCIDENTAL[code], int(count),
                        fate='released', region=REGION, water=FRESH))
    return catch_rows, effort_rows


#: A station that was shut that week is printed "Bingen Closed", and the word was
#: becoming part of its name — one station on the map twice, its history split
#: between the weeks it was open and the weeks it was not.
def clean_station(raw):
    name = re.sub(r'[\s-]*\bclosed\b\s*$', '', str(raw or '').strip(), flags=re.I)
    return re.sub(r'\s+', ' ', name).strip(" -'")


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
        name = clean_station(' '.join(w['text'] for w in row
                                      if w['x0'] < 200 and len(w['text']) > 1))
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
