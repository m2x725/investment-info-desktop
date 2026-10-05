import json
from unittest.mock import Mock
import pytest
from fastapi.testclient import TestClient
from backend.main import create_app
from backend.news import digest_excerpt,news_feed
from backend.services import beijing_now
from backend.providers import ProviderError
from test_mvp import service


def output():
    return dict(title='分析',summary='经营仍需观察。',facts=[],support=[dict(text='需核对业务变化',evidence_ids=[])],risks=[],unknowns=['来源覆盖有限'],assumptions=[])

def source(s,content='公司宣布回购股份，现金支出需要结合资金状况观察。',verification='official_download'):
    sid=s.store.add_security(dict(exchange='HK',ticker='00700',name='测试公司'))
    s.store.execute('INSERT OR IGNORE INTO watchlist VALUES(?)',(sid,))
    eid=s.store.execute('INSERT INTO evidence(security_id,title,url,published_at,content,kind,verification,fetched_at) VALUES(?,?,?,?,?,?,?,?)',
       (sid,'股份回购公告','https://www.hkexnews.hk/test.pdf',str(beijing_now().date()),content,'announcement',verification,beijing_now().isoformat()))
    return sid,eid

def test_large_multichapter_followup_and_followup_again_preserve_full_storage(tmp_path):
    s=service(tmp_path);sid,eid=source(s,'业务收入和经营现金流存在风险。'*14000)
    original={**output(),'summary':'完整正文。'*10000,'sections':[dict(key=k,label=k,status='done',report={**output(),'summary':'该章节完整内容。'*12000}) for k in ('business','financial','events','competition','valuation','countercase')]}
    encoded=json.dumps(original,ensure_ascii=False)
    rid=s.store.execute('INSERT INTO reports(security_id,kind,payload,evidence_ids,created_at) VALUES(?,?,?,?,?)',(sid,'research',encoded,json.dumps([eid]),beijing_now().isoformat()))
    s.kimi.complete.return_value=(output(),dict(prompt_tokens=100,completion_tokens=100))
    follow=s.followup(rid,'解释简单一点');s.followup(follow,'继续解释经营风险')
    assert s.kimi.complete.call_count==2
    for call in s.kimi.complete.call_args_list:
        messages=call.args[1]
        assert len(json.dumps(messages,ensure_ascii=False).encode())+2048<=120000
    assert s.store.rows('SELECT payload FROM reports WHERE id=?',(rid,))[0]['payload']==encoded
    assert len(s.store.rows('SELECT content FROM evidence WHERE id=?',(eid,))[0]['content'])>100000
    s.close()

def test_digest_contains_substance_link_and_no_model_call_by_default(tmp_path):
    s=service(tmp_path);sid,eid=source(s)
    rid=s.brief();p=json.loads(s.store.rows('SELECT payload FROM reports WHERE id=?',(rid,))[0]['payload'])
    assert '回购股份' in p['items'][0]['text'] and '与你的关注清单相关' not in p['items'][0]['text']
    assert p['items'][0]['url']=='https://www.hkexnews.hk/test.pdf'
    assert not s.kimi.complete.called
    assert '仅有标题' in digest_excerpt('股份回购','标题','title_only')
    assert '解析不足' in digest_excerpt('□'*200,'标题','official_download')
    s.close()

def test_manual_ai_digest_summarizes_items_without_enabling_background_ai(tmp_path):
    s=service(tmp_path);source(s)
    s.kimi.complete.return_value=({**output(),'items':[dict(url='https://www.hkexnews.hk/test.pdf',text='回购变化需结合现金状况观察。'),dict(url='https://evil.example',text='不能插入陌生链接')]},dict(prompt_tokens=100,completion_tokens=100))
    rid=s.brief(analyze=True);p=json.loads(s.store.rows('SELECT payload FROM reports WHERE id=?',(rid,))[0]['payload'])
    assert p['mode']=='ai_digest' and p['items'][0]['text']=='回购变化需结合现金状况观察。'
    assert not s.store.settings()['auto_research']
    assert len(p['items'])==1
    s.close()

def test_news_analysis_budget_cache_and_source_change(tmp_path):
    s=service(tmp_path);sid,eid=source(s)
    s.kimi.complete.return_value=(output(),dict(prompt_tokens=100,completion_tokens=100))
    rid=s.analyze_news('evidence:'+str(eid))
    assert s.analyze_news('evidence:'+str(eid))==rid and s.kimi.complete.call_count==1
    item=news_feed(s.store)[0]
    assert item['analysis']['id']==rid and item['summary']
    assert len(s.store.rows("SELECT * FROM expenses WHERE status='charged'"))==1
    s.store.execute('UPDATE evidence SET content=? WHERE id=?',('公司宣布改变回购安排，需要核对新的资金计划。',eid))
    assert news_feed(s.store)[0]['analysis'] is None
    assert s.analyze_news('evidence:'+str(eid))!=rid
    with pytest.raises(ProviderError,match='当前列表'):s.analyze_news('rss:https://127.0.0.1/secrets')
    s.close()

def test_news_budget_blocked_before_model_call(tmp_path):
    s=service(tmp_path);_,eid=source(s)
    s.store.save_settings({'monthly_limit':'0'})
    with pytest.raises(ProviderError,match='预算'):s.analyze_news('evidence:'+str(eid))
    assert not s.kimi.complete.called and not s.store.rows("SELECT * FROM reports WHERE kind='news_analysis'")
    s.close()

def test_news_route_uses_server_id_and_does_not_replace_company_history(tmp_path):
    app=create_app(tmp_path,scheduler=False);s=app.state.services
    source(s);s.ai_call=Mock(return_value=output());s.submit=Mock(side_effect=lambda kind,fn: fn())
    with TestClient(app) as c:
        c.headers['X-App-Token']=c.get('/api/bootstrap').json()['csrf']
        item=c.get('/api/bootstrap').json()['news'][0]
        r=c.post('/api/news/analyze',json={'news_id':item['id']})
        assert r.status_code==200
        d=c.get('/api/bootstrap').json()
        assert d['news'][0]['analysis'] and not d['reports']
        assert c.post('/api/news/analyze',json={'url':'https://127.0.0.1'}).status_code==422


def test_table_digest_is_short_and_cache_invalidation_uses_full_content(tmp_path):
    s=service(tmp_path);_,eid=source(s,'已發行股份和購回股份表格。'*500)
    s.store.execute('UPDATE evidence SET title=? WHERE id=?',('翌日披露報表',eid))
    s.kimi.complete.return_value=(output(),dict(prompt_tokens=100,completion_tokens=100))
    s.analyze_news('evidence:'+str(eid))
    old=news_feed(s.store)[0]
    assert len(old['summary'])<150
    s.store.execute('UPDATE evidence SET content=content || ? WHERE id=?',('股份数量变化记录',eid))
    new=news_feed(s.store)[0]
    assert new['summary']==old['summary'] and new['analysis'] is None
    s.close()
