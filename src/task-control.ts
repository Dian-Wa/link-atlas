import {now,type State,type Row,type Table} from './storage';
export function controlTask(s:State,put:(table:Table,row:Row)=>void,id:number,action:string){
 const t=s.tasks.find(x=>x.id===id&&!x.deleted),r=t&&s.resources.find(x=>x.id===t.resource_id&&!x.deleted);
 if(!t||!r)throw Error('任务或链接不存在');
 const allowed=action==='pause'?['queued','running']:action==='resume'?['paused']:action==='cancel'?['queued','running','paused']:[];
 if(!allowed.includes(t.status))throw Error('任务状态已变化，请刷新后再操作');
 const status=action==='pause'?'paused':action==='resume'?'queued':'canceled',message=action==='pause'?'已手动暂停，点击继续后才会抓取':action==='resume'?'已继续，等待抓取位置':'已取消抓取，链接与已有资料保留';
 put('tasks',{...t,status,owner:null,run_id:null,control_version:(t.control_version??0)+1,next_run:action==='cancel'?0:t.next_run,message,updated_at:now()});
 put('resources',{...r,status,fetch_message:message,updated_at:now()});
 return {status,message};
}
