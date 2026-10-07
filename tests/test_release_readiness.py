import json
import threading
import time
from unittest.mock import Mock
import pytest
from backend.services import beijing_now
from backend.storage import utcnow
from backend.providers import ProviderError
from backend.domain import quote_stale
from test_mvp import service


def wait_for(predicate):
    end=time.monotonic()+3
    while not predicate():
        assert time.monotonic()<end
        time.sleep(.01)


def test_close_cancels_active_and_queued_jobs_without_late_report(tmp_path):
    s=service(tmp_path);started=threading.Event()
    history=s.store.execute('INSERT INTO reports(kind,payload,evidence_ids,created_at) VALUES(?,?,?,?)',('research','{}','[]',utcnow()))
    def work():
        started.set()
        while True:
            s.check_cancelled();time.sleep(.01)
    jid=s.submit('research',work);assert started.wait(2)
    s.close()
    assert s.job_details(jid)['status']=='cancelled'
    assert not s.job_controls
    assert [r['id'] for r in s.store.rows('SELECT id FROM reports')]==[history]
    with pytest.raises(ProviderError):s.submit('research',lambda:None)


def test_interrupted_slot_recovers_without_ai_or_refresh(tmp_path):
    s=service(tmp_path);now=beijing_now().replace(hour=14,minute=0)
    key=f'brief_slot:{now.date()}:13:00'
    s.store.save_settings({'daily_times':['13:00'],'push_enabled':True,key:{'status':'generating'}})
    s.credentials.memory['push']='mock';s.ai_call=Mock();s.refresh=Mock()
    s.scheduled_briefs(now,s.store.settings())
    assert s.store.settings()[key]['status']=='saved'
    assert s.push.send.call_count==1
    s.ai_call.assert_not_called();s.refresh.assert_not_called()
    s.scheduled_briefs(now,s.store.settings());assert s.push.send.call_count==1
    s.close()


def test_important_alerts_have_no_daily_three_item_cap(tmp_path):
    s=service(tmp_path);now=beijing_now().replace(hour=0,minute=0)
    s.store.save_settings({'push_enabled':True,'daily_times':['23:59'],'last_tick':now.isoformat()})
    s.credentials.memory['push']='mock';s.refresh_fx=Mock();s.scan_import_folder=Mock()
    s.alerts=Mock(return_value=[dict(key=f'a:{i}',priority='high',title=str(i),reason='模拟',text='内容') for i in range(5)])
    s.tick(now);s.tick(now)
    assert s.push.send.call_count==5
    s.close()


def test_partial_report_job_is_not_complete_and_preview_points_to_saved(tmp_path):
    s=service(tmp_path)
    payload={'coverage':{'completed_sections':4,'total_sections':6}}
    def work():return s.store.execute('INSERT INTO reports(kind,payload,evidence_ids,created_at) VALUES(?,?,?,?)',('research',json.dumps(payload),'[]',utcnow()))
    jid=s.submit('research',work)
    wait_for(lambda:s.job_details(jid)['status']=='partial')
    detail=s.job_details(jid)
    assert detail['progress']==66 and detail['completed_sections']==4
    assert s.job_preview(jid)['report_id']==detail['result_id']
    s.close()


def test_push_rejection_retries_but_unknown_is_not_automatically_repeated(tmp_path):
    s=service(tmp_path);s.store.save_settings({'push_enabled':True});s.credentials.memory['push']='mock'
    s.push.send.side_effect=ProviderError('明确拒绝',unbilled=True)
    with pytest.raises(ProviderError):s.notify('a','标题','保存内容')
    assert s.store.rows('SELECT status FROM notifications')[0]['status']=='rejected'
    s.push.send.side_effect=None
    assert s.notify('a','标题','保存内容')=='rejected'
    assert s.push.send.call_count==1
    s.store.execute("UPDATE notifications SET created_at='2000-01-01T00:00:00+00:00' WHERE dedupe_key='a'")
    s.notify('a','标题','保存内容')
    assert s.push.send.call_count==2
    s.push.send.side_effect=ProviderError('结果不明')
    with pytest.raises(ProviderError):s.notify('b','标题','保存内容')
    assert s.notify('b','标题','保存内容')=='unknown' and s.push.send.call_count==3
    nid=s.store.rows("SELECT id FROM notifications WHERE dedupe_key='b'")[0]['id']
    s.push.send.side_effect=None;s.resend_notification(nid)
    assert s.push.send.call_args.args==('标题','保存内容')
    assert s.push.send.call_count==4
    s.close()


