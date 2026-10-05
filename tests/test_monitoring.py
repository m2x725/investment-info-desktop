import json
from datetime import timedelta
from unittest.mock import Mock
import pytest
from backend.services import beijing_now
from backend.providers import ProviderError
from backend.collection import choose
from test_mvp import service


def test_collection_every_thirty_minutes_even_at_night_without_accounts(tmp_path):
    s=service(tmp_path)
    assert s.store.settings()['scheduler_enabled']
    s.refresh=Mock(return_value=[])
    now=beijing_now().replace(hour=23,minute=0,second=0,microsecond=0)
    s.tick(now)
    s.tick(now+timedelta(minutes=29))
    assert s.refresh.call_count==1
    s.tick(now+timedelta(minutes=30))
    assert s.refresh.call_count==2
    assert s.push.send.call_count==0
    s.store.save_settings({'scheduler_paused':True})
    s.tick(now+timedelta(minutes=60))
    assert s.refresh.call_count==2
    s.close()


def test_important_disclosures_sorted_and_deduplicated_not_aggregated(tmp_path):
    s=service(tmp_path)
    sid=s.store.add_security(dict(exchange='SH',ticker='600519',name='测试公司'))
    s.store.execute('INSERT INTO watchlist VALUES(?)',(sid,))
    day=str(beijing_now().date())
    for i,(title,verification) in enumerate([('翌日披露报表','official_download'),('关于立案调查的公告','title_only'),('自动财务指标','aggregated')]):
        s.store.execute('INSERT INTO evidence(security_id,title,url,published_at,content,kind,verification,fetched_at) VALUES(?,?,?,?,?,?,?,?)',
            (sid,title,f'https://example.com/{i}',day,title,'announcement',verification,beijing_now().isoformat()))
    alerts=s.alerts()
    assert len(alerts)==2 and alerts[0]['priority']=='high'
    assert '仅有标题' in alerts[0]['text'] and '尚未确认' in alerts[0]['text']
    rid=s.brief()
    payload=json.loads(s.store.rows('SELECT payload FROM reports WHERE id=?',(rid,))[0]['payload'])
    assert len(payload['important'])==1
    s.store.save_settings({'push_enabled':True,'last_daily_day':day})
    # This test isolates event delivery: today's daily digest was already sent.
    s.store.execute("INSERT INTO notifications(dedupe_key,day,status,title,content,message,created_at) VALUES(?,?,?,?,?,?,?)",(f'daily:{day}',day,'accepted','日报','','已发送',beijing_now().isoformat()))
    s.credentials.memory['push']='test'
    s.refresh=Mock(return_value=[])
    s.push.send.side_effect=ProviderError('timeout')
    now=beijing_now()
    with pytest.raises(ProviderError):s.tick(now)
    s.tick(now+timedelta(minutes=1))
    assert s.refresh.call_count==1 and s.push.send.call_count==1
    assert s.store.rows("SELECT status FROM notifications WHERE dedupe_key NOT LIKE 'daily:%'")[0]['status']=='unknown'
    s.close()


def test_important_notice_selected_ahead_of_routine_notice():
    rows=[dict(title=t,url=str(i)) for i,t in enumerate(['2025年度报告','2026半年度报告','普通公告1','普通公告2','盈利警告'])]
    assert any(r['title']=='盈利警告' for r in choose(rows))


def test_citation_diagnostics_and_canonical_id_do_not_relax_source_checks():
    from backend.services import strict_validate_report as validate_report
    evidence=[dict(id=1,content='公司收入来自业务服务，仍存在经营风险。')]
    report=dict(title='研究',summary='仍需核对',facts=[dict(text='公司收入来自业务服务',evidence_id='1')],
        support=[dict(text='经营业务服务',evidence_ids=[1])],risks=[dict(text='存在经营风险',evidence_ids=[1])],unknowns=['完整性未知']*25,assumptions=[])
    assert validate_report(report,evidence)['facts'][0]['evidence_id']==1
    with pytest.raises(ProviderError,match='来源编号'):
        validate_report({**report,'facts':[dict(text='公司收入来自业务服务',evidence_id='99')]},evidence)
    with pytest.raises(ProviderError,match='原文中找到'):
        validate_report({**report,'facts':[dict(text='字'*2001,evidence_id=1)]},evidence)
    with pytest.raises(ProviderError,match='原文中找到'):
        validate_report({**report,'facts':[dict(text='这不是实际来源原文',evidence_id='1')]},evidence)


