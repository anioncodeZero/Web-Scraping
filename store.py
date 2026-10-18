import sqlite3
import threading
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS pages (
    url TEXT PRIMARY KEY,
    fetched_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS media (
    url TEXT PRIMARY KEY,
    category TEXT NOT NULL,
    source_page TEXT,
    local_path TEXT,
    sha256 TEXT,
    size INTEGER,
    status TEXT DEFAULT 'pending',
    error TEXT,
    fetched_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_media_sha    ON media(sha256);
CREATE INDEX IF NOT EXISTS idx_media_status ON media(status);
CREATE INDEX IF NOT EXISTS idx_media_cat    ON media(category);
"""


class Store:
    def __init__(self, db_path: Path):
        # check_same_thread=False → boleh dipakai lintas thread,
        # asalkan SEMUA akses dilindungi self._lock (di bawah).
        self.conn = sqlite3.connect(
            str(db_path),
            check_same_thread=False,
            timeout=30,
        )
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.conn.execute("PRAGMA busy_timeout=5000")
        self._lock = threading.RLock()
        with self._lock:
            self.conn.executescript(SCHEMA)
            self.conn.commit()

    def close(self):
        with self._lock:
            self.conn.close()

    # ---------- pages ----------
    def page_seen(self, url: str) -> bool:
        with self._lock:
            return self.conn.execute(
                "SELECT 1 FROM pages WHERE url=?", (url,)
            ).fetchone() is not None

    def mark_page(self, url: str) -> None:
        with self._lock:
            self.conn.execute(
                "INSERT OR IGNORE INTO pages(url) VALUES (?)", (url,)
            )
            self.conn.commit()

    # ---------- media ----------
    def add_media(self, url: str, category: str,
                  source_page: str | None = None) -> None:
        with self._lock:
            self.conn.execute(
                "INSERT OR IGNORE INTO media(url,category,source_page) "
                "VALUES (?,?,?)",
                (url, category, source_page),
            )
            self.conn.commit()

    def media_done(self, url: str) -> bool:
        with self._lock:
            return self.conn.execute(
                "SELECT 1 FROM media WHERE url=? AND status='done'", (url,)
            ).fetchone() is not None

    def sha_exists(self, sha: str) -> bool:
        with self._lock:
            return self.conn.execute(
                "SELECT 1 FROM media WHERE sha256=? AND status='done'", (sha,)
            ).fetchone() is not None

    def mark_done(self, url: str, local_path, sha256: str, size: int) -> None:
        with self._lock:
            self.conn.execute(
                "UPDATE media SET status='done', local_path=?, sha256=?, "
                "size=?, fetched_at=datetime('now') WHERE url=?",
                (str(local_path), sha256, size, url),
            )
            self.conn.commit()

    def mark_failed(self, url: str, err: str) -> None:
        with self._lock:
            self.conn.execute(
                "UPDATE media SET status='failed', error=? WHERE url=?",
                (err, url),
            )
            self.conn.commit()

    def pending_media(self):
        with self._lock:
            return self.conn.execute(
                "SELECT url, category FROM media WHERE status='pending'"
            ).fetchall()

    def retry_failed(self) -> int:
        with self._lock:
            cur = self.conn.execute(
                "UPDATE media SET status='pending', error=NULL "
                "WHERE status='failed'"
            )
            self.conn.commit()
            return cur.rowcount

    def summary(self) -> dict:
        with self._lock:
            return dict(self.conn.execute(
                "SELECT status, COUNT(*) FROM media GROUP BY status"
            ).fetchall())