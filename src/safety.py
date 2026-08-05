"""Hardening for everything this project takes from the network.

The pipeline reads a web page it does not control and turns links on it into local
filenames and HTTP requests. If that page is ever tampered with — a compromised CMS,
a hijacked DNS answer, a proxy on a hotel network — the untrusted side of that
boundary must not be able to choose where a file lands or which host is contacted.
Everything in this module exists to make that impossible rather than unlikely.
"""
import io
import os
import re
import urllib.error
import urllib.parse
import urllib.request

#: Only these hosts may ever be contacted, whatever a page or a redirect asks for.
#: Each entry is a deliberate decision, not a convenience — adding one widens the
#: attack surface of every update run.
ALLOWED_HOSTS = frozenset({
    'wdfw.wa.gov',                  # the creel report pages and PDFs
    'data.wa.gov',                  # WDFW's creel database, published as open data
    'geodataservices.wdfw.wa.gov',  # WDFW water access sites
    'services3.arcgis.com',         # WDFW salmon catch and reporting areas
    'services.arcgis.com',          # Ecology's river basin boundaries (WRIA)
    'raw.githubusercontent.com',    # the sibling project's parsed hatchery returns
})

#: no single response may exceed this; the largest real report is about 9 MB
MAX_DOWNLOAD_BYTES = 96 * 1024 * 1024

#: guard against a decompression bomb in a tampered data file
MAX_DECOMPRESSED_BYTES = 512 * 1024 * 1024

_SAFE_NAME = re.compile(r'[^A-Za-z0-9._-]+')
# device names Windows refuses to treat as ordinary files, with or without extension
_WINDOWS_RESERVED = re.compile(
    r'^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(\.|$)', re.IGNORECASE)


class SecurityError(Exception):
    """Raised when untrusted input tries to leave the boundaries set here."""


# --------------------------------------------------------------- filenames
def safe_filename(raw, fallback='download.pdf'):
    """Reduce untrusted text to a plain filename that cannot escape a directory.

    Percent-encoding is decoded *first* and repeatedly, because decoding after
    sanitising is how ``..%2f..%2f`` turns back into a traversal. Everything that
    is not an unreserved character is then replaced, so no separator, drive letter,
    NUL or leading dot can survive.
    """
    name = str(raw)
    for _ in range(3):                      # unwrap double/triple encoding
        decoded = urllib.parse.unquote(name)
        if decoded == name:
            break
        name = decoded
    name = name.replace('\x00', '')
    name = os.path.basename(name.replace('\\', '/'))
    name = _SAFE_NAME.sub('_', name).strip('._')
    if _WINDOWS_RESERVED.match(name):
        name = '_' + name
    if not name or set(name) <= {'.', '_'}:
        return fallback
    return name[:120]


def resolve_within(directory, filename):
    """Join and prove the result is really inside *directory* before it is used."""
    base = os.path.realpath(directory)
    target = os.path.realpath(os.path.join(base, safe_filename(filename)))
    if target != base and not target.startswith(base + os.sep):
        raise SecurityError(f'path {filename!r} escapes {directory!r}')
    return target


# --------------------------------------------------------------- network
def _check_url(url, *, require_https=True):
    parts = urllib.parse.urlsplit(url)
    if parts.scheme != 'https' and require_https:
        raise SecurityError(f'refusing non-HTTPS URL: {url}')
    host = (parts.hostname or '').lower()
    if host not in ALLOWED_HOSTS:
        raise SecurityError(f'refusing host {host!r}; allowed: {sorted(ALLOWED_HOSTS)}')
    return parts


class _StrictRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Follow redirects only to an allowed host over HTTPS.

    urllib follows redirects anywhere by default, so without this a 302 from a
    trusted host to ``http://attacker.example`` would be fetched without a murmur.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        try:
            _check_url(newurl)
        except SecurityError as e:
            raise urllib.error.HTTPError(newurl, code, f'blocked redirect: {e}',
                                         headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_opener = urllib.request.build_opener(_StrictRedirectHandler)


def fetch(url, *, timeout=90, user_agent, max_bytes=MAX_DOWNLOAD_BYTES):
    """GET a URL with the host allow-list, HTTPS, and a hard size ceiling applied.

    The body is read in chunks and abandoned the moment it exceeds *max_bytes*, so a
    hostile or broken server cannot exhaust memory or fill the disk.
    """
    _check_url(url)
    req = urllib.request.Request(url, headers={'User-Agent': user_agent})
    with _opener.open(req, timeout=timeout) as r:
        declared = r.headers.get('Content-Length')
        if declared and declared.isdigit() and int(declared) > max_bytes:
            raise SecurityError(f'response declares {int(declared):,} bytes, '
                                f'over the {max_bytes:,} limit: {url}')
        buf = io.BytesIO()
        while True:
            chunk = r.read(1 << 16)
            if not chunk:
                break
            buf.write(chunk)
            if buf.tell() > max_bytes:
                raise SecurityError(f'response exceeded {max_bytes:,} bytes: {url}')
        return buf.getvalue()


def head_ok(url, *, timeout=45, user_agent):
    """True when a HEAD to an allowed host returns 200."""
    try:
        _check_url(url)
    except SecurityError:
        return False
    req = urllib.request.Request(url, headers={'User-Agent': user_agent},
                                 method='HEAD')
    try:
        with _opener.open(req, timeout=timeout) as r:
            return r.status == 200
    except Exception:
        return False


# --------------------------------------------------------------- decompression
def bounded_reader(fileobj, max_bytes=MAX_DECOMPRESSED_BYTES):
    """Wrap a stream so it raises rather than expanding without limit."""
    class _Bounded(io.RawIOBase):
        def __init__(self):
            self._read = 0

        def readable(self):
            return True

        def readinto(self, b):
            chunk = fileobj.read(len(b))
            if not chunk:
                return 0
            self._read += len(chunk)
            if self._read > max_bytes:
                raise SecurityError(
                    f'refusing to expand past {max_bytes:,} bytes — '
                    f'possible decompression bomb')
            b[:len(chunk)] = chunk
            return len(chunk)

        def close(self):
            try:
                fileobj.close()
            finally:
                super().close()

    return io.BufferedReader(_Bounded())
