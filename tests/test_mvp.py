import json
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from unittest.mock import Mock
import pytest
from fastapi.testclient import TestClient
from backend.main import create_app
from backend.storage import Store, utcnow
from backend.domain import portfolio, Settings
from backend.services import Services, beijing_now, strict_validate_report as validate_report
from backend.providers import Credentials, ProviderError, Market


@pytest.fixture
def api(tmp_path):
    app = create_app(tmp_path, scheduler=False)
    app.state.services.collect_company=Mock(return_value={"failures":[]})
    app.state.services.collect_financial_history=Mock(return_value=None)
    with TestClient(app) as client:
        client.headers["X-App-Token"] = client.get("/api/bootstrap").json()["csrf"]
        yield client, app


def add(client, exchange="HK", ticker="700", quantity="100", cost="300"):
    r = client.post("/api/positions", json=dict(exchange=exchange,ticker=ticker,name="测试公司",
                                               quantity=quantity,cost=cost))
    assert r.status_code == 200
    return r.json()["id"]


def test_missing_price_fx_and_cash_denominator(api):
    c, app = api
    sid = add(c)
    assert sid == "HK:00700"
    snap = c.get("/api/bootstrap").json()["portfolio"]
    assert not snap["complete"] and snap["positions"][0]["gain"] is None
    day = str(beijing_now().date())
    assert c.post("/api/quotes/"+sid,json=dict(price="400",as_of=day,source="测试报价")).status_code == 200
    assert not c.get("/api/bootstrap").json()["portfolio"]["complete"]
    c.post("/api/fx",json=dict(rate="0.9",as_of=day,source="测试汇率"))
    c.post("/api/cash",json=dict(currency="CNY",amount="4000"))
    snap = c.get("/api/bootstrap").json()["portfolio"]
    assert snap["known_total"] == "40000.00" and snap["complete"]
    assert snap["positions"][0]["gain"] == "10000.00"
    assert snap["positions"][0]["weight"] == "90.00"
    assert portfolio(Store(app.state.store.directory))["known_total"] == "40000.00"


def test_input_boundaries_and_local_origin(api):
    c, _ = api
    body=dict(exchange="SH",ticker="600519",name="测试",quantity="1",cost="0")
    assert c.post("/api/positions",json=body,headers={"X-App-Token":""}).status_code == 403
    assert c.post("/api/positions",json=body,headers={"Origin":"https://evil.example"}).status_code == 403
    assert c.post("/api/positions",json={**body,"quantity":"NaN"}).status_code == 422
    sid=add(c,"SH","600519")
    assert c.post("/api/quotes/"+sid,json=dict(price="10",as_of=str(beijing_now().date()+timedelta(days=1)),source="测试")).status_code == 422
    assert c.put("/api/settings",json={"prices_confirmed":True}).status_code == 200
    assert c.put("/api/settings",json={"pricing_mode":"manual","prices_confirmed":True}).status_code == 422


def service(tmp_path):
    store=Store(tmp_path); creds=Credentials();creds.memory["kimi"]="test-secret"
    svc=Services(store,Mock(),Mock(),Mock(),creds)
    store.save_settings(Settings(prices_confirmed=True,input_price=1,output_price=1).model_dump(mode="json"))
    return svc


def test_refresh_persists_and_retains_old_quote_on_failure(tmp_path):
    s=service(tmp_path)
    s.collect_company=Mock(return_value={"failures":[]})
    sid=s.store.add_security(dict(exchange="HK",ticker="00700",name="测试"))
    s.store.execute("INSERT INTO watchlist VALUES(?)",(sid,))
    s.market.quote.return_value=dict(price="400",previous="390",as_of=str(beijing_now().date()),source="测试")
    s.market.announcements.return_value=[]
    assert s.refresh()==[]
    s.market.quote.side_effect=ProviderError("offline")
    assert len(s.refresh())==1
    assert s.store.rows("SELECT price FROM quotes")[0]["price"]=="400"
    s.close()


def test_budget_reservation_atomic_and_timeout_not_retried(tmp_path):
    s=service(tmp_path)
    from backend.providers import MODEL_MAX_OUTPUT_TOKENS
    from decimal import Decimal
    messages=[{"role":"user","content":"test"}]
    reservation=(Decimal(len(json.dumps(messages,ensure_ascii=False).encode('utf-8'))+2048+MODEL_MAX_OUTPUT_TOKENS)/1000000)
    s.store.save_settings({"monthly_limit":str(reservation)})
    gate=threading.Event()
    def fail(*args):
        gate.wait(2)
        raise ProviderError("timeout")
    s.kimi.complete.side_effect=fail
    with ThreadPoolExecutor(2) as pool:
        tasks=[pool.submit(s.ai_call,[{"role":"user","content":"test"}]) for _ in range(2)]
        gate.set()
        for task in tasks:
            with pytest.raises(ProviderError):task.result()
    assert s.kimi.complete.call_count==1
    assert len(s.store.rows("SELECT * FROM expenses WHERE status='reserved'"))==1
    assert s.budget()["remaining"]=="0.00"
    s.close()


def test_report_citations_and_unsupported_numbers():
    evidence=[dict(id=1,content="本期经营收入为100，经营存在不确定性。")]
    report=dict(title="研究",summary="仍需关注经营变化",facts=[dict(text="本期经营收入为100",evidence_id=1)],
                support=[dict(text="经营仍在继续",evidence_ids=[1])],
                risks=[dict(text="存在经营风险",evidence_ids=[1])],unknowns=["未核对审计意见"],assumptions=[])
    assert validate_report(report,evidence)["facts"]
    with pytest.raises(ProviderError):validate_report({**report,"summary":"利润增长999"},evidence)
    with pytest.raises(ProviderError):validate_report({**report,"facts":[dict(text="虚构内容不存在",evidence_id=1)]},evidence)


