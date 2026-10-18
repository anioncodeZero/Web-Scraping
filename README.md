<div align="center">

# 🕷️ Data Miner

**Crawl a website to exhaustion. Harvest every piece of media. Catch accidentally exposed secrets.**

[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](#-license)
[![Status](https://img.shields.io/badge/Status-Active-success.svg)]()
[![PRs](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)]()

*Media harvester + sensitive file detector with resume, dedup, and retry.*

</div>

---

> [!WARNING]
> **Authorized use only.** Use this tool **only** on sites you own or have **written permission** to test. Accessing sensitive files on servers you don't own is a criminal offense in most jurisdictions (**UU ITE Art. 30 & 46, UU PDP, CFAA, GDPR**, etc.) — even if the files are "publicly accessible."
>
> Found a leak on someone else's site? **Don't download it. Don't share it.** Report it via *responsible disclosure* (`security.txt` or the site's security email).
>
> The author is **not responsible** for misuse.

---

## 📖 Table of Contents

- [✨ Features](#-features)
- [🧠 How It Works](#-how-it-works)
- [📦 Installation](#-installation)
- [🚀 Usage](#-usage)
- [🎛️ CLI Reference](#️-cli-reference)
- [📁 Output Structure](#-output-structure)
- [🔍 Sensitive File Detection](#-sensitive-file-detection)
- [🛡️ Safety & Performance](#️-safety--performance)
- [🩺 Troubleshooting](#-troubleshooting)
- [🗺️ Roadmap](#️-roadmap)
- [⚖️ License](#️-license)

---

## ✨ Features

| | |
|---|---|
| 🕸️ **Full BFS crawl** | Walks every internal link until exhausted, not just sitemaps. |
| 🗺️ **Sitemap seeding** | Reads `robots.txt` → `sitemap.xml` (incl. index & `.gz`) for richer starting points. |
| 🖼️ **8 media extractors** | `<img>`, `<picture>`, `<video>/<audio>`, `<link>`, OG/Twitter meta, CSS `url()`, JSON-LD, `<iframe>` embeds. |
| 🧹 **Junk URL filter** | Drops trackers (`?utm_*`, `?fbclid`), non-content paths (`/feed`, `/cart`), and faceted queries. |
| 🚨 **Passive secret detection** | `<a href="/backup.zip">` is auto-classified as `sensitive`. |
| 🎯 **Active secret probing** | Wordlist-driven, with **content validation** (magic bytes, SQL markers, `.env` format) to avoid soft-404 false positives. |
| 🧬 **SHA-256 dedup** | Logos and banners appearing on 200 pages are stored only once. |
| ⏯️ **Resume & retry** | All state lives in SQLite. `Ctrl+C` is safe — re-run to resume. |
| ⚡ **Parallel downloads** | Thread pool with backoff and per-file min/max size limits. |
| 📂 **Structured output** | `images/`, `videos/`, `sensitive/`, `others/` per domain. |

---

## 🧠 How It Works

```
┌─────────────────┐
│ 1. Sitemap Seed │  robots.txt → sitemap.xml (+ index + .gz)
└────────┬────────┘
         ▼
┌─────────────────┐
│ 2. BFS Crawl    │  fetch → extract media → extract links
│                 │  → classify (media | sensitive | next page)
└────────┬────────┘
         ▼
┌─────────────────┐
│ 3. Probe        │  wordlist → validate content → reject soft-404
│    (optional)   │  only store real hits as 'sensitive'
└────────┬────────┘
         ▼
┌─────────────────┐
│ 4. Download     │  ThreadPool → stream → sha256 → dedup → save
└────────┬────────┘
         ▼
┌─────────────────┐
│ 5. Summary      │  counts per status & category
└─────────────────┘
```

Every stage is **idempotent** — re-running produces the same set thanks to URL + SHA-256 dedup.

---

## 📦 Installation

**Requires:** Python **3.10+**

```bash
git clone https://github.com/<your-username>/data-miner.git
cd data-miner

python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate

pip install -r requirements.txt
```

**`requirements.txt`**
```txt
requests>=2.31.0
beautifulsoup4>=4.12.0
tqdm>=4.66.0
```

---

## 🚀 Usage

```bash
# Crawl + download everything
python main.py https://your-site.com

# Include active sensitive-file probing
python main.py https://your-site.com --probe-sensitive

# Quick audit (no long crawl, no downloads)
python main.py https://your-site.com --probe-sensitive --max-depth 0 --no-sitemap --no-download

# Resume / retry previously failed items
python main.py https://your-site.com --retry-failed
```

---

## 🎛️ CLI Reference

| Flag | Default | Description |
|------|---------|-------------|
| `url` | — | Target URL (required). `http://` is added automatically if missing. |
| `--max-depth N` | until exhausted | BFS depth. `None` = full crawl, `0` = start URL only. |
| `--max-pages N` | `100000` | Page count safety net. |
| `--no-sitemap` | off | Skip sitemap seeding. |
| `--strict-sitemap` | off | Crawl only URLs from the sitemap, ignore `<a href>`. |
| `--no-download` | off | Crawl & probe only — skip file downloads. |
| `--workers N` | `8` | Parallel download/probe threads. |
| `--min-size BYTES` | `2048` | Minimum file size (auto-bypassed for `sensitive`). |
| `--max-size BYTES` | `524288000` | Maximum file size (500 MB default). |
| `--retry-failed` | off | Reset `failed` items → `pending` before the run. |
| `--probe-sensitive` | off | Enable wordlist-based sensitive-file probing. |
| `--wordlist PATH` | `wordlists/sensitive.txt` | Custom wordlist for probing. |

<details>
<summary><b>💡 Example combinations</b></summary>

```bash
# Heavy scan, 16 workers, 50 MB cap
python main.py https://your-site.com --probe-sensitive --workers 16 --max-size 52428800

# Inventory only (crawl without downloading)
python main.py https://your-site.com --no-download

# Resume after Ctrl+C
python main.py https://your-site.com

# Retry failed downloads only
python main.py https://your-site.com --retry-failed

# Shallow crawl for a quick test
python main.py https://your-site.com --max-depth 2 --no-sitemap

# Use a SecLists wordlist
python main.py https://your-site.com --probe-sensitive \
    --wordlist /path/to/SecLists/Discovery/Web-Content/common.txt
```

</details>

---

## 📁 Output Structure

```
output/
└── your-site.com/
    ├── images/       # .jpg .png .gif .webp .svg .avif ...
    ├── videos/       # .mp4 .webm .mkv .mov .m3u8 ...
    ├── sensitive/    # SQL dumps, .env, backup.zip, id_rsa, ...
    ├── others/       # audio, pdf, and non-categorized files
    └── crawl.db      # SQLite manifest (pages + media)
```

<details>
<summary><b>🗄️ SQLite schema</b></summary>

```sql
CREATE TABLE pages (
    url         TEXT PRIMARY KEY,
    fetched_at  TEXT DEFAULT (datetime('now'))
);

CREATE TABLE media (
    url         TEXT PRIMARY KEY,
    category    TEXT NOT NULL,          -- images|videos|sensitive|others
    source_page TEXT,                   -- page that surfaced this URL
    local_path  TEXT,                   -- local path after download
    sha256      TEXT,                   -- for dedup
    size        INTEGER,
    status      TEXT DEFAULT 'pending', -- pending|done|failed
    error       TEXT,
    fetched_at  TEXT
);
```

</details>

<details>
<summary><b>🔎 Useful queries</b></summary>

```bash
# Status summary
sqlite3 output/your-site.com/crawl.db \
  "SELECT status, COUNT(*) FROM media GROUP BY status;"

# Per category
sqlite3 output/your-site.com/crawl.db \
  "SELECT category, status, COUNT(*) FROM media GROUP BY 1,2;"

# All downloaded sensitive files
sqlite3 output/your-site.com/crawl.db \
  "SELECT url, size FROM media
   WHERE category='sensitive' AND status='done';"

# Largest files
sqlite3 output/your-site.com/crawl.db \
  "SELECT url, size FROM media ORDER BY size DESC LIMIT 20;"
```

</details>

---

## 🔍 Sensitive File Detection

### Passive (during crawl)
Links like `<a href="/backup.zip">` or `url(../db.sql)` in CSS are auto-classified as `sensitive` — recorded but not crawled as pages.

### Active (wordlist probing)
Every candidate must pass content validation to avoid false positives:

- **Magic bytes** — `SQLite format 3\0`, `PK\x03\x04` (zip), `\x1f\x8b` (gzip), `ustar` (tar).
- **SQL markers** — `CREATE TABLE`, `INSERT INTO`, `-- MySQL`, etc.
- **`.env` format** — at least 3 `KEY=value` lines and not HTML.
- **Soft-404 rejection** — fetches 2 random URLs first, hashes them, then rejects responses with matching hashes.

### What gets caught

| Category | Examples |
|----------|----------|
| **SQL dumps** | `backup.sql`, `db.sql.gz`, `dump.zip`, `*.sqlite3` |
| **Config** | `.env*`, `wp-config.php.bak`, `config.json`, `secrets.yml` |
| **Backups** | `backup.zip`, `site.tar.gz`, `db.rar` |
| **Private keys** | `id_rsa`, `*.pem`, `*.key`, `*.p12` |
| **VCS & OS** | `.git/config`, `.svn/entries`, `.DS_Store`, `.htaccess` |
| **Credentials** | `credentials.json`, `secrets.json` |
| **Logs** | `error.log`, `debug.log`, `access.log` |

### Custom wordlist
`wordlists/sensitive.txt` — one path per line, `#` for comments. Any SecLists wordlist works too.

---

## 🛡️ Safety & Performance

- **`REQUEST_DELAY = 0.4s`** — throttles requests. Raise to `1.0+` for sensitive targets.
- **SQLite WAL + `busy_timeout=5000`** — multi-thread safe.
- **`--workers`** — default `8`. Don't exceed ~32 unless the target is known to be robust; more workers = higher ban risk.
- **`Ctrl+C`** — safe. State remains consistent in `crawl.db`; re-run to resume.

---

## 🩺 Troubleshooting

| Error | Cause | Fix |
|-------|-------|-----|
| `ModuleNotFoundError` | venv not activated | `source venv/bin/activate` / `venv\Scripts\activate` |
| `database is locked` | Another `main.py` holds `crawl.db` | Close the other instance, re-run |
| `ImportError: MAX_FILE_SIZE` | Old `config.py` | Add `MAX_FILE_SIZE = 500 * 1024 * 1024` |
| `requests.exceptions.SSLError` | Broken target certificate | Set `VERIFY_SSL = False` in `config.py` (own targets only) |
| Slow downloads | Delay + small worker pool, or slow server | Increase `--workers`, lower `REQUEST_DELAY` |
| Probes all return 200 but nothing saved | Soft-404 | Normal — validator rejects error pages |

---

## 🗺️ Roadmap

- [ ] HLS / `.m3u8` support via `yt-dlp`
- [ ] JS rendering mode via Playwright (`--render-js`)
- [ ] Export manifest to JSON / CSV
- [ ] HTTP Range resume for large files
- [ ] Optional `--respect-robots` filter

---

## ⚖️ License

MIT — see [`LICENSE`](LICENSE).

Provided **as-is** for educational and internal-audit purposes. **You are fully responsible** for legal and ethical compliance. See the **Warning** section at the top.

---

<div align="center">

**Built for defenders, not attackers. Scan responsibly. 🛡️**

</div>
