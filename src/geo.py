"""Put every creel location on the map, and say how confident that is.

The heat map is only worth looking at if the dots are in the right places, so this
module keeps three tiers apart and records which one each location came from:

    exact       a WDFW dataset gives the coordinates outright — the water body
                centroid table, or the water access site layer
    matched     a ramp name in a creel table was matched to a WDFW access site
    locality    no dataset names this dock, but exactly one placed site shares its
                locality — "Blaine Marina" beside "Blaine Ramp". Drawn at the
                neighbour, which is right to within a few hundred metres and is
                labelled as the neighbour's position, never as the dock's own
    approximate a fixed place with no dataset behind it (the mouth of the Columbia,
                an ocean management area) hand-placed once, marked as approximate

Nothing is invented beyond that. A location that matches nothing simply has no
coordinates, appears in the tables, and stays off the map.
"""
import json
import os
import re
import sys
import urllib.parse
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'sources'))
import paths
import safety
import common

UA = common.UA
ACCESS = ('https://geodataservices.wdfw.wa.gov/arcgis/rest/services/WP_RealEstate/'
          'WaterAccessSites/MapServer/1/query')
CATCH_AREA = ('https://services3.arcgis.com/NJJAMXTzj98caILi/arcgis/rest/services/'
              'WDFW_Fisheries_Management_Areas/FeatureServer/1/query')

#: Places that exist in the reports but in no WDFW point dataset: ocean management
#: areas, the Columbia's fishery sections, the pikeminnow check stations. Each is
#: the centre of a stretch of water rather than a survey point, and every one is
#: labelled approximate wherever it is shown.
APPROXIMATE = {
    # ocean and coastal fisheries
    'Buoy 10': (46.2450, -123.9500),
    # halibut subareas: the centre of the water each quota covers, not a port
    'Puget Sound halibut': (48.1200, -122.7800),
    'North coast halibut (Neah Bay, La Push)': (48.1500, -125.0000),
    'South coast halibut (Westport)': (46.8000, -124.5000),
    'Columbia River halibut (incl. Oregon)': (46.2000, -124.3000),
    'Willapa Bay (Area 2.1)': (46.5300, -123.9200),
    'Columbia River ocean area (incl. Oregon)': (46.2000, -124.2000),
    'Westport (Marine Area 2)': (46.8900, -124.3000),
    'La Push (Marine Area 3)': (47.9100, -124.7500),
    'Neah Bay (Marine Area 4)': (48.3700, -124.7000),
    # Columbia River mainstem fishery sections, downstream to upstream
    'Section 1 (Bonneville)': (45.6400, -121.9400),
    'Section 2 (Camas/Washougal)': (45.5800, -122.4000),
    'Section 3 (I-5 Area)': (45.6300, -122.6700),
    'Section 4 (Vancouver)': (45.6100, -122.7500),
    'Section 5 (Woodland)': (45.9000, -122.7700),
    'Section 6 (Kalama)': (46.0100, -122.8600),
    'Section 7 (Cowlitz)': (46.1000, -122.9100),
    'Section 8 (Longview)': (46.1200, -123.0000),
    'Section 9 (Cathlamet)': (46.2000, -123.3800),
    'Section 10 (Cathlamet)': (46.2400, -123.6000),
    # pikeminnow sport-reward check stations, Columbia then Snake
    'Cathlamet': (46.2050, -123.3830), 'Willow Grove': (46.1580, -123.0480),
    'Rainier': (46.0900, -122.9370), 'Kalama': (46.0070, -122.8590),
    'Ridgefield': (45.8130, -122.7440), 'Gleason': (45.6100, -122.6300),
    'Chinook Landing': (45.5560, -122.4400), 'Washougal': (45.5810, -122.3800),
    'Beacon Rock': (45.6270, -122.0210), 'Cascade Locks': (45.6700, -121.8940),
    'Bingen': (45.7150, -121.4680), 'The Dalles': (45.6070, -121.1780),
    'Giles French': (45.7220, -120.6960), 'Umatilla': (45.9170, -119.3420),
    'Columbia Point': (46.2660, -119.2660), 'Vernita': (46.6360, -119.7160),
    "Lyon's Ferry": (46.5900, -118.2200), 'Lyons Ferry': (46.5900, -118.2200),
    'Boyer Park': (46.5840, -117.4780),
    'Greenbelt': (46.4200, -117.0300), 'Hood Park': (46.2140, -119.0200),
    'Sand Station': (45.9200, -119.2100), 'Roosevelt': (45.8500, -120.3400),
    'Stevenson': (45.6980, -121.8830), 'Windust': (46.5300, -118.5800),
    'Swallows': (46.4230, -117.0600), 'Scappoose Bay': (45.8300, -122.8200),
    # Columbia tributary reaches the weekly report names but no dataset locates
    'Cowlitz River (above I-5)': (46.1600, -122.8600),
    'Cowlitz River (below I-5)': (46.1000, -122.9300),
    'Klickitat River (above Fisher Hill)': (45.7400, -121.1800),
    'Klickitat River (below Fisher Hill)': (45.7050, -121.1700),
    'Wind River (mouth)': (45.7200, -121.7900),
    'Wind River (above Shipherd Falls)': (45.7600, -121.7900),
    'Washougal River (Slough)': (45.5800, -122.3700),
    'Lewis River Mainstem': (45.8600, -122.7300),
    'John Day Pool': (45.7200, -120.6900),
    'Bonneville Pool': (45.6900, -121.5000),
    'The Dalles Pool': (45.6100, -121.1300),
}


