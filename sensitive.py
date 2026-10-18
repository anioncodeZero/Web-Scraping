import hashlib
import re
import secrets
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urljoin

import requests
from tqdm import tqdm

from config import USER_AGENT, REQUEST_TIMEOUT, VERIFY_SSL
from utils import is_sensitive


def _looks_like_env(b: bytes) -> bool:
    try:
        text = b[:8192].decode('utf-8', 'ignore')
    except Exception:
        return False
    low = text.lower()
    if '<html' in low or '<!doctype' in low:
        return False
    kv = sum(1 for line in text.splitlines()
             if re.match(r'^\s*[A-Z_][A-Z0-9_]{0,63}\s*=\s*\S', line))
    return kv >= 3


def _looks_like_sql(b: bytes) -> bool:
    head = b[:16384].lower()
    return any(m in head for m in (
        b'create table', b'insert into', b'drop table',
        b'-- mysql', b'-- postgresql', b'begin transaction',
        b'/*!40', b'set sql_mode',
    ))


def validate_content(url: str, content: bytes, ctype: str) -> tuple[bool, str]:
    if not content:
        return False, 'empty'
    if len(content) < 60:
        return False, 'too_small'

    head = content[:1024].lower()
    if b'<!doctype html' in head or b'<html' in head:
        return False, 'html_response'

    low_url, low_ct = url.lower(), ctype.lower()
    # Content sniffing (lebih kuat dari ekstensi)
    if content[:16] == b'SQLite format 3\x00':
        return True, 'sqlite_magic'
    if content[:4] == b'PK\x03\x04':
        return True, 'zip_magic'
    if content[:2] == b'\x1f\x8b':
        return True, 'gzip_magic'
    if len(content) > 262 and content[257:262] == b'ustar':
        return True, 'tar_magic'
    if _looks_like_sql(content):
        return True, 'sql_markers'
    if '.env' in low_url or low_url.endswith('/env'):
        if _looks_like_env(content):
            return True, 'env_format'

    # Fallback: ekstensi sensitive + bukan html → percaya
    if is_sensitive(url) and 'text/html' not in low_ct:
        return True, 'sensitive_non_html'

    return False, 'not_validated'


class SensitiveProbe:
    def __init__(self, base_url, store, wordlist, *, workers=8):
        self.base_url = base_url.rstrip('/') + '/'
        self.store = store
        self.wordlist = wordlist
        self.workers = workers
        self.session = requests.Session()
        self.session.headers.update({'User-Agent': USER_AGENT})
        self._baseline_hashes = set()

    def _baseline(self):
        """Fingerprint soft-404: fetch 2 path acak."""
        for _ in range(2):
            try:
                r = self.session.get(
                    urljoin(self.base_url, secrets.token_urlsafe(20)),
                    timeout=REQUEST_TIMEOUT, verify=VERIFY_SSL,
                    allow_redirects=False)
                self._baseline_hashes.add(hashlib.sha256(r.content).hexdigest())
            except requests.RequestException:
                pass

    def _probe(self, path):
        url = urljoin(self.base_url, path)
        if self.store.media_done(url):
            return 'skip'
        try:
            time.sleep(0.1)
            r = self.session.get(url, timeout=REQUEST_TIMEOUT,
                                 verify=VERIFY_SSL, allow_redirects=False)
        except requests.RequestException:
            return 'fail'

        if r.status_code != 200:
            return 'no'

        # Tolak soft-404
        if hashlib.sha256(r.content).hexdigest() in self._baseline_hashes:
            return 'soft404'

        ctype = r.headers.get('Content-Type', '').lower()
        ok, reason = validate_content(url, r.content, ctype)
        if not ok:
            return 'miss'

        # Catat sebagai pending → downloader mengambilnya
        self.store.add_media(url, 'sensitive', self.base_url)
        return f'hit:{reason}'

    def probe(self):
        self._baseline()
        stats: dict[str, int] = {}
        with ThreadPoolExecutor(max_workers=self.workers) as ex:
            futures = [ex.submit(self._probe, w) for w in self.wordlist]
            for f in tqdm(as_completed(futures), total=len(futures),
                          desc="Probing sensitive"):
                k = f.result()
                stats[k] = stats.get(k, 0) + 1
        return stats