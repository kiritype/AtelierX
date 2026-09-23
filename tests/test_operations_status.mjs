import assert from "node:assert/strict";
import test from "node:test";
import {readFile} from "node:fs/promises";
const source=await readFile(new URL("../frontend/settings.js",import.meta.url),"utf8");
const ui=await import(`data:text/javascript,${encodeURIComponent(source)}`);

test("unavailable reasons map to Korean guidance",()=>{
 for(const reason of ["not_configured","token_missing","unreachable","unauthorized","invalid_response"]){
  const view=ui.operationsView({control_panel:"unavailable",reason,items:[],dependencies:[]});
  assert.equal(view.available,false);assert.equal(view.message,ui.operationsUnavailableText[reason]);
 }
 assert.equal(ui.operationsView({control_panel:"unavailable",reason:"unreachable"}).message,"제어판이 실행 중이 아닙니다. 이 PC에서 제어판을 실행하세요.");
 assert.match(ui.operationsView(null).message,/확인할 수 없습니다/);
});

test("available status renders labels, badges and details",()=>{
 const view=ui.operationsView({control_panel:"available",generated_at:"2026-09-23T10:00:00+09:00",items:[
  {id:"services",label:"서비스 묶음",state:"running",managed:true,pid:123,started_at:null,ports:[8190],autostart:true,last_error:null,options:{generation:true,validation:false,discord_bridge:true}},
  {id:"comfyui",label:"ComfyUI",state:"external",managed:false,pid:null,started_at:null,ports:[8188],autostart:false,last_error:null},
  {id:"tunnel",label:"Tunnel",state:"error",managed:true,pid:null,started_at:null,ports:[],autostart:false,last_error:"실패"}],
  dependencies:[{id:"cloudflared",label:"cloudflared",status:"missing",detail:"실행 파일 없음"},{id:"lms",label:"LM Studio",status:"unknown",detail:null}]});
 assert.equal(view.available,true);
 assert.deepEqual(view.items.map(i=>i.state),["실행 중","외부 실행","오류"]);
 assert.deepEqual(view.items[0].details,["PID 123","포트 8190","제어판 관리","시작 시 자동 켜기","시작 옵션: Generation, Discord Bridge"]);
 assert.deepEqual(view.items[1].details,["포트 8188"]);
 assert.equal(view.items[2].error,"실패");
 assert.deepEqual(view.dependencies,[{label:"cloudflared",status:"없음",detail:"실행 파일 없음"},{label:"LM Studio",status:"확인 불가",detail:""}]);
 assert.deepEqual(Object.values(ui.operationStateLabels),["실행 중","외부 실행","중지","시작 중","종료 중","오류"]);
 assert.equal(ui.operationsView({control_panel:"available",items:[{id:"services",state:"stopped",options:{}}],dependencies:[]}).items[0].details.at(-1),"시작 옵션: Core만");
});
