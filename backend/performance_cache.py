"""Versioned expiring caches. Old cache records without metadata are not trusted."""
import hashlib,json
from datetime import datetime,timedelta,timezone
from .storage import utcnow
VERSION='responsive-v1'

def migrate_performance(store):
    with store.connect() as db:
        needed='metadata' not in {r['name'] for r in db.execute('PRAGMA table_info(jobs)')}
        exists=db.execute("SELECT 1 FROM sqlite_master WHERE name='performance_cache'").fetchone()
    if needed or not exists:
        if store.existed_before_init:store.backup()
        with store.connect() as db:
            if needed:db.execute("ALTER TABLE jobs ADD COLUMN metadata TEXT NOT NULL DEFAULT '{}'")
            db.execute('CREATE TABLE IF NOT EXISTS performance_cache(cache_key TEXT PRIMARY KEY,kind TEXT NOT NULL,payload TEXT NOT NULL,created_at TEXT NOT NULL,expires_at TEXT NOT NULL,version TEXT NOT NULL)')
            db.execute('PRAGMA user_version=3')

def source_identity(sid, document):
    return [sid,canonical_url(document['url']),document['title'],document['published_at'],
            {key:document.get(key) for key in ('etag','last_modified','updated_at','revision')}]

def canonical_url(url):
    from urllib.parse import urlsplit,urlunsplit,parse_qsl,urlencode
    parts=urlsplit(url)
    return urlunsplit((parts.scheme.lower(),parts.netloc.lower(),parts.path,urlencode(sorted(parse_qsl(parts.query,keep_blank_values=True))),''))

def key(kind,identity):
    return hashlib.sha256(json.dumps([VERSION,kind,identity],ensure_ascii=False,sort_keys=True).encode()).hexdigest()

def get(store,kind,identity):
    rows=store.rows('SELECT * FROM performance_cache WHERE cache_key=? AND version=? AND expires_at>?',(key(kind,identity),VERSION,utcnow()))
    return json.loads(rows[0]['payload']) if rows else None

def put(store,kind,identity,payload,seconds):
    expiry=(datetime.now(timezone.utc)+timedelta(seconds=seconds)).isoformat()
    store.execute('INSERT OR REPLACE INTO performance_cache VALUES(?,?,?,?,?,?)',(key(kind,identity),kind,json.dumps(payload,ensure_ascii=False),utcnow(),expiry,VERSION))
