import React, {useState, useEffect, useRef} from 'react';
import {createRoot} from 'react-dom/client';
import {ArrowRight, BookOpen, BriefcaseBusiness, Check, ChevronRight, Eye, EyeOff, FileText, Leaf, LoaderCircle, Plus, RefreshCw, Search, Settings2, ShieldCheck, X, ExternalLink, CircleAlert, Download, Bell} from 'lucide-react';
import './style.css';
import {AccountTools,AccountSummary} from './AccountTools';

import {ReportReader} from './ReportReader';
import {NewsFeed} from './NewsFeed';
import {FxStatus} from './FxStatus';
import {BriefTimesInput,normalizeBriefTime} from './BriefTimeInput';
import {FeedbackDock} from './FeedbackDock';

type Security = {id?:string; exchange:string; ticker:string; name:string; currency?:string};
type Data = {
  csrf:string; portfolio:any; news?:any[];
  followed:Security[];watchlist:Security[];alerts:any[];brief:any;reports:any[];settings:any;budget:any;
  connections:{kimi:boolean;push:boolean;secure_persistence:boolean};events:any[];notifications:any[];
};
const today = () => new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());
const fmt = (v:any) => v == null ? '待更新' : Number(v).toLocaleString('zh-CN',{minimumFractionDigits:2,maximumFractionDigits:2});
const stamp = (v:string) => v ? new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',month:'long',day:'numeric',hour:'2-digit',minute:'2-digit'}).format(new Date(v)) : '尚未更新';
const sidOf = (s:Security) => s.id || s.exchange+':'+s.ticker;

