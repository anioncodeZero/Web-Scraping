import hashlib
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import unquote, urlparse

import requests
from tqdm import tqdm

from config import (
    USER_AGENT, REQUEST_TIMEOUT, REQUEST_DELAY, VERIFY_SSL,
    DEFAULT_WORKERS, MIN_FILE_SIZE, MAX_RETRIES, MAX_FILE_SIZE,
)

from utils import categorize, sanitize_filename


class Downloader:
    def __init__(self, output_dir, store, *,
                 workers=DEFAULT_WORKERS,
                 min_size=MIN_FILE_SIZE,
                 max_retries=MAX_RETRIES,
                 max_size=MAX_FILE_SIZE):
        self.output_dir = Path(output_dir)
        for sub in ('images', 'videos', 'sensitive', 'others'):
            (self.output_dir / sub).mkdir(parents=True, exist_ok=True)
        self.store       = store
        self.workers     = workers
        self.min_size    = min_size
        self.max_retries = max_retries
        self.max_size    = max_size

    # ---------------- helpers ----------------
    def _filename(self, url):
        name = os.path.basename(unquote(urlparse(url).path)) or 'file'
        return sanitize_filename(name)

    def _unique(self, folder: Path, name: str) -> Path:
        t = folder / name
        if not t.exists():
            return t
        stem, ext = os.path.splitext(name)
        i = 1
        while (cand := folder / f"{stem}_{i}{ext}").exists():
            i += 1
        return cand

    # ---------------- single download ----------------
    def _one(self, url, category):
        if self.store.media_done(url):
            return 'skip'

        for attempt in range(self.max_retries):
            target = None
            try:
                time.sleep(REQUEST_DELAY)
                s = requests.Session()
                s.headers.update({'User-Agent': USER_AGENT})

                with s.get(url, timeout=REQUEST_TIMEOUT,
                           stream=True, verify=VERIFY_SSL) as r:
                    if r.status_code != 200:
                        raise RuntimeError(f"HTTP {r.status_code}")

                    ctype    = r.headers.get('Content-Type', '').lower()
                    real_cat = categorize(url, ctype)

                    # ---- batas ukuran atas (via Content-Length jika ada) ----
                    cl = r.headers.get('Content-Length')
                    if cl and cl.isdigit() and int(cl) > self.max_size:
                        self.store.mark_failed(
                            url, f'too_large({cl}b)')
                        return 'fail'

                    folder = self.output_dir / real_cat

                    name = self._filename(url)
                    if '.' not in name and ctype:
                        ext = ctype.split('/')[-1].split(';')[0].strip()
                        ext = {'jpeg': 'jpg', 'svg+xml': 'svg'}.get(ext, ext)
                        if ext:
                            name = f"{name}.{ext}"
                    target = self._unique(folder, name)

                    h, total = hashlib.sha256(), 0
                    with open(target, 'wb') as f:
                        for chunk in r.iter_content(8192):
                            if not chunk:
                                continue
                            f.write(chunk)
                            h.update(chunk)
                            total += len(chunk)
                            # ---- batas ukuran bawah saat streaming
                            # (kalau server tidak kirim Content-Length)
                            if total > self.max_size:
                                f.close()
                                target.unlink(missing_ok=True)
                                self.store.mark_failed(
                                    url, f'too_large(>{self.max_size}b)')
                                return 'fail'

                # ---- cek ukuran minimal ----
                # sensitive BYPASS min_size: .env / config bisa <2KB
                if total < self.min_size and real_cat != 'sensitive':
                    target.unlink(missing_ok=True)
                    self.store.mark_failed(url, f'too_small({total}b)')
                    return 'small'

                # ---- dedup by hash ----
                digest = h.hexdigest()
                if self.store.sha_exists(digest):
                    target.unlink(missing_ok=True)
                    self.store.mark_done(url, '', digest, total)
                    return 'dupe'

                self.store.mark_done(url, target, digest, total)
                return 'ok'

            except Exception as e:
                # kalau file setengah jadi tertinggal, buang supaya tidak
                # lolos sebagai file valid di run berikutnya
                if target is not None and target.exists():
                    try:
                        target.unlink()
                    except OSError:
                        pass
                if attempt == self.max_retries - 1:
                    self.store.mark_failed(url, str(e))
                    return 'fail'
                time.sleep(2 ** attempt)

        return 'fail'

    # ---------------- batch runner ----------------
    def run(self, media_list=None):
        if media_list is None:
            media_list = self.store.pending_media()

        stats = {'ok': 0, 'skip': 0, 'dupe': 0, 'small': 0, 'fail': 0}
        if not media_list:
            return stats

        with ThreadPoolExecutor(max_workers=self.workers) as ex:
            futures = [ex.submit(self._one, u, c) for u, c in media_list]
            for f in tqdm(as_completed(futures), total=len(futures),
                          desc="Downloading"):
                try:
                    stats[f.result()] += 1
                except Exception:
                    stats['fail'] += 1
        return stats