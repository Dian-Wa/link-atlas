import {networkFetch} from './transport';
export const LOCAL_SERVICE='http://127.0.0.1:8787';
export type BridgeState={endpoint:string;status:'idle'|'checking'|'connected'|'offline';message:string};
let state:BridgeState={endpoint:LOCAL_SERVICE,status:'idle',message:'请启动本机抓取服务，然后点击连接'};
let pending:Promise<boolean>|null=null,lastCheck=0,nextCheck=0;
const key='atlas-local-fetch-enabled';
export function isLocalService(endpoint:string){try{return ['127.0.0.1','localhost','[::1]'].includes(new URL(endpoint).hostname);}catch{return false;}}
export const bridgeState=()=>state;
function update(value:BridgeState){state=value;window.dispatchEvent(new Event('atlas-bridge-changed'));}
export function bridgeDisconnected(endpoint:string){nextCheck=Date.now()+10000;update({endpoint,status:'offline',message:'本机服务未启动、已断开或浏览器未允许本地网络访问；任务继续排队'});}
export async function connectService(endpoint:string,interactive=true):Promise<boolean>{
 if(pending)return pending;
 if(interactive&&isLocalService(endpoint))sessionStorage.setItem(key,endpoint);
 update({endpoint,status:'checking',message:'正在连接，请在浏览器提示中允许本地网络访问…'});
 pending=(async()=>{try{const response=await networkFetch(endpoint.replace(/\/$/,'')+'/fetch-api/health',{signal:AbortSignal.timeout(interactive?20000:3000),referrerPolicy:'no-referrer',cache:'no-store'});const value=await response.json();if(!response.ok||value.app!=='link-atlas-fetch'||value.storage!=='none')throw Error('此地址不是拾链无数据库抓取服务');if(isLocalService(endpoint)&&value.mode!=='local')throw Error('本机服务版本不匹配，请运行新版启动脚本');lastCheck=Date.now();nextCheck=lastCheck+10000;update({endpoint,status:'connected',message:isLocalService(endpoint)?'本机抓取已连接 · 仅在这台电脑执行':'抓取服务已连接'});return true;}catch(error){bridgeDisconnected(endpoint);if((error as Error).message.includes('不是拾链')||(error as Error).message.includes('版本不匹配'))update({...state,message:(error as Error).message});return false;}finally{pending=null;}})();
 return pending;
}
export async function localServiceReady(endpoint:string){
 if(!isLocalService(endpoint))return true;
 if(sessionStorage.getItem(key)!==endpoint)return false;
 if(state.endpoint===endpoint&&state.status==='connected'&&Date.now()-lastCheck<10000)return true;
 if(Date.now()<nextCheck)return false;
 return connectService(endpoint,false);
}
