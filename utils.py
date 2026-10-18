import os
import re
from urllib.parse import urlparse

IMAGE_EXTS = {'.jpg','.jpeg','.png','.gif','.bmp','.webp','.svg',
              '.tiff','.tif','.ico','.avif','.heic'}
VIDEO_EXTS = {'.mp4','.webm','.avi','.mov','.mkv','.flv','.wmv',
              '.m4v','.3gp','.mpeg','.mpg','.ogv','.ts','.m2ts','.mts'}
AUDIO_EXTS = {'.mp3','.wav','.ogg','.flac','.aac','.m4a','.wma'}

# --- SENSITIVE ---
SENSITIVE_NAMES = {
    '.env', '.env.local', '.env.bak', '.env.old', '.env.backup',
    '.env.dev', '.env.development', '.env.prod', '.env.production',
    '.env.staging', '.env.example', '.env.sample',
    '.htaccess', '.htpasswd', '.ds_store', '.gitignore',
    'web.config', 'wp-config.php', 'config.php', 'configuration.php',
    'dockerfile', 'docker-compose.yml', 'docker-compose.yaml',
    'id_rsa', 'id_dsa', 'id_ecdsa', 'id_ed25519',
    'credentials.json', 'secrets.json', 'secrets.yml', 'secrets.yaml',
    'local_settings.py', 'settings.py',
}
SENSITIVE_EXTS = {
    '.sql', '.sqlite', '.sqlite3', '.db', '.mdb', '.accdb',
    '.bak', '.old', '.backup', '.orig', '.save', '.swp', '.swo',
    '.log', '.dump', '.dmp',
    '.pem', '.key', '.p12', '.pfx', '.jks', '.keystore',
    '.conf', '.cfg', '.ini',
}
SENSITIVE_ARCHIVE_EXTS = {'.zip','.tar','.gz','.tgz','.rar','.7z','.bz2','.xz'}
SENSITIVE_ARCHIVE_KEYWORDS = {
    'backup','db','database','dump','sql','mysql','postgres',
    'site','www','wp','wordpress','admin','export','data','prod',
    'prod','production','staging',
}
SENSITIVE_PATH_RE = re.compile(
    r'(^|/)(\.git|\.svn|\.hg|\.bzr|\.env\.|backups?|database|dump)(/|$)',
    re.I,
)


def get_domain(url): return urlparse(url).netloc.replace(':', '_') or 'unknown'

def sanitize_filename(name):
    name = re.sub(r'[^\w\-_.]', '_', name)
    if len(name) > 200:
        stem, ext = os.path.splitext(name)
        name = stem[:200 - len(ext)] + ext
    return name or 'file'

def normalize_url(url): return urlparse(url)._replace(fragment='').geturl()

def is_internal(url, base_domain): return urlparse(url).netloc == base_domain


def is_sensitive(url: str, content_type: str | None = None) -> bool:
    p = urlparse(url)
    name = os.path.basename(p.path).lower()
    ext = os.path.splitext(p.path)[1].lower()

    if name in SENSITIVE_NAMES:
        return True
    if ext in SENSITIVE_EXTS:
        return True
    if SENSITIVE_PATH_RE.search(p.path):
        return True
    if ext in SENSITIVE_ARCHIVE_EXTS:
        stem = os.path.splitext(p.path)[0].lower()
        if any(kw in stem for kw in SENSITIVE_ARCHIVE_KEYWORDS):
            return True
    if content_type:
        ct = content_type.lower()
        if ct in ('application/x-sql', 'application/sql',
                  'application/x-sqlite3', 'application/x-httpd-php',
                  'application/x-msdownload'):
            return True
    return False


def categorize(url: str, content_type: str | None = None) -> str:
    if is_sensitive(url, content_type):
        return 'sensitive'
    if content_type:
        ct = content_type.lower()
        if ct.startswith('image/'): return 'images'
        if ct.startswith('video/'): return 'videos'
        if ct.startswith('audio/'): return 'others'
    ext = os.path.splitext(urlparse(url).path)[1].lower()
    if ext in IMAGE_EXTS: return 'images'
    if ext in VIDEO_EXTS: return 'videos'
    return 'others'