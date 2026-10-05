"""Additive, backed-up migrations; legacy tables and reports remain readable."""
def migrate(store):
    with store.connect() as db:
        version=db.execute('PRAGMA user_version').fetchone()[0]
    if version>=2:
        with store.connect() as db:db.execute("CREATE TABLE IF NOT EXISTS fx_history(day TEXT PRIMARY KEY,rate TEXT NOT NULL,source TEXT NOT NULL)")
        return
    if getattr(store,"existed_before_init",True):store.backup()
    with store.connect() as db:
        db.executescript('''
        CREATE TABLE IF NOT EXISTS accounts(id TEXT PRIMARY KEY,name TEXT NOT NULL,mode TEXT NOT NULL DEFAULT 'snapshot',history_complete INTEGER NOT NULL DEFAULT 0);
        INSERT OR IGNORE INTO accounts VALUES('eastmoney','东方财富港股通','snapshot',0);
        CREATE TABLE IF NOT EXISTS holding_snapshots(account_id TEXT NOT NULL,security_id TEXT NOT NULL,quantity TEXT NOT NULL,broker_cost TEXT,cost_currency TEXT,broker_value TEXT,broker_gain TEXT,as_of TEXT,PRIMARY KEY(account_id,security_id));
        CREATE TABLE IF NOT EXISTS imports(id TEXT PRIMARY KEY,filename TEXT NOT NULL,fingerprint TEXT NOT NULL,payload TEXT NOT NULL,status TEXT NOT NULL,created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS ledger(id INTEGER PRIMARY KEY,account_id TEXT NOT NULL,security_id TEXT,kind TEXT NOT NULL,day TEXT NOT NULL,quantity TEXT NOT NULL,amount_cny TEXT NOT NULL,fee_cny TEXT NOT NULL,broker_ref TEXT,dedupe_key TEXT NOT NULL,payload TEXT NOT NULL,UNIQUE(account_id,dedupe_key));
        CREATE TABLE IF NOT EXISTS quote_metadata(security_id TEXT PRIMARY KEY,quoted_at TEXT,timezone TEXT NOT NULL,delay_seconds INTEGER,market_state TEXT NOT NULL,precision TEXT NOT NULL,fetched_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS daily_values(account_id TEXT NOT NULL,day TEXT NOT NULL,value_cny TEXT NOT NULL,flows_cny TEXT NOT NULL,PRIMARY KEY(account_id,day));
        CREATE TABLE IF NOT EXISTS price_history(security_id TEXT NOT NULL,day TEXT NOT NULL,close TEXT NOT NULL,currency TEXT NOT NULL,adjustment TEXT NOT NULL,source TEXT NOT NULL,PRIMARY KEY(security_id,day,adjustment));
        CREATE TABLE IF NOT EXISTS research_runs(id TEXT PRIMARY KEY,security_id TEXT,kind TEXT NOT NULL,snapshot TEXT NOT NULL,status TEXT NOT NULL,created_at TEXT NOT NULL,report_id INTEGER);
        CREATE TABLE IF NOT EXISTS research_sections(run_id TEXT NOT NULL,section TEXT NOT NULL,payload TEXT NOT NULL,status TEXT NOT NULL,PRIMARY KEY(run_id,section));
        CREATE TABLE IF NOT EXISTS source_chunks(evidence_id INTEGER NOT NULL,ordinal INTEGER NOT NULL,content TEXT NOT NULL,quality TEXT NOT NULL,PRIMARY KEY(evidence_id,ordinal));
        CREATE TABLE IF NOT EXISTS tool_cache(cache_key TEXT PRIMARY KEY,payload TEXT NOT NULL,created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS fx_history(day TEXT PRIMARY KEY,rate TEXT NOT NULL,source TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS financial_history(security_id TEXT NOT NULL,period TEXT NOT NULL,payload TEXT NOT NULL,source TEXT NOT NULL,PRIMARY KEY(security_id,period));
        PRAGMA user_version=2;
        ''')