def _arcgis(url, *, where='1=1', out_fields='*', geometry=True, extra=None):
    """Page an ArcGIS layer, asking for WGS84 so nothing has to be reprojected."""
    out, offset = [], 0
    while True:
        params = {'where': where, 'outFields': out_fields, 'outSR': 4326,
                  'f': 'json', 'returnGeometry': str(bool(geometry)).lower(),
                  'resultOffset': offset, 'resultRecordCount': 1000}
        params.update(extra or {})
        blob = safety.fetch(url + '?' + urllib.parse.urlencode(params),
                            timeout=120, user_agent=UA)
        page = json.loads(blob)
        feats = page.get('features', [])
        out.extend(feats)
        if len(feats) < 1000 or not page.get('exceededTransferLimit'):
            return out
        offset += 1000


def access_sites(refresh=False, say=print):
    """WDFW's water access sites: the ramps the Puget Sound creel is sampled at."""
    if os.path.exists(paths.GIS_ACCESS) and not refresh:
        with open(paths.GIS_ACCESS, encoding='utf-8') as f:
            return json.load(f)
    sites = []
    for f in _arcgis(ACCESS, out_fields='WaterAccessSiteName,County,BoatRamps'):
        g, a = f.get('geometry') or {}, f['attributes']
        if not g.get('x') or not a.get('WaterAccessSiteName'):
            continue
        sites.append({'name': a['WaterAccessSiteName'], 'county': a.get('County'),
                      'ramps': a.get('BoatRamps'),
                      'lat': round(g['y'], 6), 'lon': round(g['x'], 6)})
    with open(paths.GIS_ACCESS, 'w', encoding='utf-8') as f:
        json.dump(sites, f, indent=0)
    say(f'   water access sites: {len(sites)}')
    return sites


SHORE = ('https://geodataservices.wdfw.wa.gov/arcgis/rest/services/FP_FishMaps/'
         'ShoreFishingSites/MapServer/0/query')


