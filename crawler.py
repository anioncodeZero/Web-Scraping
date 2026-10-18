import json
import re
import time
from urllib.parse import (
    urljoin, urlparse, urlunparse, parse_qsl, urlencode,
)

import requests
from bs4 import BeautifulSoup
from tqdm import tqdm

from config import (
    USER_AGENT, REQUEST_TIMEOUT, REQUEST_DELAY, VERIFY_SSL,
    MAX_DEPTH, MAX_PAGES,
)
from utils import categorize, normalize_url, is_internal, is_sensitive


# ===================================================================== #
#  Filter URL sampah (dipakai juga oleh main.py untuk seed sitemap)
# ===================================================================== #

JUNK_QUERY_KEYS = {
    'utm_source', 'utm_medium', 'utm_campaign', 'utm_term', 'utm_content',
    'fbclid', 'gclid', 'yclid', 'msclkid', 'ref', 'referrer',
    'replytocom', 'preview', 's', 'search', 'q',
}

JUNK_PATH_RE = re.compile(
    r'/(feed|rss|wp-login\.php|wp-admin|wp-json|xmlrpc\.php|'
    r'cart|checkout|account|login|logout|signup|register)(/|$)',
    re.I,
)


def _clean_query(url: str) -> str:
    """Buang query param tracker/noise, urutkan sisanya."""
    p = urlparse(url)
    if not p.query:
        return url
    kept = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True)
            if k.lower() not in JUNK_QUERY_KEYS]
    new_q = urlencode(sorted(kept))
    return urlunparse(p._replace(query=new_q, fragment=''))


def _is_junk(url: str, base_domain: str) -> bool:
    """True kalau URL ini kemungkinan tidak menghasilkan media baru."""
    p = urlparse(url)
    if p.netloc != base_domain:
        return True
    if JUNK_PATH_RE.search(p.path):
        return True
    if len(parse_qsl(p.query)) > 6:      # faceted nav ekstrem
        return True
    return False


# ===================================================================== #
#  Crawler
# ===================================================================== #

CSS_URL_RE    = re.compile(r"url\(\s*['\"]?([^'\")]+)['\"]?\s*\)", re.I)
EMBED_DOMAINS = ('youtube.com', 'youtu.be', 'vimeo.com',
                 'dailymotion.com', 'streamable.com')


