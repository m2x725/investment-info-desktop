import asyncio,json,threading,time,subprocess,sys
from unittest.mock import Mock
import httpx
import pytest
from fastapi.testclient import TestClient
from backend.cancellation import JobControl,JobCancelled
from backend.task_io import bind_control,wait_process,cancellable_lock,async_request
from backend.providers import Credentials,Kimi,ProviderError
from backend.services import Services
from backend.storage import Store,utcnow
from backend.research_engine import ResearchEngine,SECTIONS
from backend import performance_cache as cache


def service(tmp_path,real=False):
    cred=Credentials();cred.memory['kimi']='mock-key'
    s=Services(Store(tmp_path),Mock(),Kimi(cred) if real else Mock(),Mock(),cred)
    s.store.save_settings({'monthly_limit':'20','online_research':False,'prices_confirmed':True,
                          'model_sync':{'status':'ready','checked_at':utcnow()}})
    s.collect_company=Mock();s.collect_financial_history=Mock()
    return s


def sample(s):
    sid=s.store.add_security({'exchange':'HK','ticker':'00700','name':'模拟公司'})
    eid=s.store.execute('INSERT INTO evidence(security_id,title,url,published_at,content,kind,verification,fetched_at) VALUES(?,?,?,?,?,?,?,?)',
        (sid,'模拟年报','https://example.com/annual','2026-01-01','公司收入100。现金流良好，风险是行业竞争。','financial','official_download',utcnow()))
    return sid,eid


def answer(eid):
    return {'title':'模拟章节','summary':'公司收入结构及行业竞争需要持续观察。','facts':[{'text':'公司收入100。','evidence_id':eid}],
            'support':[],'risks':[],'unknowns':['模拟资料'],'assumptions':[]}


def until(predicate,timeout=3):
    end=time.monotonic()+timeout
    while time.monotonic()<end:
        if predicate():return
        time.sleep(.01)
    assert predicate(), 'condition not reached'


@pytest.mark.parametrize('method',['GET','POST'])
def test_blocked_async_transport_interrupts_in_two_seconds(method):
    control=JobControl();entered=threading.Event();stopped=threading.Event();errors=[]
    async def handler(request):
        entered.set()
        try:await asyncio.sleep(60)
        finally:stopped.set()
        return httpx.Response(200,json={})
    client=httpx.Client(transport=httpx.MockTransport(handler))
    def work():
        try:async_request(client,method,'https://example.com',control)
        except BaseException as exc:errors.append(exc)
    thread=threading.Thread(target=work);thread.start();assert entered.wait(2)
    start=time.monotonic();control.cancelled.set()
    for closer in list(control.closers):closer()
    thread.join(2)
    assert not thread.is_alive() and stopped.is_set() and time.monotonic()-start<2
    assert isinstance(errors[0],JobCancelled if method=='GET' else httpx.ReadError)
    client.close()


def test_api_ack_immediate_while_resource_cleanup_pending(tmp_path):
    from backend.main import create_app
    app=create_app(tmp_path,scheduler=False);s=app.state.services
    entered,release=threading.Event(),threading.Event()
    def work():entered.set();release.wait(3);s.check_cancelled()
    with TestClient(app) as c:
        jid=s.submit('research',work);assert entered.wait(2)
        token=c.get('/api/bootstrap').json()['csrf'];start=time.monotonic()
        ack=c.post('/api/jobs/'+jid+'/cancel',json={},headers={'X-App-Token':token}).json()
        assert time.monotonic()-start<1 and ack['status']=='cancelled' and ack['cleanup_pending']
        assert c.get('/api/jobs/'+jid).json()['cleanup_pending']
        assert c.get('/api/jobs/'+jid+'/preview').json()=={'available':False}
        release.set();until(lambda:not s.job_details(jid)['cleanup_pending'])


def test_subprocess_cancel_terminates_and_reaps():
    control=JobControl();entered=threading.Event();errors=[]
    process=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)'])
    def work():
        with bind_control(control):
            entered.set()
            try:wait_process(process,60)
            except BaseException as exc:errors.append(exc)
    thread=threading.Thread(target=work);thread.start();assert entered.wait(1)
    start=time.monotonic();control.cancelled.set();thread.join(2)
    assert not thread.is_alive() and process.poll() is not None and time.monotonic()-start<2
    assert isinstance(errors[0],JobCancelled)


def test_lock_wait_cancel_preserves_owner_lock():
    lock=threading.Lock();lock.acquire();control=JobControl();errors=[]
    def work():
        try:
            with cancellable_lock(lock,control):pass
        except BaseException as exc:errors.append(exc)
    thread=threading.Thread(target=work);thread.start();control.cancelled.set();thread.join(2)
    assert isinstance(errors[0],JobCancelled) and lock.locked()
    lock.release()


