import gzip
import re
import xml.etree.ElementTree as ET
from urllib.parse import urljoin, urlparse

import requests

from config import USER_AGENT, REQUEST_TIMEOUT, VERIFY_SSL

NS = {'sm': 'http://www.sitemaps.org/schemas/sitemap/0.9'}


def _fetch(session, url):
    try:
        r = session.get(url, timeout=REQUEST_TIMEOUT, verify=VERIFY_SSL)
        if r.status_code != 200:
            return None
        c = r.content
        if url.endswith('.gz'):
            try: c = gzip.decompress(c)
            except OSError: pass
        return c
    except requests.RequestException:
        return None


def discover_pages(session: requests.Session, base_url: str) -> list[str]:
    p = urlparse(base_url)
    root = f"{p.scheme}://{p.netloc}"
    session.headers.setdefault('User-Agent', USER_AGENT)

    sitemaps = set()
    robots = _fetch(session, urljoin(root, '/robots.txt'))
    if robots:
        for line in robots.decode('utf-8', 'ignore').splitlines():
            m = re.match(r'(?i)^sitemap:\s*(\S+)', line.strip())
            if m:
                sitemaps.add(m.group(1).strip())

    for c in ('/sitemap.xml', '/sitemap_index.xml', '/sitemap-index.xml',
              '/wp-sitemap.xml'):
        sitemaps.add(urljoin(root, c))

    pages, seen, queue = set(), set(), list(sitemaps)
    while queue:
        sm = queue.pop(0)
        if sm in seen or len(seen) > 100:
            continue
        seen.add(sm)
        content = _fetch(session, sm)
        if not content:
            continue
        try:
            root_el = ET.fromstring(content)
        except ET.ParseError:
            continue

        tag = root_el.tag.lower()
        if tag.endswith('sitemapindex'):
            for loc in root_el.findall('.//sm:sitemap/sm:loc', NS):
                if loc.text:
                    queue.append(loc.text.strip())
        elif tag.endswith('urlset'):
            for loc in root_el.findall('.//sm:url/sm:loc', NS):
                if loc.text:
                    pages.add(loc.text.strip())

    return sorted(pages)