import json
import threading
from unittest.mock import Mock
from decimal import Decimal
import pytest
import httpx
from fastapi.testclient import TestClient
from backend.storage import Store,utcnow
from backend.services import Services
from backend.providers import Credentials,Kimi,ProviderError
from backend.model_profile import parse_official_rates,select_api_profile,usage_cost,PROFILE
from backend.cancellation import JobCancelled
from backend.main import create_app


def service(tmp_path):
    credentials=Credentials();credentials.memory['kimi']='fake-key'
    return Services(Store(tmp_path),Mock(),Mock(),Mock(),credentials)


def report(store):
    return store.execute('INSERT INTO reports(kind,payload,evidence_ids,created_at) VALUES(?,?,?,?)',('research','{}','[]',utcnow()))


def test_cancel_discards_child_reports_diagnostics_sections_and_late_result(tmp_path):
    s=service(tmp_path);old=report(s.store)
    entered,release=threading.Event(),threading.Event()
    def work():
        report(s.store)
        s.store.execute('INSERT INTO research_outputs VALUES(?,?,?,?,?,?,?)',(None,None,'chapter','{}','validated','',utcnow()))
        s.store.execute('INSERT INTO research_runs VALUES(?,?,?,?,?,?,?)',('child',None,'company','{}','running',utcnow(),None))
        s.store.execute('INSERT INTO research_sections VALUES(?,?,?,?)',('child','business','{}','done'))
        entered.set();release.wait(3)
        # Even a late write without a checkpoint cannot persist a cancelled report.
        return report(s.store)
    jid=s.submit('portfolio',work)
    assert entered.wait(3)
    assert s.cancel_job(jid)['accepted']
    assert s.store.rows('SELECT id FROM reports')==[{'id':old}]
    assert not s.store.rows('SELECT * FROM research_runs')
    assert not s.store.rows('SELECT * FROM research_sections')
    assert not s.store.rows('SELECT * FROM research_outputs')
    release.set();s.executor.shutdown(wait=True)
    row=s.store.rows('SELECT * FROM jobs WHERE id=?',(jid,))[0]
    assert row['status']=='cancelled' and row['result_id'] is None
    assert s.store.rows('SELECT id FROM reports')==[{'id':old}]


def test_queued_cancel_does_not_run_and_finished_job_keeps_report(tmp_path):
    s=service(tmp_path);release=threading.Event();started=threading.Event();count=[]
    def block():
        count.append(1)
        if len(count)==2:started.set()
        release.wait(3)
    s.submit('block',block);s.submit('block',block)
    assert started.wait(3)
    work=Mock();jid=s.submit('research',work)
    assert s.cancel_job(jid)['accepted']
    assert s.store.rows('SELECT status FROM jobs WHERE id=?',(jid,))[0]['status']=='cancelled'
    release.set();s.executor.shutdown(wait=True);work.assert_not_called()
    s2=service(tmp_path/'finished');jid=s2.submit('research',lambda:report(s2.store));s2.executor.shutdown(wait=True)
    assert not s2.cancel_job(jid)['accepted']
    assert len(s2.store.rows('SELECT * FROM reports'))==1


def test_cancel_after_usage_keeps_charge_and_stops_next_call(tmp_path):
    s=service(tmp_path);entered,release=threading.Event(),threading.Event()
    def completion(*args):
        entered.set();release.wait(3)
        return {},{'prompt_tokens':1000,'completion_tokens':100}
    s.kimi.complete.side_effect=completion
    def work():
        s.ai_call([{'role':'user','content':'test'}]);s.ai_call([]);return report(s.store)
    jid=s.submit('research',work);assert entered.wait(3);s.cancel_job(jid);release.set();s.executor.shutdown(wait=True)
    assert s.kimi.complete.call_count==1
    assert not s.store.rows('SELECT * FROM reports')
    expense=s.store.rows('SELECT * FROM expenses')[0]
    assert expense['status']=='charged' and Decimal(expense['amount'])==Decimal('0.0092')


def test_cancel_unknown_network_result_retains_reservation(tmp_path):
    s=service(tmp_path);entered,release=threading.Event(),threading.Event()
    def completion(*args):
        entered.set();release.wait(3);raise ProviderError('network interrupted')
    s.kimi.complete.side_effect=completion
    jid=s.submit('followup',lambda:s.ai_call([]));assert entered.wait(3);s.cancel_job(jid);release.set();s.executor.shutdown(wait=True)
    assert s.store.rows('SELECT * FROM expenses')[0]['status']=='reserved'
    assert s.store.rows('SELECT status FROM jobs WHERE id=?',(jid,))[0]['status']=='cancelled'


