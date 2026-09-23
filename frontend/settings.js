const el=(tag,text="",className="")=>{const n=document.createElement(tag);n.textContent=text;if(className)n.className=className;return n;};
const button=(text,fn)=>{const n=el("button",text,"button");n.type="button";n.onclick=fn;return n;};
const errorText=(e)=>e?.code?`${e.code}: ${e.message||"Request failed"}`:e?.message||String(e);
export const numberValue=(v,fallback=undefined)=>v===""?fallback:Number(v);
const finite=(value,label)=>{ if(!Number.isFinite(value)) throw new Error(`${label} must be a finite number`); return value; };
const safeInteger=(value,label)=>{ value=finite(value,label); if(!Number.isSafeInteger(value)) throw new Error(`${label} must be a safe integer`); return value; };
export const generationSettings=d=>({diffusion_model:d.diffusion_model,text_encoder:d.text_encoder,vae:d.vae,width:safeInteger(numberValue(d.width),"Width"),height:safeInteger(numberValue(d.height),"Height"),seed:safeInteger(numberValue(d.seed),"Seed"),steps:safeInteger(numberValue(d.steps),"Steps"),cfg:finite(numberValue(d.cfg),"CFG"),sampler:d.sampler,scheduler:d.scheduler,loras:(d.loras||[]).map(x=>({name:x.name.trim(),strength:finite(numberValue(x.strength),"LoRA strength")}))});
export const postprocessSettings=d=>{const r=JSON.parse(JSON.stringify(d.base||{}));if(d.upscale_enabled)r.upscale={upscale_model:d.upscale_model,scale:finite(numberValue(d.upscale_scale),"Upscale scale")};else delete r.upscale;if(d.encode_enabled)r.encode={webp_enabled:!!d.webp_enabled,webp_quality:safeInteger(numberValue(d.webp_quality),"WebP quality")};else delete r.encode;return r;};
export const connectionProblem=error=>{
 if(error?.status===401||error?.status===403)return {title:"Core 인증이 필요합니다.",detail:"Cloudflare Access 로그인을 확인하거나 아래에 Bearer 토큰을 입력하세요."};
 if(error?.status===404)return {title:"이 Core는 저장 연결 설정을 지원하지 않습니다.",detail:"Bearer 토큰으로 현재 브라우저에서만 연결할 수 있습니다."};
 return {title:"Core에 연결할 수 없습니다.",detail:"Core 서비스와 네트워크를 확인한 뒤 다시 시도하세요."};
};
export const connectionDisplay=value=>({
 auth:value?.auth_mode==="cloudflare_access"?"Cloudflare Access":"Bearer",
 browserMemory:value?.auth_mode==="bearer"&&!value?.configured,
 canSave:!!value?.configured
});
export const operationStateLabels={running:"실행 중",external:"외부 실행",stopped:"중지",starting:"시작 중",stopping:"종료 중",error:"오류"};
export const dependencyStatusLabels={ok:"정상",warning:"주의",missing:"없음",unknown:"확인 불가"};
export const operationsUnavailableText={not_configured:"이 Core에는 운영 제어판 연결이 설정되어 있지 않습니다. 제어판 또는 실행기에서 Core를 시작하면 연결됩니다.",token_missing:"제어판 상태 토큰이 아직 없습니다. 이 PC에서 제어판을 한 번 실행하세요.",unreachable:"제어판이 실행 중이 아닙니다. 이 PC에서 제어판을 실행하세요.",unauthorized:"제어판이 상태 조회 토큰을 거부했습니다. 제어판과 Core를 다시 시작하세요.",invalid_response:"제어판 응답을 해석할 수 없습니다. 제어판과 Core 버전을 확인하세요."};
const optionLabels={generation:"Generation",validation:"Validation",discord_bridge:"Discord Bridge"};
const timeText=value=>{const d=new Date(value);return Number.isNaN(d.getTime())?String(value):d.toLocaleString("ko-KR");};
export const operationsView=value=>{
 if(value?.control_panel!=="available")return {available:false,message:operationsUnavailableText[value?.reason]||"운영 제어판 상태를 확인할 수 없습니다.",items:[],dependencies:[]};
 const items=(value.items||[]).map(item=>{const details=[];if(item.pid!=null)details.push(`PID ${item.pid}`);if(item.started_at)details.push(`시작 ${timeText(item.started_at)}`);if(item.ports?.length)details.push(`포트 ${item.ports.join(", ")}`);if(item.state!=="external")details.push(item.managed?"제어판 관리":"제어판 관리 아님");if(item.autostart)details.push("시작 시 자동 켜기");if(item.options){const on=Object.entries(optionLabels).filter(([k])=>item.options[k]).map(([,t])=>t);details.push(`시작 옵션: ${on.length?on.join(", "):"Core만"}`);}return {label:item.label||item.id,state:operationStateLabels[item.state]||item.state,details,error:item.last_error||null};});
 const dependencies=(value.dependencies||[]).map(d=>({label:d.label||d.id,status:dependencyStatusLabels[d.status]||d.status,detail:d.detail||""}));
 return {available:true,generatedAt:value.generated_at?timeText(value.generated_at):null,items,dependencies};
};
const genDraft=s=>({diffusion_model:s.diffusion_model||"",text_encoder:s.text_encoder||"",vae:s.vae||"",width:String(s.width??1024),height:String(s.height??1024),seed:String(s.seed??0),steps:String(s.steps??24),cfg:String(s.cfg??4.5),sampler:s.sampler||"euler",scheduler:s.scheduler||"normal",loras:(s.loras||[]).map(x=>({name:x.name||"",strength:String(x.strength??1)}))});
const postDraft=s=>({base:JSON.parse(JSON.stringify(s)),upscale_enabled:!!s.upscale,upscale_model:s.upscale?.upscale_model||"4x-UltraSharp.safetensors",upscale_scale:String(s.upscale?.scale??1.5),encode_enabled:!!s.encode,webp_enabled:!!s.encode?.webp_enabled,webp_quality:String(s.encode?.webp_quality??90)});
const validationDraft=(kind,s={})=>kind==="providers"?{provider_id:s.provider_id||"",model:s.model||"",url:s.url||"",timeout_seconds:String(s.timeout_seconds??30),max_tokens:s.max_tokens==null?"":String(s.max_tokens),response_format:s.response_format||"json_object",image_format:s.image_format||"original",shared_gpu:!!s.shared_gpu,api_key_env:s.api_key_env}:{profile_id:s.profile_id||"",output_conditions:!!s.output_conditions,positive_prompt:!!s.positive_prompt,negative_prompt:!!s.negative_prompt,consistency:kind==="group-profiles"};
const validationSetting=(kind,d,id)=>kind==="providers"?(()=>{const r={provider_id:(id??d.provider_id).trim(),revision:1,model:d.model.trim(),url:d.url.trim(),timeout_seconds:safeInteger(numberValue(d.timeout_seconds),"Timeout"),response_format:d.response_format,image_format:d.image_format,shared_gpu:!!d.shared_gpu};if(d.max_tokens!=="")r.max_tokens=safeInteger(numberValue(d.max_tokens),"Max tokens");if(d.api_key_env)r.api_key_env=d.api_key_env;return r;})():kind==="group-profiles"?{profile_id:(id??d.profile_id).trim(),revision:1,consistency:true}:{profile_id:(id??d.profile_id).trim(),revision:1,output_conditions:!!d.output_conditions,positive_prompt:!!d.positive_prompt,negative_prompt:!!d.negative_prompt,body_parts:[],metadata:false,consistency:false};

