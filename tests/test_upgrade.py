import base64,json,sqlite3
from datetime import date,timedelta
from decimal import Decimal
from unittest.mock import Mock
import pytest
from backend.storage import Store,utcnow
from backend.imports import preview,commit
from backend.accounting import ledger_state,overview,activate,xirr,time_weighted,risk_analysis
from backend.research_engine import ResearchEngine,readable,index_source,material_pack,public_url,SECTIONS
from backend.financial_math import growth,dcf
from backend.providers import Credentials,ProviderError
from backend.services import Services
from backend.domain import Settings
from backend.data_adapters import save_quote

@pytest.fixture
def svc(tmp_path):
    credentials=Credentials();credentials.memory['kimi']='mock-test-key'
    s=Services(Store(tmp_path),Mock(),Mock(),Mock(),credentials)
    s.store.save_settings(Settings(monthly_limit=20,input_price=1,output_price=1,prices_confirmed=True,online_research=False).model_dump(mode='json'))
    s.collect_company=Mock(return_value={})
    s.collect_financial_history=Mock(return_value=None)
    yield s
    s.close()

def ingest(store,text,kind='holdings',**opts):
    return preview(store,dict(filename='样本.csv',kind=kind,content_base64=base64.b64encode(text.encode()).decode(),**opts))

def row(i,kind,q='0',amount='0',fee='0',day='2026-01-01',sid='HK:00700',included=True):
    return dict(id=i,kind=kind,quantity=q,amount_cny=amount,fee_cny=fee,day=day,security_id=sid,payload=json.dumps({'amount_includes_fees':included}))

def add(s,negative=False):
    p=ingest(s.store,'证券代码,证券名称,持仓数量,成本价,持仓盈亏\n700,测试公司,100,'+('-108.457' if negative else '10')+',99\n',cost_currency='CNY')
    commit(s.store,p['id'],{})
    save_quote(s.store,'HK:00700',dict(price='20',previous='19',as_of='2026-10-02',source='模拟公开报价',quoted_at='2026-10-02T16:08:00+08:00',precision='second',delay_seconds=None))
    s.store.execute("INSERT OR REPLACE INTO fx VALUES('HKD','0.9','2026-10-02','模拟汇率')")
    return 'HK:00700'

def evidence(s,sid):
    return s.store.execute('INSERT INTO evidence(security_id,title,url,published_at,content,kind,verification,fetched_at) VALUES(?,?,?,?,?,?,?,?)',(sid,'年度业绩','https://example.com/report','2026-01-01','公司收入100。现金流良好，风险是行业竞争。','financial','official_download',utcnow()))

def report(eid=1,partial=False):
    return dict(title='测试章节',summary='业务经营及竞争需要结合来源判断。',facts=[dict(text='公司收入100。',evidence_id=eid)],support=[],risks=[],unknowns=[],assumptions=[],partial_output=partial)

def test_negative_broker_cost_and_quote_timestamp_survive_restart(svc):
    add(svc,True)
    snap=overview(Store(svc.store.directory));p=snap['positions'][0]
    assert p['broker_cost']=='-108.457' and p['broker_gain']=='99'
    assert p['gain'] is None and p.get('snapshot_gain_cny') is None
    assert p['base_value']=='1800.00'
    assert p['as_of']=='2026-10-02' and p['broker_as_of']!=p['as_of']
    assert p['quote_metadata']['quoted_at']=='2026-10-02T16:08:00+08:00'
    assert p['quote_metadata']['delay_seconds'] is None

def test_repeated_batch_idempotent_and_code_zero(svc):
    p=ingest(svc.store,'证券代码,名称,持仓数量,成本价\n00700,测试,10,5\n')
    assert p['rows'][0]['ticker']=='00700'
    commit(svc.store,p['id'],{});assert commit(svc.store,p['id'],{})['already_committed']
    assert len(svc.store.rows('SELECT * FROM positions'))==1

