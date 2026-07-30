"""Every file location in one place, so the scripts run the same on Windows and macOS.

Large derived files (downloaded reports, the parse cache) live outside version
control. The extracted rows are stored gzipped, and are read and written
transparently by ``open_text``.
"""
import gzip, io, os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, 'src')
SOURCES = os.path.join(SRC, 'sources')
DATA = os.path.join(ROOT, 'data')
DOCS = os.path.join(ROOT, 'docs')
CACHE = os.path.join(ROOT, '.cache')

PAGE_DIR = os.path.join(CACHE, 'pages')       # fetched HTML, one file per page
PDF_DIR = os.path.join(CACHE, 'pdf')          # fetched PDF reports
API_DIR = os.path.join(CACHE, 'api')          # raw Socrata pulls

#: one row per date x location x species x fate, from every source
RAW = os.path.join(DATA, 'creel_rows.csv.gz')
#: angler effort per date x location, kept separate because it is not per-species
EFFORT = os.path.join(DATA, 'creel_effort.csv.gz')

#: fisheries tracked against a ceiling rather than counted: encounter guidelines
#: and harvest quotas, which are not catch and are not stored as if they were
QUOTAS = os.path.join(DATA, 'quotas.json')
#: emergency rule changes, which is what actually opens and closes water
RULES = os.path.join(DATA, 'rules.json')
MANIFEST = os.path.join(DATA, 'manifest.json')
PAYLOAD = os.path.join(DATA, 'dashboard_data.json')
PLACE_GEO = os.path.join(DATA, 'place_geo.json')        # location -> lat/lon
GIS_ACCESS = os.path.join(DATA, 'wdfw_access_sites.json')
CATCH_AREAS = os.path.join(DATA, 'catch_areas.json')    # marine area polygons
OUTLINE = os.path.join(DATA, 'wa_outline.json')
BUILD_INFO = os.path.join(DATA, 'build_info.json')

TEMPLATE = os.path.join(SRC, 'template.html')
DASHBOARD = os.path.join(DOCS, 'index.html')
PREVIEW = os.path.join(DOCS, 'preview.png')
RUN_LOG = os.path.join(CACHE, 'last_run.log')


def ensure_dirs():
    for d in (DATA, DOCS, CACHE, PAGE_DIR, PDF_DIR, API_DIR):
        os.makedirs(d, exist_ok=True)


def open_text(path, mode='r', **kw):
    """Open a path for text I/O, transparently gzipping anything ending in .gz."""
    kw.setdefault('encoding', 'utf-8')
    if str(path).endswith('.gz'):
        if 'b' in mode:
            raise ValueError('use open_text for text modes only')
        if 'w' in mode:
            # mtime=0 keeps the bytes deterministic, so unchanged data does not look
            # modified to git and the daily refresh only commits real changes
            raw = gzip.GzipFile(filename=path, mode='wb', compresslevel=9, mtime=0)
        else:
            import safety
            raw = safety.bounded_reader(gzip.GzipFile(filename=path, mode='rb'))
        return io.TextIOWrapper(raw, encoding=kw['encoding'],
                                newline=kw.get('newline', ''))
    if 'newline' not in kw:
        kw['newline'] = ''
    return open(path, mode, **kw)
