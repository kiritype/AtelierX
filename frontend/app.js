import {ApiClient} from './api.js';
import {autoConnection, connectionMessage} from './connection.js';
const pages={production:['제작','캐릭터의 다음 장면을 만드세요.'],gallery:['갤러리','완성된 이미지와 캐릭터의 일관성을 살펴보세요.'],jobs:['작업 현황','생성부터 검증까지, 진행 중인 작업을 확인하세요.'],settings:['설정','작업 방식에 맞게 스튜디오를 조정하세요.']};
const states=Object.fromEntries(Object.keys(pages).map(k=>[k,{}]));
let api=null,cleanup=null,serial=0,current='production';
const main=document.querySelector('#workspace');
function notify(message,error=false){const n=document.querySelector('#notice');n.hidden=false;n.textContent=String(message);n.className=error?'error notice':'notice';}
async function navigate(page,id){
 if(!pages[page])page='production';
 if(id){states[page].selectedId=id;states[page].id=id;}
 document.querySelector('#notice').hidden=true;current=page;location.hash=page;window.scrollTo({top:0,behavior:'instant'});
 const ticket=++serial; if(cleanup){cleanup();cleanup=null;}
 document.querySelector('#page-title').textContent=pages[page][0];document.querySelector('#page-description').textContent=pages[page][1];
 document.querySelectorAll('[data-page]').forEach(b=>{b.classList.toggle('active',b.dataset.page===page);b.setAttribute('aria-current',b.dataset.page===page?'page':'false');});
 if(!api)return;
 const host=document.createElement('div');host.className='page-content';host.textContent='불러오는 중…';main.replaceChildren(host);
 try {const module=await import(`./${page}.js`);if(ticket!==serial)return;host.textContent='';const dispose=await module.mount(host,{api,state:states[page],navigate,notify,onConnectionSaved:async()=>{try{await api.get('/health');document.querySelector('#connection-status').textContent='Core 연결됨';notify('저장한 Core 연결을 확인했습니다.');await navigate(current);}catch(error){notify(`${error.code||'CONNECTION_ERROR'}: ${error.message}`,true);}}});if(ticket!==serial){if(typeof dispose==='function')dispose();return;}cleanup=typeof dispose==='function'?dispose:null;}
 catch(e){if(ticket===serial){host.textContent='화면을 불러오지 못했습니다.';notify(`${e.code||'UI_ERROR'}: ${e.message}`,true);}}
}
document.querySelectorAll('[data-page]').forEach(b=>b.addEventListener('click',()=>navigate(b.dataset.page)));
document.querySelector('.brand').addEventListener('click',e=>{e.preventDefault();navigate('production');});
document.querySelector('#connection-toggle').onclick=()=>{const panel=document.querySelector('#connection-panel');panel.hidden=!panel.hidden;};
document.querySelector('#connection-form').addEventListener('submit',async e=>{e.preventDefault();const button=e.submitter;button.disabled=true;try{const next=new ApiClient({token:document.querySelector('#core-token').value});await next.get('/health');api=next;document.querySelector('#core-token').value='';document.querySelector('#connection-panel').hidden=true;document.querySelector('#connection-status').textContent='Core 연결됨';notify('스튜디오에 연결했습니다.');await navigate(current);}catch(error){notify(`${error.code||'CONNECTION_ERROR'}: ${error.message}`,true);}finally{button.disabled=false;}});
window.addEventListener('hashchange',()=>{const next=location.hash.slice(1);if(next!==current)navigate(next);});
window.addEventListener('beforeunload',e=>{if(Object.values(states).some(s=>s.dirty)){e.preventDefault();e.returnValue='';}});
async function start(){current=location.hash.slice(1)||'production';const result=await autoConnection(ApiClient);if(result.kind==='connected'){api=result.api;document.querySelector('#connection-panel').hidden=true;document.querySelector('#connection-status').textContent='Core 연결됨';await navigate(current);return;}if(result.kind==='connection_settings'){api=result.api;states.settings.settings={section:'connection',drafts:{}};document.querySelector('#connection-panel').hidden=true;document.querySelector('#connection-status').textContent='Core 연결 설정 필요';notify('Access 연결은 확인됐지만 Core 연결 설정을 확인해야 합니다.',true);await navigate('settings');return;}document.querySelector('#connection-status').textContent=result.kind==='auth_required'?'인증 필요':'연결 대기';notify(connectionMessage(result,window.location.origin),true);}
start();