def test_transaction_refs_conflicts_and_suspects_atomic(svc):
    text='日期,业务类型,证券代码,名称,成交数量,人民币交收金额,费用,流水号\n20260101,买入,700,测试,100,900,2,A\n'
    p=ingest(svc.store,text,'transactions',settlement_currency='CNY');commit(svc.store,p['id'],{})
    again=ingest(svc.store,text,'transactions',settlement_currency='CNY');assert again['rows'][0]['duplicate']=='exact';commit(svc.store,again['id'],{})
    changed=ingest(svc.store,text.replace(',2,A',',3,A'),'transactions',settlement_currency='CNY')
    with pytest.raises(ProviderError,match='冲突'):commit(svc.store,changed['id'],{})
    no_ref=text.replace(',A\n',',\n')
    p=ingest(svc.store,no_ref,'transactions',settlement_currency='CNY');commit(svc.store,p['id'],{})
    dup=ingest(svc.store,no_ref,'transactions',settlement_currency='CNY')
    assert dup['rows'][0]['duplicate']=='suspected'
    with pytest.raises(ProviderError,match='疑似'):commit(svc.store,dup['id'],{})
    assert len(svc.store.rows('SELECT * FROM ledger'))==2

def test_hkd_settlement_not_implicitly_cny(svc):
    p=ingest(svc.store,'日期,业务类型,代码,成交数量,发生金额,币种\n20260101,买入,700,100,1000,HKD\n','transactions')
    assert not p['rows'] and p['issues']

def test_xlsx_and_tsv_local_import(svc):
    import io,openpyxl
    wb=openpyxl.Workbook();wb.active.append(['证券代码','名称','持仓数量','成本价']);wb.active.append(['00700','测试',5,-2]);out=io.BytesIO();wb.save(out)
    p=preview(svc.store,{'filename':'持仓.xlsx','content_base64':base64.b64encode(out.getvalue()).decode()})
    assert p['rows'][0]['broker_cost']=='-2'
    p=ingest(svc.store,'证券代码\t名称\t持仓数量\t成本价\n00700\t测试\t5\t2\n')
    assert p['rows'][0]['quantity']=='5'

def test_partial_history_blocks_sell_not_whole_snapshot(svc):
    add(svc)
    assert overview(svc.store)['net_investment'] is None
    with pytest.raises(ProviderError,match='期初'):ledger_state([row(1,'SELL','5','100')])

def test_weighted_cost_fees_dividend_split_external_cash():
    rows=[row(1,'DEPOSIT',amount='5000'),row(2,'BUY','100','1000','10',included=False),row(3,'BUY','100','1200'),row(4,'SELL','50','700','5',included=False),row(5,'DIVIDEND',amount='100'),row(6,'SPLIT','150'),row(7,'WITHDRAWAL',amount='200'),row(8,'FEE',amount='3')]
    state=ledger_state(rows)
    assert state['positions']['HK:00700']=={'quantity':Decimal(300),'cost_cny':Decimal('1657.5')}
    assert state['realized_gain']==Decimal('142.5') and state['cash']==Decimal('3382') and state['net_investment']==Decimal('4800')
    reduced=ledger_state([row(1,'BUY','100','1000'),row(2,'SPLIT','-50')]);assert reduced['positions']['HK:00700']['quantity']==50
    with pytest.raises(ProviderError):ledger_state([row(1,'BUY','100','1000'),row(2,'SPLIT','-100')])
    with pytest.raises(ProviderError):ledger_state([row(1,'BUY','100','1000'),row(2,'SPLIT','5','50')])

def test_activate_quantity_check_and_no_snapshot_double_count(svc):
    add(svc)
    p=ingest(svc.store,'日期,业务类型,代码,成交数量,人民币交收金额,流水号\n20260101,入金,,0,5000,D\n20260101,买入,700,100,1000,B\n','transactions',settlement_currency='CNY')
    commit(svc.store,p['id'],{});activate(svc.store,True)
    snap=overview(svc.store)
    assert snap['known_total']=='5800.00' and snap['total_gain']=='800.00'
    assert snap['positions'][0]['quantity']=='100' and snap['positions'][0]['gain_cny']=='800.00'
    assert snap['positions'][0]['accounting_cost_cny']=='1000.00'
    new=ingest(svc.store,'日期,业务类型,成交数量,人民币交收金额,流水号\n20260102,分红,0,10,E\n','transactions',settlement_currency='CNY');commit(svc.store,new['id'],{})
    assert overview(svc.store)['account']['mode']=='snapshot'