def lake_sites(refresh=False, say=print):
    """WDFW's shore fishing sites, which is the only WDFW layer that names lakes.

    The statewide creel covers a great many lakes, and the water body centroid table
    only carries the ones a creel project has been run on. This fills in the rest.
    """
    path = os.path.join(paths.DATA, 'wdfw_shore_sites.json')
    if os.path.exists(path) and not refresh:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    out = []
    for f in _arcgis(SHORE, out_fields='LakeName,County,Latitude,Longitude'):
        a = f['attributes']
        g = f.get('geometry') or {}
        lat = a.get('Latitude') or g.get('y')
        lon = a.get('Longitude') or g.get('x')
        if not a.get('LakeName') or lat is None or lon is None:
            continue
        out.append({'name': a['LakeName'], 'county': a.get('County'),
                    'lat': round(float(lat), 6), 'lon': round(float(lon), 6)})
    with open(path, 'w', encoding='utf-8') as fh:
        json.dump(out, fh, indent=0)
    say(f'   shore fishing sites: {len(out)}')
    return out


def catch_areas(refresh=False, say=print):
    """Puget Sound salmon catch and reporting area outlines, thinned for the web.

    The published polygons follow every inlet at survey resolution and run to several
    megabytes. The dashboard draws them as a background, so points closer together
    than roughly a hundred metres are dropped — visually identical, an order of
    magnitude smaller to ship.
    """
    if os.path.exists(paths.CATCH_AREAS) and not refresh:
        with open(paths.CATCH_AREAS, encoding='utf-8') as f:
            return json.load(f)
    out = []
    for f in _arcgis(CATCH_AREA, out_fields='*'):
        a = f['attributes']
        number = a.get('AreaName') or ''
        name = f'Area {number}' if number else ''
        rings = (f.get('geometry') or {}).get('rings') or []
        thin = [_thin(r) for r in rings if len(r) > 3]
        if not thin:
            continue
        out.append({'name': str(name), 'code': str(number), 'rings': thin})
    with open(paths.CATCH_AREAS, 'w', encoding='utf-8') as f:
        json.dump(out, f, separators=(',', ':'))
    say(f'   catch area outlines: {len(out)}')
    return out


WRIA = ('https://services.arcgis.com/6lCKYNJLvwTXqrmp/arcgis/rest/services/'
        'ECY/FeatureServer/11/query')

#: WDFW's ocean salmon areas are defined by latitude lines running out from named
#: points on the coast — Leadbetter Point, the Queets River, Cape Alava — rather than
#: by a published polygon, and no WDFW service draws them. They are laid out here as
#: offshore bands between those latitudes, from the coast out to about forty miles,
#: and are marked approximate wherever they are drawn: the boundaries are real, the
#: seaward edge is a drawing device.
#: south edge, north edge, and roughly where the shoreline runs at that latitude
OCEAN_BANDS = [
    ('1', 'Marine Area 1 (Ilwaco)', 46.25, 46.63, -124.05),
    ('2', 'Marine Area 2 (Westport)', 46.63, 47.53, -124.10),
    ('3', 'Marine Area 3 (La Push)', 47.53, 48.17, -124.55),
    ('4', 'Marine Area 4 (Neah Bay)', 48.17, 48.42, -124.62),
]
#: the seaward edge is drawn just inside the map frame rather than at the real limit,
#: which is forty miles out and would push the whole state to the right
OCEAN_WEST = -125.05


def ocean_areas():
    """The four ocean areas as bands, so the coast is not a blank on a filled map."""
    out = []
    for code, name, south, north, coast in OCEAN_BANDS:
        ring = [[OCEAN_WEST, south], [coast, south],
                [coast, north], [OCEAN_WEST, north], [OCEAN_WEST, south]]
        out.append({'name': name, 'code': code, 'kind': 'ocean',
                    'precision': 'approximate', 'rings': [ring]})
    return out


