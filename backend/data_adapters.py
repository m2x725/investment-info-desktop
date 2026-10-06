"""Optional AKShare/Futu adapters; quote permissions never imply trading permissions."""
from datetime import datetime
from zoneinfo import ZoneInfo
from .domain import dec
from .providers import ProviderError
from .storage import utcnow

def save_quote(store,sid,q):
    with store.connect() as db:
        db.execute('INSERT OR REPLACE INTO quotes VALUES(?,?,?,?,?,?)',(sid,q['price'],q.get('previous'),q['as_of'],q['source'],utcnow()))
        db.execute('INSERT OR REPLACE INTO quote_metadata VALUES(?,?,?,?,?,?,?)',(sid,q.get('quoted_at'),'Asia/Shanghai',q.get('delay_seconds'),q.get('market_state','unknown'),q.get('precision','date_only'),utcnow()))

def futu_quote(security):
    try:
        import futu
        ctx=futu.OpenQuoteContext(host='127.0.0.1',port=11111)
        try:
            code=security['exchange']+'.'+security['ticker']
            ret,rows=ctx.get_market_snapshot([code])
            if ret!=futu.RET_OK or rows.empty:raise ValueError('permission')
            r=rows.iloc[0];stamp=datetime.fromisoformat(r['update_time']).replace(tzinfo=ZoneInfo('Asia/Shanghai'))
            return {'price':str(dec(r['last_price'])),'previous':str(dec(r['prev_close_price'])),'as_of':stamp.date().isoformat(),'quoted_at':stamp.isoformat(),'source':'富途OpenD账户行情（延迟按账户权限核对）','precision':'second','delay_seconds':None,'market_state':'unknown'}
        finally:ctx.close()
    except Exception as exc:raise ProviderError('富途行情未就绪或权限不足，保留已有价格并使用公开备用源。') from exc

def collect_history(store,s):
    try:
        import akshare as ak
        frame=ak.stock_hk_hist(symbol=s['ticker'],period='daily',adjust='qfq') if s['exchange']=='HK' else ak.stock_zh_a_hist(symbol=s['ticker'],period='daily',adjust='qfq')
        with store.connect() as db:
            for _,r in frame.tail(800).iterrows():
                db.execute('INSERT OR REPLACE INTO price_history VALUES(?,?,?,?,?,?)',(s['id'],str(r['日期'])[:10],str(dec(r['收盘'])),s['currency'],'qfq','AKShare公开复权日线'))
        return {'count':len(frame)}
    except Exception as exc:raise ProviderError('历史行情接口未完成；未生成统计风险数据。') from exc

def _fetch_financial_history(s):
    import json
    import akshare as ak
    statements={}
    if s['exchange']=='HK':
        for name in ('资产负债表','利润表','现金流量表'):
            frame=ak.stock_financial_hk_report_em(stock=s['ticker'],symbol=name,indicator='年度')
            if not frame.empty and any(str(c).zfill(5)!=s['ticker'] for c in frame['SECURITY_CODE'].unique()):raise ValueError('identity')
            records=json.loads(frame.to_json(orient='records',date_format='iso',force_ascii=False))
            for r in records:
                period=str(r.get('REPORT_DATE',''))[:10]
                if not period:continue
                statements.setdefault(period,{}).setdefault(name,[]).append(r)
    else:
        for name,method in (('资产负债表',ak.stock_balance_sheet_by_report_em),('利润表',ak.stock_profit_sheet_by_report_em),('现金流量表',ak.stock_cash_flow_sheet_by_report_em)):
            frame=method(symbol=s['exchange']+s['ticker'])
            records=json.loads(frame.to_json(orient='records',date_format='iso',force_ascii=False))
            for r in records:
                if r.get('SECUCODE')!=s['ticker']+'.'+s['exchange']:continue
                period=str(r.get('REPORT_DATE',''))[:10]
                statements.setdefault(period,{}).setdefault(name,[]).append(r)
    return statements

def collect_financial_history(store,s):
    """Save raw statement rows with identity; unconfirmed historical currency stays unknown."""
    import json
    try:
        import os, subprocess, sys, tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory(prefix='wealth-history-') as directory:
            source=Path(directory)/'security.json';output=Path(directory)/'result.json'
            source.write_text(json.dumps(dict(s),ensure_ascii=False),encoding='utf-8')
            command=([sys.executable,'--financial-worker'] if getattr(sys,'frozen',False)
                     else [sys.executable,'-m','backend.history_worker'])
            options={'creationflags':subprocess.CREATE_NO_WINDOW} if sys.platform=='win32' else {}
            env={**os.environ,'OMP_NUM_THREADS':'2','OPENBLAS_NUM_THREADS':'2','MKL_NUM_THREADS':'2'}
            result=subprocess.run(command+[str(source),str(output)],timeout=45,env=env,
                                  stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,**options)
            if result.returncode or not output.exists():raise ValueError('history worker failed')
            statements=json.loads(output.read_text(encoding='utf-8'))
        for period in sorted(statements,reverse=True)[:4]:
            payload={'statements':statements[period],'currency':'UNKNOWN' if s['exchange']=='HK' else 'CNY','unit':'原接口金额字段；港股单位待与报告核对','verification':'aggregated_unreconciled'}
            store.execute('INSERT OR REPLACE INTO financial_history VALUES(?,?,?,?)',(s['id'],period,json.dumps(payload,ensure_ascii=False),'AKShare／东方财富财务报表'))
        for period in sorted(statements,reverse=True)[:4]:
            content=json.dumps({'period':period,'statements':statements[period],'currency':'UNKNOWN' if s['exchange']=='HK' else 'CNY','unit':'接口原字段，单位及币种应与官方报告核对'},ensure_ascii=False)
            store.execute('INSERT INTO evidence(security_id,title,url,published_at,content,kind,verification,fetched_at,report_period) VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(security_id,url,title) DO UPDATE SET content=excluded.content,fetched_at=excluded.fetched_at',(s['id'],period+'历史财务表','https://data.eastmoney.com/',period,content,'financial','aggregated_unreconciled',utcnow(),period))
        return len(statements)
    except Exception as exc:raise ProviderError('历史财务表接口未完成；继续以官方原文研究，并标明结构化指标缺口。') from exc

def collect_fx_history(store,client):
    from datetime import timedelta,timezone
    end=datetime.now(timezone.utc).date();start=end-timedelta(days=1600)
    r=client.get('https://api.frankfurter.app/'+str(start)+'..'+str(end),params={'from':'HKD','to':'CNY'})
    r.raise_for_status()
    with store.connect() as db:
        db.execute('CREATE TABLE IF NOT EXISTS fx_history(day TEXT PRIMARY KEY,rate TEXT NOT NULL,source TEXT NOT NULL)')
        for day,values in r.json().get('rates',{}).items():
            rate=dec(values['CNY'])
            if rate>0:db.execute('INSERT OR REPLACE INTO fx_history VALUES(?,?,?)',(day,str(rate),'ECB参考汇率／Frankfurter；非港股通结算汇率'))