def test_returns_no_fabricated_flow_adjusted_twr():
    assert xirr([row(1,'DEPOSIT',amount='100',day='2025-01-01')],Decimal('110'),'2026-01-01')=='10.00'
    assert xirr([row(1,'DEPOSIT',amount='100',day='2025-01-01')],Decimal('100'),'2026-01-01')=='0.00'
    closes=[dict(day='2025-01-01',value_cny='100'),dict(day='2025-01-02',value_cny='110')]
    assert time_weighted(closes,{})=='10.00' and time_weighted(closes,{'2025-01-02':Decimal(10)}) is None

def test_schema_backup_preserves_legacy_records(svc):
    sid=add(svc);rid=svc.store.execute('INSERT INTO reports VALUES(NULL,?,?,?,?,?)',(sid,'research','{"title":"旧报告"}','[]',utcnow()))
    with svc.store.connect() as db:db.execute('PRAGMA user_version=0')
    migrated=Store(svc.store.directory)
    assert migrated.rows('SELECT payload FROM reports WHERE id=?',(rid,))[0]['payload']=='{"title":"旧报告"}'
    backups=list((migrated.directory/'backups').glob('*.db'));assert backups
    with sqlite3.connect(backups[-1]) as db:assert db.execute('SELECT COUNT(*) FROM reports').fetchone()[0]==1

def test_garbled_source_excluded_and_historical_chunks_retained(svc):
    sid=add(svc);eid=evidence(svc,sid)
    good=svc.store.rows('SELECT * FROM evidence WHERE id=?',(eid,))[0]
    bad={**good,'id':eid+1,'content':'□�'*100}
    assert readable(good['content']) and not readable(bad['content'])
    index_source(svc.store,good)
    assert material_pack(svc.store,[good,bad],'financial')[0]['id']==eid
    assert not public_url('https://127.0.0.1/private') and public_url('https://www.hkexnews.hk/report.pdf')

def test_chapter_checkpoints_resume_without_recharging_completed(svc):
    sid=add(svc);eid=evidence(svc,sid)
    svc.ai_call=Mock(side_effect=[report(eid),ProviderError('mock timeout')])
    engine=ResearchEngine(svc);rid=engine.company(sid,'完整研究')
    payload=json.loads(svc.store.rows('SELECT payload FROM reports WHERE id=?',(rid,))[0]['payload'])
    run=payload['run_id'];assert payload['coverage']['completed_sections']==1
    svc.ai_call=Mock(return_value=report(eid));rid2=engine.company(sid,'完整研究',run)
    resumed=json.loads(svc.store.rows('SELECT payload FROM reports WHERE id=?',(rid2,))[0]['payload'])
    assert svc.ai_call.call_count==4 # completed and uncertain chapters are not blindly retried
    assert resumed['sections'][1]['status']=='uncertain' and resumed['as_of']==payload['as_of']

def test_partial_output_continues_and_keeps_original(svc):
    sid=add(svc);eid=evidence(svc,sid)
    svc.ai_call=Mock(return_value={**report(eid,True),'summary':'已生成的长正文'})
    engine=ResearchEngine(svc);rid=engine.company(sid,'研究');first=json.loads(svc.store.rows('SELECT payload FROM reports WHERE id=?',(rid,))[0]['payload'])
    svc.ai_call=Mock(return_value={**report(eid),'summary':'续写部分'})
    rid2=engine.company(sid,'研究',first['run_id']);second=json.loads(svc.store.rows('SELECT payload FROM reports WHERE id=?',(rid2,))[0]['payload'])
    assert second['sections'][0]['report']['summary']=='已生成的长正文\n\n续写部分'
    assert second['coverage']['completed_sections']==6
    assert json.loads(svc.ai_call.call_args_list[0].args[0][1]['content'])['continuation']['summary']=='已生成的长正文'

