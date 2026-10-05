import {useId} from 'react';
export function normalizeBriefTime(value:string){
 const match=value.trim().replace('：',':').match(/^(\d{1,2}):(\d{1,2})$/);
 if(!match||Number(match[1])>23||Number(match[2])>59)return value;
 return match[1].padStart(2,'0')+':'+match[2].padStart(2,'0');
}
export function BriefTimeInput({value,onChange,label='每日简报时间（北京时间）'}: {value:string;onChange:(value:string)=>void;label?:string}){
 const helpId=useId();
 const normalized=normalizeBriefTime(value),valid=/^\d{2}:\d{2}$/.test(normalized);
 const [hour,minute]=valid?normalized.split(':'):['08','00'];
 return <div className="brief-time-field"><label>{label}<input type="text" inputMode="text" autoComplete="off" aria-describedby={helpId} required pattern="(0?[0-9]|1[0-9]|2[0-3])[:：]([0-5]?[0-9])" title="请输入00:00到23:59之间的时间" placeholder="例如 08:30" value={value} onChange={e=>onChange(e.target.value)} onBlur={e=>{const time=normalizeBriefTime(e.target.value);if(time!==value)onChange(time)}}/></label><small id={helpId}>24小时制，可直接输入，例如 08:30</small><details><summary>选择小时和分钟</summary><div className="brief-time-selects"><label>小时<select value={hour} onChange={e=>onChange(e.target.value+':'+minute)}>{Array.from({length:24},(_,i)=>String(i).padStart(2,'0')).map(v=><option key={v} value={v}>{v}</option>)}</select></label><span>:</span><label>分钟<select value={minute} onChange={e=>onChange(hour+':'+e.target.value)}>{Array.from({length:60},(_,i)=>String(i).padStart(2,'0')).map(v=><option key={v} value={v}>{v}</option>)}</select></label></div></details></div>;
}

export function BriefTimesInput({values,onChange}:{values:string[];onChange:(values:string[])=>void}){
 return <div className="brief-times"><h3>简报推送时间（北京时间）</h3><p className="help">每个时间点生成并推送一份。电脑需开机联网；晚开机补最近一份。</p>{values.map((value,i)=><div className="brief-time-row" key={i}><BriefTimeInput label={'时间 '+(i+1)} value={value} onChange={v=>onChange(values.map((old,j)=>j===i?v:old))}/><button type="button" className="text-button" disabled={values.length===1} aria-label={'移除时间 '+(i+1)} onClick={()=>onChange(values.filter((_,j)=>j!==i))}>移除</button></div>)}<button type="button" className="secondary" onClick={()=>{const next=Array.from({length:24},(_,i)=>String(i).padStart(2,'0')+':00').find(v=>!values.includes(v))||'08:30';onChange([...values,next]);}}>添加时间</button></div>;
}