def test_real_kimi_transport_cancel_retains_unknown_billing_and_allows_next_job(tmp_path):
    s=service(tmp_path,real=True);entered=threading.Event()
    async def handler(request):entered.set();await asyncio.sleep(60);return httpx.Response(200,json={})
    s.kimi.client.close();s.kimi.client=httpx.Client(transport=httpx.MockTransport(handler))
    jid=s.submit('followup',lambda:s.ai_call([{'role':'user','content':'mock'}]))
    assert entered.wait(2);start=time.monotonic();s.cancel_job(jid)
    until(lambda:jid not in s.job_controls)
    assert time.monotonic()-start<2
    assert s.store.rows('SELECT status FROM expenses')[0]['status']=='reserved'
    nextjob=s.submit('test',lambda:None);until(lambda:s.job_details(nextjob)['status']=='done')
    s.close();s.kimi.client.close()


def test_parallel_chapters_preview_dependency_and_cancellation(tmp_path):
    s=service(tmp_path);sid,eid=sample(s);business_done=threading.Event();release=threading.Event()
    calls=[];active=0;maximum=0;lock=threading.Lock()
    def complete(model,messages):
        nonlocal active,maximum
        payload=json.loads(messages[1]['content']);chapter=payload['chapter']
        with lock:active+=1;maximum=max(maximum,active);calls.append(chapter)
        try:
            if chapter==SECTIONS[0][1]:time.sleep(.05);business_done.set()
            else:
                control=s.job_context.control
                while not release.wait(.02):
                    if control.cancelled.is_set():raise ProviderError('mock interrupted')
            return answer(eid),{'prompt_tokens':100,'completion_tokens':100}
        finally:
            with lock:active-=1
    s.kimi.complete.side_effect=complete
    jid=s.submit('research',lambda:s.research(sid,'完整研究'))
    assert business_done.wait(2)
    until(lambda:s.job_details(jid)['completed_sections']>=1)
    preview=s.job_preview(jid)
    assert preview['available'] and preview['preview'] and preview['payload']['coverage']['total_sections']==6
    assert preview['payload']['sections'][0]['report']['summary']
    assert SECTIONS[-1][1] not in calls and maximum==2
    start=time.monotonic();s.cancel_job(jid);until(lambda:jid not in s.job_controls)
    assert time.monotonic()-start<2 and s.job_preview(jid)=={'available':False}
    assert not s.store.rows('SELECT * FROM reports') and not s.store.rows('SELECT * FROM research_sections')
    s.close()


def test_fixed_delay_benchmark_and_complete_countercase(tmp_path):
    s=service(tmp_path);sid,eid=sample(s);calls=[];active=0;maximum=0;lock=threading.Lock()
    def complete(model,messages):
        nonlocal active,maximum
        data=json.loads(messages[1]['content'])
        if data['chapter']==SECTIONS[-1][1]:assert len(data['completed_chapters'])==5
        with lock:active+=1;maximum=max(maximum,active);calls.append(data['chapter'])
        time.sleep(.2)
        with lock:active-=1
        return answer(eid),{'prompt_tokens':100,'completion_tokens':100}
    s.kimi.complete.side_effect=complete
    parallel=s.parallel
    s.parallel=lambda items,func,workers=2:[func(item) for item in items]
    start=time.monotonic();serial=s.submit('research',lambda:s.research(sid,'研究'))
    until(lambda:s.job_details(serial)['status'] in ('done','failed'))
    assert s.job_details(serial)['status']=='done'
    baseline=time.monotonic()-start
    s.parallel=parallel;calls.clear();maximum=0
    start=time.monotonic();jid=s.submit('research',lambda:s.research(sid,'研究'))
    until(lambda:s.job_details(jid)['status'] in ('done','failed'))
    details=s.job_details(jid);elapsed=time.monotonic()-start
    assert details['status']=='done' and maximum==2 and len(calls)==6
    assert details['stage_seconds']['first_result']<elapsed
    payload=json.loads(s.store.rows('SELECT payload FROM reports')[0]['payload'])
    assert payload['coverage']['completed_sections']==6
    print(f'BENCH serial={baseline:.3f}s concurrent={elapsed:.3f}s first_result={details["stage_seconds"]["first_result"]:.3f}s')
    assert elapsed<baseline*.95
    s.close()