def table(model='kimi-k2.6',input_rate='9.25'):
    columns=['模型','计费单位','输入价格（缓存命中）','输入价格（缓存未命中）','输出价格','上下文窗口']
    return '<DocTable columns={['+','.join('{ title: '+json.dumps(c,ensure_ascii=False)+' }' for c in columns)+']} rows={'+json.dumps([[model,'1M tokens','¥1.25','¥'+input_rate,'¥30.00','262,144 tokens']],ensure_ascii=False)+'} />'


def test_official_rates_follow_response_and_ignore_unsupported_models():
    rates=parse_official_rates(table())
    profile=select_api_profile([{'id':'kimi-k2.6','context_length':260000}],rates)
    assert profile['input_price']=='9.25' and profile['context_length']==260000
    assert usage_cost({**profile,'pricing_mode':'provider'},{'prompt_tokens':1000,'completion_tokens':100,'cached_tokens':600})==Decimal('0.00745')
    with pytest.raises(ValueError):parse_official_rates(table(input_rate='invalid'))
    with pytest.raises(ValueError):select_api_profile([{'id':'unknown-new-model'}],rates)


def test_automatic_profile_gets_models_and_public_rates_without_chat(tmp_path):
    credentials=Credentials();credentials.memory['kimi']='fake-key'
    k=Kimi(credentials);calls=[]
    def handle(request):
        calls.append(request)
        if request.url.host=='api.moonshot.cn':
            return httpx.Response(200,json={'data':[{'id':'kimi-k2.6','context_length':250000}]})
        assert 'authorization' not in request.headers
        return httpx.Response(200,text=table())
    k.client=httpx.Client(transport=httpx.MockTransport(handle))
    s=Services(Store(tmp_path),Mock(),k,Mock(),credentials)
    s.sync_model_profile(force=True);cfg=s.store.settings()
    assert cfg['pricing_mode']=='provider' and cfg['input_price']=='9.25'
    assert cfg['context_length']==250000
    s.sync_model_profile();assert len(calls)==2
    assert all(r.method=='GET' for r in calls)
    s.close();k.client.close()


def test_model_auth_failure_blocks_paid_calls(tmp_path):
    credentials=Credentials();credentials.memory['kimi']='fake-key';k=Kimi(credentials)
    k.client=httpx.Client(transport=httpx.MockTransport(lambda r:httpx.Response(401,json={})))
    s=Services(Store(tmp_path),Mock(),k,Mock(),credentials)
    with pytest.raises(ProviderError):s.ai_call([])
    assert not s.store.rows('SELECT * FROM expenses')
    assert s.store.settings()['model_sync']['status']=='unavailable'
    s.close();k.client.close()


def test_cancel_endpoint_requires_csrf_and_is_idempotent(tmp_path):
    app=create_app(tmp_path,scheduler=False);s=app.state.services
    entered,release=threading.Event(),threading.Event()
    def work():entered.set();release.wait(3);s.check_cancelled()
    with TestClient(app) as c:
        jid=s.submit('research',work);assert entered.wait(3)
        assert c.post('/api/jobs/'+jid+'/cancel',json={}).status_code==403
        token=c.get('/api/bootstrap').json()['csrf']
        assert c.post('/api/jobs/'+jid+'/cancel',json={},headers={'X-App-Token':token}).json()['accepted']
        release.set();s.executor.shutdown(wait=True)
        assert c.post('/api/jobs/'+jid+'/cancel',json={},headers={'X-App-Token':token}).json()=={'accepted':False}


def test_settings_save_cannot_overwrite_managed_api_parameters(tmp_path):
    app=create_app(tmp_path,scheduler=False)
    with TestClient(app) as c:
        app.state.store.save_settings({'pricing_mode':'provider','provider_profile':{**PROFILE,'input_price':'9.25','output_price':'30'},'model_sync':{'status':'ready','checked_at':utcnow()}})
        csrf=c.get('/api/bootstrap').json()['csrf']
        result=c.put('/api/settings',json={'pricing_mode':'builtin','input_price':'1','output_price':'1','monthly_limit':'20'},headers={'X-App-Token':csrf})
        assert result.status_code==200
        settings=result.json()['settings']
        assert settings['pricing_mode']=='provider' and settings['input_price']=='9.25'
        assert settings['monthly_limit']=='20'


def test_cancelled_control_closes_only_its_registered_transport(tmp_path):
    s=service(tmp_path);entered,release=threading.Event(),threading.Event();closed=threading.Event()
    def work():
        control=s.job_context.control
        control.register(closed.set)
        entered.set();release.wait(3);control.check()
    jid=s.submit('research',work);assert entered.wait(3)
    s.cancel_job(jid);assert closed.wait(3)
    release.set();s.executor.shutdown(wait=True)
    assert s.store.rows('SELECT status FROM jobs WHERE id=?',(jid,))[0]['status']=='cancelled'