def basins(refresh=False, say=print):
    """Washington's water resource inventory areas — the state's river basins.

    Fresh water has no equivalent of a marine catch area: a creel on the Cowlitz is
    reported as "Cowlitz River" and nothing says how far that reaches. The WRIA
    boundaries are the unit the state already manages water by, every river in the
    creel sits inside exactly one, and they tile the whole state — which is what lets
    the map show fresh water as filled ground rather than a scatter of dots.
    """
    path = os.path.join(paths.DATA, 'wa_basins.json')
    if os.path.exists(path) and not refresh:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    out = []
    for f in _arcgis(WRIA, out_fields='WRIA_NR,WRIA_NM'):
        a = f['attributes']
        rings = (f.get('geometry') or {}).get('rings') or []
        # basins are drawn as filled background, so they are thinned much harder than
        # the marine areas: a bay's shape tells a reader where they are, a basin's
        # thousandth inlet does not, and the whole set has to travel in the page
        thin = [_thin(r, tolerance=0.02) for r in rings if len(r) > 3]
        thin = [r for r in thin if len(r) > 5 and _spans(r) > 0.06]
        if not thin:
            continue
        out.append({'name': a.get('WRIA_NM') or '', 'code': str(a.get('WRIA_NR')),
                    'kind': 'basin', 'rings': thin})
    with open(path, 'w', encoding='utf-8') as fh:
        json.dump(out, fh, separators=(',', ':'))
    say(f'   river basins: {len(out)}')
    return out


def _spans(ring):
    """How wide a ring is, in degrees — used to drop specks the eye cannot see."""
    xs = [p[0] for p in ring]
    ys = [p[1] for p in ring]
    return max(max(xs) - min(xs), max(ys) - min(ys))


def point_in_rings(lon, lat, rings):
    """Whether a coordinate falls inside a polygon, holes and all."""
    inside = False
    for ring in rings:
        j = len(ring) - 1
        for i, (x, y) in enumerate(ring):
            xj, yj = ring[j]
            if (y > lat) != (yj > lat):
                if lon < (xj - x) * (lat - y) / ((yj - y) or 1e-12) + x:
                    inside = not inside
            j = i
    return inside


def area_centroids(areas=None):
    """A representative point inside each catch and reporting area.

    Two hundred Puget Sound marinas and city docks appear in no WDFW coordinate
    dataset, and leaving them off the map hides most of the sound's fishing. Each one
    does report the area it was sampled in, so it is drawn at that area's centre and
    labelled as an area position — the honest statement being "somewhere in Area 10",
    not a false precision about which dock.
    """
    areas = areas if areas is not None else catch_areas()
    grouped = {}
    for a in areas:
        m = re.match(r'(\d+(?:\.\d+)?)', a.get('code') or '')
        if not m:
            continue
        grouped.setdefault(m.group(1), []).extend(a['rings'])
    out = {}
    for number, rings in grouped.items():
        biggest = max(rings, key=len)
        lons = [p[0] for p in biggest]
        lats = [p[1] for p in biggest]
        out[number] = (round(sum(lats) / len(lats), 6), round(sum(lons) / len(lons), 6))
    return out


def _thin(ring, tolerance=0.001):
    kept = [ring[0]]
    for x, y in ring[1:-1]:
        px, py = kept[-1]
        if abs(x - px) > tolerance or abs(y - py) > tolerance:
            kept.append([round(x, 4), round(y, 4)])
    kept.append([round(ring[-1][0], 4), round(ring[-1][1], 4)])
    return kept


# --------------------------------------------------------------- name matching
_NOISE = re.compile(
    r'\b(ramp|ramps|public|boat|launch|access|site|dock|pier|marina|drystack|'
    r'shore|beach|park|state|county|city|the|wdfw|no |number)\b', re.I)
_PAREN = re.compile(r'\((?:formerly|prev\.?|previously)[^)]*\)', re.I)


