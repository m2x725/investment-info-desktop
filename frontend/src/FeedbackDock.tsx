import {useEffect,useLayoutEffect,useRef} from 'react';
import {Check,CircleAlert,LoaderCircle,X} from 'lucide-react';
export function FeedbackDock({error,notice,progress,onErrorClose,onNoticeClose,onViewResult,onHeight}:any){
 const ref=useRef<HTMLDivElement>(null);
 const closeHandlers=useRef({onErrorClose,onNoticeClose});
 closeHandlers.current={onErrorClose,onNoticeClose};
 useEffect(()=>{
  if(!error&&!notice)return;
  let timer:ReturnType<typeof setTimeout>;
  const reset=()=>{clearTimeout(timer);timer=setTimeout(()=>{if(error)closeHandlers.current.onErrorClose();if(notice)closeHandlers.current.onNoticeClose();},20000);};
  const events=['pointerdown','pointermove','keydown','scroll','wheel','touchstart'] as const;
  events.forEach(event=>window.addEventListener(event,reset,{passive:true,capture:true}));
  reset();
  return()=>{clearTimeout(timer);events.forEach(event=>window.removeEventListener(event,reset,true));};
 },[error,notice]);
 useLayoutEffect(()=>{const node=ref.current;if(!node)return;const measure=()=>onHeight(node.children.length?Math.ceil(node.getBoundingClientRect().height)+12:0);measure();const observer=new ResizeObserver(measure);observer.observe(node);return()=>observer.disconnect();},[error,notice,progress,onHeight]);
 return <div className="feedback-dock" ref={ref} aria-label="任务状态">
  {error&&<div className="feedback error" role="alert"><CircleAlert size={20}/><span>{error}</span><button aria-label="关闭错误提示" onClick={onErrorClose}><X size={18}/></button></div>}
  {notice&&<div className="feedback success" role="status" aria-live="polite"><Check size={20}/><span>{notice}</span>{onViewResult&&<button className="feedback-result" onClick={onViewResult}>查看结果</button>}<button aria-label="关闭成功提示" onClick={onNoticeClose}><X size={18}/></button></div>}
  {progress&&<div className="feedback progress" role="status" aria-live="polite"><LoaderCircle size={20} className="spin"/><span>{progress}</span></div>}
 </div>;
}