def test_tool_fee_cache_and_uncertain_reservation(svc):
    svc.store.save_settings({'online_research':True});svc.kimi.tool=Mock(return_value={'search_results':[{'title':'测试公司'}]})
    e=ResearchEngine(svc);e.tool('search_pro',{'text_query':'测试'});e.tool('search_pro',{'text_query':'测试'})
    assert svc.kimi.tool.call_count==1 and svc.store.rows('SELECT amount FROM expenses')[0]['amount']=='0.015'
    svc.kimi.tool.side_effect=ProviderError('timeout')
    with pytest.raises(ProviderError):e.tool('fetch',{'url':'https://example.com'})
    assert svc.store.rows("SELECT reserved FROM expenses WHERE status='reserved'")[0]['reserved']=='0.01'
    svc.store.save_settings({'monthly_limit':'0.01'})
    with pytest.raises(ProviderError):e.tool('search_pro',{'text_query':'other'})
    assert svc.kimi.tool.call_count==2

def test_portfolio_cloud_payload_excludes_money_and_quantity(svc):
    sid=add(svc);eid=evidence(svc,sid);svc.ai_call=Mock(return_value=report(eid))
    rid=ResearchEngine(svc).portfolio()
    cloud=json.loads(svc.ai_call.call_args.args[0][1]['content'])
    assert set(cloud['holdings'][0])=={'id','name','industry','weight','currency'}
    text=json.dumps(cloud)
    for private in ('quantity','cost_cny','broker_cost','account_id','known_total','loss_cny'):assert private not in text
    saved=json.loads(svc.store.rows('SELECT payload FROM reports WHERE id=?',(rid,))[0]['payload'])
    assert saved['risk']['scenarios'][0]['loss_cny']=='180.00' and saved['snapshot']['known_total']=='1800.00'

def test_latest_retrieval_is_shared_limited_and_not_skipped_for_existing_report(svc):
    sid=add(svc);eid=evidence(svc,sid)
    svc.store.execute('INSERT INTO reports VALUES(NULL,?,?,?,?,?)',(sid,'research',json.dumps(report(eid)),json.dumps([eid]),utcnow()))
    svc.store.save_settings({'online_research':True});svc.kimi.tool=Mock(return_value={'search_results':[]});svc.ai_call=Mock(return_value=report(eid))
    ResearchEngine(svc).portfolio();assert svc.kimi.tool.call_count==1
    assert '最新公告' in svc.kimi.tool.call_args.args[1]['text_query']

def test_risk_cash_scenarios_and_insufficient_history(svc):
    add(svc);svc.store.execute("INSERT INTO cash VALUES('CNY','200')");snap=overview(svc.store)
    risk=risk_analysis(svc.store,snap)
    assert risk['scenarios'][0]['loss_cny']=='180.00' and risk['correlation'] is None
    assert risk['industry_weights']['行业未分类']=='90.00'
    svc.store.execute('DELETE FROM fx');assert risk_analysis(svc.store,overview(svc.store))['correlation'] is None

def test_riskfolio_actual_installed_component_with_cny_history(svc):
    sid=svc.store.add_security(dict(exchange='SH',ticker='600519',name='模拟A股'))
    svc.store.execute('INSERT INTO positions VALUES(?,?,?,?,?)',(sid,'100','10','测试',utcnow()))
    save_quote(svc.store,sid,dict(price='20',as_of='2026-10-02',source='模拟'))
    for i in range(140):
        svc.store.execute('INSERT INTO price_history VALUES(?,?,?,?,?,?)',(sid,str(date(2026,1,1)+timedelta(days=i)),str(10+i*.02+(i%7)*.01),'CNY','qfq','模拟历史序列'))
    risk=risk_analysis(svc.store,overview(svc.store))
    assert risk['observations']==139 and risk['correlation'][sid][sid]==1.0
    assert risk['risk_contribution'][sid]>0

