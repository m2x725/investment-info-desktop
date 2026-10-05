from datetime import datetime,timezone,timedelta
from unittest.mock import Mock
import pytest
from test_mvp import service,api
from backend.providers import ProviderError
from backend.domain import portfolio

NOW=datetime(2026,10,5,3,tzinfo=timezone.utc)
def make(tmp_path):
 s=service(tmp_path);s.collector=Mock();s.collector.fx.return_value={'rate':'0.900123','as_of':'2026-10-02','source':'测试参考汇率'}
 return s

def test_latest_daily_rate_and_distinct_fetch_time(tmp_path):
 s=make(tmp_path);s.refresh_fx(now=NOW)
 p=portfolio(s.store)
 assert p['fx']['rate']=='0.900123' and p['fx']['as_of']=='2026-10-02'
 assert p['fx_metadata']['fetched_at']==NOW.isoformat()
 s.refresh_fx(now=NOW+timedelta(minutes=29));assert s.collector.fx.call_count==1
 s.refresh_fx(now=NOW+timedelta(minutes=30));assert s.collector.fx.call_count==2
 s.close()

def test_failure_retains_success_and_backoff(tmp_path):
 s=make(tmp_path);s.refresh_fx(now=NOW)
 s.collector.fx.side_effect=TimeoutError()
 with pytest.raises(ProviderError):s.refresh_fx(force=True,now=NOW+timedelta(minutes=1))
 p=portfolio(s.store)
 assert p['fx']['rate']=='0.900123' and p['fx_metadata']['fetched_at']==NOW.isoformat()
 assert p['fx_status']['status']=='failed'
 s.refresh_fx(now=NOW+timedelta(minutes=2));assert s.collector.fx.call_count==2
 s.close()

@pytest.mark.parametrize('rate,day',[('0','2026-10-02'),('NaN','2026-10-02'),('0.9','2026-10-06'),('0.9','bad')])
def test_invalid_rates_never_overwrite(tmp_path,rate,day):
 s=make(tmp_path);s.refresh_fx(now=NOW)
 s.collector.fx.return_value={'rate':rate,'as_of':day,'source':'测试来源'}
 with pytest.raises(ProviderError):s.refresh_fx(force=True,now=NOW)
 assert portfolio(s.store)['fx']['as_of']=='2026-10-02'
 s.close()

def test_older_rate_does_not_replace_newer(tmp_path):
 s=make(tmp_path);s.refresh_fx(now=NOW)
 s.collector.fx.return_value={'rate':'0.8','as_of':'2026-10-01','source':'旧来源'}
 with pytest.raises(ProviderError):s.refresh_fx(force=True,now=NOW)
 assert portfolio(s.store)['fx']['rate']=='0.900123'
 s.close()

def test_empty_account_weekend_still_updates_when_scheduler_enabled(tmp_path):
 s=make(tmp_path);s.refresh=Mock();s.brief=Mock();s.scan_import_folder=Mock();s.store.save_settings({'scheduler_enabled':True,'scheduler_paused':False})
 s.tick(NOW-timedelta(days=1))
 assert s.collector.fx.called
 s.close()

def test_fx_refresh_api_preserves_manual_fallback_and_async_job(api):
 import time
 from backend.services import beijing_now
 c,app=api
 day=str(beijing_now().date())
 assert c.post('/api/fx',json={'rate':'0.9','as_of':day,'source':'测试来源'}).status_code==200
 assert c.get('/api/bootstrap').json()['portfolio']['fx_metadata']['kind']=='manual'
 app.state.services.collector.fx=Mock(return_value={'rate':'0.900123','as_of':day,'source':'测试参考汇率'})
 r=c.post('/api/fx/refresh',json={});assert r.status_code==200
 for _ in range(100):
  job=c.get('/api/jobs/'+r.json()['job_id']).json()
  if job['status'] in ('done','failed'):break
  time.sleep(.01)
 assert job['status']=='done'
 p=c.get('/api/bootstrap').json()['portfolio']
 assert p['fx']['rate']=='0.900123' and p['fx_metadata']['kind']=='daily_reference'

def test_beijing_timestamp_does_not_add_timezone_twice(tmp_path):
 s=make(tmp_path)
 evening=datetime(2026,10,4,23,tzinfo=timezone(timedelta(hours=8)))
 s.collector.fx.return_value={'rate':'0.9','as_of':'2026-10-05','source':'错误未来日期'}
 with pytest.raises(ProviderError):s.refresh_fx(force=True,now=evening)
 assert portfolio(s.store)['fx'] is None
 s.close()