def test_versioned_cache_expiry_and_source_identity(tmp_path):
    s=service(tmp_path)
    cache.put(s.store,'tool',['company','history','v1'],{'ok':True},604800)
    assert cache.get(s.store,'tool',['company','history','v1'])=={'ok':True}
    assert cache.get(s.store,'tool',['other','history','v1']) is None
    assert cache.get(s.store,'tool',['company','history','v2']) is None
    s.store.execute("UPDATE performance_cache SET expires_at='2000-01-01'")
    assert cache.get(s.store,'tool',['company','history','v1']) is None
    assert cache.canonical_url('https://EXAMPLE.com/x?b=2&a=1#fragment')=='https://example.com/x?a=1&b=2'
    s.close()


def test_tool_cache_ttl_and_failed_result_not_cached(tmp_path):
    s=service(tmp_path);engine=ResearchEngine(s);s.kimi.tool.return_value={'search_results':[{'title':'模拟资料'}]}
    engine.tool('search_pro',{'text_query':'history'},identity='HK:00700',ttl=604800)
    engine.tool('search_pro',{'text_query':'history'},identity='HK:00700',ttl=604800)
    assert s.kimi.tool.call_count==1
    s.kimi.tool.return_value={}
    engine.tool('fetch',{'url':'https://example.com/empty'});engine.tool('fetch',{'url':'https://example.com/empty'})
    assert s.kimi.tool.call_count==3
    s.close()


def test_migration_backup_and_old_reports_survive(tmp_path):
    import sqlite3
    s=service(tmp_path);old=s.store.execute('INSERT INTO reports(kind,payload,evidence_ids,created_at) VALUES(?,?,?,?)',('research','{}','[]',utcnow()));s.close()
    with sqlite3.connect(tmp_path/'portfolio.db') as db:
        db.execute('DROP TABLE performance_cache');db.execute('ALTER TABLE jobs DROP COLUMN metadata')
    store=Store(tmp_path)
    assert store.rows('SELECT id FROM reports')==[{'id':old}]
    assert list((tmp_path/'backups').glob('*.db'))
    assert store.rows('PRAGMA user_version')[0]['user_version']==3


def test_successful_financial_history_cache_and_new_report_invalidation(tmp_path,monkeypatch):
    s=service(tmp_path);sid,eid=sample(s)
    # Use actual service cache logic, mock only external process.
    s.collect_financial_history=Services.collect_financial_history.__get__(s)
    adapter=Mock(return_value=3);monkeypatch.setattr('backend.data_adapters.collect_financial_history',adapter)
    s.collect_financial_history(sid);s.collect_financial_history(sid);assert adapter.call_count==1
    s.collect_company=Services.collect_company.__get__(s)
    s.collector=Mock();s.market=Mock()
    s.market.official_text.return_value='新财报原文：公司收入100。现金流与利润说明。'
    s.collector.documents.return_value=[{'title':'新年度报告','url':'https://example.com/new','published_at':'2026-04-01','kind':'financial'}]
    s.collector.financials.side_effect=ProviderError('mock gap')
    s.collector.fx.side_effect=ProviderError('mock gap')
    s.collect_company(sid,quote=False)
    s.collect_financial_history(sid);assert adapter.call_count==2
    s.close()


def test_changed_source_revision_refetch_and_corrupt_body_not_cached(tmp_path):
    s=service(tmp_path);sid,_=sample(s);s.collect_company=Services.collect_company.__get__(s)
    s.collector=Mock();s.market=Mock()
    document={'title':'官方来源','url':'https://example.com/doc','published_at':'2026-01-01','kind':'announcement','revision':'one'}
    s.collector.documents.return_value=[document]
    s.collector.financials.side_effect=ProviderError('mock gap');s.collector.fx.side_effect=ProviderError('mock gap')
    s.market.official_text.return_value='公司收入100。现金流良好，风险是行业竞争。'
    s.collect_company(sid,False);s.collect_company(sid,False);assert s.market.official_text.call_count==1
    s.store.execute("DELETE FROM performance_cache WHERE kind='documents'");document['revision']='two'
    s.collect_company(sid,False);assert s.market.official_text.call_count==2
    s.store.execute("DELETE FROM performance_cache WHERE kind='documents'");document['revision']='three'
    s.market.official_text.return_value='[第1页]公司收入100。\n[第2页][此页文字不可读，未用作证据]'
    s.collect_company(sid,False);s.collect_company(sid,False);assert s.market.official_text.call_count==4
    s.close()


def test_pdf_limit_is_global_and_cancellable():
    from backend.task_io import PDF_LIMIT
    control=JobControl();started=threading.Event();errors=[]
    with cancellable_lock(PDF_LIMIT):
        def work():
            try:
                started.set()
                with cancellable_lock(PDF_LIMIT,control):pytest.fail('must not parse concurrently')
            except BaseException as exc:errors.append(exc)
        thread=threading.Thread(target=work);thread.start();assert started.wait(1)
        control.cancelled.set();thread.join(2)
        assert isinstance(errors[0],JobCancelled)