def test_financial_math_growth_dcf_and_invalid_inputs():
    assert growth('120','100')=='20.00' and growth('1','0') is None
    result=dcf(['100','110'],'.1','.02','20','10');assert Decimal(result['value_per_share'])>0
    with pytest.raises(ValueError):dcf(['100'],'.01','.02','0','10')

def test_restore_validation_and_preserved_pre_restore_copy(svc,tmp_path):
    from backend.restore import restore
    add(svc);backup=svc.store.backup()
    svc.store.execute('DELETE FROM positions')
    result=restore(backup,svc.store.directory,check_running=False)
    assert result['previous_backup'] and overview(Store(svc.store.directory))['positions']
    invalid=tmp_path/'unrelated.db'
    with sqlite3.connect(invalid) as db:db.execute('CREATE TABLE unrelated(x)')
    before=svc.store.path.read_bytes()
    with pytest.raises(ValueError):restore(invalid,svc.store.directory,check_running=False)
    assert svc.store.path.read_bytes()==before

def test_folder_detection_previews_once_never_commits(svc,tmp_path):
    folder=tmp_path/'exports';folder.mkdir();(folder/'持仓.csv').write_text('证券代码,名称,持仓数量,成本价\n00700,测试,5,-1\n', encoding='utf-8')
    svc.store.save_settings({'import_folder':str(folder)})
    svc.scan_import_folder();svc.scan_import_folder()
    assert len(svc.store.rows('SELECT * FROM imports'))==1
    assert not svc.store.rows('SELECT * FROM positions')

def test_event_update_only_disclosure_not_quote_refresh(svc):
    sid=add(svc);eid=evidence(svc,sid)
    svc.store.execute('INSERT INTO reports VALUES(NULL,?,?,?,?,?)',(sid,'research',json.dumps(report(eid)),json.dumps([eid]),utcnow()))
    svc.ai_call=Mock(return_value=report(eid))
    rid=ResearchEngine(svc).event_update(sid,[dict(title='新增公告',reason='涉及业务变化',url='https://example.com/report')])
    assert svc.store.rows('SELECT kind FROM reports WHERE id=?',(rid,))[0]['kind']=='event_update'
    svc.market.quote.return_value=dict(price='21',previous='20',as_of='2026-10-02',source='模拟报价')
    svc.collector.fx=Mock(return_value=dict(rate='0.9',as_of='2026-10-02',source='模拟汇率'))
    svc.refresh_quotes();assert svc.ai_call.call_count==1

def test_full_snapshot_replacement_and_bad_rows_are_explicit(svc):
    add(svc)
    p=ingest(svc.store,'证券代码,名称,持仓数量,成本价\n01810,模拟小米,50,10\n',replace_snapshot=True)
    commit(svc.store,p['id'],{})
    assert [r['security_id'] for r in svc.store.rows('SELECT * FROM positions')]==['HK:01810']
    p=ingest(svc.store,'证券代码,名称,持仓数量,成本价\n00700,测试,5,abc\n01810,模拟,50,10\n',replace_snapshot=True)
    assert len(p['issues'])==1 and len(p['rows'])==1
    with pytest.raises(ProviderError,match='完整快照'):commit(svc.store,p['id'],{'accept_valid_rows':True})
    assert svc.store.rows('SELECT security_id FROM positions')[0]['security_id']=='HK:01810'

def test_http_import_and_overview_new_routes(tmp_path):
    from backend.main import create_app
    from fastapi.testclient import TestClient
    app=create_app(tmp_path,scheduler=False)
    app.state.services.collect_company=Mock()
    with TestClient(app) as c:
        c.headers['X-App-Token']=c.get('/api/bootstrap').json()['csrf']
        p=c.post('/api/imports/preview',json={'filename':'持仓.csv','content_base64':base64.b64encode('证券代码,名称,持仓数量,成本价\n00700,测试,10,-5\n'.encode()).decode()}).json()
        assert c.post('/api/imports/'+p['id']+'/commit',json={}).status_code==200
        assert c.get('/api/portfolio/overview').json()['positions'][0]['broker_cost']=='-5'
        assert c.get('/api/imports/'+p['id']).json()['status']=='committed'

