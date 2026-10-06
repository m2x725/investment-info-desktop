import json
import threading
from unittest.mock import Mock
from decimal import Decimal
import pytest
from backend.domain import Settings
from backend.storage import Store
from backend.providers import Credentials, ProviderError
from backend.services import Services
from backend.model_profile import usage_cost


def test_builtin_and_legacy_manual_settings(tmp_path):
    store=Store(tmp_path)
    settings=store.settings()
    assert settings['pricing_mode']=='builtin'
    assert settings['input_price']=='6.5' and settings['prices_confirmed']
    assert Settings().model_dump()['model']=='kimi-k2.6'
    store.save_settings({'input_price':'2','output_price':'3'})
    assert store.settings()['pricing_mode']=='manual'
    assert store.settings()['input_price']=='2'
    preset=Settings(pricing_mode='builtin',model='kimi-custom',input_price=99)
    assert preset.model=='kimi-k2.6' and preset.input_price==Decimal('6.5')


def test_usage_cost_cache_and_missing_cache():
    settings=Settings().model_dump(mode='json')
    assert usage_cost(settings,{'prompt_tokens':1000,'completion_tokens':100,'cached_tokens':600})==Decimal('0.00596')
    assert usage_cost(settings,{'prompt_tokens':1000,'completion_tokens':100})==Decimal('0.0092')
    with pytest.raises(ValueError):usage_cost(settings,{'prompt_tokens':10,'completion_tokens':1,'cached_tokens':11})


def test_progress_scope_monotonic_and_failed_job(tmp_path):
    store=Store(tmp_path);service=Services(store,Mock(),Mock(),Mock(),Credentials())
    blocked=threading.Event();release=threading.Event()
    def run():
        service.job_progress('第一阶段',20)
        with service.progress_scope(20,60):service.job_progress('子任务',50)
        service.job_progress('较小范围',10)
        blocked.set();release.wait(3)
        raise ProviderError('测试中断')
    jid=service.submit('research',run)
    assert blocked.wait(3)
    assert store.rows('SELECT progress FROM jobs WHERE id=?',(jid,))[0]['progress']==40
    release.set();service.executor.shutdown(wait=True)
    job=store.rows('SELECT * FROM jobs WHERE id=?',(jid,))[0]
    assert job['status']=='failed' and job['progress']==40


def test_success_100_and_old_database_migration(tmp_path):
    store=Store(tmp_path)
    store.execute('ALTER TABLE jobs DROP COLUMN progress')
    store=Store(tmp_path)
    assert list((tmp_path/'backups').glob('*.db'))
    service=Services(store,Mock(),Mock(),Mock(),Credentials())
    jid=service.submit('research',lambda:None)
    service.executor.shutdown(wait=True)
    assert store.rows('SELECT * FROM jobs WHERE id=?',(jid,))[0]['progress']==100