def test_independent_schedule_delivers_while_collection_is_blocked(tmp_path):
    s=service(tmp_path);entered=threading.Event();sent=threading.Event()
    def blocked(**kwargs):
        entered.set()
        while True:s.check_cancelled();time.sleep(.01)
    s.store.save_settings({'daily_times':['00:00']})
    s.tick=blocked;s.scheduled_briefs=Mock(side_effect=lambda *a,**kw:sent.set())
    s.start_scheduler()
    assert entered.wait(2) and sent.wait(2)
    s.close();assert not s.scheduler.is_alive() and not s.brief_scheduler.is_alive()


def test_missing_and_old_quotes_share_freshness_rule():
    assert quote_stale(None)
    assert quote_stale({'as_of':'2000-01-01'})
    assert not quote_stale({'as_of':str(beijing_now().date())})
    assert quote_stale({'as_of':'invalid'})


def test_rejected_push_stops_automatic_retry_after_three_attempts(tmp_path):
    s=service(tmp_path);s.store.save_settings({'push_enabled':True});s.credentials.memory['push']='mock'
    s.push.send.side_effect=ProviderError('明确拒绝',unbilled=True)
    for i in range(3):
        with pytest.raises(ProviderError):s.notify('limited','标题','内容')
        s.store.execute("UPDATE notifications SET created_at='2000-01-01T00:00:00+00:00' WHERE dedupe_key='limited'")
    assert s.notify('limited','标题','内容')=='rejected'
    assert s.push.send.call_count==3
    s.close()


def test_saved_slot_with_deleted_report_is_recovered(tmp_path):
    s=service(tmp_path);now=beijing_now().replace(hour=14,minute=0)
    key=f'brief_slot:{now.date()}:13:00'
    s.store.save_settings({'daily_times':['13:00'],key:{'status':'saved','report_id':999}})
    s.ai_call=Mock();s.scheduled_briefs(now,s.store.settings(),refresh=False)
    rid=s.store.settings()[key]['report_id']
    assert rid!=999 and s.store.rows('SELECT id FROM reports WHERE id=?',(rid,))
    s.ai_call.assert_not_called();s.close()


def test_native_exit_stops_tasks_before_closing_window():
    from backend.desktop import WindowController
    from types import SimpleNamespace
    order=[]
    window=SimpleNamespace(destroy=lambda:order.append('destroy'))
    controller=WindowController(window,SimpleNamespace(should_exit=False),lambda:order.append('stop'))
    controller.quit();controller.quit()
    assert order==['stop','destroy']


def test_bootstrap_recovers_active_user_task_and_resend_requires_confirmation(tmp_path):
    from backend.main import create_app
    from fastapi.testclient import TestClient
    app=create_app(tmp_path,scheduler=False);s=app.state.services
    started=threading.Event()
    def work():
        started.set()
        while True:s.check_cancelled();time.sleep(.01)
    with TestClient(app) as client:
        jid=s.submit('research',work);assert started.wait(2)
        data=client.get('/api/bootstrap').json()
        assert data['active_jobs'][0]['id']==jid
        response=client.post('/api/notifications/1/resend',json={},headers={'X-App-Token':data['csrf']})
        assert response.status_code==400
        s.cancel_job(jid)


def test_backup_integrity_and_existing_reports_preserved(tmp_path):
    import sqlite3
    s=service(tmp_path)
    rid=s.store.execute('INSERT INTO reports(kind,payload,evidence_ids,created_at) VALUES(?,?,?,?)',('research','{}','[]',utcnow()))
    path=s.store.backup()
    with sqlite3.connect(path) as db:
        assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        assert db.execute('SELECT id FROM reports').fetchone()[0]==rid
    s.close()