def test_valid_unicode_garbled_cid_maps_rejected_but_good_pages_kept(svc):
    sid=add(svc);eid=evidence(svc,sid)
    garbage='㛮ᷯ㛡⟳␌ 灭 劳㕉⎌ᷯ㕉䈊 灮 '*30
    assert not readable(garbage) and not readable('(cid:14062)(cid:7663)')
    content='[第1页]\n公司收入100。现金流良好。\n[第2页]\n[此页文字不可读，未用作证据；待备用网页或OCR]'
    source={**svc.store.rows('SELECT * FROM evidence WHERE id=?',(eid,))[0],'content':content}
    index_source(svc.store,source);pack=material_pack(svc.store,[source],'financial')
    assert pack and '公司收入100' in pack[0]['content'] and '此页文字不可读' not in pack[0]['content']

def test_budget_stop_is_resumable_not_mistaken_for_paid_timeout(svc):
    sid=add(svc);eid=evidence(svc,sid)
    svc.ai_call=Mock(side_effect=[report(eid),ProviderError('预算不足',unbilled=True)])
    engine=ResearchEngine(svc);rid=engine.company(sid,'研究')
    first=json.loads(svc.store.rows('SELECT payload FROM reports WHERE id=?',(rid,))[0]['payload'])
    assert first['sections'][1]['status']=='pending'
    svc.ai_call=Mock(return_value=report(eid));engine.company(sid,'研究',first['run_id'])
    assert svc.ai_call.call_count==5


def test_old_pdf_cover_does_not_hide_corrupt_body_or_repeat_processed_ocr():
    from backend.research_engine import needs_pdf_repair
    bad='[第1页]2026年中期报告\n[第2页]'+('㛮ᷯ㛡⟳␌ 灭 '*30)
    assert needs_pdf_repair(bad)
    partial='[第1页]公司收入100，经营情况如下。\n[第2页][此页文字不可读，未用作证据；待备用网页或OCR]'
    assert not needs_pdf_repair(partial)

def test_search_limits_history_dates_and_excerpt_fallback(svc):
    sid=add(svc);svc.store.save_settings({'online_research':True})
    svc.kimi.tool=Mock(return_value={'search_results':[]})
    s=svc.store.rows('SELECT * FROM securities WHERE id=?',(sid,))[0]
    svc.store.execute('INSERT INTO research_runs VALUES(?,?,?,?,?,?,?)',('search-test',sid,'company',json.dumps({'as_of':utcnow()}),'running',utcnow(),None))
    engine=ResearchEngine(svc);engine.retrieve(s,'search-test')
    calls=svc.kimi.tool.call_args_list
    assert len(calls)==12 and '2025' in calls[0].args[1]['text_query']
    assert 'time_window' not in calls[-1].args[1] # historical gap search must not be limited to the latest90days
    svc.kimi.tool=Mock(return_value={'search_results':[dict(title='测试公司 最新公告',url='https://example.com/latest',snippet='测试公司新增业务资料，收入情况待核对。',chunks=[])]})
    svc.store.execute('INSERT INTO research_runs VALUES(?,?,?,?,?,?,?)',('excerpt-test',sid,'retrieval',json.dumps({'as_of':utcnow()}),'running',utcnow(),None))
    engine=ResearchEngine(svc);engine.fetches=8;engine.retrieve(s,'excerpt-test',latest_only=True)
    rows=svc.store.rows("SELECT content,verification FROM evidence WHERE url='https://example.com/latest'")
    assert rows[0]['content'].startswith('测试公司新增') and rows[0]['verification']=='search_excerpt'
    assert svc.kimi.tool.call_count==1

def test_traditional_annual_reports_are_not_hidden_by_daily_disclosures():
    from backend.collection import choose
    rows=[dict(title='翌日披露報表',url='https://example.com/daily'),dict(title='2025年度報告',url='https://example.com/annual'),dict(title='2026年中期報告',url='https://example.com/interim')]
    selected=choose(rows)
    assert selected[0]['url'].endswith('/annual') and selected[1]['url'].endswith('/interim')
