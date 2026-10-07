import json
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from datetime import datetime
from urllib.parse import urlparse
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware
from .storage import Store, utcnow
from .accounting import overview,activate
from .imports import preview,commit
from .research_engine import ResearchEngine
from .domain import Security, Position, Cash, ManualQuote, Fx, Evidence, Settings, Secrets, ResearchRequest, Followup, ValuationInput, portfolio, valuation
from .providers import Credentials, Market, Kimi, Push, ProviderError
from .services import Services, beijing_now
from .news import news_feed,refresh_news


def create_app(data_dir=None, scheduler=True):
    store = Store(data_dir)
    credentials = Credentials()
    services = Services(store, Market(), Kimi(credentials), Push(credentials), credentials)
    csrf = secrets.token_urlsafe(32)

    @asynccontextmanager
    async def lifespan(app):
        if scheduler:
            services.start_scheduler()
        yield
        services.close()

    app = FastAPI(title="投资信息台", lifespan=lifespan, docs_url=None, redoc_url=None)
    app.state.store, app.state.services = store, services
    app.state.credentials, app.state.csrf = credentials, csrf
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "testserver"])

    @app.middleware("http")
    async def local_boundary(request: Request, call_next):
        origin = request.headers.get("origin")
        if origin and urlparse(origin).netloc != request.headers.get("host"):
            return JSONResponse({"detail": "只允许从本机应用操作。"}, status_code=403)
        if request.url.path.startswith("/api/") and request.method not in ("GET", "HEAD"):
            if not secrets.compare_digest(request.headers.get("X-App-Token", ""), csrf):
                return JSONResponse({"detail": "页面已过期，请刷新后重试。"}, status_code=403)
            try:
                size = int(request.headers.get("content-length", "0") or 0)
            except ValueError:
                return JSONResponse({"detail": "请求长度无效。"}, status_code=400)
            if size > (15000000 if request.url.path=='/api/imports/preview' else 400000):
                return JSONResponse({"detail": "资料过大，请减少原文章节。"}, status_code=413)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = "default-src 'self'; connect-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        if (request.url.path.startswith("/api/") or
                response.headers.get("content-type", "").startswith("text/html")):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(ProviderError)
    async def provider_error(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=409)

    def has_security(sid):
        if not store.rows("SELECT id FROM securities WHERE id=?", (sid,)):
            raise HTTPException(404, "未找到证券，请先加入自选或持仓。")

    def check_limit(item):
        sid = f'{item.exchange}:{item.ticker}'
        followed = store.followed()
        if len(followed) >= 30 and sid not in [s["id"] for s in followed]:
            raise HTTPException(409, "首版最多关注 30 只证券，请先移除不再关注的公司。")

    @app.get("/api/bootstrap")
    def bootstrap():
        latest = store.rows("SELECT * FROM reports WHERE kind='brief' ORDER BY id DESC LIMIT 1")
        reports = store.rows("SELECT id,security_id,kind,payload,created_at FROM reports "
                            "WHERE kind NOT IN ('brief','news_analysis') ORDER BY id DESC LIMIT 20")
        for row in reports:
            row["payload"] = json.loads(row["payload"])
        return {"csrf": csrf, "active_jobs":store.rows("SELECT id,kind,message FROM jobs WHERE status IN ('queued','running','cancelling') AND kind NOT IN ('background_update','scheduled_brief') ORDER BY created_at"), "portfolio": overview(store), "followed": store.followed(),
                "watchlist": store.rows("SELECT s.* FROM watchlist w JOIN securities s ON s.id=w.security_id"),
                "alerts": services.alerts(), "news":news_feed(store), "brief": {**latest[0], "payload": json.loads(latest[0]["payload"])} if latest else None,
                "reports": reports, "settings": store.settings(), "budget": services.budget(),
                "connections": {"kimi": bool(credentials.get("kimi")), "push": bool(credentials.get("push")),
                                "secure_persistence": credentials.persisted},
                "events": store.rows("SELECT * FROM events ORDER BY id DESC LIMIT 12"),
                "notifications": store.rows("SELECT id,title,status,message,created_at FROM notifications ORDER BY id DESC LIMIT 8")}

    @app.post('/api/news/analyze')
    def analyze_news(body: dict):
        news_id=body.get('news_id')
        if not isinstance(news_id,str) or not 1<=len(news_id)<=2048:raise HTTPException(422,'新闻编号无效。')
        return {'job_id':services.submit('news_analysis',lambda:services.analyze_news(news_id))}

    @app.post('/api/news/refresh')
    def update_news():
        return {'job_id':services.submit('news',lambda:refresh_news(store,services.market.client))}

    @app.post('/api/imports/preview')
    def preview_import(body:dict):
        return preview(store,body)

    @app.get('/api/imports')
    def list_imports():
        return store.rows('SELECT id,filename,status,created_at FROM imports ORDER BY created_at DESC LIMIT 30')

    @app.get('/api/imports/{iid}')
    def get_import(iid:str):
        rows=store.rows('SELECT payload,status FROM imports WHERE id=?',(iid,))
        if not rows:raise HTTPException(404,'导入不存在')
        return {**json.loads(rows[0]['payload']),'status':rows[0]['status']}

    @app.post('/api/imports/{iid}/commit')
    def commit_import(iid:str,body:dict):
        return commit(store,iid,body)

    @app.get('/api/portfolio/overview')
    def portfolio_overview():
        return overview(store)

    @app.post('/api/portfolio/activate-ledger')
    def activate_ledger(body:dict):
        return activate(store,body.get('history_complete') is True)

    @app.post('/api/portfolio/research')
    def portfolio_research():
        if not overview(store)['positions']:raise HTTPException(409,'请先导入持仓。')
        return {'job_id':services.submit('portfolio',services.portfolio_research)}

    @app.post('/api/quotes/refresh')
    def quote_refresh():
        return {'job_id':services.submit('quotes',services.refresh_quotes)}

    @app.get('/api/research/runs')
    def research_runs():
        return store.rows('SELECT id,security_id,kind,status,created_at,report_id FROM research_runs ORDER BY created_at DESC LIMIT 30')

    @app.post('/api/research/runs/{run_id}/resume')
    def resume_research(run_id:str):
        runs=store.rows('SELECT * FROM research_runs WHERE id=?',(run_id,))
        if not runs or runs[0]['kind']!='company':raise HTTPException(404,'公司研究断点不存在')
        r=runs[0]
        return {'job_id':services.submit('research',lambda:services.research(r['security_id'],json.loads(r['snapshot'])['question'],run_id))}

    @app.post('/api/history/refresh')
    def history_refresh():
        from .data_adapters import collect_history,collect_fx_history,collect_financial_history
        def run():
            for s in store.followed():
                try:
                    collect_history(store,s)
                    collect_financial_history(store,s)
                except ProviderError as e:store.event('history',str(e))
            try:collect_fx_history(store,services.market.client)
            except Exception:store.event('history','历史汇率未完成；相关统计暂缺失。')
        return {'job_id':services.submit('history',run)}

    @app.get("/api/search")
    def search(q: str):
        if len(q) > 60:
            raise HTTPException(422, "搜索内容过长")
        return services.market.lookup(q)

    @app.post("/api/positions")
    def save_position(body: Position):
        check_limit(body)
        already=f'{body.exchange}:{body.ticker}' in [s["id"] for s in store.followed()]
        sid = store.add_security(body.model_dump(mode="json"))
        store.execute("INSERT OR REPLACE INTO positions VALUES(?,?,?,?,?)",
                      (sid, str(body.quantity), str(body.cost), body.note, utcnow()))
        return {"id": sid,"collection_job":None if already else services.submit("collection",lambda:services.collect_company(sid))}

    @app.delete("/api/positions/{sid}")
    def delete_position(sid: str):
        with store.connect() as db:
            db.execute("DELETE FROM positions WHERE security_id=?", (sid,))
            db.execute("DELETE FROM holding_snapshots WHERE security_id=?", (sid,))
            db.execute("UPDATE accounts SET mode='snapshot',history_complete=0 WHERE id='eastmoney'")
        return {"ok": True}

    @app.post("/api/watchlist")
    def watch(body: Security):
        check_limit(body)
        already=f'{body.exchange}:{body.ticker}' in [s["id"] for s in store.followed()]
        sid = store.add_security(body.model_dump())
        store.execute("INSERT OR IGNORE INTO watchlist VALUES(?)", (sid,))
        return {"id": sid,"collection_job":None if already else services.submit("collection",lambda:services.collect_company(sid))}

    @app.post("/api/collect/{sid}")
    def collect(sid: str):
        has_security(sid)
        return {"job_id":services.submit("collection",lambda:services.collect_company(sid))}

    @app.delete("/api/watchlist/{sid}")
    def unwatch(sid: str):
        store.execute("DELETE FROM watchlist WHERE security_id=?", (sid,))
        return {"ok": True}

    @app.post("/api/cash")
    def cash(body: Cash):
        store.execute("INSERT OR REPLACE INTO cash VALUES(?,?)", (body.currency, str(body.amount)))
        return {"ok": True}

    @app.post("/api/quotes/{sid}")
    def manual_quote(sid: str, body: ManualQuote):
        has_security(sid)
        store.execute("INSERT OR REPLACE INTO quotes VALUES(?,?,?,?,?,?)",
                      (sid, str(body.price), str(body.previous) if body.previous else None,
                       str(body.as_of), "手动录入：" + body.source, utcnow()))
        store.execute("INSERT OR REPLACE INTO quote_metadata VALUES(?,?,?,?,?,?,?)",(sid,None,'Asia/Shanghai',None,'unknown','date_only',utcnow()))
        return {"ok": True}

    @app.post('/api/fx/refresh')
    def refresh_fx():
        return {'job_id':services.submit('fx',lambda:services.refresh_fx(force=True))}

    @app.post("/api/fx")
    def fx(body: Fx):
        store.execute("INSERT OR REPLACE INTO fx VALUES('HKD',?,?,?)", (str(body.rate), str(body.as_of), "手动录入：" + body.source))
        store.save_settings({'fx_metadata':{'kind':'manual','fetched_at':utcnow(),'rate_date':str(body.as_of),'source':'手动录入：'+body.source},'fx_status':{'status':'manual','checked_at':utcnow(),'message':'手动汇率，下次自动检查将更新'}})
        return {"ok": True}

    @app.get("/api/evidence/{sid}")
    def evidence(sid: str):
        return store.rows("SELECT * FROM evidence WHERE security_id=? ORDER BY published_at DESC,id DESC", (sid,))

    @app.post("/api/evidence")
    def save_evidence(body: Evidence):
        has_security(body.security_id)
        try:
            eid = store.execute("INSERT INTO evidence(security_id,title,url,published_at,report_period,locator,content,kind,verification,fetched_at)"
                                " VALUES(?,?,?,?,?,?,?,?,?,?)",
                                (body.security_id, body.title, body.url, str(body.published_at), body.report_period,
                                 body.locator, body.content, body.kind, "manual_unverified", utcnow()))
        except Exception:
            raise HTTPException(409, "这份资料已保存，请查看资料列表。")
        return {"id": eid}

    @app.post("/api/import-pdf")
    def import_pdf(body: dict):
        url = str(body.get("url", ""))
        return {"content": services.market.official_text(url),
                "note": "文本来自官方 PDF 直链；请核对标题、日期和报告期后保存。截取前120页、最多80000字符。"}

    @app.get("/api/valuation/{sid}")
    def get_valuation(sid: str):
        has_security(sid)
        return valuation(store,sid)

    @app.put("/api/valuation/{sid}")
    def save_valuation(sid: str, body: ValuationInput):
        has_security(sid)
        evidence=store.rows("SELECT * FROM evidence WHERE id=? AND security_id=? AND verification!='title_only'",
                            (body.evidence_id,sid))
        if not evidence:
            raise HTTPException(422,"指标必须引用这家公司的原文，不能引用只有标题的材料。")
        if body.as_of > datetime.fromisoformat(evidence[0]["published_at"]).date():
            raise HTTPException(422,"财务截止日期不能晚于所引材料的发布日期。")
        values=[str(v) if v is not None else None for v in (body.eps,body.book_per_share,body.dividend_per_share)]
        store.execute("INSERT OR REPLACE INTO valuation_inputs VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                      (sid,body.evidence_id,body.currency,body.earnings_basis,body.report_period,str(body.as_of),
                       *values,body.locator,utcnow()))
        return valuation(store,sid)

    @app.post("/api/refresh")
    def refresh():
        return {"job_id": services.submit("refresh", services.refresh)}

    @app.post("/api/research")
    def research(body: ResearchRequest):
        has_security(body.security_id)
        return {"job_id": services.submit("research", lambda: services.research(body.security_id, body.question))}

    @app.post("/api/reports/{rid}/followup")
    def followup(rid: int, body: Followup):
        return {"job_id": services.submit("followup", lambda: services.followup(rid, body.question))}

    @app.get("/api/reports/{rid}")
    def report(rid: int):
        rows = store.rows("SELECT * FROM reports WHERE id=?", (rid,))
        if not rows:
            raise HTTPException(404, "报告不存在")
        result = rows[0]
        result["payload"] = json.loads(result["payload"])
        ids = json.loads(result["evidence_ids"])
        result["evidence"] = store.rows("SELECT id,title,url,published_at,verification,locator FROM evidence WHERE id IN "
                                      "(" + ",".join("?" for _ in ids) + ")", ids) if ids else []
        return result

    @app.get("/api/jobs/{jid}")
    def job(jid: str):
        rows = store.rows("SELECT * FROM jobs WHERE id=?", (jid,))
        if not rows:
            raise HTTPException(404, "任务不存在")
        return services.job_details(jid)

    @app.get("/api/jobs/{jid}/preview")
    def job_preview(jid: str):
        if not store.rows("SELECT id FROM jobs WHERE id=?",(jid,)):raise HTTPException(404,"任务不存在")
        return services.job_preview(jid)

    @app.post("/api/brief")
    def brief(body: dict):
        return {"job_id": services.submit("brief", lambda: services.brief(send=bool(body.get("send", False)),analyze=body.get("analyze")))}

    @app.post('/api/jobs/{jid}/cancel')
    def cancel_job(jid: str):
        if not store.rows('SELECT id FROM jobs WHERE id=?',(jid,)):
            raise HTTPException(404, '任务不存在')
        return services.cancel_job(jid)

    @app.post('/api/notifications/{nid}/resend')
    def resend(nid:int,body:dict):
        if body.get('confirm') is not True:raise HTTPException(400,'重发可能重复收件，请确认后继续。')
        return {'job_id':services.submit('push_resend',lambda:services.resend_notification(nid))}

    @app.put("/api/settings")
    def settings(body: Settings):
        values=body.model_dump(mode="json")
        if store.settings().get('provider_profile'):
            for key in ('model','input_price','output_price','cached_input_price','pricing_version','pricing_source','prices_confirmed'):
                values.pop(key,None)
            values['pricing_mode']='provider'
        store.save_settings(values)
        return {"ok": True, "settings": store.settings()}

    @app.put("/api/credentials")
    def save_credentials(body: Secrets):
        if body.kimi_key or body.clear_kimi:
            credentials.set("kimi", "" if body.clear_kimi else body.kimi_key.strip())
            store.save_settings({'model_sync':{}})
        if body.push_key or body.clear_push:
            credentials.set("push", "" if body.clear_push else body.push_key.strip())
        try:sync=services.sync_model_profile(force=True) if body.kimi_key else None
        except ProviderError:sync=store.settings().get('model_sync')
        return {"ok": True, "persisted": credentials.persisted, "model_sync":sync, "settings":store.settings()}

    @app.post("/api/push-test")
    def test_push():
        key = "test:" + utcnow()
        status = services.notify(key, "投资信息台连接测试", "这是一条连接测试，不包含个人持仓。请在微信确认收到消息。")
        return {"status": status}

    @app.post('/api/push-alert-test')
    def test_alert_push():
        status=services.notify('test:alert:'+utcnow(), '重点提醒测试（模拟）',
            '这是一条模拟重点提醒，不代表真实市场事件。\n\n事件：模拟公司发布重要公告。\n关联：你的关注公司。\n关注重点：核对公告及其影响。\n\n[示例来源：港交所披露易](https://www.hkexnews.hk/)\n\n本测试不调用 AI，不修改持仓或真实事件。')
        return {'status':status}

    @app.get("/api/backup")
    def backup():
        path = store.backup()
        return FileResponse(path, filename=path.name, media_type="application/octet-stream")

    frontend = Path(__file__).resolve().parent.parent / "frontend" / "dist"
    if frontend.exists():
        app.mount("/", StaticFiles(directory=frontend, html=True), name="frontend")
    else:
        @app.get("/")
        def missing_frontend():
            return JSONResponse({"detail": "前端尚未构建。请在 frontend 执行 npm install 与 npm run build。"}, status_code=503)
    return app
