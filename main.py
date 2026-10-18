import argparse
import sys
from pathlib import Path
from urllib.parse import urlparse

import requests

from config import BASE_OUTPUT_DIR, USER_AGENT
from utils import get_domain
from store import Store
from sitemap import discover_pages
from crawler import Crawler, _clean_query, _is_junk
from downloader import Downloader


def _load_wordlist(path: Path) -> list[str]:
    """Baca wordlist: skip baris kosong & komentar '#'."""
    if not path.exists():
        return []
    words = []
    for line in path.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        words.append(line)
    return words


def main():
    ap = argparse.ArgumentParser(
        description="Data miner: crawl + probe file sensitif + download semua media."
    )
    ap.add_argument('url', help='URL target, mis. https://situs.com')

    # ---- crawl ----
    ap.add_argument('--max-depth', type=int, default=None,
                    help='Kedalaman crawl (default: sampai buntu)')
    ap.add_argument('--max-pages', type=int, default=100_000,
                    help='Batas jumlah halaman (default: 100000)')
    ap.add_argument('--no-sitemap', action='store_true',
                    help='Jangan pakai sitemap sebagai seed')
    ap.add_argument('--strict-sitemap', action='store_true',
                    help='Hanya crawl URL dari sitemap (abaikan <a href>)')

    # ---- download ----
    ap.add_argument('--no-download', action='store_true',
                    help='Crawl saja, tanpa download')
    ap.add_argument('--workers', type=int, default=8,
                    help='Thread download paralel (default: 8)')
    ap.add_argument('--min-size', type=int, default=2048,
                    help='Byte minimal file (default: 2048). Sensitive bypass.')
    ap.add_argument('--max-size', type=int, default=500 * 1024 * 1024,
                    help='Byte maksimal file (default: 500MB)')
    ap.add_argument('--retry-failed', action='store_true',
                    help='Ulangi download/probe yang sebelumnya gagal')

    # ---- sensitive probe ----
    ap.add_argument('--probe-sensitive', action='store_true',
                    help='Probe path sensitif (SQL dump, .env, backup, dll.)')
    ap.add_argument('--wordlist',
                    default=str(Path('wordlists') / 'sensitive.txt'),
                    help='File wordlist untuk probing')

    args = ap.parse_args()

    # ---- siapkan URL & folder output ----
    url = args.url if args.url.startswith(('http', 'https')) else 'http://' + args.url
    domain   = get_domain(url)
    site_dir = BASE_OUTPUT_DIR / domain
    site_dir.mkdir(parents=True, exist_ok=True)

    print(f"[*] Target     : {url}")
    print(f"[*] Domain     : {domain}")
    print(f"[*] Output dir : {site_dir.resolve()}")

    store = Store(site_dir / 'crawl.db')
    try:
        # ---- retry mode ----
        if args.retry_failed:
            n = store.retry_failed()
            print(f"[+] {n} item 'failed' ditandai ulang sebagai 'pending'")

        # ---- 1. Sitemap seeding ----
        seeds: list[str] = []
        if not args.no_sitemap:
            s = requests.Session()
            s.headers['User-Agent'] = USER_AGENT
            print("[*] Membaca sitemap ...")
            raw_seeds = discover_pages(s, url)
            base_netloc = urlparse(url).netloc

            # bersihkan + filter junk, dedup
            seen_s, seeds_clean = set(), []
            for sm in raw_seeds:
                sm = _clean_query(sm)
                if _is_junk(sm, base_netloc):
                    continue
                if sm in seen_s:
                    continue
                seen_s.add(sm)
                seeds_clean.append(sm)

            seeds = seeds_clean
            dropped = len(raw_seeds) - len(seeds)
            print(f"[+] Sitemap     : {len(raw_seeds)} URL "
                  f"({dropped} dibuang sebagai junk, {len(seeds)} dipakai)")

        # ---- 2. Crawl ----
        print("[*] Crawling ...")
        crawler = Crawler(
            url, store,
            max_depth=args.max_depth,
            max_pages=args.max_pages,
            seeds=seeds,
        )
        if args.strict_sitemap:
            crawler.strict = True
        attempted = crawler.crawl()
        print(f"[+] Crawl selesai: {attempted} halaman dicoba")

        # ---- 3. Sensitive probe ----
        if args.probe_sensitive:
            wl_path = Path(args.wordlist)
            if not wl_path.is_absolute():
                # cari relatif terhadap script main.py
                wl_path = Path(__file__).parent / wl_path
            words = _load_wordlist(wl_path)
            if not words:
                print(f"[!] Wordlist kosong / tidak ada: {wl_path}")
            else:
                from sensitive import SensitiveProbe
                print(f"[*] Probing {len(words)} path sensitif "
                      f"(workers={args.workers}) ...")
                probe = SensitiveProbe(url, store, words,
                                       workers=args.workers)
                stats = probe.probe()
                hits  = {k: v for k, v in stats.items() if k.startswith('hit:')}
                total_hits = sum(hits.values())
                print(f"[+] Probe selesai. Hit: {total_hits}")
                for k, v in sorted(hits.items()):
                    print(f"    {k:<22} {v}")

        # ---- 4. Download ----
        if not args.no_download:
            print(f"[*] Download (workers={args.workers}, "
                  f"min={args.min_size}b, max={args.max_size}b) ...")
            dl = Downloader(
                site_dir, store,
                workers=args.workers,
                min_size=args.min_size,
                max_size=args.max_size,
            )
            stats = dl.run()
            print(f"[+] Download: ok={stats['ok']}  skip={stats['skip']}  "
                  f"dupe={stats['dupe']}  small={stats['small']}  "
                  f"fail={stats['fail']}")
        else:
            print("[*] Download di-skip (--no-download)")

        # ---- 5. Ringkasan ----
        print("\n[✓] Ringkasan database:")
        summary = store.summary()
        for status, n in sorted(summary.items()):
            print(f"    {status:<10} {n}")

        # hitung per kategori (media non-pending)
        rows = store.conn.execute(
            "SELECT category, COUNT(*) FROM media "
            "WHERE status='done' GROUP BY category ORDER BY 2 DESC"
        ).fetchall()
        if rows:
            print("\n[✓] File tersimpan per kategori:")
            for cat, n in rows:
                print(f"    {cat:<10} {n}")

        print(f"\n[✓] Folder output: {site_dir.resolve()}")
        print(f"[✓] Manifest DB  : {(site_dir / 'crawl.db').resolve()}")

    except KeyboardInterrupt:
        print("\n[!] Dihentikan oleh user. State tersimpan di crawl.db — "
              "jalankan ulang untuk resume.", file=sys.stderr)
        sys.exit(130)
    finally:
        store.close()


if __name__ == '__main__':
    main()