def test_long_report_is_fully_verified_and_preserved():
    from backend.services import strict_validate_report as validate_report
    quote='公司收入来自业务服务。'*300
    evidence=[dict(id=1,content=quote,locator='章节')]
    report=dict(title='研究',summary='需要核对。'*500,facts=[dict(text=quote,evidence_id=1)],
        support=[],risks=[dict(text='资料覆盖有限',evidence_ids=[1])],unknowns=['完整性未知']*25,assumptions=[])
    facts=validate_report(report,evidence)['facts']
    assert len(facts)==1 and facts[0]['text']==quote
    validated=validate_report(report,evidence)
    assert validated['summary']==report['summary'] and len(validated['unknowns'])==25
    assert ''.join(f['text'] for f in facts)==quote
    with pytest.raises(ProviderError,match='原文中找到'):
        validate_report({**report,'facts':[dict(text=quote+'虚构尾句',evidence_id=1)]},evidence)


def test_saved_daily_digest_delivered_after_time_change_without_regeneration(tmp_path):
    s=service(tmp_path)
    now=beijing_now().replace(hour=14,minute=21,second=0,microsecond=0)
    day=str(now.date())
    payload={'title':f'{day} 今日关注','items':[{'title':'业务更新','date':day,'text':'已保存要点','url':'https://example.com'}],'notes':[]}
    s.store.execute("INSERT INTO reports(kind,payload,evidence_ids,created_at) VALUES(?,?,?,?)",('brief',json.dumps(payload),'[]',now.isoformat()))
    s.store.save_settings({'last_daily_day':day,'daily_time':'14:20','push_enabled':True,'last_tick':now.isoformat()})
    s.credentials.memory['push']='test'
    s.refresh=Mock()
    s.brief=Mock()
    s.tick(now)
    assert s.push.send.call_count==1
    assert '已保存要点' in s.push.send.call_args.args[1]
    assert 'https://example.com' in s.push.send.call_args.args[1]
    s.brief.assert_not_called()
    s.tick(now+timedelta(minutes=1))
    assert s.push.send.call_count==1
    s.store.save_settings({'daily_time':'14:22'})
    s.tick(now+timedelta(minutes=2))
    assert s.push.send.call_count==1
    s.close()


def test_saved_daily_digest_respects_future_time_and_unknown_delivery(tmp_path):
    s=service(tmp_path)
    now=beijing_now().replace(hour=14,minute=19,second=0,microsecond=0)
    day=str(now.date())
    payload={'title':f'{day} 今日关注','items':[],'notes':[]}
    s.store.execute("INSERT INTO reports(kind,payload,evidence_ids,created_at) VALUES(?,?,?,?)",('brief',json.dumps(payload),'[]',now.isoformat()))
    s.store.save_settings({'last_daily_day':day,'daily_time':'14:20','push_enabled':True,'last_tick':now.isoformat()})
    s.credentials.memory['push']='test'
    s.refresh=Mock()
    s.tick(now)
    s.push.send.assert_not_called()
    s.push.send.side_effect=ProviderError('推送结果不明')
    with pytest.raises(ProviderError):s.tick(now+timedelta(minutes=1))
    s.tick(now+timedelta(minutes=2))
    assert s.push.send.call_count==1
    s.close()


def test_multiple_brief_slots_and_changed_time_are_independent(tmp_path):
    s=service(tmp_path);now=beijing_now().replace(hour=8,minute=0,second=0,microsecond=0)
    s.store.save_settings({'daily_times':['08:00','12:00'],'push_enabled':True})
    s.credentials.memory['push']='test';s.refresh=Mock()
    s.scheduled_briefs(now,s.store.settings())
    s.scheduled_briefs(now+timedelta(minutes=1),s.store.settings())
    assert s.push.send.call_count==1
    s.scheduled_briefs(now.replace(hour=12),s.store.settings())
    assert s.push.send.call_count==2
    keys=[r['dedupe_key'] for r in s.store.rows('SELECT dedupe_key FROM notifications')]
    assert keys==[f'daily:{now.date()}:08:00',f'daily:{now.date()}:12:00']
    s.store.save_settings({'daily_times':['08:00','12:00','12:05']})
    s.scheduled_briefs(now.replace(hour=12,minute=5),s.store.settings())
    assert s.push.send.call_count==3
    assert len(s.store.rows("SELECT id FROM reports WHERE kind='brief'"))==3
    s.close()


