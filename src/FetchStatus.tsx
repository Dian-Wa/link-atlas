import {useSyncExternalStore} from 'react';
import {bridgeState} from './local-bridge';
export type FetchInfo={id?:number;status:string;message?:string;fetch_message?:string;next_run?:number;attempts?:number;wait_reason?:string;fetch_local?:boolean;fetch_task?:FetchInfo};
let snapshot={time:Date.now(),bridge:bridgeState(),online:navigator.onLine};
const listeners=new Set<()=>void>();let timer:ReturnType<typeof setInterval>|null=null;
function update(){snapshot={time:Date.now(),bridge:bridgeState(),online:navigator.onLine};for(const listener of listeners)listener();}
function subscribe(listener:()=>void){listeners.add(listener);if(listeners.size===1){timer=setInterval(update,1000);window.addEventListener('atlas-bridge-changed',update);window.addEventListener('online',update);window.addEventListener('offline',update);}return()=>{listeners.delete(listener);if(!listeners.size){if(timer)clearInterval(timer);timer=null;window.removeEventListener('atlas-bridge-changed',update);window.removeEventListener('online',update);window.removeEventListener('offline',update);}};}
function useClock(){return useSyncExternalStore(subscribe,()=>snapshot);}
const labels:Record<string,string>={running:'抓取中',success:'抓取成功',partial:'部分完成',failed:'抓取失败'};
function seconds(value:number){const n=Math.max(0,Math.ceil(value));return n>=60?`${Math.floor(n/60)}分${n%60}秒`:`${n}秒`;}
export function describeFetch(item:FetchInfo,state=snapshot){const task=item.fetch_task??item,status=item.status,message=task.message||item.fetch_message||'',remaining=Math.max(0,(task.next_run??0)-state.time/1000),reason=task.wait_reason||(message.includes('限流')?'rate_limit':message.includes('本机')?'local_connection':message.includes('网络')?'network_retry':'queue');
 if(status!=='queued')return {label:labels[status]||status,detail:status==='running'?'正在读取元信息，你可以继续浏览和编辑。':message,remaining:0,task};
 if(!state.online)return {label:'等待网络恢复',detail:'浏览器当前离线，恢复网络后继续；原链接与资料保留。',remaining:0,task};
 if(remaining>0&&['rate_limit','network_retry','service_busy'].includes(reason)){const label=reason==='rate_limit'?'远端限流':reason==='service_busy'?'服务繁忙':'网络重试';return {label,detail:`${seconds(remaining)}后重试 · 下次尝试 ${new Date((task.next_run??0)*1000).toLocaleTimeString('zh-CN',{hour12:false})}`,remaining,task};}
 if(item.fetch_local!==false&&state.bridge.status!=='connected')return {label:'等待本机连接',detail:state.bridge.status==='checking'?'正在连接本机服务，请按浏览器提示授权。':'启动本机抓取工具，点击“连接本机抓取”，并允许本机网络访问；不会消耗网页重试次数。',remaining:0,task};
 return {label:'排队中',detail:remaining>0?`${seconds(remaining)}后继续尝试`:'等待空闲抓取位置；最多同时抓取 3 条。',remaining,task};
}
export function FetchStatus({item}:{item:FetchInfo}){const state=useClock(),view=describeFetch(item,state);return <span className={'status '+item.status} title={view.detail}><span/>{view.label}</span>;}
export function FetchMessage({item}:{item:FetchInfo}){const state=useClock(),view=describeFetch(item,state);return <span className="fetch-live-message" data-testid={view.remaining>0?'fetch-countdown-'+view.task.id:undefined}>{view.detail||'等待提取信息'}</span>;}
