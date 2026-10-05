import json
from unittest.mock import Mock
import pytest
from backend.services import strict_validate_report as validate_report
from backend.providers import ProviderError, Kimi, Credentials
from test_mvp import service


def sample(text='营业收入为1,234.00元',locator='第12页'):
    return dict(title='报告',summary='收入为1234元',facts=[dict(text=text,evidence_id='1',locator=locator)],
        support=[dict(text='收入为1,234元',evidence_ids=['1'])],risks=[dict(text='来源有限',evidence_ids=['1'])],
        unknowns=['完整性未知'],assumptions=[])


def test_locator_derived_from_quote_not_any_page_present():
    evidence=[dict(id=1,content='[第12页] 营业收入为1,234.00元\n[第99页] 其他内容')]
    p=sample(locator='第99页')
    r=validate_report(p,evidence)
    assert r['facts'][0]['locator']=='[第12页]' and r['validation_warnings']
    r=validate_report(sample(locator='第 12 页'),evidence)
    assert r['facts'][0]['locator_status']=='derived_from_source' and not r['validation_warnings']
    assert r['support'][0]['evidence_ids']==[1]


def test_missing_or_guessed_chapter_retains_verified_text_with_warning():
    e=[dict(id=1,content='营业收入为1,234.00元',locator='自动读取，可能截断')]
    for loc in ('管理层讨论',None,{},''):
        r=validate_report(sample(locator=loc),e)
        assert r['facts'][0]['locator']=='位置未核实'


def test_pdf_whitespace_tolerated_without_merging_digits_or_changing_facts():
    e=[dict(id=1,content='[第12页] 营业\n收入为1,234.00元')]
    r=validate_report(sample(),e)
    assert r['facts'][0]['quote_match']=='layout_whitespace'
    with pytest.raises(ProviderError,match='原文中找到'):
        validate_report(sample(text='营业收入为1,235.00元'),e)
    with pytest.raises(ProviderError,match='原文中找到'):
        validate_report(sample(text='营业收入为10元'),[dict(id=1,content='营业收入为1 0元')])


@pytest.mark.parametrize('section,bad',[('facts',[None]),('support',[None]),('risks',[{'text':'风险','evidence_ids':[True]}]),('facts',[{'text':'营业收入为1,234.00元','evidence_id':True}])])
def test_malformed_items_fail_with_explained_error(section,bad):
    with pytest.raises(ProviderError):
        validate_report({**sample(),section:bad},[dict(id=1,content='营业收入为1,234.00元')])


def test_rejected_response_is_local_diagnostic_not_published(tmp_path):
    s=service(tmp_path)
    e=[dict(id=1,content='营业收入为1,234.00元')]
    p=sample(text='虚构收入完全不存在')
    result=s.validate_output(p,e,sid='HK:01810',stage='draft')
    assert not result['facts'] and result['unverified'][0]['text']==p['facts'][0]['text']
    rows=s.store.rows('SELECT * FROM research_outputs')
    assert len(rows)==1 and rows[0]['status']=='needs_review'
    assert json.loads(rows[0]['payload'])==p
    assert not s.store.rows('SELECT * FROM reports')
    assert b'test-secret' not in s.store.path.read_bytes()
    s.close()


def test_provider_exact_json_fence_and_output_truncation():
    credentials=Credentials();credentials.memory['kimi']='test'
    k=Kimi(credentials);k.client=Mock()
    payload=sample()
    k.client.post.return_value=Mock(json=lambda:dict(usage=dict(prompt_tokens=10,completion_tokens=10),
        choices=[dict(finish_reason='stop',message=dict(content='```json\n'+json.dumps(payload)+'\n```'))]))
    assert k.complete('kimi-k2.6',[])[0]==payload
    k.client.post.return_value=Mock(json=lambda:dict(usage=dict(prompt_tokens=10,completion_tokens=10),
        choices=[dict(finish_reason='length',message=dict(content=json.dumps(payload)))]))
    assert k.complete('kimi-k2.6',[])[0]['partial_output'] is True


def test_two_stage_research_publishes_with_warning_without_paid_retry(tmp_path):
    from backend.storage import utcnow
    s=service(tmp_path)
    sid=s.store.add_security(dict(exchange='HK',ticker='01810',name='合成测试公司'))
    body='[第12页] 营业\n收入为1,234.00元。'
    eid=s.store.execute('INSERT INTO evidence(security_id,title,url,published_at,content,kind,verification,fetched_at) VALUES(?,?,?,?,?,?,?,?)',
        (sid,'合成测试来源','https://example.com/test','2026-01-01',body,'financial','official_download',utcnow()))
    s.store.save_settings({'collection:'+sid:{'checked_at':utcnow(),'status':'done'}})
    p=sample(locator='第999页');p['facts'][0]['evidence_id']=str(eid)
    p['support'][0]['evidence_ids']=[str(eid)];p['risks'][0]['evidence_ids']=[str(eid)]
    s.kimi.complete.return_value=(p,dict(prompt_tokens=10,completion_tokens=10))
    rid=s._research(sid,'主要靠什么赚钱')
    payload=json.loads(s.store.rows('SELECT payload FROM reports WHERE id=?',(rid,))[0]['payload'])
    assert payload['facts'][0]['locator']=='[第12页]' and payload['validation_warnings']
    assert s.kimi.complete.call_count==2
    assert len(s.store.rows("SELECT * FROM research_outputs WHERE status='needs_review'"))==2
    assert len(s.store.rows("SELECT * FROM expenses WHERE status='charged'"))==2
    s.close()


def test_decimal_rounding_is_explicit_but_changed_numbers_still_fail():
    evidence=[dict(id=1,content='每股净资产10.320668元，引用原文。')]
    p=sample(text='每股净资产10.320668元',locator='')
    p['summary']='每股净资产10.32元';p['support']=[]
    result=validate_report(p,evidence)
    assert any('10.320668' in w and '舍入' in w for w in result['validation_warnings'])
    for bad in ('每股净资产10.33元','每股净资产10元','每股净资产103.20元'):
        with pytest.raises(ProviderError,match='数字'):
            validate_report({**p,'summary':bad},evidence)


def test_noncritical_checks_preserve_readable_report_and_label_bad_content():
    from backend.services import validate_report as publish
    e=[dict(id=1,content='营业收入为1,234.00元')]
    p=sample();p.pop('title');p.pop('unknowns');p.pop('assumptions')
    p['summary']='模型推论中出现尚无来源的999元'
    p['support']='只有文字，没有来源编号'
    p['risks']=[]
    p['facts'].append(dict(text='这句不是原文',evidence_id=1))
    r=publish(p,e)
    assert r['summary']==p['summary'] and r['validation_status']=='needs_review'
    assert len(r['facts'])==1 and len(r['unverified'])==1
    assert r['support'][0]['text']==p['support'] and r['validation_warnings']
    with pytest.raises(ProviderError):publish({},e)