def test_sleep_catches_up_latest_slot_without_burst_and_late_key_uses_saved(tmp_path):
    s=service(tmp_path);now=beijing_now().replace(hour=13,minute=0,second=0,microsecond=0)
    s.store.save_settings({'daily_times':['08:00','12:00','18:00'],'push_enabled':True})
    s.refresh=Mock();s.scheduled_briefs(now,s.store.settings())
    assert len(s.store.rows("SELECT id FROM reports WHERE kind='brief'"))==1
    assert s.store.settings()[f'brief_slot:{now.date()}:08:00']['status']=='skipped'
    s.credentials.memory['push']='test';s.scheduled_briefs(now,s.store.settings())
    assert s.push.send.call_count==1
    assert len(s.store.rows("SELECT id FROM reports WHERE kind='brief'"))==1
    s.close()


def test_failed_ai_falls_back_and_does_not_retry(tmp_path):
    s=service(tmp_path);now=beijing_now().replace(hour=8,minute=0,second=0,microsecond=0)
    s.store.save_settings({'daily_times':['08:00','12:00'],'auto_research':True,'push_enabled':True})
    s.credentials.memory['push']='test';s.refresh=Mock()
    original=s.brief
    def failing_ai(**kwargs):
        if kwargs.get('analyze') is not False:raise ProviderError('模型结果不明')
        return original(**kwargs)
    s.brief=Mock(side_effect=failing_ai)
    s.scheduled_briefs(now,s.store.settings())
    s.scheduled_briefs(now+timedelta(minutes=1),s.store.settings())
    assert s.brief.call_count==2 and s.push.send.call_count==1
    assert 'AI分析未完成' in s.push.send.call_args.args[1]
    s.scheduled_briefs(now.replace(hour=12),s.store.settings())
    assert s.brief.call_count==4 and s.push.send.call_count==2
    s.close()


def test_missing_kimi_sends_source_digest_and_recovers_old_failed_slot(tmp_path):
    s=service(tmp_path);now=beijing_now().replace(hour=8,minute=0,second=0,microsecond=0)
    s.store.save_settings({'daily_times':['08:00','12:00'],'auto_research':True,'push_enabled':True})
    s.credentials.memory.pop('kimi',None);s.credentials.memory['push']='test';s.refresh=Mock()
    s.ai_call=Mock(side_effect=AssertionError('must not call AI'))
    s.scheduled_briefs(now,s.store.settings())
    assert s.push.send.call_count==1 and 'Kimi未配置' in s.push.send.call_args.args[1]
    s.store.save_settings({f'brief_slot:{now.date()}:12:00':{'status':'failed'}})
    s.scheduled_briefs(now.replace(hour=12),s.store.settings())
    assert s.push.send.call_count==2 and '未重新调用AI' in s.push.send.call_args.args[1]
    s.ai_call.assert_not_called();s.close()


def test_brief_times_validation():
    from backend.domain import Settings
    assert Settings(daily_times=['18:00','08:00','08:00']).daily_times==['08:00','18:00']
    for times in [[],['25:00'],['08:60'],['8:00']]:
        with pytest.raises(ValueError):Settings(daily_times=times)


def test_no_local_total_push_cap_even_with_old_setting(tmp_path):
    s=service(tmp_path)
    s.store.save_settings({'push_enabled':True,'push_daily_limit':1})
    s.credentials.memory['push']='test'
    for i in range(8):assert s.notify(f'test:uncapped:{i}','测试','模拟消息')=='accepted'
    assert s.push.send.call_count==8
    assert s.notify('test:uncapped:0','测试','模拟消息')=='accepted'
    assert s.push.send.call_count==8
    s.close()