def normalise(name):
    n = _PAREN.sub(' ', str(name or ''))
    n = re.sub(r'\*|\(\d+\)|\(\*?\d+\)\*?', ' ', n)
    n = n.replace('&', ' and ').replace('/', ' ').replace('-', ' ')
    n = re.sub(r'[.,\']', '', n).lower()
    n = _NOISE.sub(' ', n)
    n = re.sub(r'\bcreek\b', 'cr', n)
    n = re.sub(r'\briver\b', 'r', n)
    n = re.sub(r'\blake\b', 'lk', n)
    n = re.sub(r'\bsaint\b|\bst\b', 'st', n)
    return re.sub(r'\s+', ' ', n).strip()


def build(locations, *, water_bodies=None, sites=None, lakes=None, say=print):
    """location name -> {lat, lon, precision, matched_to}, for what can be placed."""
    water_bodies = water_bodies or {}
    sites = sites or access_sites(say=say)
    lakes = lakes if lakes is not None else lake_sites(say=say)

    by_site = {}
    for s in sites:
        by_site.setdefault(normalise(s['name']), s)
    for s in lakes:
        by_site.setdefault(normalise(s['name']), s)
    by_water = {}
    for name, rec in water_bodies.items():
        by_water.setdefault(normalise(name), (name, rec))

    out, unplaced = {}, []
    for loc in sorted(set(locations)):
        if not loc:
            continue
        key = normalise(loc)
        if loc in APPROXIMATE:
            lat, lon = APPROXIMATE[loc]
            out[loc] = {'lat': lat, 'lon': lon, 'precision': 'approximate',
                        'matched_to': loc}
            continue
        if key in by_water:
            name, rec = by_water[key]
            out[loc] = {'lat': rec['lat'], 'lon': rec['lon'], 'precision': 'exact',
                        'matched_to': name}
            continue
        if key in by_site:
            s = by_site[key]
            out[loc] = {'lat': s['lat'], 'lon': s['lon'], 'precision': 'matched',
                        'matched_to': s['name']}
            continue
        # one-sided containment, but only when it is unambiguous: "elliott bay"
        # may match one site, never three
        if key:
            hits = [s for k, s in by_site.items()
                    if k and (k.startswith(key + ' ') or key.startswith(k + ' '))]
            names = {s['name'] for s in hits}
            if len(names) == 1:
                s = hits[0]
                out[loc] = {'lat': s['lat'], 'lon': s['lon'],
                            'precision': 'matched', 'matched_to': s['name']}
                continue
            hits = [(n, r) for k, (n, r) in by_water.items()
                    if k and (k.startswith(key + ' ') or key.startswith(k + ' '))]
            if len({n for n, _ in hits}) == 1:
                name, rec = hits[0]
                out[loc] = {'lat': rec['lat'], 'lon': rec['lon'],
                            'precision': 'exact', 'matched_to': name}
                continue
        unplaced.append(loc)

    # Second pass: a dock no dataset names, beside exactly one that it does. The
    # locality is the leading word of the name — Blaine, Edmonds, Kingston — and it
    # is only used when one placed site claims it, so an ambiguous locality still
    # leaves the dock off the map rather than guessing between two.
    by_locality = defaultdict(set)
    for name, rec in out.items():
        token = normalise(name).split()
        if token:
            by_locality[token[0]].add((rec['lat'], rec['lon'], name))
    still = []
    for loc in unplaced:
        token = normalise(loc).split()
        siblings = by_locality.get(token[0]) if token else None
        if siblings and len(siblings) == 1:
            lat, lon, neighbour = next(iter(siblings))
            out[loc] = {'lat': lat, 'lon': lon, 'precision': 'locality',
                        'matched_to': neighbour}
        else:
            still.append(loc)

    say(f'   placed {len(out)} of {len(out) + len(still)} locations '
        f'({len(still)} without coordinates)')
    return out, still


if __name__ == '__main__':
    import sources.socrata as socrata          # noqa: E402
    wb = socrata.water_body_geo()
    placed, missing = build(list(wb), water_bodies=wb)
    print(len(placed), 'placed;', missing[:20])
