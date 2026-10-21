import {read,write,nextId,text,initialize,type Row} from './storage';
const AUTH='link-atlas-browser-accounts-v1',SESSION='atlas-browser-session';
export type User={id:number;username:string;workspace_name:string;avatar:string};
export const workspace=(id:number)=>'link-atlas-browser-space-'+id;
const hex=(buffer:ArrayBuffer)=>Array.from(new Uint8Array(buffer)).map(x=>x.toString(16).padStart(2,'0')).join('');
const random=()=>hex(crypto.getRandomValues(new Uint8Array(24)).buffer);
const sessionHashes=new Map<string,Promise<string>>();
async function hash(password:string,salt:string){const key=await crypto.subtle.importKey('raw',new TextEncoder().encode(password),'PBKDF2',false,['deriveBits']);return hex(await crypto.subtle.deriveBits({name:'PBKDF2',hash:'SHA-256',salt:new TextEncoder().encode(salt),iterations:600000},key,256));}
function password(value:unknown){if(typeof value!=='string'||value.length<8||value.length>128)throw Error('密码需要 8–128 个字符');return value;}
const profile=(row:Row):User=>({id:row.id,username:row.username,workspace_name:row.workspace_name,avatar:row.avatar});
export async function current():Promise<User|null>{try{const session=JSON.parse(sessionStorage.getItem(SESSION)||'null');if(!session)return null;const row=(await read(AUTH)).meta.find(x=>x.id===session.id);if(!row||row.session_version!==session.version)return null;const key=session.token+row.salt;let promise=sessionHashes.get(key);if(!promise){promise=hash(session.token,row.salt);sessionHashes.set(key,promise);}if(!(row.session_hashes??[row.session_hash]).includes(await promise))return null;return profile(row);}catch{return null;}}
export async function accountsRoute(path:string,data:any):Promise<unknown>{
 if(path==='/status')return {initialized:(await read(AUTH)).meta.length>0};
 if(path==='/logout'){sessionStorage.removeItem(SESSION);window.dispatchEvent(new Event('atlas-session-expired'));return {logged_out:true};}
 if(path==='/register'||path==='/login'){
  const username=text(data.username,32).normalize('NFKC').toLowerCase();if(!/^[\p{L}\p{N}_.-]{2,32}$/u.test(username))throw Error('账号需为 2–32 个字母、数字、中文或 . _ -');
  const secret=password(data.password);const existing=(await read(AUTH)).meta.find(x=>x.username===username);
  if(path==='/register'&&existing)throw Error('账号已存在');
  if(path==='/login'&&(!existing||existing.password_hash!==await hash(secret,existing.salt)))throw Error('账号或密码错误');
  const salt=existing?.salt??random(),password_hash=existing?.password_hash??await hash(secret,salt),token=random(),session_hash=await hash(token,salt);
  const row=await write(AUTH,(s,put)=>{if(path==='/register'&&s.meta.some(x=>x.username===username))throw Error('账号已存在');const row:Row=existing?{...s.meta.find(x=>x.id===existing.id)!}:{id:nextId(s.meta),username,workspace_name:'我的资源空间',avatar:'',salt,password_hash,session_version:0};row.session_hashes=[...(row.session_hashes??[row.session_hash]).filter(Boolean),session_hash].slice(-20);put('meta',row);return row;});
  await initialize(workspace(row.id));sessionStorage.setItem(SESSION,JSON.stringify({id:row.id,token,version:row.session_version}));void navigator.storage?.persist?.().catch(()=>{});return profile(row);
 }
 const user=await current();if(!user)throw Object.assign(Error('请先登录浏览器本地账号'),{status:401});
 if(path==='/me')return user;
 if(path==='/profile'){
  const name=text(data.workspace_name,40);let avatar=data.avatar;
  if(typeof avatar!=='string')throw Error('头像格式无效');
  if(avatar){if(avatar.length>2800000||!/^data:image\/(png|jpeg|webp);base64,/.test(avatar))throw Error('头像仅支持最大 2 MiB 的 PNG / JPEG / WebP');const img=new Image();img.src=avatar;await img.decode();if(img.width*img.height>4000000)throw Error('头像像素过大');const canvas=document.createElement('canvas'),scale=Math.min(1,256/Math.max(img.width,img.height));canvas.width=Math.max(1,Math.round(img.width*scale));canvas.height=Math.max(1,Math.round(img.height*scale));canvas.getContext('2d')!.drawImage(img,0,0,canvas.width,canvas.height);avatar=canvas.toDataURL('image/png');}
  return write(AUTH,(s,put)=>{const row={...s.meta.find(x=>x.id===user.id)!,workspace_name:name,avatar};put('meta',row);return profile(row);});
 }
 if(path==='/password'){
  const row=(await read(AUTH)).meta.find(x=>x.id===user.id)!;if(typeof data.old_password!=='string'||data.old_password.length>128||await hash(data.old_password,row.salt)!==row.password_hash)throw Error('原密码错误');
  const salt=random(),password_hash=await hash(password(data.new_password),salt),token=random(),session_hash=await hash(token,salt);
  const version=await write(AUTH,(s,put)=>{const fresh=s.meta.find(x=>x.id===user.id)!;if(fresh.password_hash!==row.password_hash)throw Error('密码已在其他标签页修改，请重新登录');const session_version=fresh.session_version+1;put('meta',{...fresh,salt,password_hash,session_hashes:[session_hash],session_version});return session_version;});sessionStorage.setItem(SESSION,JSON.stringify({id:user.id,token,version}));return {changed:true};
 }
 throw Error('不支持的账号操作');
}