def test_push_unknown_dedup_and_no_secret_storage(tmp_path):
    s=service(tmp_path);s.credentials.memory["push"]="SCTtest-secret";s.store.save_settings({"push_enabled":True})
    s.push.send.side_effect=ProviderError("网络结果不明")
    with pytest.raises(ProviderError):s.notify("daily:test","标题","内容")
    assert s.notify("daily:test","标题","内容")=="unknown"
    assert s.push.send.call_count==1
    s.push.send.side_effect=None
    for n in range(4):assert s.notify(str(n),"标题","内容")=="accepted"
    assert s.notify("six","标题","内容")=="accepted"
    assert b"test-secret" not in s.store.path.read_bytes()
    s.close()


def test_late_boot_daily_once_and_unknown_push_does_not_regenerate(tmp_path):
    s=service(tmp_path);s.store.save_settings({"scheduler_enabled":True,"push_enabled":True})
    s.credentials.memory["push"]="test"
    s.refresh=Mock(return_value=[])
    s.push.send.side_effect=ProviderError("timeout")
    now=beijing_now().replace(hour=9,minute=30)
    with pytest.raises(ProviderError):s.tick(now)
    s.tick(now)
    assert len(s.store.rows("SELECT * FROM reports WHERE kind='brief'"))==1
    assert s.push.send.call_count==1
    s.close()


def test_unconfigured_research_stays_local(api):
    c,app=api;sid=add(c)
    with pytest.raises(ProviderError):app.state.services.research(sid,"研究")
    assert app.state.store.rows("SELECT * FROM expenses")==[]
    r=c.put("/api/credentials",json={"kimi_key":"test-secret"})
    assert r.status_code==200
    assert "test-secret" not in c.get("/api/bootstrap").text


def test_official_pdf_rejects_unapproved_hosts():
    market=Market()
    for url in ["http://static.cninfo.com.cn/x.pdf","https://127.0.0.1/x.pdf",
                "https://static.cninfo.com.cn.evil.example/x.pdf"]:
        with pytest.raises(ProviderError):market.official_text(url)


def test_legacy_research_history_followup_and_weekly_limit(tmp_path):
    s=service(tmp_path)
    sid=s.store.add_security(dict(exchange="SH",ticker="600519",name="测试公司"))
    eid=s.store.execute("INSERT INTO evidence(security_id,title,url,published_at,content,kind,verification,fetched_at) VALUES(?,?,?,?,?,?,?,?)",
        (sid,"测试报告","https://example.com/report",str(beijing_now().date()),"本期收入100，经营存在不确定性。","financial","manual_unverified",utcnow()))
    payload=dict(title="测试研究",summary="资料仍需进一步核对",facts=[dict(text="本期收入100",evidence_id=eid)],
        support=[dict(text="业务仍在经营",evidence_ids=[eid])],risks=[dict(text="存在经营风险",evidence_ids=[eid])],
        unknowns=["审计意见尚未核对"],assumptions=[])
    s.kimi.complete.return_value=(payload,dict(prompt_tokens=100,completion_tokens=100))
    rid=s._research(sid,"经营风险")
    assert s.kimi.complete.call_count==2
    assert "manual_unverified" in json.dumps(s.kimi.complete.call_args.args)
    assert s.store.rows("SELECT kind FROM reports WHERE id=?",(rid,))[0]["kind"]=="research"
    fid=s.followup(rid,"解释简单一点")
    assert s.store.rows("SELECT kind FROM reports WHERE id=?",(fid,))[0]["kind"]=="followup"
    s.store.save_settings({"weekly_research_limit":1})
    with pytest.raises(ProviderError):s._research(sid,"再次研究")
    backup=s.store.backup()
    import sqlite3
    with sqlite3.connect(backup) as db:
        assert db.execute("SELECT COUNT(*) FROM reports").fetchone()[0]==2
    s.close()


def test_tencent_fallback_validates_symbol_and_timestamp():
    market=Market()
    fields=[""]*31
    fields[2],fields[3],fields[4],fields[30]="00700","400.5","390","2026/10/02 16:08:10"
    response=Mock(content=('v_hk00700="'+"~".join(fields)+'";').encode("gb18030"))
    market.client=Mock();market.client.get.return_value=response
    market._eastmoney_quote=Mock(side_effect=ProviderError("offline"))
    assert market.quote(dict(exchange="HK",ticker="00700"))["price"]=="400.5"
    with pytest.raises(ProviderError):market.quote(dict(exchange="HK",ticker="00005"))


def test_other_service_fees_reduce_model_budget(tmp_path):
    s=service(tmp_path)
    s.store.save_settings({"monthly_limit":"1","other_service_cost":"1"})
    assert s.budget()["used"]=="1.00"
    assert s.budget()["remaining"]=="0.00"
    with pytest.raises(ProviderError):s.ai_call([{"role":"user","content":"test"}])
    assert s.kimi.complete.call_count==0
    with pytest.raises(ValueError):Settings(monthly_limit=10,other_service_cost=11)
    s.close()


def test_alert_push_test_is_simulated_and_has_no_ai_or_real_event(api):
    c,app=api
    app.state.credentials.memory['push']='test'
    app.state.store.save_settings({'push_enabled':True})
    app.state.services.push=Mock()
    app.state.services.ai_call=Mock()
    response=c.post('/api/push-alert-test')
    assert response.status_code==200
    args=app.state.services.push.send.call_args.args
    assert '模拟' in args[0] and '不代表真实市场事件' in args[1]
    app.state.services.ai_call.assert_not_called()
    assert not app.state.store.rows('SELECT id FROM evidence')
