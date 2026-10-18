from pathlib import Path

BASE_OUTPUT_DIR   = Path("output")
USER_AGENT        = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)
REQUEST_TIMEOUT   = 20
REQUEST_DELAY     = 0.4
VERIFY_SSL        = True

MAX_DEPTH         = None          # None = sampai buntu
MAX_PAGES         = 100_000

DEFAULT_WORKERS   = 8
MIN_FILE_SIZE     = 2048          # skip favicon/tracker < 2KB
MAX_FILE_SIZE = 500 * 1024 * 1024   # 500 MB — batas keras per file
MAX_RETRIES       = 3
