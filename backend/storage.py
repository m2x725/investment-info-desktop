"""SQLite persistence. Financial values are decimal strings; credentials never enter SQLite."""
import json
import os
import sqlite3
import sys
import threading
import re
from contextlib import contextmanager, closing
from pathlib import Path
from datetime import datetime, timezone


def utcnow():
    return datetime.now(timezone.utc).isoformat()


def default_data_dir():
    if os.getenv("WEALTH_DATA_DIR"):
        return Path(os.environ["WEALTH_DATA_DIR"]).expanduser()
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA", Path.home())) / "RetirementWealth"
    if sys.platform == "darwin" and getattr(sys, "frozen", False):
        return Path.home() / "Library" / "Application Support" / "InvestmentInfo"
    return Path.home() / ".retirement-wealth"


DEFAULTS = {
    "pricing_mode": "auto", "model": "kimi-k2.6", "monthly_limit": "200", "input_price": "0",
    "output_price": "0", "prices_confirmed": False, "daily_time": "08:00",
    "scheduler_enabled": True, "scheduler_paused": False, "push_enabled": False, "auto_research": False, "event_research": False,
    "concentration": "15", "move_threshold": "5", "weekly_research_limit": 2, "other_service_cost": "0", "import_folder": "", "online_research": True,
}


