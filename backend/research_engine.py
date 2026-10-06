"""Versioned research workflow with source retrieval, checkpoints and local portfolio snapshots."""
import hashlib,ipaddress,json,re,uuid,unicodedata
from datetime import datetime,timedelta,timezone
from urllib.parse import urlparse
from .domain import dec,money,valuation
from .providers import ProviderError
from .storage import utcnow
from .accounting import overview,risk_analysis

TEMPLATE_VERSION='hk-connect-2026.10-v1'
SECTIONS=[('business','业务与盈利来源'),('financial','历史财务、现金流与资本分配'),('events','最新经营、政策与重大事件'),('competition','行业与同业竞争'),('valuation','估值、预期与情景'),('countercase','反方证据、论点失效条件与观察指标')]
KEYWORDS={'business':r'业务|業務|收入|营收|分部|segment|business|revenue','financial':r'现金|現金|負債|负债|利润|利潤|cash|debt|profit','events':r'公告|变更|变化|监管|政策|announcement|change|2026','competition':r'竞争|競爭|行业|市场|market|competit|industry','valuation':r'估值|股价|盈利|earnings|valuation|利润','countercase':r'风险|風險|risk|不确定|uncertain'}

def readable(text):
    if not isinstance(text,str) or not text.strip():return False
    if len(re.findall(r'\[第\d+页\]',text))>1:
        return any(readable(part) for part in re.split(r'(?=\[第\d+页\])',text) if part.strip())
    if '[此页文字不可读' in text:return False
    if re.search(r'\(cid:\d+\)',text):return False
    suspicious=sum(text.count(c) for c in ('�','□','◻'))+sum(0xe000<=ord(c)<=0xf8ff for c in text)
    if suspicious/max(1,len(text))>=.01:return False
    # Broken CID maps may emit valid Unicode, especially combining marks, radicals and math symbols.
    anomalous=sum(unicodedata.category(c).startswith('M') or (ord(c)>127 and unicodedata.category(c) in ('Sm','So','Sk','Ll','Lo') and not (0x4e00<=ord(c)<=0x9fff or 0xff00<=ord(c)<=0xffef)) for c in text)
    return anomalous/max(1,len(text))<.04

def needs_pdf_repair(text):
    if '[此页文字不可读' in text:return False # already processed; keep explicit gaps rather than rerender every 30 minutes
    pages=[part for part in re.split(r'(?=\[第\d+页\])',text) if part.strip()]
    return any(not readable(part) for part in pages)


def public_url(url):
    try:
        p=urlparse(url)
        if p.scheme!='https' or not p.hostname or p.username or p.password or p.port not in (None,443):return False
        h=p.hostname.lower()
        if h in ('localhost','localhost.localdomain') or h.endswith(('.local','.internal')):return False
        try:return ipaddress.ip_address(h).is_global
        except ValueError:return '.' in h
    except ValueError:return False

def index_source(store,e):
    text=e['content'];quality='readable' if readable(text) else 'unreadable'
    # Source boundaries retained. Chunking controls context, not saved/report length.
    chunks=re.split(r'(?=\[第\d+页\])|\n(?=#{1,4} )',text)
    parts=[c[start:start+3500] for c in chunks for start in range(0,len(c),3000) if c[start:start+3500].strip()]
    with store.connect() as db:
        db.execute('DELETE FROM source_chunks WHERE evidence_id=?',(e['id'],))
        for n,c in enumerate(parts):db.execute('INSERT INTO source_chunks VALUES(?,?,?,?)',(e['id'],n,c,'readable' if readable(c) else 'unreadable'))
    return quality

def material_pack(store,evidence,topic,byte_limit=65000):
    ranked=[]
    pattern=KEYWORDS.get(topic,'')
    for e in evidence:
        if not readable(e['content']):continue
        chunks=store.rows('SELECT * FROM source_chunks WHERE evidence_id=?',(e['id'],))
        if not chunks:index_source(store,e);chunks=store.rows('SELECT * FROM source_chunks WHERE evidence_id=?',(e['id'],))
        for c in chunks:
            if not readable(c['content']):continue
            score=len(re.findall(pattern,c['content'],re.I))+ (3 if e['kind']=='financial' and topic=='financial' else 0)
            ranked.append((score,e['published_at'],e,c))
    ranked.sort(key=lambda x:(x[0],x[1]),reverse=True)
    selected={};size=0
    for _,_,e,c in ranked:
        content=c['content'];length=len(content.encode())
        if size+length>byte_limit:continue
        entry=selected.setdefault(e['id'],{k:e.get(k) for k in ('id','title','url','published_at','report_period','verification')})
        entry['content']=entry.get('content','')+'\n'+content;size+=length
    return list(selected.values())

