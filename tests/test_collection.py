from unittest.mock import Mock
from datetime import datetime,timezone
import json
import httpx
import pytest
from backend.collection import Collector, choose, today
from backend.providers import Market, ProviderError
from backend.main import create_app
from backend.domain import valuation
from test_mvp import service, api


def test_reports_prefer_full_annual_and_interim():
    rows=[dict(title=t,url=str(i)) for i,t in enumerate(["股份购回","2026半年度报告","2025年度报告摘要","2025年度报告","2024年度报告"])]
    chosen=choose(rows)
    assert chosen[0]["title"]=="2025年度报告"
    assert chosen[2]["title"]=="2026半年度报告"
    assert len(chosen)==4
    assert not any("摘要" in r["title"] for r in chosen)
    assert any("2024" in r["title"] for r in chosen)


def test_hk_identity_is_confirmed_and_actual_currency_corrected():
    def handler(req):
        if req.url.path.endswith("prefix.do"):
            return httpx.Response(200,text='callback({"stockInfo":[{"code":"00700","stockId":7609}]});')
        if req.url.path.endswith("titleSearchServlet.do"):
            assert req.url.params["stockId"]=="7609"
            assert "fromDate" in req.url.params
            return httpx.Response(200,json={"result":json.dumps([
                dict(STOCK_CODE="00001",FILE_TYPE="PDF",FILE_LINK="/listedco/listconews/sehk/wrong.pdf",DATE_TIME="01/01/2025 17:00",TITLE="错误公司"),
                dict(STOCK_CODE="00700<br/>80700",FILE_TYPE="PDF",FILE_LINK="/listedco/listconews/sehk/2025/0401/20250401001_c.pdf",DATE_TIME="01/04/2025 17:00",TITLE="2024 年報")])})
        if req.url.params["reportName"]=="RPT_HKF10_FN_MAININDICATOR":
            return httpx.Response(200,json={"result":{"data":[dict(SECUCODE="00700.HK",REPORT_DATE="2025-12-31",BASIC_EPS=9,BPS=90,CURRENCY="HKD")]}})
        return httpx.Response(200,json={"result":{"data":[{"REPORT_LIST":[dict(SECUCODE="00700.HK",REPORT_DATE="2025-12-31",CURRENCY="人民币")]}]}})
    market=Market();market.client=httpx.Client(transport=httpx.MockTransport(handler))
    collector=Collector(market)
    docs=collector.documents(dict(exchange="HK",ticker="00700"))
    assert len(docs)==1 and "错误" not in docs[0]["title"]
    assert collector.financials(dict(exchange="HK",ticker="00700"))["currency"]=="CNY"


def test_automatic_collection_preserves_cache_and_marks_failed_body(tmp_path):
    s=service(tmp_path)
    sid=s.store.add_security(dict(exchange="SH",ticker="600519",name="测试公司"))
    s.collector=Mock()
    s.collector.documents.return_value=[dict(title="2025年度报告",url="https://static.cninfo.com.cn/finalpage/2026-04-01/1.PDF",
            published_at="2026-04-01",kind="financial")]
    s.market.quote.return_value=dict(price="100",previous="90",as_of=str(today()),source="测试报价")
    s.market.official_text.return_value="[第1页] 测试财报原文，每股收益5元，每股净资产20元。"
    s.collector.financials.return_value=dict(currency="CNY",eps="5",book_per_share="20",dividend_per_share=None,
        as_of="2025-12-31",report_period="2025年度",earnings_basis="annual",url="https://example.com/financial",
        locator="聚合财务指标",publication="2026-04-01")
    assert s.collect_company(sid)["status"]=="done"
    v=valuation(s.store,sid)
    assert v["pe"]=="20.00" and v["pb"]=="5.00"
    assert s.collect_company(sid)["status"]=="done"
    assert s.market.official_text.call_count==1
    assert len(s.store.rows("SELECT * FROM evidence"))==2
    s.collector.documents.return_value.append(dict(title="新公告",url="https://static.cninfo.com.cn/finalpage/2026-04-01/2.PDF",
            published_at="2026-04-01",kind="announcement"))
    s.store.execute("DELETE FROM performance_cache WHERE kind='documents'") # simulate expired directory
    s.market.official_text.side_effect=ProviderError("timeout")
    assert s.collect_company(sid)["status"]=="partial"
    rows=s.store.rows("SELECT * FROM evidence WHERE title='新公告'")
    assert rows[0]["verification"]=="title_only"
    assert len(s.store.rows("SELECT * FROM evidence WHERE verification='official_download'"))==1
    s.close()


def test_add_company_enqueues_collection_and_research_fetches_without_manual_material(api):
    c,app=api
    r=c.post("/api/watchlist",json=dict(exchange="HK",ticker="700",name="测试公司"))
    assert r.status_code==200 and r.json()["collection_job"]
    with pytest.raises(ProviderError):
        app.state.services.research("HK:00700","分析业务")
    assert app.state.services.collect_company.called


def test_excerpt_contains_financial_sections_instead_of_only_cover():
    text="[第1页] 封面\n"+"一般说明"*2000+"\n[第50页] 营业收入100元。\n"+"附注"*2000+"\n[第80页] 每股收益5元。"
    from backend.services import Services
    excerpt=Services.research_excerpt(text)
    assert len(excerpt)<=4000 and "营业收入100元" in excerpt and "每股收益5元" in excerpt