class Crawler:
    def __init__(self, start_url, store, *,
                 max_depth=MAX_DEPTH,
                 max_pages=MAX_PAGES,
                 seeds=None):
        self.start_url   = normalize_url(start_url)
        self.base_domain = urlparse(self.start_url).netloc
        self.store       = store
        self.max_depth   = max_depth
        self.max_pages   = max_pages
        self.seeds       = [normalize_url(u) for u in (seeds or [])]
        self.strict      = False
        self.session     = requests.Session()
        self.session.headers.update({'User-Agent': USER_AGENT})

    # ------------------------------------------------------------- #
    #  Media extractors
    # ------------------------------------------------------------- #
    def _add_media(self, raw_url, category, page_url):
        if not raw_url:
            return
        full = urljoin(page_url, raw_url)
        if not full.startswith(('http://', 'https://')):
            return
        self.store.add_media(full, category, page_url)

    def _extract_img(self, soup, page_url):
        for img in soup.find_all('img'):
            for attr in ('src', 'data-src', 'data-original',
                         'data-lazy', 'data-url'):
                v = img.get(attr)
                if v:
                    self._add_media(v, 'images', page_url)
            ss = img.get('srcset')
            if ss:
                for part in ss.split(','):
                    u = part.strip().split(' ')[0]
                    if u:
                        self._add_media(u, 'images', page_url)

    def _extract_picture(self, soup, page_url):
        for src in soup.select('picture source[srcset]'):
            for part in src.get('srcset', '').split(','):
                u = part.strip().split(' ')[0]
                if u:
                    self._add_media(u, 'images', page_url)

    def _extract_video_audio(self, soup, page_url):
        for tag in soup.find_all(['video', 'audio']):
            cat = 'videos' if tag.name == 'video' else 'others'
            src = tag.get('src')
            if src:
                self._add_media(src, cat, page_url)
            for so in tag.find_all('source', src=True):
                self._add_media(so['src'], cat, page_url)
            poster = tag.get('poster')
            if poster:
                self._add_media(poster, 'images', page_url)

    def _extract_link(self, soup, page_url):
        for lk in soup.find_all('link', href=True):
            href = lk['href']
            full = urljoin(page_url, href)
            cat = categorize(full)
            if cat in ('images', 'videos', 'sensitive'):
                self._add_media(href, cat, page_url)

    def _extract_meta(self, soup, page_url):
        for meta in soup.find_all('meta'):
            prop    = (meta.get('property') or meta.get('name') or '').lower()
            content = meta.get('content')
            if not content:
                continue
            if prop in ('og:image', 'og:image:url', 'og:image:secure_url',
                        'twitter:image', 'twitter:image:src'):
                self._add_media(content, 'images', page_url)
            elif prop in ('og:video', 'og:video:url', 'og:video:secure_url',
                          'twitter:player:stream'):
                self._add_media(content, 'videos', page_url)

    def _extract_css(self, css_text, page_url):
        for m in CSS_URL_RE.finditer(css_text or ''):
            u = m.group(1).strip()
            if u.startswith(('data:', '#')):
                continue
            self._add_media(u, categorize(urljoin(page_url, u)), page_url)

    def _extract_style(self, soup, page_url):
        for st in soup.find_all('style'):
            self._extract_css(st.string, page_url)
        for el in soup.find_all(style=True):
            self._extract_css(el['style'], page_url)

    def _extract_jsonld(self, soup, page_url):
        for sc in soup.find_all('script', type='application/ld+json'):
            try:
                data = json.loads(sc.string or '{}')
            except (json.JSONDecodeError, TypeError):
                continue
            for it in (data if isinstance(data, list) else [data]):
                if not isinstance(it, dict):
                    continue
                for k in ('contentUrl', 'image', 'thumbnailUrl', 'embedUrl'):
                    v  = it.get(k)
                    vs = v if isinstance(v, list) else ([v] if v else [])
                    for x in vs:
                        if isinstance(x, str) and x.startswith(('http', '/')):
                            full = urljoin(page_url, x)
                            self._add_media(x, categorize(full), page_url)

    def _extract_iframe(self, soup, page_url):
        for ifr in soup.find_all('iframe', src=True):
            full = urljoin(page_url, ifr['src'])
            if any(d in full for d in EMBED_DOMAINS):
                self._add_media(ifr['src'], 'videos', page_url)

    def _extract_media_from_soup(self, soup, page_url):
        self._extract_img(soup, page_url)
        self._extract_picture(soup, page_url)
        self._extract_video_audio(soup, page_url)
        self._extract_link(soup, page_url)
        self._extract_meta(soup, page_url)
        self._extract_style(soup, page_url)
        self._extract_jsonld(soup, page_url)
        self._extract_iframe(soup, page_url)

    # ------------------------------------------------------------- #
    #  Link extraction (dengan filter junk + sensitive)
    # ------------------------------------------------------------- #
    def _extract_links(self, soup, page_url):
        next_pages = []
        for a in soup.find_all('a', href=True):
            link = normalize_url(urljoin(page_url, a['href']))
            if not link.startswith(('http://', 'https://')):
                continue
            if not is_internal(link, self.base_domain):
                continue

            link = _clean_query(link)
            if _is_junk(link, self.base_domain):
                continue

            # klasifikasi
            if is_sensitive(link):
                self.store.add_media(link, 'sensitive', page_url)
                continue

            cat = categorize(link)
            if cat in ('images', 'videos'):
                self.store.add_media(link, cat, page_url)
                continue

            if self.store.page_seen(link):
                continue
            next_pages.append(link)
        return next_pages

    # ------------------------------------------------------------- #
    #  Fetch & proses satu halaman
    # ------------------------------------------------------------- #
    def _fetch(self, url):
        try:
            time.sleep(REQUEST_DELAY)
            return self.session.get(
                url, timeout=REQUEST_TIMEOUT,
                allow_redirects=True, verify=VERIFY_SSL,
            )
        except requests.RequestException:
            return None

    def _process_page(self, url):
        """Return list URL internal baru, atau None kalau fetch gagal."""
        resp = self._fetch(url)
        if resp is None or resp.status_code != 200:
            return None

        ctype = resp.headers.get('Content-Type', '').lower()

        # Resource non-HTML → langsung catat sebagai media
        if not ctype.startswith('text/html'):
            self.store.add_media(url, categorize(url, ctype), url)
            return []

        try:
            soup = BeautifulSoup(resp.text, 'html.parser')
        except Exception:
            return []

        # Media ekstraksi (img, video, css, jsonld, dll.)
        self._extract_media_from_soup(soup, url)

        # Kalau strict mode: abaikan <a href> sama sekali
        if self.strict:
            return []

        return self._extract_links(soup, url)

    # ------------------------------------------------------------- #
    #  Main loop (BFS)
    # ------------------------------------------------------------- #
    def crawl(self) -> int:
        queue         = []
        seen_in_queue = set()

        # seed dari sitemap
        for s in self.seeds:
            if s not in seen_in_queue:
                queue.append((s, 0))
                seen_in_queue.add(s)

        # seed dari start_url
        if self.start_url not in seen_in_queue:
            queue.append((self.start_url, 0))
            seen_in_queue.add(self.start_url)

        pbar      = tqdm(desc="Crawling", unit="page")
        attempted = 0
        try:
            while queue and attempted < self.max_pages:
                url, depth = queue.pop(0)

                if self.store.page_seen(url):
                    continue
                if self.max_depth is not None and depth > self.max_depth:
                    continue

                attempted += 1
                pbar.update(1)
                pbar.set_postfix_str(
                    f"queue={len(queue)} attempted={attempted}")

                next_pages = self._process_page(url)
                if next_pages is None:
                    # fetch gagal → jangan mark_page, biar bisa di-retry
                    continue

                self.store.mark_page(url)

                if self.strict:
                    continue  # tidak menambah antrian dari link

                for nxt in next_pages:
                    if nxt in seen_in_queue:
                        continue
                    seen_in_queue.add(nxt)
                    queue.append((nxt, depth + 1))
        finally:
            pbar.close()
        return attempted