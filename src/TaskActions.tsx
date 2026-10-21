import {useState} from 'react';
import {Pause,Play,Square} from 'lucide-react';
export default function TaskActions({task,onChanged}:{task:{id?:number;status:string};onChanged:()=>Promise<unknown>}){
 const [busy,setBusy]=useState(false),[confirm,setConfirm]=useState(false),[error,setError]=useState('');
 const active=['queued','running','paused'].includes(task.status);
 if(!task.id||!active)return null;
 async function control(action:string){setBusy(true);setError('');try{const response=await fetch('/api/tasks/'+task.id+'/'+action,{method:'POST',body:'{}'}),value=await response.json();if(!response.ok)throw Error(value.detail);setConfirm(false);await onChanged();}catch(e){setError((e as Error).message);}finally{setBusy(false);}}
 return <div className="task-controls"><div className="task-control-buttons">{task.status==='paused'?<button className="button secondary small" disabled={busy} aria-label={'继续任务 '+task.id} onClick={()=>void control('resume')}><Play size={13}/>继续</button>:<button className="button secondary small" disabled={busy} aria-label={'暂停任务 '+task.id} onClick={()=>void control('pause')}><Pause size={13}/>暂停</button>}<button className="button secondary small" disabled={busy} aria-label={'取消任务 '+task.id} onClick={()=>setConfirm(true)}><Square size={13}/>取消抓取</button></div>{confirm&&<div className="task-cancel-confirm" role="alert"><p>取消此任务？链接和已有资料会保留，可重新发起抓取。</p><div><button className="button secondary small" disabled={busy} onClick={()=>setConfirm(false)}>返回</button><button className="button danger-button small" disabled={busy} onClick={()=>void control('cancel')}>确认取消抓取</button></div></div>}{error&&<p className="form-error" role="alert">{error}</p>}</div>;
}
