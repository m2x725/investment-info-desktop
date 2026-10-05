from datetime import timedelta
import json
import pytest
from backend.services import beijing_now, strict_validate_report as validate_report
from backend.providers import ProviderError
from test_mvp import api, add, service


def prepare(c):
    sid=add(c)
    day=str(beijing_now().date())
    e=c.post("/api/evidence",json=dict(security_id=sid,title="验收用财报",
         url="https://example.com/test-report",published_at=day,content="本期每股收益为9元，每股净资产90元，全年每股现金股息1.8元。",locator="第12页"))
    assert e.status_code==200
    c.post("/api/quotes/"+sid,json=dict(price="400",as_of=day,source="测试来源"))
    body=dict(evidence_id=e.json()["id"],currency="CNY",earnings_basis="annual",
              report_period="2025年度",as_of=day,eps="9",book_per_share="90",dividend_per_share="1.8",locator="第12页基本每股收益")
    return sid,body,day


def test_cross_currency_ratios_and_loss_rules(api):
    c,_=api
    sid,body,day=prepare(c)
    r=c.put("/api/valuation/"+sid,json=body)
    assert r.status_code==200 and r.json()["pe"] is None
    assert any("币种" in w for w in r.json()["warnings"])
    c.post("/api/fx",json=dict(rate="0.9",as_of=day,source="测试汇率"))
    v=c.get("/api/valuation/"+sid).json()
    assert (v["pe"],v["pb"],v["dividend_yield"])==("40.00","4.00","0.50")
    r=c.put("/api/valuation/"+sid,json={**body,"eps":"-9","book_per_share":"0","dividend_per_share":"0"}).json()
    assert r["pe"] is None and r["pb"] is None and r["dividend_yield"]=="0.00"
    assert any("不能当作低估" in w for w in r["warnings"])


def test_valuation_requires_matching_full_evidence_and_date(api):
    c,_=api
    sid,body,day=prepare(c)
    other=add(c,"SH","600519")
    assert c.put("/api/valuation/"+other,json=body).status_code==422
    assert c.put("/api/valuation/"+sid,json={**body,"evidence_id":999}).status_code==422
    assert c.put("/api/valuation/"+sid,json={**body,"eps":None,"book_per_share":None,"dividend_per_share":None}).status_code==422
    assert c.put("/api/valuation/"+sid,json={**body,"as_of":str(beijing_now().date()+timedelta(days=1))}).status_code==422


def test_exact_numbers_and_locator_verification():
    e=[dict(id=1,content="全年每股收益100元。",locator="第12页")]
    p=dict(title="测试",summary="全年每股收益100.00元",facts=[dict(text="全年每股收益100元",evidence_id=1,locator="第12页")],
           support=[],risks=[dict(text="存在未确认风险",evidence_ids=[1])],unknowns=["资料不足"],assumptions=[])
    assert validate_report(p,e)
    with pytest.raises(ProviderError):validate_report({**p,"summary":"每股收益10元"},e)
    result=validate_report({**p,"facts":[dict(text="全年每股收益100元",evidence_id=1,locator="第999页")]},e)
    assert result['facts'][0]['locator']=='位置未核实' and result['validation_warnings']
    assert validate_report({**p,"summary":"PE为40倍"},e,{"pe":"40.00"})


def test_report_preserves_original_calculation_snapshot(api):
    from unittest.mock import Mock
    c,app=api
    sid,body,day=prepare(c)
    c.put("/api/valuation/"+sid,json=body)
    c.post("/api/fx",json=dict(rate="0.9",as_of=day,source="测试汇率"))
    app.state.credentials.memory["kimi"]="test"
    app.state.store.save_settings({"prices_confirmed":True,"input_price":"1","output_price":"1"})
    result=dict(title="测试报告",summary="按已录入输入计算PE为40.00倍",
        facts=[dict(text="本期每股收益为9元",evidence_id=body["evidence_id"],locator="第12页")],
        support=[],risks=[dict(text="输入与口径仍需核实",evidence_ids=[body["evidence_id"]])],
        unknowns=["财报原文尚未独立核实"],assumptions=[])
    app.state.services.kimi.complete=Mock(return_value=(result,dict(prompt_tokens=100,completion_tokens=100)))
    rid=app.state.services.research(sid,"估值怎么看")
    snapshot=c.get("/api/reports/"+str(rid)).json()["payload"]["calculation"]
    assert snapshot["pe"]=="40.00" and snapshot["inputs"]["currency"]=="CNY"
    c.post("/api/quotes/"+sid,json=dict(price="800",as_of=day,source="新测试报价"))
    assert c.get("/api/valuation/"+sid).json()["pe"]=="80.00"
    assert c.get("/api/reports/"+str(rid)).json()["payload"]["calculation"]==snapshot


def test_scheduler_pause_preserves_manual_features(tmp_path):
    from unittest.mock import Mock
    s=service(tmp_path)
    s.store.save_settings({"scheduler_enabled":True,"scheduler_paused":True})
    s.refresh=Mock()
    s.tick(beijing_now().replace(hour=9))
    assert s.refresh.call_count==0
    assert s.brief(send=False)>0
    s.close()


def test_legacy_schema_backed_up_before_extension(tmp_path):
    import sqlite3
    from backend.storage import Store
    original=Store(tmp_path)
    sid=original.add_security(dict(exchange="SH",ticker="600519",name="测试持仓"))
    original.execute("INSERT INTO watchlist VALUES(?)",(sid,))
    original.execute("DROP TABLE valuation_inputs")
    upgraded=Store(tmp_path)
    assert len(upgraded.followed())==1
    backups=list((tmp_path/"backups").glob("*.db"))
    assert len(backups)==1
    with sqlite3.connect(backups[0]) as db:
        assert db.execute("SELECT COUNT(*) FROM watchlist").fetchone()[0]==1
        assert db.execute("SELECT name FROM sqlite_master WHERE name='valuation_inputs'").fetchall()==[]
    assert upgraded.rows("SELECT name FROM sqlite_master WHERE name='valuation_inputs'")


def test_interrupted_notification_restores_as_unknown(tmp_path):
    from backend.storage import Store, utcnow
    store=Store(tmp_path)
    store.execute("INSERT INTO notifications(dedupe_key,day,status,title,content,message,created_at) VALUES(?,?,?,?,?,?,?)",
                  ("daily:test",str(beijing_now().date()),"sending","标题","内容","等待推送",utcnow()))
    restored=Store(tmp_path)
    row=restored.rows("SELECT * FROM notifications")[0]
    assert row["status"]=="unknown" and "上次运行中断" in row["message"]
