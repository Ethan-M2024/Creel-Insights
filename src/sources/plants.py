"""What WDFW put in the water, and how big the fish came back.

Two tables that answer questions the creel cannot answer alone.

    plants      every juvenile release WDFW record: the rack, the water it went
                into, the brood year, and how many fish. 109,000 rows back to the
                1950s, published as open data.
                https://data.wa.gov/resource/6fex-3r7d

    sizes       the fork length of sampled fish, by species and return year, out of
                the coded wire tag recovery programme. Four million fish, sampled
                from the same sport fisheries this dashboard reads, back to the
                1970s. It is asked for as an aggregate rather than fetched row by
                row, because nobody needs four million rows to see a trend.
                https://data.wa.gov/resource/auvb-4rvk

The recovery table records a decoded tag but not the code itself, so a fish cannot
be traced to the rack that released it from this source. What can be said honestly
is which hatcheries stock a water and how many they put in, which is what the plant
table gives, and that is how it is presented.
"""
import json
import os
import re
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import paths

BASE = 'https://data.wa.gov/resource/{}.json'
PLANTS = '6fex-3r7d'
RECOVERIES = 'auvb-4rvk'

#: releases before this are of historical interest only; the creel cannot see them
FIRST_BROOD = 2010


def _get(dataset, query, timeout=180):
    return json.loads(common.get_text(BASE.format(dataset) + query, timeout=timeout))


def plants(refresh=False, say=print):
    """Every juvenile release since 2010, by rack, water, species and brood year."""
    cache = os.path.join(paths.API_DIR, 'fish_plants.json')
    if os.path.exists(cache) and not refresh:
        with open(cache, encoding='utf-8') as f:
            return json.load(f)
    rows, offset = [], 0
    while True:
        page = _get(PLANTS,
                    f'?$limit=50000&$offset={offset}&$order=:id'
                    f'&$where=release_year>=%27{FIRST_BROOD}%27')
        rows.extend(page)
        if len(page) < 50000:
            break
        offset += 50000
    os.makedirs(paths.API_DIR, exist_ok=True)
    with open(cache, 'w', encoding='utf-8') as f:
        json.dump(rows, f)
    say(f'   fish plants: {len(rows):,} releases since {FIRST_BROOD}')
    return rows


def sizes(refresh=False, say=print):
    """Median fork length by species and return year, from the tag recoveries.

    Asked for as an aggregate. The whole table is four million fish and the answer
    is fifty rows a species, so the arithmetic is left to the server.
    """
    cache = os.path.join(paths.API_DIR, 'cwt_sizes.json')
    if os.path.exists(cache) and not refresh:
        with open(cache, encoding='utf-8') as f:
            return json.load(f)
    query = ('?$select=species,returnyear,count(*) as n,'
             'avg(forklength_cm) as mean&'
             '$where=forklength_cm IS NOT NULL AND forklength_cm > 10 '
             'AND forklength_cm < 200&'
             '$group=species,returnyear&$order=species,returnyear&$limit=5000')
    rows = _get(RECOVERIES, query.replace(' ', '%20'))
    out = []
    for r in rows:
        try:
            year, n, mean = int(r['returnyear']), int(r['n']), float(r['mean'])
        except (KeyError, TypeError, ValueError):
            continue
        # a species-year off a handful of fish says nothing about size
        if n < 200 or year < 1975:
            continue
        out.append({'species': common.species(r.get('species')), 'year': year,
                    'n': n, 'mean': round(mean, 1)})
    os.makedirs(paths.API_DIR, exist_ok=True)
    with open(cache, 'w', encoding='utf-8') as f:
        json.dump(out, f)
    say(f'   sampled sizes: {len(out):,} species-years from the tag recoveries')
    return out


def load(full=False, say=print):
    return plants(refresh=full, say=say), sizes(refresh=full, say=say)


if __name__ == '__main__':
    releases, lengths = load()
    facs = defaultdict(int)
    for r in releases:
        facs[(r.get('facility') or '').strip()] += common.num(r.get('number_released')) or 0
    print('top racks by fish released since 2010:')
    for name, n in sorted(facs.items(), key=lambda kv: -kv[1])[:6]:
        print(f'   {name[:34]:36} {n:>12,}')
    chinook = [r for r in lengths if r['species'] == 'Chinook'][-6:]
    print('chinook mean length by return year:', [(r['year'], r['mean']) for r in chinook])
