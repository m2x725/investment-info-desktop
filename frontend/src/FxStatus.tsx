import {RefreshCw} from 'lucide-react';
const time=(value?:string)=>{if(!value)return '未记录';const d=new Date(value);return Number.isNaN(d.valueOf())?'未记录':d.toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',month:'numeric',day:'numeric',hour:'2-digit',minute:'2-digit',hour12:false});};
export function FxStatus({portfolio,disabled,onRefresh}:any){
 const p=portfolio,meta=p.fx_metadata||{},status=p.fx_status||{};
 return <div className="fx-status"><div className="fx-status-top"><div><span className="eyebrow">港币参考汇率</span><strong>{p.fx?`1 HKD = ${p.fx.rate} CNY`:'正在获取汇率'}</strong></div><button className="icon-button" aria-label="更新港币汇率" disabled={disabled} onClick={onRefresh}><RefreshCw size={18}/></button></div><p className="meta">{p.fx?`${p.fx.as_of} · ${meta.kind==='manual'?'手动录入':'每日参考值'}`:'暂无成功报价'}{meta.fetched_at&&` · 获取于 ${time(meta.fetched_at)}（北京时间）`}</p>{p.fx&&<details><summary>来源与更新状态</summary><p className="help">{p.fx.source}；用于参考估值，实际交收按券商流水。</p><p className="help">开机自动检查，运行时每30分钟检查；获取时间不代表报价时间。</p></details>}{(status.status==='failed'||p.fx_stale)&&<p className="fx-warning" role="status">{status.status==='failed'?status.message:'汇率日期较旧，等待来源更新。'}</p>}</div>;
}