class Store:
    def __init__(self, directory=None):
        self.write_context = threading.local()
        self.directory = Path(directory) if directory else default_data_dir()
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / "portfolio.db"
        self.existed_before_init=self.path.exists()
        if self.path.exists():
            with self.connect() as db:
                tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if "positions" in tables and "valuation_inputs" not in tables:
                # Online backup succeeds before extending an existing database schema.
                self.backup()
        with self.connect() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS securities(
              id TEXT PRIMARY KEY, exchange TEXT NOT NULL, ticker TEXT NOT NULL,
              name TEXT NOT NULL, currency TEXT NOT NULL, industry TEXT DEFAULT '');
            CREATE TABLE IF NOT EXISTS positions(
              security_id TEXT PRIMARY KEY REFERENCES securities(id), quantity TEXT NOT NULL,
              cost TEXT NOT NULL, note TEXT DEFAULT '', updated_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS watchlist(
              security_id TEXT PRIMARY KEY REFERENCES securities(id));
            CREATE TABLE IF NOT EXISTS cash(currency TEXT PRIMARY KEY, amount TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS quotes(
              security_id TEXT PRIMARY KEY REFERENCES securities(id), price TEXT NOT NULL,
              previous TEXT, as_of TEXT NOT NULL, source TEXT NOT NULL, fetched_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS fx(currency TEXT PRIMARY KEY, rate TEXT NOT NULL,
              as_of TEXT NOT NULL, source TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS evidence(
              id INTEGER PRIMARY KEY, security_id TEXT REFERENCES securities(id),
              title TEXT NOT NULL, url TEXT NOT NULL, published_at TEXT NOT NULL,
              report_period TEXT DEFAULT '', locator TEXT DEFAULT '', content TEXT NOT NULL,
              kind TEXT NOT NULL, verification TEXT NOT NULL, fetched_at TEXT NOT NULL,
              UNIQUE(security_id,url,title));
            CREATE TABLE IF NOT EXISTS reports(
              id INTEGER PRIMARY KEY, security_id TEXT, kind TEXT NOT NULL, payload TEXT NOT NULL,
              evidence_ids TEXT NOT NULL, created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS research_outputs(
              id INTEGER PRIMARY KEY, security_id TEXT, stage TEXT NOT NULL,
              payload TEXT NOT NULL, status TEXT NOT NULL, error TEXT NOT NULL, created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS valuation_inputs(
              security_id TEXT PRIMARY KEY REFERENCES securities(id),
              evidence_id INTEGER NOT NULL REFERENCES evidence(id),
              currency TEXT NOT NULL, earnings_basis TEXT NOT NULL, report_period TEXT NOT NULL,
              as_of TEXT NOT NULL, eps TEXT, book_per_share TEXT, dividend_per_share TEXT,
              locator TEXT NOT NULL, updated_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS jobs(
              id TEXT PRIMARY KEY, kind TEXT NOT NULL, status TEXT NOT NULL,
              message TEXT NOT NULL, result_id INTEGER, created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS expenses(
              id INTEGER PRIMARY KEY, month TEXT NOT NULL, status TEXT NOT NULL,
              amount TEXT NOT NULL, reserved TEXT NOT NULL, created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS notifications(
              id INTEGER PRIMARY KEY, dedupe_key TEXT UNIQUE NOT NULL, day TEXT NOT NULL,
              status TEXT NOT NULL, title TEXT NOT NULL, content TEXT NOT NULL,
              message TEXT NOT NULL, created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS events(
              id INTEGER PRIMARY KEY, kind TEXT NOT NULL, message TEXT NOT NULL, created_at TEXT NOT NULL);
            """)
            for key, val in DEFAULTS.items():
                db.execute("INSERT OR IGNORE INTO settings VALUES(?,?)", (key, json.dumps(val)))
            # A stopped process cannot finish its previous jobs. Keep reserved spend conservatively.
            db.execute("UPDATE jobs SET status='failed',message='上次运行中断，请重新开始。' WHERE status IN ('queued','running')")
            db.execute("UPDATE jobs SET status='cancelled',message='已取消，本次报告与草稿未保存',result_id=NULL WHERE status='cancelling'")
            db.execute("UPDATE notifications SET status='unknown',message='上次运行中断，收件结果不明；请在微信核对。' WHERE status='sending'")

        with self.connect() as db:
            needs_progress = 'progress' not in {r['name'] for r in db.execute('PRAGMA table_info(jobs)')}
        if needs_progress:
            if self.existed_before_init:self.backup()
            self.execute('ALTER TABLE jobs ADD COLUMN progress INTEGER NOT NULL DEFAULT 0')

        from .upgrade_schema import migrate
        migrate(self)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def rows(self, sql, args=()):
        with self.connect() as db:
            return [dict(row) for row in db.execute(sql, args).fetchall()]

    def execute(self, sql, args=()):
        control = getattr(self.write_context, 'control', None)
        if control and re.search(r'\b(?:INTO|UPDATE|FROM)\s+(?:reports|research_outputs|research_runs|research_sections)\b', sql, re.I):
            with control.lock:
                control.check()
                with self.connect() as db:
                    rowid = db.execute(sql, args).lastrowid
                control.record(sql, args, rowid)
                return rowid
        with self.connect() as db:
            return db.execute(sql, args).lastrowid

    def settings(self):
        from .model_profile import resolve_profile
        return resolve_profile({r["key"]: json.loads(r["value"]) for r in self.rows("SELECT * FROM settings")})

    def save_settings(self, values):
        with self.connect() as db:
            for key, val in values.items():
                db.execute("INSERT OR REPLACE INTO settings VALUES(?,?)", (key, json.dumps(val)))

    def event(self, kind, message):
        self.execute("INSERT INTO events(kind,message,created_at) VALUES(?,?,?)", (kind, message, utcnow()))

    def add_security(self, item):
        sid = f'{item["exchange"]}:{item["ticker"]}'
        self.execute(
            "INSERT INTO securities(id,exchange,ticker,name,currency) VALUES(?,?,?,?,?) "
            "ON CONFLICT(id) DO UPDATE SET name=excluded.name",
            (sid, item["exchange"], item["ticker"], item["name"], "HKD" if item["exchange"] == "HK" else "CNY"))
        return sid

    def followed(self):
        return self.rows("SELECT DISTINCT s.* FROM securities s WHERE id IN "
                         "(SELECT security_id FROM positions UNION SELECT security_id FROM watchlist) ORDER BY name")

    def backup(self):
        folder = self.directory / "backups"
        folder.mkdir(exist_ok=True)
        target = folder / f'portfolio-{datetime.now().strftime("%Y%m%d-%H%M%S-%f")}.db'
        with self.connect() as db, closing(sqlite3.connect(target)) as dest:
            db.backup(dest)
        return target