export async function mount(container,ctx){
 const state=ctx.state.settings??={section:"global",drafts:{}};let ticket=0,disposed=false;
 const root=el("section","","panel"),nav=el("nav","","settings-nav"),content=el("section","","panel"),layout=el("div","","settings-layout");layout.append(nav,content);root.append(layout);container.replaceChildren(root);
 const sections=[["connection","Core 연결"],["global","전역 Prompt"],["regeneration","자동 재생성"],["generation","생성 Preset"],["postprocess","후처리 Preset"],["single-profiles","단일 검사 Profile"],["group-profiles","묶음 검사 Profile"],["providers","검사 Provider"],["nodes","실행 환경 상태"]],navs=new Map();
 const dirty=d=>{d.dirty=true;ctx.state.dirty=true;}, clean=()=>ctx.state.dirty=Object.values(state.drafts).some(d=>d.dirty);
 const draft=(key,server,make)=>state.drafts[key]??={key,value:make(server),baseRevision:server.revision,dirty:false,conflict:false};
 const field=(label,control,hint="")=>{const w=el("label","","field");w.append(el("span",label),control);if(hint)w.append(el("small",hint));return w;};
 const input=(d,key,options={})=>{const n=document.createElement("input");Object.assign(n,options);if(n.type==="checkbox")n.checked=!!d.value[key];else n.value=d.value[key]??"";n.addEventListener(n.type==="checkbox"?"change":"input",()=>{d.value[key]=n.type==="checkbox"?n.checked:n.value;dirty(d);});return n;};
 const choices=(d,key,items)=>{const n=document.createElement("select");items.forEach(([v,t])=>n.append(new Option(t,v,undefined,d.value[key]===v)));n.onchange=()=>{d.value[key]=n.value;dirty(d);};return n;};
 const conflict=(d,reload)=>{if(!d.conflict)return null;const box=el("div","","error");box.append(el("p","다른 곳에서 설정이 변경되었습니다. 초안은 보존했고 자동 덮어쓰기를 하지 않았습니다."),button("최신값 불러오기 (초안 교체)",reload));return box;};
 const reload=async(d,path,make)=>{try{const server=await ctx.api.get(path);state.drafts[d.key]={key:d.key,value:make(server),baseRevision:server.revision,dirty:false,conflict:false};clean();render();}catch(e){ctx.notify(errorText(e),true);}};
 const save=async(d,request)=>{try{await request();delete state.drafts[d.key];clean();ctx.notify("저장했습니다.");render();}catch(e){if(e?.status===409||e?.code==="CORE_REVISION_CONFLICT"){d.conflict=true;ctx.notify("revision 충돌입니다. 초안을 유지합니다.",true);render();}else ctx.notify(errorText(e),true);}};
 sections.forEach(([id,title])=>{const b=button(title,()=>{state.section=id;render();});navs.set(id,b);nav.append(b);});
 async function render(){const current=++ticket,section=state.section;navs.forEach((b,id)=>{const active=id===section;b.classList.toggle("active",active);b.toggleAttribute("aria-current",active);});content.replaceChildren(el("p","설정을 불러오는 중…","muted"));try{if(section==="connection"){await connection(current);return;}if(section==="nodes"){await nodes(current);return;}const path=["global","regeneration"].includes(section)?"/v1/settings":["generation","postprocess"].includes(section)?`/v1/presets/${section}?limit=50&offset=0`:`/v1/validation-settings/${section}?include_archived=true`;const result=await ctx.api.get(path);if(disposed||current!==ticket)return;if(section==="generation"){let resources=null,resourcesError=null;try{resources=await ctx.api.get("/v1/generation/resources");}catch(error){resourcesError=errorText(error);}if(disposed||current!==ticket||state.section!==section)return;state.generationResources=resources;state.generationResourcesError=resourcesError;}if(["global","regeneration"].includes(section))globals(result);else if(["generation","postprocess"].includes(section))presets(section,result);else validations(section,result);}catch(e){if(current===ticket&&!disposed&&state.section===section)content.replaceChildren(el("p",errorText(e),"error"));}}
 async function connection(current){
  const manualForm=(problem)=>{
   const form=el("div","","grid"),token=document.createElement("input");
   token.type="password";token.autocomplete="off";token.required=true;token.placeholder="Core Bearer 토큰";token.setAttribute("aria-label","Core Bearer 토큰");
   const connect=button("브라우저에서 연결",async()=>{if(!token.value)return;connect.disabled=true;try{await ctx.onManualConnection?.(token.value);token.value="";}catch(error){ctx.notify(errorText(error),true);}finally{connect.disabled=false;}});
   form.append(el("h2",problem.title),el("p",problem.detail,"muted"),field("Bearer 토큰",token,"입력값은 브라우저 메모리에만 유지하며 저장하거나 표시하지 않습니다."),connect,el("p","Pilot에서는 Core 호스트의 .atelierx/pilot/token.txt에서 토큰을 확인하세요. 일반 실행에서는 Core 설정 또는 환경 변수의 토큰을 사용하세요.","muted"));
   content.replaceChildren(form);
  };
  try{
   const value=await ctx.api.get("/v1/frontend-connection");
   if(disposed||current!==ticket)return;
   const display=connectionDisplay(value);
   const form=el("div","","grid");
   form.append(el("h2","Core 연결"),el("p",`인증 방식: ${display.auth}`));
   if(display.browserMemory){
    form.append(el("p","브라우저 연결: 확인됨 · 메모리 연결","muted"),el("p","이 Core에는 서버 저장 연결 설정이 없습니다. 현재 탭을 닫거나 새로고침하면 다시 연결해야 합니다.","muted"));
    const token=document.createElement("input");token.type="password";token.autocomplete="off";token.placeholder="새 Bearer 토큰";token.setAttribute("aria-label","교체할 Core Bearer 토큰");
    const replaceToken=button("브라우저 연결 교체",async()=>{if(!token.value)return;replaceToken.disabled=true;try{await ctx.onManualConnection?.(token.value);token.value="";}catch(e){ctx.notify(errorText(e),true);}finally{replaceToken.disabled=false;}});
    const replace=el("details");replace.append(el("summary","Bearer 토큰 교체"),field("Bearer 토큰",token,"입력값은 브라우저 메모리에만 유지합니다."),replaceToken);form.append(replace);
    content.replaceChildren(form);return;
   }
   form.append(el("p",`서버 토큰: ${value.token_configured?"저장됨":"저장되지 않음"}`),el("p",`서버 연결 상태: ${value.connected?"확인됨":"확인 필요"}`));
   if(value.public_origin)form.append(el("p",`공개 주소: ${value.public_origin}`,"muted"));
   const token=document.createElement("input");token.type="password";token.autocomplete="off";token.required=true;token.placeholder="현재 Core 토큰";token.setAttribute("aria-label","저장할 Core 토큰");
   const saveToken=button("Core 연결 저장",async()=>{if(!token.value)return;saveToken.disabled=true;try{await ctx.api.put("/v1/frontend-connection",{token:token.value});token.value="";ctx.notify("Core 연결 토큰을 서버에 저장했습니다.");await ctx.onConnectionSaved?.();if(!disposed)await render();}catch(e){ctx.notify(errorText(e),true);}finally{saveToken.disabled=false;}});
   if(value.auth_mode==="cloudflare_access"&&value.connected){
    form.append(el("p","Cloudflare Access 연결이 확인되어 토큰 입력이 필요하지 않습니다.","muted"));
    const replace=el("details");replace.append(el("summary","저장 토큰 교체"),field("Core 토큰",token,"서버의 비공개 연결 토큰을 교체합니다. 브라우저 입력값은 즉시 지웁니다."),saveToken);form.append(replace);
   }else form.append(field("Core 토큰",token,"서버의 비공개 연결 토큰을 저장하고 브라우저 입력값은 즉시 지웁니다."),saveToken);
   content.replaceChildren(form);
  }catch(e){if(disposed||current!==ticket)return;manualForm(connectionProblem(e));}
 }
 function globals(server){const section=state.section,key=`settings:${section}`,make=s=>section==="global"?{positive_quality:s.positive_quality||"",negative:s.negative||""}:{auto_regeneration_enabled:!!s.auto_regeneration_enabled,max_auto_regenerations:String(s.max_auto_regenerations??5)},d=draft(key,server,make),form=el("div","","grid");content.replaceChildren(el("h2",section==="global"?"전역 Prompt":"자동 재생성"));if(section==="global")form.append(field("품질 Positive",input(d,"positive_quality",{placeholder:"전역 품질 조건"})),field("품질 Negative",input(d,"negative",{placeholder:"생성에서 제외할 품질 조건"}),"생성 전용입니다. 캐릭터별 금지 요소는 제작 화면에서 편집합니다."));else form.append(field("자동 재생성 사용",input(d,"auto_regeneration_enabled",{type:"checkbox"})),field("최대 자동 횟수",input(d,"max_auto_regenerations",{type:"number",min:0,step:1}),"새 최초·수동 요청부터 적용됩니다."));form.append(el("p",`기준 revision: ${d.baseRevision}`,"muted"),button("저장",()=>save(d,()=>ctx.api.patch("/v1/settings",section==="global"?{revision:d.baseRevision,positive_quality:d.value.positive_quality,negative:d.value.negative}:{revision:d.baseRevision,auto_regeneration_enabled:d.value.auto_regeneration_enabled,max_auto_regenerations:numberValue(d.value.max_auto_regenerations)}))));const c=conflict(d,()=>reload(d,"/v1/settings",make));if(c)form.append(c);content.append(form);}
 function resourceChoice(d,key,values,requireList=false,unavailable=false){const current=String(d.value[key]??"");const options=Array.isArray(values)?[...new Set(values.filter(value=>typeof value==="string"&&value))]:[];if(!options.length&&!requireList)return input(d,key);if(current&&!options.includes(current))options.unshift(current);const control=document.createElement("select");control.append(new Option(options.length?"선택":"목록 확인 불가", ""));options.forEach(value=>control.append(new Option(value===current&&unavailable?`${value} · 현재값`:value,value,undefined,value===current)));control.value=current;control.onchange=()=>{d.value[key]=control.value;dirty(d);};return control;}
 function presetControls(kind,d,name,action){const f=el("div","","grid"),v=d.value;if(kind==="generation"){const resources=state.generationResources||{},unavailable=Boolean(state.generationResourcesError);f.append(field("Preset 이름",name),field("Diffusion model",resourceChoice(d,"diffusion_model",resources.diffusion_models,true,unavailable),unavailable?`목록을 불러오지 못했습니다. 저장된 현재값은 유지합니다: ${state.generationResourcesError}`:"Core 등록 목록"),field("Text encoder",resourceChoice(d,"text_encoder",resources.text_encoders,true,unavailable)),field("VAE",resourceChoice(d,"vae",resources.vaes,true,unavailable)),field("너비",input(d,"width",{type:"number",min:256,max:1920,step:16})),field("높이",input(d,"height",{type:"number",min:256,max:1920,step:16})),field("Seed",input(d,"seed",{type:"number",min:0,step:1})),field("Steps",input(d,"steps",{type:"number",min:1,max:100,step:1})),field("CFG",input(d,"cfg",{type:"number",min:0,max:20,step:.1})),field("Sampler",resourceChoice(d,"sampler",resources.samplers)),field("Scheduler",resourceChoice(d,"scheduler",resources.schedulers)));const ls=el("fieldset");ls.append(el("legend","LoRA"));v.loras.forEach((x,i)=>{const row=el("div","","row"),model=document.createElement("input"),strength=document.createElement("input");model.value=x.name;strength.type="number";strength.step=.05;strength.value=x.strength;model.oninput=()=>{x.name=model.value;dirty(d);};strength.oninput=()=>{x.strength=strength.value;dirty(d);};row.append(model,strength,button("제거",()=>{v.loras.splice(i,1);dirty(d);render();}));ls.append(row);});ls.append(button("+ LoRA",()=>{v.loras.push({name:"",strength:"1"});dirty(d);render();}));f.append(ls);}else f.append(field("Preset 이름",name),field("Upscale 사용",input(d,"upscale_enabled",{type:"checkbox"})),v.upscale_enabled?field("Upscale model",input(d,"upscale_model")):null,v.upscale_enabled?field("최종 배율",input(d,"upscale_scale",{type:"number",min:.01,step:.1}),"모델 고유 배율과 별개입니다."):null,field("WebP Encode 사용",input(d,"encode_enabled",{type:"checkbox"})),v.encode_enabled?field("WebP 출력",input(d,"webp_enabled",{type:"checkbox"})):null,v.encode_enabled?field("WebP 품질",input(d,"webp_quality",{type:"number",min:1,max:100,step:1})):null);f.append(action);return f;}
 function presets(kind,page){content.replaceChildren(el("h2",kind==="generation"?"생성 Preset":"후처리 Preset"),el("p",kind==="generation"?"Prompt·endpoint·secret·경로는 Preset에 저장하지 않습니다.":"Upscale과 Encode를 기본 폼으로 편집합니다. 나머지 stage는 고급 JSON에서 유지합니다.","muted"));const key=`preset:new:${kind}`,d=state.drafts[key]??={key,value:kind==="generation"?genDraft({}):postDraft({}),dirty:false},name=document.createElement("input");name.placeholder="새 Preset 이름";name.value=d.name||"";name.oninput=()=>{d.name=name.value;dirty(d);};const create=el("details");create.append(el("summary","새 Preset"),presetControls(kind,d,name,button("Preset 생성",async()=>{try{await ctx.api.post(`/v1/presets/${kind}`,{name:d.name||"",settings:kind==="generation"?generationSettings(d.value):postprocessSettings(d.value)});delete state.drafts[key];clean();render();}catch(e){ctx.notify(errorText(e),true);}})));content.append(create);for(const p of page.items||[]){const pkey=`preset:${kind}:${p.id}`,make=s=>kind==="generation"?genDraft(s.settings):postDraft(s.settings),row=el("section","","panel"),edit=draft(pkey,p,make),n=document.createElement("input");n.value=edit.name??p.name;n.oninput=()=>{edit.name=n.value;dirty(edit);};row.append(el("h3",`${p.name} r${p.revision}${p.archived?" (보관)":""}`),presetControls(kind,edit,n,button("수정 저장",()=>save(edit,()=>ctx.api.patch(`/v1/presets/${kind}/${p.id}`,{revision:edit.baseRevision,name:edit.name||p.name,settings:kind==="generation"?generationSettings(edit.value):postprocessSettings(edit.value)})))));const json=document.createElement("textarea");json.value=JSON.stringify(p.settings,null,2);const adv=el("details");adv.append(el("summary","고급: 전체 설정 JSON"),json,button("JSON 적용",()=>{try{edit.value=make({settings:JSON.parse(json.value)});dirty(edit);render();}catch(_){ctx.notify("JSON 형식이 올바르지 않습니다.",true);}}));row.append(adv,button(p.archived?"보관 해제":"보관",()=>save(edit,()=>ctx.api.patch(`/v1/presets/${kind}/${p.id}`,{revision:edit.baseRevision,archived:!p.archived}))));const c=conflict(edit,()=>reload(edit,`/v1/presets/${kind}/${p.id}`,make));if(c)row.append(c);content.append(row);}}
 function validationControls(kind,d,id,action){const f=el("div","","grid");if(kind==="providers")f.append(field("Provider ID",id),field("Model",input(d,"model")),field("URL",input(d,"url",{type:"url"}),"http(s) endpoint만 저장합니다."),field("Timeout (seconds)",input(d,"timeout_seconds",{type:"number",min:1,step:1})),field("최대 응답 토큰",input(d,"max_tokens",{type:"number",min:1,step:1}),"비우면 Provider 기본값을 사용합니다."),field("Response format",choices(d,"response_format",[["json_object","JSON object"],["json_schema","JSON schema"],["text","Text"]])),field("Image format",choices(d,"image_format",[["original","Original"],["png","PNG"]])),field("공유 GPU",input(d,"shared_gpu",{type:"checkbox"})),el("p","API key와 credential 입력은 제공하지 않습니다.","muted"));else if(kind==="group-profiles")f.append(field("Profile ID",id),field("일관성 검사",input(d,"consistency",{type:"checkbox"}),"묶음 Profile은 이 검사만 지원합니다."));else f.append(field("Profile ID",id),field("출력 조건",input(d,"output_conditions",{type:"checkbox"})),field("Positive Prompt",input(d,"positive_prompt",{type:"checkbox"})),field("Negative Prompt",input(d,"negative_prompt",{type:"checkbox"})));f.append(action);return f;}
 function validations(kind,page){
  const title=kind==="providers"?"검사 Provider":kind==="single-profiles"?"단일 검사 Profile":"묶음 검사 Profile";
  content.replaceChildren(el("h2",title),el("p","저장된 설정은 revision으로 고정됩니다. API key는 입력·표시·복사하지 않습니다.","muted"));
  const key=`validation:new:${kind}`,d=state.drafts[key]??={key,value:validationDraft(kind),dirty:false},idKey=kind==="providers"?"provider_id":"profile_id",id=document.createElement("input");
  id.value=d.value[idKey];id.oninput=()=>{d.value[idKey]=id.value;dirty(d);};
  const create=el("details");
  create.append(el("summary","새 설정"),validationControls(kind,d,id,button("등록",async()=>{try{await ctx.api.post(`/v1/validation-settings/${kind}`,validationSetting(kind,d.value));delete state.drafts[key];clean();render();}catch(e){ctx.notify(errorText(e),true);}})));
  content.append(create);
  for(const s of page.items||[]){
   const ident=s.provider_id||s.profile_id,pkey=`validation:${kind}:${ident}`,make=x=>validationDraft(kind,x),edit=draft(pkey,s,make),row=el("section","","panel"),locked=document.createElement("input");
   locked.value=ident;locked.disabled=true;
   row.append(el("h3",`${ident} r${s.revision}${s.archived?" (보관)":""}`),validationControls(kind,edit,locked,button("수정 저장",()=>save(edit,()=>ctx.api.patch(`/v1/validation-settings/${kind}/${encodeURIComponent(ident)}`,{revision:edit.baseRevision,setting:validationSetting(kind,edit.value,ident)})))));
   const json=document.createElement("textarea");json.value=JSON.stringify(s,null,2);
   const advanced=el("details");
   advanced.append(el("summary","고급: 설정 JSON"),json,button("JSON 적용",()=>{try{edit.value=make(JSON.parse(json.value));dirty(edit);render();}catch(_){ctx.notify("JSON 형식이 올바르지 않습니다.",true);}}));
   const cloneId=document.createElement("input");cloneId.placeholder="복제할 새 ID";cloneId.setAttribute("aria-label",`${ident} 복제할 새 ID`);
   row.append(advanced,button("보관",()=>save(edit,()=>ctx.api.post(`/v1/validation-settings/${kind}/${encodeURIComponent(ident)}/archive`,{revision:edit.baseRevision}))),cloneId,button("복제",async()=>{if(!cloneId.value.trim())return;try{await ctx.api.post(`/v1/validation-settings/${kind}/${encodeURIComponent(ident)}/clone`,{id:cloneId.value.trim()});render();}catch(e){ctx.notify(errorText(e),true);}}));
   if(kind==="providers")row.append(button("Validation 연결 확인",async()=>{try{const r=await ctx.api.get(`/v1/validation-settings/providers/${encodeURIComponent(ident)}/connection`);ctx.notify(`Validation 연결: ${r.validation_service_reachable}`);}catch(e){ctx.notify(errorText(e),true);}}));
   const c=conflict(edit,()=>reload(edit,`/v1/validation-settings/${kind}/${encodeURIComponent(ident)}`,make));if(c)row.append(c);content.append(row);
  }
 }
 async function nodes(current){
  const block=el("section","","section"),refresh=button("새로고침",()=>render());
  const head=el("div","","row");head.append(el("h3","운영 제어판"),refresh);block.append(head);
  let value;try{value=await ctx.api.get("/v1/operations/status");}catch(e){value=null;block.append(el("p",errorText(e),"error"));}
  if(disposed||current!==ticket)return;
  if(value){
   const view=operationsView(value);
   if(!view.available)block.append(el("p",view.message,"muted"));
   else{
    if(view.generatedAt)block.append(el("p",`확인 시각: ${view.generatedAt}`,"muted"));
    const list=el("div","","grid");
    view.items.forEach(item=>{const box=el("div");const top=el("div","","row");top.append(el("strong",item.label),el("span",item.state,"badge"));box.append(top);if(item.details.length)box.append(el("small",item.details.join(" · ")));if(item.error)box.append(el("p",`최근 오류: ${item.error}`,"error"));list.append(box);});
    if(!view.items.length)list.append(el("p","표시할 항목이 없습니다.","muted"));
    block.append(list,el("h3","의존성 점검"));
    const deps=el("ul");view.dependencies.forEach(d=>{const li=el("li"),row=el("div","","row");row.append(el("span",d.label),el("span",d.status,"badge"));li.append(row);if(d.detail)li.append(el("small",d.detail));deps.append(li);});
    block.append(view.dependencies.length?deps:el("p","의존성 점검 결과가 없습니다.","muted"));
   }
  }
  block.append(el("p","이 화면은 상태만 표시합니다. 시작·종료와 로그는 이 PC의 제어판에서 확인하세요.","muted"));
  content.replaceChildren(el("h2","실행 환경 상태"),block,el("p","same-origin Core API에는 Generation 등록 Node 조회 경로가 없습니다. 이 화면은 모델 설치·다운로드·재시작을 하지 않습니다.","muted"));
 }
 await render();return()=>{disposed=true;ticket++;container.replaceChildren();};
}