def context_text(text,limit=5000):
    """Bound context copies only; original report and source remain fully stored."""
    blob=text.encode('utf-8')
    if len(blob)<=limit:return text
    half=(limit-150)//2
    return blob[:half].decode('utf-8','ignore')+'\n[上下文选段；完整已保存正文未删减]\n'+blob[-half:].decode('utf-8','ignore')


class ResearchEngine:
    def __init__(self,services):
        self.svc=services;self.store=services.store;self.searches=0;self.fetches=0

    def tool(self,name,payload):
        cache_key=hashlib.sha256(json.dumps([name,payload],sort_keys=True).encode()).hexdigest()
        cached=self.store.rows('SELECT * FROM tool_cache WHERE cache_key=?',(cache_key,))
        if cached and datetime.now(timezone.utc)-datetime.fromisoformat(cached[0]['created_at'])<timedelta(hours=6):return json.loads(cached[0]['payload'])
        settings=self.store.settings()
        if not settings.get('prices_confirmed') or not self.svc.credentials.get('kimi'):raise ProviderError('联网研究需要已配置的Kimi密钥和费用设置。')
        fee=dec('.015' if name=='search_pro' else '.01')
        eid=self.svc.reserve_expense(fee)
        try:
            result=self.svc.kimi.tool(name,payload)
            billed=bool(result.get('search_results')) if name=='search_pro' else bool(result.get('markdown','').strip())
            self.store.execute("UPDATE expenses SET status='charged',amount=? WHERE id=?",(str(fee if billed else 0),eid))
            self.store.execute('INSERT OR REPLACE INTO tool_cache VALUES(?,?,?)',(cache_key,json.dumps(result,ensure_ascii=False),utcnow()))
            return result
        except Exception:
            self.store.event('tools','联网工具调用结果不明；保留费用预留，不自动重试。')
            raise

    def retrieve(self,s,run,latest_only=False):
        cfg=self.store.settings();warnings=[];fetches=0;searches=0
        if not cfg.get('online_research',True):return ['联网研究已关闭，本次仅使用缓存资料。']
        name=s['name'];code=s['ticker'];year=datetime.now(timezone.utc).year
        queries=[f'{name} {code} {year-1-i} 年报 年度业绩 分部 收入 现金流' for i in range(3)]
        queries += [f'{name} {code} {label}' for _,label in SECTIONS]
        if latest_only:queries=[f'{name} {code} 最新公告 经营变化 财报 政策 风险']
        for n,query in enumerate(queries):
            checkpoint=self.store.rows('SELECT status,payload FROM research_sections WHERE run_id=? AND section=?',(run,'search:'+str(n)))
            if checkpoint:
                if checkpoint[0]['status']=='uncertain':warnings.append('上一轮搜索结果不明，本次未重复付费。')
                continue
            if self.searches>=12:
                warnings.append('本次研究已达到12次搜索上限，其他缺口保留。');break
            self.searches+=1;searches+=1
            self.store.execute('INSERT OR REPLACE INTO research_sections VALUES(?,?,?,?)',(run,'search:'+str(n),'{}','uncertain'))
            try:
                request={'text_query':query,'limit':5}
                if latest_only or 5<=n<=8:request['time_window']={'start':(datetime.now(timezone.utc)-timedelta(days=90)).date().isoformat(),'end':datetime.now(timezone.utc).date().isoformat()}
                result=self.tool('search_pro',request)
                self.store.execute("UPDATE research_sections SET payload=?,status='done' WHERE run_id=? AND section=?",(json.dumps(result,ensure_ascii=False),run,'search:'+str(n)))
                for source in result.get('search_results',[]):
                    url=source.get('url','')
                    if not public_url(url):continue
                    title=source.get('title','');snippet=source.get('snippet','')
                    # Different-company leads do not enter evidence; company identity is still checked in report review.
                    company_match=name in title+snippet or code in title+snippet
                    context=not latest_only and n in (6,8) and not company_match
                    if not company_match and not context:continue
                    if context:title='[行业/同业背景] '+title
                    content='\n'.join(c.get('text','') for c in source.get('chunks',[])) or snippet
                    verification='context_excerpt' if context else 'search_excerpt'
                    if self.fetches<8:
                        self.fetches+=1;fetches+=1
                        try:
                            fetched=self.tool('fetch',{'url':url}).get('markdown')
                            if fetched:content=fetched;verification='context_retrieved' if context else 'web_retrieved'
                        except Exception:warnings.append('部分正文抓取未完成，保留搜索片段并标注来源。')
                    if not readable(content):warnings.append(title+'：正文不可读');continue
                    date_value=source.get('date','')
                    publication=date_value[:10] if re.match(r'^\d{4}-\d{2}-\d{2}',date_value) else ''
                    self.store.execute('INSERT INTO evidence(security_id,title,url,published_at,content,kind,verification,fetched_at,locator) VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(security_id,url,title) DO UPDATE SET content=excluded.content,verification=excluded.verification,published_at=excluded.published_at,fetched_at=excluded.fetched_at',
                        (s['id'],title or '联网研究资料',url,publication,content,'financial' if n<3 and not latest_only else 'news',verification,utcnow(),'搜索日期未确认' if not publication else '网页正文；身份与口径需复核'))
                if n==8 and not latest_only:
                    saved=self.store.rows("SELECT content,title,report_period FROM evidence WHERE security_id=? AND verification!='title_only'",(s['id'],))
                    body='\n'.join(e['content'] for e in saved if readable(e['content']))
                    gaps=[label for key,label in SECTIONS if not re.search(KEYWORDS[key],body,re.I)]
                    for old_year in (year-1,year-2,year-3):
                        if not any(str(old_year) in e['title']+e.get('report_period','') for e in saved):gaps.insert(0,str(old_year)+' 年度财务及官方业绩材料')
                    queries.extend(f'{name} {code} 官方原文 补充 {gap}' for gap in gaps[:3])
            except Exception as exc:
                warnings.append(str(exc) if isinstance(exc,ProviderError) else '联网检索未完成')
                break # no repeated charged failure
        runrow=self.store.rows('SELECT snapshot FROM research_runs WHERE id=?',(run,))[0]
        snap=json.loads(runrow['snapshot']);snap['retrieval']={'searches':searches,'fetches':fetches,'warnings':warnings}
        self.store.execute('UPDATE research_runs SET snapshot=? WHERE id=?',(json.dumps(snap,ensure_ascii=False),run))
        return warnings

    def company(self,sid,question,run_id=None):
        security=self.store.rows('SELECT * FROM securities WHERE id=?',(sid,))[0]
        if run_id:
            runs=self.store.rows('SELECT * FROM research_runs WHERE id=? AND security_id=?',(run_id,sid))
            if not runs:raise ProviderError('研究断点不存在或公司不一致。')
            run=run_id
            if runs[0]['status']=='done':return runs[0]['report_id']
        else:
            run=uuid.uuid4().hex
            self.store.execute('INSERT INTO research_runs VALUES(?,?,?,?,?,?,?)',(run,sid,'company',json.dumps({'as_of':utcnow(),'question':question},ensure_ascii=False),'running',utcnow(),None))
        from .services import SYSTEM
        warnings=[]
        try:
            with self.svc.progress_scope(0,35):self.svc.collect_company(sid)
        except Exception:warnings.append('官方资料更新失败，继续使用可读缓存和联网检索。')
        self.svc.job_progress("正在补充历史财务数据",35)
        try:self.svc.collect_financial_history(sid)
        except Exception:warnings.append('结构化历史财务表未更新；保留官方报告和明确缺口。')
        self.svc.job_progress("正在联网搜索并补充研究资料",40)
        try:warnings+=self.retrieve(security,run)
        except Exception:warnings.append('联网检索未完成，已保留研究断点。')
        evidence=self.store.rows("SELECT * FROM evidence WHERE security_id=? AND verification!='title_only' ORDER BY published_at DESC",(sid,))
        for e in evidence:index_source(self.store,e)
        good=[e for e in evidence if readable(e['content'])]
        for e in good:
            missing=e['content'].count('[此页文字不可读')
            if missing:warnings.append(e['title']+'：'+str(missing)+'页未读取，不作为证据。')
        if not good:
            self.store.execute("UPDATE research_runs SET status='partial' WHERE id=?",(run,))
            raise ProviderError('没有取得可读原文；已自动检索并保存断点，未付费生成空泛报告。')
        run_snapshot=json.loads(self.store.rows('SELECT snapshot FROM research_runs WHERE id=?',(run,))[0]['snapshot'])
        calculation=run_snapshot.get('calculation') or valuation(self.store,sid);sections=[]
        from .financial_math import valuation_scenarios
        calculation['valuation_scenarios']=valuation_scenarios(calculation)
        calculation['financial_history']=[{'period':r['period'],'source':r['source'],'currency':json.loads(r['payload']).get('currency'),'verification':'aggregated_unreconciled'} for r in self.store.rows('SELECT * FROM financial_history WHERE security_id=? ORDER BY period',(sid,))]
        if 'calculation' not in run_snapshot:
            run_snapshot['calculation']=calculation
            self.store.execute('UPDATE research_runs SET snapshot=? WHERE id=?',(json.dumps(run_snapshot,ensure_ascii=False),run))
        for index,(key,label) in enumerate(SECTIONS):
            self.svc.job_progress(f"AI正在分析：{label}（{index+1}/{len(SECTIONS)}）",50+40*index/len(SECTIONS))
            previous=self.store.rows('SELECT * FROM research_sections WHERE run_id=? AND section=?',(run,key))
            if previous and previous[0]['status']=='done':sections.append({'key':key,'label':label,'status':'done','report':json.loads(previous[0]['payload'])});continue
            if previous and previous[0]['status']=='uncertain':
                sections.append({'key':key,'label':label,'status':'uncertain','report':{'summary':'上次调用结果不明，本次未重复调用；请先核对平台账单，确需重做时发起新研究。'}});continue
            materials=material_pack(self.store,good,key)
            continuation=json.loads(previous[0]['payload']) if previous and previous[0]['status']=='partial' else None
            self.store.execute('INSERT OR REPLACE INTO research_sections VALUES(?,?,?,?)',(run,key,'{}','uncertain'))
            try:
                payload=self.svc.ai_call([{'role':'system','content':SYSTEM+'\n采用研究模板 '+TEMPLATE_VERSION+'。只完成当前章节，完整分析证据、推论、假设及缺口，不写交易指令。'}, {'role':'user','content':json.dumps({'company':security,'as_of':run_snapshot['as_of'],'question':question,'chapter':label,'materials':materials,'calculation':calculation,'completed_chapters':[{ 'chapter':s['label'],'summary':context_text(s['report']['summary'])} for s in sections] if key=='countercase' else [],'continuation':{'summary':context_text(continuation['summary'],20000),'saved_characters':len(continuation['summary'])} if continuation else None,'instruction':'若continuation有内容，仅续写缺失部分，避免重复已保存内容'},ensure_ascii=False)}])
                checked=self.svc.validate_output(payload,good,calculation,sid,key)
                if continuation:
                    checked['summary']=continuation['summary']+'\n\n'+checked['summary']
                    for field in ('facts','support','risks','unknowns','assumptions','validation_warnings'):
                        checked[field]=continuation.get(field,[])+checked.get(field,[])
                checked['partial_output']=bool(payload.get('partial_output'))
                self.store.execute("UPDATE research_sections SET payload=?,status='done' WHERE run_id=? AND section=?",(json.dumps(checked,ensure_ascii=False),run,key))
                if checked['partial_output']:
                    self.store.execute("UPDATE research_sections SET status='partial' WHERE run_id=? AND section=?",(run,key))
                    sections.append({'key':key,'label':label,'status':'partial','report':checked})
                    break
                sections.append({'key':key,'label':label,'status':'done','report':checked})
            except Exception as exc:
                status='pending' if getattr(exc,'unbilled',False) else 'uncertain'
                self.store.execute('UPDATE research_sections SET status=? WHERE run_id=? AND section=?',(status,run,key))
                sections.append({'key':key,'label':label,'status':status,'report':{'summary':str(exc) if isinstance(exc,ProviderError) else '本章节未完成；已有内容保留。'}})
                warnings.append('部分章节未完成；可查看已生成内容和断点。')
                break
        done=[s for s in sections if s['status'] in ('done','partial')]
        if not done:
            self.store.execute("UPDATE research_runs SET status='partial' WHERE id=?",(run,))
            raise ProviderError('研究章节尚未完成；断点已保存，调用结果不明时不会自动重复付费。')
        self.svc.job_progress('正在核验并保存报告',95)
        summary='\n\n'.join(s['label']+'：'+s['report']['summary'] for s in done)
        report={'title':security['name']+' · 系统研究','summary':summary,'facts':[],'support':[],'risks':[],'unknowns':warnings,'assumptions':[],'sections':sections,'as_of':run_snapshot['as_of'],'run_id':run,'template_version':TEMPLATE_VERSION,'calculation':calculation,'model':self.store.settings()['model'],'coverage':{'readable_sources':len(good),'unreadable_sources':len(evidence)-len(good),'completed_sections':len([s for s in sections if s['status']=='done']),'total_sections':len(SECTIONS)}}
        for section in done:
            for field in ('facts','support','risks','unknowns','assumptions'):report[field]+=section['report'].get(field,[])
        report['validation_warnings']=warnings+list(dict.fromkeys(w for s in done for w in s['report'].get('validation_warnings',[])))
        report['validation_status']='needs_review'
        rid=self.store.execute('INSERT INTO reports(security_id,kind,payload,evidence_ids,created_at) VALUES(?,?,?,?,?)',(sid,'research',json.dumps(report,ensure_ascii=False),json.dumps([e['id'] for e in good]),utcnow()))
        self.store.execute('UPDATE research_runs SET status=?,report_id=? WHERE id=?',('done' if len([s for s in sections if s['status']=='done'])==len(SECTIONS) else 'partial',rid,run))
        return rid

    def portfolio(self):
        from .services import SYSTEM
        self.svc.job_progress("正在核算持仓与组合风险",5)
        snapshot=overview(self.store);risk=risk_analysis(self.store,snapshot);run=uuid.uuid4().hex
        self.store.execute('INSERT INTO research_runs VALUES(?,?,?,?,?,?,?)',(run,None,'portfolio',json.dumps(snapshot,ensure_ascii=False),'running',utcnow(),None))
        # Monetary values, quantity, cost, and account identifiers never enter the model request.
        holdings=[{k:p.get(k) for k in ('id','name','industry','weight','currency')} for p in snapshot['positions']]
        evidence=[];reports=[];warnings=[]
        ordered=sorted(snapshot['positions'],key=lambda x:float(x.get('weight') or 0),reverse=True)
        for index,p in enumerate(ordered):
            self.svc.job_progress('正在更新持仓研究：'+p['name'],10+70*index/max(1,len(ordered)))
            security=self.store.rows('SELECT * FROM securities WHERE id=?',(p['id'],))[0]
            child=run+'-'+p['id']
            self.store.execute('INSERT INTO research_runs VALUES(?,?,?,?,?,?,?)',(child,p['id'],'retrieval',json.dumps({'as_of':snapshot['as_of']}),'running',utcnow(),None))
            try:self.retrieve(security,child,latest_only=True)
            except Exception:self.store.event('research','组合最新资料查询未完成；保留缺口。')
            evidence+=self.store.rows("SELECT * FROM evidence WHERE security_id=? AND verification!='title_only'",(p['id'],))
            self.store.execute("UPDATE research_runs SET status='done' WHERE id=?",(child,))
            rows=self.store.rows("SELECT payload,evidence_ids FROM reports WHERE security_id=? AND kind='research' ORDER BY id DESC LIMIT 1",(p['id'],))
            if not rows:
                try:
                    with self.svc.progress_scope(10+70*index/len(ordered),10+70*(index+1)/len(ordered)):
                        self.company(p['id'],'完整公司底稿：业务、历史财务、最新事件、竞争、估值与反方证据')
                    rows=self.store.rows("SELECT payload,evidence_ids FROM reports WHERE security_id=? AND kind='research' ORDER BY id DESC LIMIT 1",(p['id'],))
                except Exception as exc:warnings.append(p['name']+'：个股底稿未完成，组合结论覆盖有限。')
            if rows:
                report=json.loads(rows[0]['payload']);reports.append({'company':p['name'],'summary':context_text(report['summary'],2000),'as_of':report.get('as_of'),'coverage':report.get('coverage')})
                ids=json.loads(rows[0]['evidence_ids'])
                if ids:evidence+=self.store.rows('SELECT * FROM evidence WHERE id IN ('+','.join('?' for _ in ids)+')',ids)
        good=list({e['id']:e for e in evidence if readable(e['content'])}.values())
        if not holdings:raise ProviderError('请先导入持仓，组合分析不会猜测账户。')
        if not good:raise ProviderError('没有可读研究来源，已保留快照；请先更新资料。')
        risk['warnings']+=warnings
        clean_risk={k:risk[k] for k in ('industry_weights','currency_weights','observations','warnings')}
        self.svc.job_progress('AI正在综合分析组合',85)
        try:payload=self.svc.ai_call([{'role':'system','content':SYSTEM+'\n分析组合共同业务因素、仓位集中、论点变化、优先复查和观察指标。缺少个股研究时明确说明，不能称为完整尽调。'}, {'role':'user','content':json.dumps({'as_of':snapshot['as_of'],'holdings':holdings,'research':reports,'risk':clean_risk,'materials':material_pack(self.store,good,'countercase')},ensure_ascii=False)}])
        except ProviderError as exc:
            if not exc.unbilled:raise
            payload={'title':'组合计算快照 · 综合研究未完成','summary':'本地核算与已生成的公司底稿已保留，综合模型调用未执行：'+str(exc),'facts':[],'support':[],'risks':[],'unknowns':[str(exc)],'assumptions':[]}
            risk['warnings'].append('本次综合模型研究未完成，不能作为完整组合分析。')
        self.svc.job_progress('正在核验并保存组合报告',95)
        report=self.svc.validate_output(payload,good,None,None,'portfolio')
        report.update(as_of=snapshot['as_of'],snapshot=snapshot,risk=risk,run_id=run,template_version=TEMPLATE_VERSION,coverage={'holdings':len(holdings),'researched':len(reports)},model=self.store.settings()['model'])
        rid=self.store.execute('INSERT INTO reports(security_id,kind,payload,evidence_ids,created_at) VALUES(?,?,?,?,?)',(None,'portfolio',json.dumps(report,ensure_ascii=False),json.dumps(list({e['id'] for e in good})),utcnow()))
        self.store.execute("UPDATE research_runs SET status='done',report_id=? WHERE id=?",(rid,run))
        return rid


    def event_update(self,sid,events):
        """One incremental report for new disclosures; quotes alone never invoke AI."""
        from .services import SYSTEM
        cached=self.store.rows("SELECT payload FROM reports WHERE security_id=? AND kind IN ('research','event_update') ORDER BY id DESC LIMIT 1",(sid,))
        if not cached:return None
        good=[e for e in self.store.rows("SELECT * FROM evidence WHERE security_id=? AND verification!='title_only'",(sid,)) if readable(e['content'])]
        if not good:return None
        prior=json.loads(cached[0]['payload'])
        s=self.store.rows('SELECT * FROM securities WHERE id=?',(sid,))[0]
        payload=self.svc.ai_call([{'role':'system','content':SYSTEM+'\n只更新新增事件对历史持仓论点的影响，指出哪些判断改变、哪些不变及需要复查的指标，不重写整份尽调。'}, {'role':'user','content':json.dumps({'company':s,'as_of':utcnow(),'previous_research':context_text(prior['summary'],20000),'new_events':[{'title':e['title'],'reason':e['reason'],'url':e.get('url')} for e in events],'materials':material_pack(self.store,good,'events')},ensure_ascii=False)}])
        report=self.svc.validate_output(payload,good,None,sid,'event_update')
        report.update(as_of=utcnow(),model=self.store.settings()['model'],template_version=TEMPLATE_VERSION)
        rid=self.store.execute('INSERT INTO reports(security_id,kind,payload,evidence_ids,created_at) VALUES(?,?,?,?,?)',(sid,'event_update',json.dumps(report,ensure_ascii=False),json.dumps([e['id'] for e in good]),utcnow()))
        return rid