function App(){
  const [data,setData]=useState<Data|null>(null),[page,setPage]=useState('home');
  const [error,setError]=useState(''),[notice,setNotice]=useState(''),[pending,setPending]=useState('');
  const [hidden,setHidden]=useState(localStorage.getItem('wealth-visible')!=='yes');
  const [selected,setSelected]=useState(''),[report,setReport]=useState<any>(null);
  const [query,setQuery]=useState(''),[found,setFound]=useState<Security[]>([]);
  const [editing,setEditing]=useState<any>(null),[showHolding,setShowHolding]=useState(false);
  const [evidence,setEvidence]=useState<any[]>([]),[showEvidence,setShowEvidence]=useState(false);
  const [credentialForm,setCredentialForm]=useState({kimi_key:'',push_key:''});
  const previewSeen=useRef('');
  const [task,setTask]=useState<{id:string;label:string;completion?:string;detail?:string;progress?:number;cancelling?:boolean;elapsed?:number;completed?:number;total?:number}|null>(null);
  const [removeId,setRemoveId]=useState('');
  const [feedbackHeight,setFeedbackHeight]=useState(0);
  const [completedResult,setCompletedResult]=useState<any>(null);
  const [resultJump,setResultJump]=useState<{id:string;token:number}|null>(null);
  const [researchQuestion,setResearchQuestion]=useState('业务、最新变化、估值与继续持有的风险');
  const [config,setConfig]=useState<any>(null);
  const [valuation,setValuation]=useState<any>(null);
  async function api(path:string,method='GET',body?:any){
    const response=await fetch('/api'+path,{method,headers:{'Content-Type':'application/json','X-App-Token':data?.csrf||''},body:body===undefined?undefined:JSON.stringify(body)});
    const result=await response.json();
    if(!response.ok){
      const detail=result.detail;
      throw new Error(typeof detail==='string'?detail:Array.isArray(detail)?detail.map((x:any)=>x.msg).join('；'):'操作未完成，请重试。');
    }return result;
  }
  async function load(){
    const d=await api('/bootstrap');setData(d);setConfig((old:any)=>old||d.settings);
    setSelected(old=>d.followed.some((s:Security)=>s.id===old)?old:(d.followed[0]?.id||''));
    return d;
  }
  useEffect(()=>{load().catch(e=>setError(e.message));},[]);
  useEffect(()=>{
    let active=true;
    const latest=data?.reports.find(r=>page==='portfolio'?r.kind==='portfolio':page==='research'&&r.security_id===selected);
    const compatible=page==='portfolio'?report?.kind==='portfolio':report?.security_id===selected;
    if(latest&&!compatible)api('/reports/'+latest.id).then(r=>{if(active)setReport(r)}).catch(e=>{if(active)setError(e.message)});
    return()=>{active=false};
  },[page,selected]);
  useEffect(()=>{
    const update=()=>{if(document.visibilityState==='visible')load().catch(e=>setError(e.message));};
    const timer=setInterval(update,30000);
    document.addEventListener('visibilitychange',update);
    return()=>{clearInterval(timer);document.removeEventListener('visibilitychange',update);};
  },[]);
  useEffect(()=>{
    if(!task)return;
    let active=true;
    const timer=setInterval(async()=>{
      try{
        const j=await api('/jobs/'+task.id);
        if(!active)return;
        if((j.status==='running'||j.status==='queued')&&j.message)setTask(current=>current?.id===task.id?{...current,detail:j.message,progress:j.progress,elapsed:j.elapsed_seconds,completed:j.completed_sections,total:j.total_sections}:current);
        if(j.status==='running'&&j.completed_sections>0){
          const revision=j.preview_run+':'+j.completed_sections;
          if(previewSeen.current!==revision){
            const preview=await api('/jobs/'+task.id+'/preview');
            if(active&&preview.available){previewSeen.current=revision;setReport(preview);setPage('research');if(preview.security_id)setSelected(preview.security_id);}
          }
        }
        if(j.status==='cancelling')setTask(current=>current?.id===task.id?{...current,cancelling:true,detail:j.message}:current);
        if(j.status==='cancelled'){clearInterval(timer);const fresh=await load();if(active){setTask(null);setCompletedResult(null);setReport((current:any)=>current?.preview&&current.job_id===task.id?null:current);setNotice('已取消，本次报告与草稿未保存。');}return;}
        if(j.status==='done'||j.status==='failed'){
          clearInterval(timer);await load();
          if(j.status==='failed'){setError(j.message);setReport((current:any)=>current?.preview&&current.job_id===task.id?{...current,previewFailed:true}:current);}
          else {
            if(j.result_id){const r=await api('/reports/'+j.result_id);if(active)setCompletedResult(r);if(active&&r.kind==='news_analysis'){setPage('home');}else if(active){setReport(r);if(r.security_id)setSelected(r.security_id);if(r.kind!=='brief')setPage(r.kind==='portfolio'?'portfolio':'research');}}
            if(active)setNotice((task.completion||'任务已完成并保存。')+' · 100%');
          }
          if(active)setTask(null);
        }
      }catch(e:any){if(active){setError(e.message);setTask(null);clearInterval(timer);}}
    },900);
    return()=>{active=false;clearInterval(timer)};
  },[task?.id]);
  useEffect(()=>{
    let active=true;setEvidence([]);setValuation(null);
    if(selected){
      Promise.all([api('/evidence/'+encodeURIComponent(selected)),api('/valuation/'+encodeURIComponent(selected))]).then(([e,v])=>{if(active){setEvidence(e);setValuation(v);}}).catch(e=>{if(active)setError(e.message);});
    }
    return ()=>{active=false};
  },[selected,data?.reports.length,data?.settings.last_refresh,data?.portfolio.fx?.rate,data?.settings['collection:'+selected]?.checked_at]);
  async function action(label:string,fn:()=>Promise<any>){
    setError('');setNotice('');setCompletedResult(null);setPending(label);
    try{await fn();}catch(e:any){setError(e.message);}finally{setPending('');}
  }
  async function job(path:string,label:string,body:any={}){
    if(task)throw new Error('已有任务在处理，请等待完成。');
    const r=await api(path,'POST',body);setTask({id:r.job_id,label,completion:/research|followup|news\/analyze/.test(path)?'分析已完成，结果已保存。':path==='/brief'?'简报已整理完成并保存。':'更新已完成。'});
  }
  async function cancelAnalysis(){
    if(!task||task.cancelling)return;
    const id=task.id;setTask(current=>current?.id===id?{...current,cancelling:true,detail:'正在停止…'}:current);
    try{
      const result=await api('/jobs/'+id+'/cancel','POST',{});
      if(result.accepted){setTask(null);setCompletedResult(null);setReport((current:any)=>(current?.preview&&current.job_id===id)||(result.discarded_report_ids||[]).includes(current?.id)?null:current);setNotice('已取消，本次报告与草稿未保存。');previewSeen.current='';void load().catch(()=>{});}
      else setTask(current=>current?.id===id?{...current,cancelling:false}:current);
    }
    catch(e:any){setError(e.message);setTask(current=>current?.id===id?{...current,cancelling:false}:current);}
  }
  function viewCompletedResult(){
    if(!completedResult)return;
    const r=completedResult;
    if(r.kind==='brief'){setData(d=>d?{...d,brief:r}:d);setPage('home');}
    else if(r.kind==='news_analysis'){setPage('home');}
    else {setReport(r);if(r.security_id)setSelected(r.security_id);setPage(r.kind==='portfolio'?'portfolio':'research');}
    setResultJump({id:r.kind==='news_analysis'?'news:'+r.payload.news_id:'report:'+r.id,token:Date.now()});
  }
  useEffect(()=>{
    if(!resultJump||resultJump.id.startsWith('news:'))return;
    const frame=requestAnimationFrame(()=>{
      const node=Array.from(document.querySelectorAll<HTMLElement>('[data-result-id]')).find(n=>n.dataset.resultId===resultJump.id);
      node?.scrollIntoView({behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth',block:'start'});
      node?.focus({preventScroll:true});
    });
    return()=>cancelAnimationFrame(frame);
  },[resultJump,page]);
  function formValues(e:React.FormEvent<HTMLFormElement>){e.preventDefault();return Object.fromEntries(new FormData(e.currentTarget));}
  function toggleHidden(){setHidden(!hidden);localStorage.setItem('wealth-visible',hidden?'yes':'no');}
  const amount=(v:any)=>hidden?'••••••':fmt(v);
  const navigate=(p:string)=>{setPage(p);setRemoveId('');};
  const disabled=!!pending||!!task;
  if(!data)return <main className="initial"><Leaf size={36}/><h1>投资信息台</h1><p>{error||'正在打开你的本地资料…'}</p>{error&&<button onClick={()=>load().catch(e=>setError(e.message))}>重试</button>}</main>;
  const company=data.followed.find(s=>s.id===selected);
  const securityFields=(item:any={})=><div className="form-grid">
    <label>交易所{item.id&&<input type="hidden" name="exchange" value={item.exchange}/>}<select name={item.id?undefined:'exchange'} disabled={!!item.id} defaultValue={item.exchange||'SH'} required><option value="SH">上交所 · A股</option><option value="SZ">深交所 · A股</option><option value="BJ">北交所 · A股</option><option value="HK">香港 · 港股</option></select></label>
    <label>股票代码<input name="ticker" readOnly={!!item.id} defaultValue={item.ticker||''} inputMode="numeric" placeholder="如 600519 或 00700" required maxLength={6}/></label>
    <label className="wide">公司名称<input name="name" defaultValue={item.name||''} placeholder="如 贵州茅台、腾讯控股" required maxLength={60}/></label>
  </div>;
  const searchBar=<form className="search-bar" onSubmit={e=>{e.preventDefault();action('搜索证券',async()=>setFound(await api('/search?q='+encodeURIComponent(query))));}}>
    <Search size={22}/><input aria-label="搜索公司或股票代码" value={query} onChange={e=>setQuery(e.target.value)} placeholder="输入公司名称或股票代码" required/>
    <button className="primary" disabled={disabled}>查找公司</button>
  </form>;
  const searchResults=found.length>0&&<div className="search-results">{found.map(s=><button key={sidOf(s)} className="result-row" disabled={disabled} onClick={()=>action('加入关注',async()=>{
    const r=await api('/watchlist','POST',s);setSelected(r.id);await load();setFound([]);setQuery('');setNotice('已加入自选，正在自动收集财报和公告。');if(r.collection_job)setTask({id:r.collection_job,label:'自动收集公司资料'});
  })}><span><strong>{s.name}</strong><small>{s.exchange} · {s.ticker}</small></span><span>加入关注<Plus size={18}/></span></button>)}</div>;
  return <div className="shell" style={{'--feedback-clearance':`${feedbackHeight}px`} as React.CSSProperties}>
    <aside className="sidebar">
      <a className="brand" href="#home" onClick={()=>navigate('home')}><span className="brand-mark"><Leaf size={25}/></span><span>投资信息台</span></a>
      <nav aria-label="主要导航">{[['home','今日关注',BookOpen],['research','公司研究',Search],['portfolio','我的持仓',BriefcaseBusiness]].map(([p,label,Icon]:any)=><button key={p} className={page===p?'nav active':'nav'} onClick={()=>navigate(p)}><Icon size={22}/>{label}{page===p&&<ChevronRight size={18}/>}</button>)}</nav>
      <div className="sidebar-note"><ShieldCheck size={17}/><span>数据保存在本机</span></div>
      <button className={page==='settings'?'nav active settings-nav':'nav settings-nav'} onClick={()=>navigate('settings')}><Settings2 size={19}/>维护设置</button>
    </aside>
    <main>
      <FeedbackDock error={error} notice={notice} progress={task?(task.detail||task.label):pending?pending+'…':''} percent={task?.progress??(task?0:undefined)} onCancel={task?cancelAnalysis:undefined} cancelling={!!task?.cancelling} elapsed={task?.elapsed} completed={task?.completed} total={task?.total} onErrorClose={()=>setError('')} onNoticeClose={()=>{setNotice('');setCompletedResult(null)}} onViewResult={completedResult?viewCompletedResult:undefined} onHeight={setFeedbackHeight}/>
      {feedbackHeight>0&&<div className="feedback-spacer" aria-hidden="true" style={{height:feedbackHeight}}/>}
      <header className="topline"><span>{new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',year:'numeric',month:'long',day:'numeric',weekday:'long'}).format(new Date())}</span><span className="local-state"><span/>本机运行</span></header>
      {page==='home'&&<>
        <div className="page-heading"><h1>今日关注</h1><p>与你关注的公司有关的信息</p></div>
        <div className="home-layout"><section className="reading-paper result-target" data-result-id={data.brief?'report:'+data.brief.id:undefined} tabIndex={-1}>
          <div className="section-title"><h2>今日简报</h2><button className="text-button" disabled={disabled} onClick={()=>action('整理简报',()=>job('/brief','整理简报'))}><RefreshCw size={17}/>整理原文</button><button className="secondary" disabled={disabled} onClick={()=>action('AI总结简报',()=>job('/brief','总结今日关键内容',{analyze:true}))} title="调用 Kimi 总结关键内容，计入预算">AI 总结</button></div>
          {data.brief?<><p className="meta">生成于 {stamp(data.brief.created_at)} · {data.brief.payload.mode==='ai_digest'?'AI 要点':'原文要点'}</p>
            {data.brief.payload.items.length?data.brief.payload.items.map((item:any,i:number)=><article className="brief-item" key={i}><h3>{item.title}</h3><p>{item.text.startsWith('与你的关注清单相关。')?(data.news?.find((n:any)=>n.url===item.url)?.summary||'旧简报尚未提炼要点，请点击「整理一份」。'):item.text}</p>{item.summary_kind&&<small>{item.summary_kind}</small>}<div className="article-foot"><span>{item.date}</span><a href={item.url} target="_blank" rel="noreferrer">阅读原始来源<ExternalLink size={15}/></a></div></article>):<div className="empty-inline"><FileText size={34}/><h3>暂未获得可展示的新资料</h3><p>请检查关注清单和数据更新状态。<br/>这不代表市场没有重要信息。</p></div>}
            {data.brief.payload.analysis&&<article className="brief-item"><h3>分析与可能影响（推论）</h3><p>{data.brief.payload.analysis.summary}</p></article>}
            <div className="reading-note">{data.brief.payload.notes.map((n:string,i:number)=><p key={i}>{n}</p>)}</div>
          </>:<div className="empty-inline"><BookOpen size={38}/><h3>从你关心的公司开始</h3><p>添加持仓或自选公司后，自动收集资料。<br/>简报会围绕这些公司整理。</p><button className="primary" onClick={()=>navigate('portfolio')}>添加关注公司<ArrowRight size={18}/></button></div>}
        </section><aside className="home-side">
          <section><h2>重点关注与新披露</h2><p className="meta">{data.settings.scheduler_paused?'自动收集已暂停':data.settings.scheduler_enabled?'每30分钟自动更新':'自动收集未开启'}</p>{data.alerts.length?data.alerts.map((a:any)=><div className={a.priority==='high'?'attention important-attention':'attention'} key={a.key}><small>{a.priority==='high'?'重点关注 · ':'新披露 · '}{a.reason}</small><h3>{a.title}</h3><p>{a.text}</p>{a.url&&<a href={a.url} target="_blank" rel="noreferrer">查看来源<ExternalLink size={14}/></a>}</div>):<p className="muted">本次检查未触发已配置提醒。<br/>覆盖 {data.followed.length} 家关注公司；部分数据可能尚未更新。</p>}<p className="meta">最近检查：{stamp(data.settings.last_refresh)}</p></section>
          <section className="research-invite"><h2>公司研究</h2><button className="secondary" onClick={()=>navigate('research')}>研究一家公司<ArrowRight size={17}/></button></section>
          <section className="delivery"><Bell size={21}/><div><strong>微信简报</strong><p>{data.settings.scheduler_enabled&&!data.settings.scheduler_paused&&data.settings.push_enabled&&data.connections.push?'开机联网时，每天 '+(data.settings.daily_times||[data.settings.daily_time]).join('、')+' 更新':'尚未开启，请在维护设置中配置'}</p></div></section>
        </aside></div>
        <NewsFeed resultJump={resultJump} news={data.news||[]} disabled={disabled} status={data.settings.news_status} onRefresh={()=>action('更新新闻',()=>job('/news/refresh','更新官方新闻'))} onAnalyze={(news_id:string)=>action('分析新闻',()=>job('/news/analyze','分析新闻关键内容与影响',{news_id}))}/>
      </>}
      {page==='portfolio'&&<>
        <div className="page-heading split"><div><h1>我的持仓</h1></div><button className="primary" onClick={()=>{setEditing(null);setShowHolding(!showHolding)}}><Plus size={19}/>添加持仓</button></div>
        <div className="portfolio-summary"><div><span>已录入资产估值 · 人民币</span><div className="valuation">{amount(data.portfolio.known_total)}<button className="icon-button" aria-label={hidden?'显示金额':'隐藏金额'} onClick={toggleHidden}>{hidden?<Eye size={21}/>:<EyeOff size={21}/>}</button></div></div><p>{!data.portfolio.has_assets?'尚未录入持仓或现金':data.portfolio.complete?'按已录入资产计算，不代表全部财富':'估值不完整；缺少行情或汇率，仓位暂不计算'}{data.portfolio.fx_stale&&<><br/>港币汇率已超过四天，请更新。</>}</p><button className="secondary" disabled={disabled} onClick={()=>action('更新资料',()=>job('/quotes/refresh','更新报价'))}><RefreshCw size={18}/>更新行情</button></div>
        <button className="primary" disabled={disabled||!data.portfolio.positions.length} onClick={()=>action('分析组合',()=>job('/portfolio/research','正在分析持仓与最新资料'))}>分析我的持仓<ArrowRight size={18}/></button>
        {report?.kind==='portfolio'&&<ReportReader report={report} amount={amount} disabled={disabled} onClose={()=>setReport(null)}/>}
        {data.reports.some(r=>r.kind==='portfolio')&&<details className="report-history"><summary>历史组合报告</summary>{data.reports.filter(r=>r.kind==='portfolio').map(r=><button className="history-row" key={r.id} onClick={()=>action('打开组合报告',async()=>setReport(await api('/reports/'+r.id)))}><FileText size={20}/><span>{r.payload.title}<small>{stamp(r.created_at)}</small></span></button>)}</details>}
        <AccountSummary p={data.portfolio} amount={amount}/>
        {showHolding&&<section className="form-section"><div className="section-title"><h2>{editing?'修改持仓':'添加持仓'}</h2><button className="icon-button" aria-label="关闭录入" onClick={()=>setShowHolding(false)}><X size={20}/></button></div><form key={editing?.id||'new'} onSubmit={e=>{const f=formValues(e);action('保存持仓',async()=>{const r=await api('/positions','POST',f);if(r.collection_job)setTask({id:r.collection_job,label:'自动收集公司资料'});setShowHolding(false);setEditing(null);await load();setNotice('持仓已保存在本机。');});}}>
          {securityFields(editing||{})}<div className="form-grid"><label>持有数量（股）<input name="quantity" type="number" min="0.000001" step="0.000001" required defaultValue={editing?.quantity||''}/></label><label>券商显示的每股成本<input name="cost" type="number" step="0.000001" required defaultValue={editing?.cost||''}/></label><label className="wide">成本说明（选填）<input name="note" maxLength={300} defaultValue={editing?.note||''} placeholder="例如：券商显示的摊薄成本"/></label></div>
          <p className="help">币种随交易所确定。浮盈亏按填写成本计算，不含未录入的分红、费用与历史交易。</p><button className="primary" disabled={disabled}>保存持仓<Check size={18}/></button>
        </form></section>}
        <section className="table-section"><h2>持仓明细</h2>{data.portfolio.positions.length?<div className="table-scroll"><table><thead><tr><th>公司</th><th>数量 / 成本</th><th>市值 / 浮盈亏</th><th>仓位</th><th>操作</th></tr></thead><tbody>{data.portfolio.positions.map((p:any)=><tr key={p.id}><td><strong>{p.name}</strong><small>{p.exchange} · {p.ticker} · {p.currency}</small><small>{p.as_of?(p.quote_metadata?.quoted_at?stamp(p.quote_metadata.quoted_at):p.as_of+' · 只有日期')+' · '+(p.quote_metadata?.delay_seconds?'延迟约'+Math.ceil(p.quote_metadata.delay_seconds/60)+'分钟':'延迟未确认'):'尚无报价'}</small></td><td>{hidden?'••••':fmt(p.quantity)}<small>券商成本 {amount(p.broker_cost??p.cost)} · {p.cost_currency||p.currency}</small></td><td>{amount(p.market_value)}<small className={p.gain&&Number(p.gain)<0?'loss':''}>核算盈亏 {amount(p.gain_cny??p.snapshot_gain_cny??p.gain)}{p.broker_gain!=null&&<small>券商显示盈亏 {amount(p.broker_gain)} CNY</small>}</small></td><td>{p.weight==null?'待完善':p.weight+'%'}</td><td><div className="row-actions"><button onClick={()=>{setEditing(p);setShowHolding(true)}}>修改</button><button onClick={()=>{setSelected(p.id);navigate('research');setReport(null)}}>研究</button><button className="danger" onClick={()=>{if(removeId===p.id)action('移除持仓',async()=>{await api('/positions/'+encodeURIComponent(p.id),'DELETE');await load();setRemoveId('')});else setRemoveId(p.id)}}>{removeId===p.id?'确认移除':'移除'}</button></div></td></tr>)}</tbody></table></div>:<div className="empty-row"><BriefcaseBusiness size={28}/><p>还没有录入持仓。只需要公司、数量和成本即可开始。</p></div>}<p className="help">{data.portfolio.valuation_note}</p></section>
        <div className="two-columns">
          <section className="form-section"><h2>现金与汇率</h2><FxStatus portfolio={data.portfolio} disabled={disabled} onRefresh={()=>action('更新汇率',()=>job('/fx/refresh','更新港币参考汇率'))}/><details><summary>调整现金</summary><form onSubmit={e=>{const f=formValues(e);action('保存现金',async()=>{await api('/cash','POST',f);await load();setNotice('现金已保存。');})}}>
            <div className="form-grid"><label>币种<select name="currency"><option value="CNY">人民币</option><option value="HKD">港币</option></select></label><label>现金余额<input type="number" name="amount" min="0" step="0.01" required/></label></div><button className="secondary" disabled={disabled}>保存现金</button>
          </form></details>{data.portfolio.cash.map((c:any)=><p className="cash-line" key={c.currency}>{c.currency==='CNY'?'人民币':'港币'}现金 <strong>{amount(c.amount)}</strong></p>)}
          <details><summary>手动修正汇率</summary><form onSubmit={e=>{const f=formValues(e);action('保存汇率',async()=>{await api('/fx','POST',f);await load();setNotice('汇率已保存。');})}}><label>1 港币折合人民币<input name="rate" type="number" step="0.000001" min="0.000001" required defaultValue={data.portfolio.fx?.rate||''}/></label><label>汇率日期<input name="as_of" type="date" required defaultValue={data.portfolio.fx?.as_of||today()} max={today()}/></label><label>来源<input name="source" required minLength={2} placeholder="例如：中国银行网站"/></label><button className="secondary" disabled={disabled}>保存汇率</button></form></details>
          </section>
          <section className="form-section"><h2>自选公司</h2>{searchBar}{searchResults}<details><summary>按代码手动加入</summary><form onSubmit={e=>{const f=formValues(e);action('保存自选',async()=>{const r=await api('/watchlist','POST',f);if(r.collection_job)setTask({id:r.collection_job,label:'自动收集公司资料'});await load();setNotice('已加入自选，软件自动收集资料。');})}}>{securityFields()}<button className="secondary" disabled={disabled}>加入自选</button></form></details>
            <div className="watchlist">{data.watchlist.map(s=><div key={s.id}><span><strong>{s.name}</strong><small>{s.exchange} · {s.ticker}</small></span><button className="icon-button" aria-label={'移除自选'+s.name} onClick={()=>action('移除自选',async()=>{await api('/watchlist/'+encodeURIComponent(s.id!),'DELETE');await load()})}><X size={17}/></button></div>)}</div>
          </section>
        </div>
      </>}
      {page==='research'&&<>
        <div className="page-heading"><h1>公司研究</h1></div>{searchBar}{searchResults}
        <div className="company-select"><label>当前关注公司<select value={selected} onChange={e=>{setSelected(e.target.value);setReport(null)}}><option value="">请选择公司</option>{data.followed.map(s=><option key={s.id} value={s.id}>{s.name} · {s.ticker}</option>)}</select></label><button className="text-button" onClick={()=>navigate('portfolio')}>手动添加公司<Plus size={17}/></button></div>
        {company?<><section className="research-start"><div><h2>{company.name}</h2><p>{company.exchange} · {company.ticker}　{evidence.filter(e=>e.verification!=='title_only').length} 份资料</p></div><button className="primary" disabled={disabled} onClick={()=>action('开始研究',()=>job('/research','研究公司',{security_id:selected,question:researchQuestion}))}>开始分析<ArrowRight size={18}/></button></section>
          <div className="research-topics"><p>研究主题</p><div className="button-row">{['主要靠什么赚钱','最近有什么变化','估值怎么看','继续持有要关注什么'].map(q=><button key={q} className={researchQuestion===q?'primary':'secondary'} aria-pressed={researchQuestion===q} onClick={()=>setResearchQuestion(q)}>{q}</button>)}</div><label>研究问题<input value={researchQuestion} onChange={e=>setResearchQuestion(e.target.value)} maxLength={300}/></label></div>
          {(!data.connections.kimi||!data.settings.prices_confirmed)&&<p className="reading-note">请在维护设置粘贴 Kimi API 密钥。</p>}
          {report&&report.kind!=='portfolio'&&report.kind!=='brief'&&<ReportReader report={report} amount={amount} disabled={disabled} onClose={()=>setReport(null)} onFollowup={(q:string)=>action('回答问题',()=>job('/reports/'+report.id+'/followup','回答问题',{question:q}))}/> }
          {!report&&<div className="report-empty"><h3>点击分析，报告会自动打开</h3></div>}
          <details className="research-data"><summary>资料与估值参考</summary>
          <div className="collection-state" role="status"><p>{data.settings['collection:'+selected]?.message||'添加公司后自动查找财报和公告。'}</p><button className="secondary" disabled={disabled} onClick={()=>action('自动收集资料',()=>job('/collect/'+encodeURIComponent(selected),'自动收集公司资料'))}><RefreshCw size={18}/>重新收集资料</button></div>
          <section className="sources-section"><div className="section-title"><h2>自动收集的研究资料</h2><button className="text-button" onClick={()=>setShowEvidence(!showEvidence)}><Plus size={17}/>{showEvidence?'收起补录':'数据源失败时补录'}</button></div>
            {showEvidence&&<form className="evidence-form" onSubmit={e=>{const f=formValues(e);action('保存资料',async()=>{await api('/evidence','POST',{...f,security_id:selected});setEvidence(await api('/evidence/'+encodeURIComponent(selected)));setShowEvidence(false);setNotice('原文已保存。手动资料仍需核实。');})}}>
              <div className="form-grid"><label className="wide">资料标题<input name="title" required minLength={2} maxLength={200}/></label><label className="wide">原始来源链接<input name="url" type="url" required placeholder="https://…" id="source-url"/></label>
                <label>发布日期<input name="published_at" type="date" required defaultValue={today()} max={today()}/></label><label>资料类型<select name="kind"><option value="financial">财报</option><option value="announcement">公告</option><option value="news">新闻</option></select></label><label>报告期（选填）<input name="report_period" placeholder="如 2026 年半年报"/></label><label>页码或章节（选填）<input name="locator" placeholder="如 第 12 页"/></label>
              </div><label>原文内容<textarea name="content" id="source-content" rows={8} minLength={20} maxLength={80000} required placeholder="粘贴原文，保留单位、报告期和页码。只有标题不能形成研究。"/></label>
              <div className="button-row"><button className="secondary" type="button" disabled={disabled} onClick={()=>action('读取官方 PDF',async()=>{
                const input=document.getElementById('source-url') as HTMLInputElement;const result=await api('/import-pdf','POST',{url:input.value});(document.getElementById('source-content') as HTMLTextAreaElement).value=result.content;setNotice(result.note);
              })}>从官方 PDF 读取</button><button className="primary" disabled={disabled}>保存原文</button></div><p className="help">支持巨潮、交易所、披露易 PDF 直链。自动提取文本后仍需核对日期、标题和完整性。</p>
            </form>}
            {evidence.length?evidence.map(e=><div className="source-row" key={e.id}><FileText size={19}/><div><a href={e.url} target="_blank" rel="noreferrer">{e.title}<ExternalLink size={14}/></a><small>{e.published_at} · {e.verification==='title_only'?'仅标题，尚未读取原文':e.verification==='official_download'?'官方PDF自动获取（可能截断）':e.verification==='aggregated'?'聚合财务数据，尚待核实':'手动资料，尚待核实'} · {e.locator||'未填写页码'}</small></div></div>):<p className="muted">软件正在查找官方财报和公告。收集失败时会显示原因，可以稍后重新收集。</p>}
          </section>
          <section className="sources-section"><h2>估值参考（代码计算）</h2><p className="help">按所存报价和财报每股指标计算；输入仍需核实，倍数本身不能决定是否值得投资。</p>
            <div className="valuation-metrics"><div><span>PE（倍）</span><strong>{valuation?.pe??'暂不计算'}</strong></div><div><span>PB（倍）</span><strong>{valuation?.pb??'暂不计算'}</strong></div><div><span>历史股息率（%）</span><strong>{valuation?.dividend_yield??'暂不计算'}</strong></div></div>
            {valuation?.inputs&&<p className="meta">{valuation.inputs.report_period} · {valuation.inputs.earnings_basis==='ttm'?'滚动十二个月':'年度'}每股收益 · 财报币种 {valuation.inputs.currency} · <a href={valuation.inputs.url} target="_blank" rel="noreferrer">{valuation.inputs.title}</a> · {valuation.inputs.locator}</p>}
            {valuation?.warnings?.map((w:string,i:number)=><p className="help" key={i}>{w}</p>)}
            <details><summary>查看计算输入／数据源失败时修正</summary><p className="help">指标默认自动获取。只有需要纠正来源数据时才使用以下补录。填写的是“每股”的金额，币种以财报为准；不要把万元、总额或半年收益当作年度每股值。缺失项留空，零股息只在原文明确无全年现金股息时填写。</p><form key={selected+':valuation'} onSubmit={e=>{const f:any=formValues(e);['eps','book_per_share','dividend_per_share'].forEach(k=>{if(!f[k])f[k]=null});action('保存财务指标',async()=>{setValuation(await api('/valuation/'+encodeURIComponent(selected),'PUT',f));setNotice('指标已保存，估值由代码重算；原文与口径仍需核对。');})}}>
              <label>所引财报<select name="evidence_id" required defaultValue={valuation?.inputs?.evidence_id||''}><option value="">请选择原文</option>{evidence.filter(e=>e.verification!=='title_only').map(e=><option key={e.id} value={e.id}>{e.title}</option>)}</select></label>
              <div className="form-grid"><label>财报币种<select name="currency" defaultValue={valuation?.inputs?.currency||'CNY'}><option value="CNY">人民币</option><option value="HKD">港币</option></select></label><label>收益口径<select name="earnings_basis" defaultValue={valuation?.inputs?.earnings_basis||'annual'}><option value="annual">完整年度</option><option value="ttm">滚动十二个月</option></select></label><label>报告期<input name="report_period" minLength={4} maxLength={60} required defaultValue={valuation?.inputs?.report_period||''} placeholder="例如：2025年度"/></label><label>财务截止日期<input name="as_of" type="date" required max={today()} defaultValue={valuation?.inputs?.as_of||''}/></label>
                {[['eps','每股收益（元 / 股）'],['book_per_share','每股净资产（元 / 股）'],['dividend_per_share','全年每股现金股息（元 / 股）']].map(([k,label])=><label key={k}>{label}<input name={k} type="number" step="0.000001" min={k==='dividend_per_share'?0:undefined} defaultValue={valuation?.inputs?.[k]??''}/></label>)}<label>页码及会计口径<input name="locator" required minLength={2} maxLength={100} defaultValue={valuation?.inputs?.locator||''} placeholder="如第12页，基本每股收益"/></label></div><button className="secondary" disabled={disabled}>保存指标并重算</button>
            </form><div className="help">{valuation?.quote&&<p>报价 {valuation.quote.price} {company.currency}，{valuation.quote.as_of}，{valuation.quote.source}</p>}{valuation?.fx&&<p>换算汇率 1港币 = {valuation.fx.rate}人民币，{valuation.fx.as_of}，{valuation.fx.source}</p>}<p>PE = 股价 ÷ 同币种每股收益；PB = 股价 ÷ 同币种每股净资产；历史股息率 = 全年每股现金股息 ÷ 同币种股价 × 100%。</p></div></details>
          </section>
          </details>
          <details className="report-history"><summary>历史研究</summary>
          {data.reports.filter(r=>r.security_id===selected).map(r=><button className="history-row" key={r.id} onClick={()=>action('打开报告',async()=>setReport(await api('/reports/'+r.id)))}><FileText size={21}/><span><strong>{r.payload.title}</strong><small>{stamp(r.created_at)}</small></span><ChevronRight size={20}/></button>)}
          </details>
        </>:<div className="empty-inline"><Search size={38}/><h2>先选择你想了解的公司</h2><p>可以搜索公司，也可以从持仓页手动添加。</p></div>}
      </>}
      {page==='settings'&&<>
        <div className="page-heading"><h1>维护设置</h1></div>
        <section className="form-section"><h2>连接服务</h2><div className="connection-list"><p><span className={data.connections.kimi?'status on':'status'}>{data.connections.kimi?'已填写':'待配置'}</span>Kimi 开放平台</p><p><span className={data.connections.push?'status on':'status'}>{data.connections.push?'已填写':'待配置'}</span>Server酱微信推送</p></div><p className="help">密钥状态不代表调用成功。</p>
          {!data.connections.secure_persistence&&<p className="reading-note">此 Mac 上密钥仅保留到程序退出。Windows 版使用凭据管理器。</p>}
          <form onSubmit={e=>{e.preventDefault();action('保存连接',async()=>{const saved=await api('/credentials','PUT',credentialForm);if(saved.settings)setConfig(saved.settings);setCredentialForm({kimi_key:'',push_key:''});await load();setNotice(saved.model_sync?.status==='unavailable'?'密钥已保存，模型配置暂未核实，请检查网络或密钥权限。':'连接已保存，模型参数自动配置。');})}}><label>Kimi API 密钥<input type="password" autoComplete="off" value={credentialForm.kimi_key} onChange={e=>setCredentialForm({...credentialForm,kimi_key:e.target.value})} placeholder="留空则保留现有密钥"/></label><label>Server酱 SendKey<input type="password" autoComplete="off" value={credentialForm.push_key} onChange={e=>setCredentialForm({...credentialForm,push_key:e.target.value})} placeholder="以 SCT 开头；留空则保留"/></label>
            <div className="button-row"><button className="primary" disabled={disabled}>保存连接</button><button className="secondary" type="button" disabled={disabled} onClick={()=>action('发送测试',async()=>{await api('/push-test','POST',{});await load();setNotice('服务已接受测试消息；请在微信确认收到。');})}>发送微信测试</button><button className="secondary" type="button" disabled={disabled} onClick={()=>action('测试重点提醒',async()=>{await api('/push-alert-test','POST',{});await load();setNotice('重点提醒测试已提交，请在微信确认收到。');})}>测试重点提醒</button></div>
          </form><div className="button-row small-actions"><button className="text-button" disabled={disabled} onClick={()=>action('清除密钥',async()=>{await api('/credentials','PUT',{clear_kimi:true});await load();setNotice('Kimi 密钥已清除；环境变量配置需另行移除。');})}>清除 Kimi 密钥</button><button className="text-button" disabled={disabled} onClick={()=>action('清除密钥',async()=>{await api('/credentials','PUT',{clear_push:true});await load();setNotice('推送密钥已清除；环境变量配置需另行移除。');})}>清除推送密钥</button></div>
        </section>
        <details className="maintenance-group"><summary>导入持仓与交易流水</summary><AccountTools job={job} api={api} action={action} load={load} disabled={disabled} settings={config||data.settings}/></details>
        {config&&<section className="form-section"><h2>更新、提醒与费用</h2><form onSubmit={e=>{e.preventDefault();action('保存设置',async()=>{const times=Array.from(new Set((config.daily_times||[config.daily_time]).map(normalizeBriefTime))).sort();const settings={...config,daily_times:times,daily_time:times[0]};const saved=await api('/settings','PUT',settings);setConfig(saved.settings||settings);await load();setNotice('设置已保存。电脑开机联网时后台按规则工作。');})}}>
          <p className="help">模型与费率自动获取，粘贴 Kimi API 密钥即可使用。</p><div className="form-grid">
            {[['monthly_limit','每月上限（元，最多200）'],['other_service_cost','其他服务月费（推送、数据等，元）'],['concentration','单股关注阈值（%）'],['move_threshold','价格变化阈值（%）']].map(([key,label])=><label key={key}>{label}<input type="number" step={key==='weekly_research_limit'?'1':'0.01'} min="0" required value={config[key]??'0'} onChange={e=>setConfig({...config,[key]:e.target.value})}/></label>)}
          </div><BriefTimesInput values={config.daily_times||[config.daily_time]} onChange={daily_times=>setConfig({...config,daily_times})}/><label>报价来源<select value={config.quote_provider||'public'} onChange={e=>setConfig({...config,quote_provider:e.target.value})}><option value="public">公开行情（可能延迟，按报价时间判断）</option><option value="futu">富途本地OpenD（需账号行情权限）</option></select></label>{[['online_research','研究时自动联网检索与补充资料'],['scheduler_enabled','启用定时收集（每30分钟）与每日简报'],['scheduler_paused','暂停开始新的定时任务（当前任务可完成）'],['push_enabled','启用微信推送（需绑定接收者）'],['auto_research','日报中启用 AI 原文分析（会产生费用）'],['event_research','新增重大资料时更新研究论点（会产生费用）']].map(([key,label])=><label className="check-label" key={key}><input type="checkbox" checked={!!config[key]} onChange={e=>setConfig({...config,[key]:e.target.checked})}/><span>{label}</span></label>)}
          <details className="model-settings"><summary>模型连接状态</summary><p className="help">当前模型：{config.model} · {config.model_sync?.status==='ready'?'已自动同步':config.model_sync?.status==='cached_rates'?'使用上次核实费率':'待自动核实'}</p>{config.model_sync?.message&&<p className="help">{config.model_sync.message}</p>}{config.model_sync?.checked_at&&<p className="help">最近检查：{stamp(config.model_sync.checked_at)}</p>}</details>
          <p className="help">费用按返回用量估算，以平台账单为准；超时保留预留费用。</p><button className="primary" disabled={disabled}>保存设置</button>
        </form><div className="budget-line"><span>{data.budget.month} 本机费用估算（含服务月费）：<strong>¥{fmt(data.budget.used)}</strong> / ¥{fmt(data.budget.limit)}</span>{data.budget.warning&&<strong className="loss">已达到预算的 80%</strong>}</div></section>}
        <details className="maintenance-group"><summary>备份与运行记录</summary><section className="form-section"><div className="section-title"><h2>维护与备份</h2><a className="secondary" href="/api/backup" download><Download size={18}/>下载数据库备份</a></div><p className="help">备份含个人资产与资料，不含密钥，请妥善保存。恢复需先停止程序，按 README 操作。</p>
          <div className="button-row"><button className="secondary" disabled={disabled} onClick={()=>action('更新资料',()=>job('/quotes/refresh','更新报价'))}>更新行情</button><button className="secondary" disabled={disabled} onClick={()=>action('推送日报',()=>job('/brief','整理并推送日报',{send:true}))}>整理并推送今日简报</button></div><h3>最近运行记录</h3>{data.events.length?data.events.map(e=><div className="log-row" key={e.id}><small>{stamp(e.created_at)}</small><span>{e.message}</span></div>):<p className="muted">尚无运行记录。</p>}<h3>最近推送</h3>{data.notifications.length?data.notifications.map(n=><div className="log-row" key={n.id}><small>{stamp(n.created_at)}</small><span>{n.title} · {n.message}</span></div>):<p className="muted">尚未发送消息。</p>}
        </section></details><details className="maintenance-group"><summary>手动修正行情</summary><section className="form-section"><h2>补录行情</h2><p className="muted">数据源不可用时，可录入带日期和来源的报价。不会被标为自动核实数据。</p><form onSubmit={e=>{const f:any=formValues(e);const sid=f.sid;delete f.sid;if(!f.previous)delete f.previous;action('保存报价',async()=>{await api('/quotes/'+encodeURIComponent(sid),'POST',f);await load();setNotice('手动报价已保存。');})}}>
          <label>公司<select name="sid" required><option value="">请选择</option>{data.followed.map(s=><option key={s.id} value={s.id}>{s.name}</option>)}</select></label><div className="form-grid"><label>每股价格<input name="price" type="number" min="0.000001" step="0.000001" required/></label><label>前一交易日价格（选填）<input name="previous" type="number" min="0.000001" step="0.000001"/></label><label>报价日期<input name="as_of" type="date" defaultValue={today()} max={today()} required/></label><label>报价来源<input name="source" minLength={2} required placeholder="如券商行情页面"/></label></div><button className="secondary" disabled={disabled}>保存报价</button>
        </form></section></details>
      </>}
      <footer>信息研究工具 · 不执行交易</footer>
    </main>
  </div>;
}
createRoot(document.getElementById('root')!).render(<App/>);
