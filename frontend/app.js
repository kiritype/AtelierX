import {ApiClient} from './api.js';
import {autoConnection, connectionMessage} from './connection.js';
const pages={fragments:['조각 관리','전역 Prompt 조각을 카테고리별로 정리합니다.'],production:['캐릭터 관리','작품, 캐릭터, 의상을 준비합니다.'],creation:['이미지 생성','선택한 캐릭터와 조각으로 이미지 생성을 준비합니다.'],jobs:['작업 현황','생성부터 검증까지 작업 진행을 확인합니다.'],review:['검토','단일 검사와 그룹 일관성 검토를 진행합니다.'],gallery:['갤러리','단일 검사 통과 결과를 탐색하고 내려받습니다.'],settings:['설정','작업 방식과 연결을 조정합니다.']};
const states=Object.fromEntries(Object.keys(pages).map(k=>[k,{}]));
let api=null,serial=0,current='production';
let activeRoute=null,activeLifecycle=null;
const lifecycles=new Set();
const main=document.querySelector('#workspace');
const routeKey=(page,id)=>`${page}\u0000${id||''}`;
function endLifecycle(lifecycle){
 if(!lifecycle)return;
 lifecycle.controller.abort();
 if(lifecycle.cleanup){lifecycle.cleanup();lifecycle.cleanup=null;}
}
function notify(message,error=false){const n=document.querySelector('#notice');n.hidden=false;n.textContent=String(message);n.className=error?'error notice':'notice';}
const healthStatus=health=>{const details=[health?.version,health?.build].filter(value=>typeof value==='string'&&value);return `Core 연결됨${details.length?` · ${details.join(' / ')}`:''}`;};
async function navigate(page,id,fromHistory=false,force=false){
 if(!pages[page])page='production';
 if(!force&&page===current&&routeKey(page,id)===activeRoute)return;
 if(page!==current && states[current]?.dirty && !window.confirm('미저장 내용이 있습니다. 다른 화면으로 이동할까요? 입력은 현재 탭에서 유지됩니다.')){history.replaceState(null,'',`#${current}`);return;}
  states[current].scrollY=window.scrollY;
 if(id){states[page].selectedId=id;states[page].id=id;}
 document.querySelector('#notice').hidden=true;current=page;if(!fromHistory)history.pushState(null,'',`#${page}${id?'/'+encodeURIComponent(id):''}`);window.scrollTo({top:0,behavior:'instant'});
 const ticket=++serial;
 for(const lifecycle of lifecycles)endLifecycle(lifecycle);
 lifecycles.clear();activeLifecycle=null;activeRoute=null;
 document.querySelector('#page-title').textContent=pages[page][0];document.querySelector('#page-description').textContent=pages[page][1];
 document.querySelectorAll('[data-page]').forEach(b=>{b.classList.toggle('active',b.dataset.page===page);b.setAttribute('aria-current',b.dataset.page===page?'page':'false');});
 if(!api)return;
 const host=document.createElement('div');host.className='page-content';host.textContent='불러오는 중…';
 const lifecycle={controller:new AbortController(),cleanup:null,detailRoute:null};
 lifecycles.add(lifecycle);main.replaceChildren(host);
 let module;
 try {module=await import(`./${page}.js`);}
 catch(e){if(ticket===serial){const retry=document.createElement('button');retry.type='button';retry.className='button';retry.textContent='화면 새로고침';retry.onclick=()=>window.location.reload();host.replaceChildren(document.createElement('h2'),document.createElement('p'),retry);host.children[0].textContent='화면 파일을 불러오지 못했습니다.';host.children[1].textContent='Cloudflare Access 로그인과 연결 상태를 확인한 뒤, 준비되면 화면을 새로고침하세요.';notify('화면 파일을 불러오지 못했습니다. 로그인 또는 연결을 확인한 뒤 새로고침하세요.',true);}lifecycles.delete(lifecycle);return;}
 try {if(ticket!==serial)return;host.textContent='';const dispose=await module.mount(host,{api,state:states[page],navigate,notify,isActive:()=>ticket===serial&&!lifecycle.controller.signal.aborted,signal:lifecycle.controller.signal,onDetailChange:(id)=>{if(ticket!==serial||lifecycle.controller.signal.aborted)return;lifecycle.detailRoute=routeKey(current,id);activeRoute=lifecycle.detailRoute;history.pushState(null,'',`#${current}${id?'/'+encodeURIComponent(id):''}`);},onConnectionSaved:async()=>{try{const health=await api.get('/health');document.querySelector('#connection-status').textContent=healthStatus(health);notify('저장한 Core 연결을 확인했습니다.');const initial=route();await navigate(current,initial.id,true,true);}catch(error){notify(`${error.code||'CONNECTION_ERROR'}: ${error.message}`,true);}},onManualConnection:async(token)=>{const next=new ApiClient({token});const health=await next.get('/health');api=next;document.querySelector('#connection-status').textContent=healthStatus(health);notify('브라우저 메모리에서 Core 연결을 확인했습니다.');const initial=route();await navigate(current,initial.id,true,true);}});lifecycle.cleanup=typeof dispose==='function'?dispose:null;if(ticket!==serial){endLifecycle(lifecycle);return;}activeLifecycle=lifecycle;activeRoute=lifecycle.detailRoute||routeKey(page,id);window.scrollTo({top:states[page].scrollY||0,behavior:'instant'});}
 catch(e){if(ticket===serial){host.textContent='화면을 불러오지 못했습니다.';notify(`${e.code||'UI_ERROR'}: ${e.message}`,true);}}
 finally {if(activeLifecycle!==lifecycle)lifecycles.delete(lifecycle);}
}
document.querySelectorAll('[data-page]').forEach(b=>b.addEventListener('click',()=>navigate(b.dataset.page)));
document.querySelector('.skip-link').addEventListener('click',e=>{e.preventDefault();main.setAttribute('tabindex','-1');main.focus();});
document.querySelector('.brand').addEventListener('click',e=>{e.preventDefault();navigate('production');});
document.querySelector('#connection-toggle').onclick=()=>{states.settings.settings??={section:'connection',drafts:{}};states.settings.settings.section='connection';navigate('settings',undefined,false,true);};
function route(){const [page,encoded]=location.hash.slice(1).split('/');let id;try{id=encoded?decodeURIComponent(encoded):undefined;}catch{}return {page:pages[page]?page:'production',id};}
window.addEventListener('popstate',()=>{const next=route();if(current==='fragments'&&states.fragments.dirty&&next.page==='fragments'){history.replaceState(null,'',`#fragments${states.fragments.selectedId?'/'+encodeURIComponent(states.fragments.selectedId):''}`);notify('저장하거나 편집을 취소한 뒤 이동하세요.',true);return;}if(next.page==='gallery'&&!next.id){states.gallery.selected=null;states.gallery.mobileDetail=false;}if(next.page==='fragments'&&!next.id){states.fragments.selectedId=null;states.fragments.mobilePanel='list';if(!states.fragments.dirty){states.fragments.selected=null;states.fragments.editor=null;}}navigate(next.page,next.id,true);});
window.addEventListener('beforeunload',e=>{if(Object.values(states).some(s=>s.dirty)){e.preventDefault();e.returnValue='';}});
async function start(){const initial=route();current=initial.page;if(initial.id)states[current].selectedId=initial.id;const result=await autoConnection(ApiClient);api=result.api;if(result.kind==='connected'){document.querySelector('#connection-status').textContent='Core 연결됨';await navigate(current,initial.id,true);return;}states.settings.settings={section:'connection',drafts:{}};document.querySelector('#connection-status').textContent=result.kind==='auth_required'?'인증 필요':result.kind==='unreachable'?'연결 대기':'Core 연결 설정 필요';notify(result.kind==='connection_settings'?'Access 연결은 확인됐지만 Core 연결 설정을 확인해야 합니다.':connectionMessage(result,window.location.origin),true);await navigate('settings');}
start();
