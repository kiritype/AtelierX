import assert from "node:assert/strict";
import {readFile} from "node:fs/promises";
const source=await readFile(new URL("../frontend/settings.js",import.meta.url),"utf8");
const ui=await import(`data:text/javascript,${encodeURIComponent(source)}`);
assert.equal(ui.numberValue("",undefined),undefined);
assert.deepEqual(ui.generationSettings({diffusion_model:"m",text_encoder:"t",vae:"v",width:"1024",height:"768",seed:"1",steps:"24",cfg:"4.5",sampler:"euler",scheduler:"normal",loras:[{name:"detail/lora.safetensors",strength:".8"}]}),{diffusion_model:"m",text_encoder:"t",vae:"v",width:1024,height:768,seed:1,steps:24,cfg:4.5,sampler:"euler",scheduler:"normal",loras:[{name:"detail/lora.safetensors",strength:.8}]});
assert.throws(()=>ui.generationSettings({diffusion_model:"m",text_encoder:"t",vae:"v",width:"1024",height:"768",seed:"9007199254740992",steps:"24",cfg:"4.5",sampler:"euler",scheduler:"normal",loras:[]}),/safe integer/);
assert.deepEqual(ui.postprocessSettings({upscale_enabled:true,upscale_model:"4x-UltraSharp.safetensors",upscale_scale:"1.5",encode_enabled:true,webp_enabled:true,webp_quality:"90"}),{upscale:{upscale_model:"4x-UltraSharp.safetensors",scale:1.5},encode:{webp_enabled:true,webp_quality:90}});
assert.deepEqual(ui.postprocessSettings({base:{detailer:{face_enabled:true},censor:{segmentation_model:"seg.pt",labels:"skin"},alpha:{segmentation_model:"seg.pt"},upscale:{upscale_model:"old",scale:2}},upscale_enabled:true,upscale_model:"new",upscale_scale:"1.5",encode_enabled:false}),{detailer:{face_enabled:true},censor:{segmentation_model:"seg.pt",labels:"skin"},alpha:{segmentation_model:"seg.pt"},upscale:{upscale_model:"new",scale:1.5}});
