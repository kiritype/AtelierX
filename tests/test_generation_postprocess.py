import asyncio
import tempfile
import unittest

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from atelierx.generation import NODE, create_app
from atelierx.common import ApiError
from atelierx.generation_pipeline import build_anima_prompt, upscale_dimensions, validate_pipeline


INPUT = {"diffusion_model": "anima", "text_encoder": "encoder", "vae": "vae", "positive_prompt": "character",
         "negative_prompt": "", "width": 512, "height": 512, "seed": 1, "steps": 24, "cfg": 4.5,
         "sampler": "euler", "scheduler": "normal"}


def anima_schema():
    required = {}
    for key, value in INPUT.items():
        if key in {"positive_prompt", "negative_prompt"}: required[key] = ["STRING", {}]
        elif type(value) is int: required[key] = ["INT", {"min": 0, "max": 2**64 - 1}]
        elif type(value) is float: required[key] = ["FLOAT", {"min": 0, "max": 20}]
        else: required[key] = [[value], {}]
    return {"input": {"required": required, "optional": {"lora_stack": ["STRING", {}]}}}


class PostprocessTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.posts = []; self.history = {}; self.pending = []
        schemas = {NODE: anima_schema(), "SaveImage": {}, "AtelierXUpscale": {"input": {"required": {"upscale_model": [["4x-UltraSharp.safetensors"], {}]}}},
                   "AtelierXDetectNsfwMask": {"input": {"required": {"segmentation_model": [["nsfw.pt"], {}]}}},
                   "AtelierXCensor": {"input": {"required": {"treatment": [["mosaic", "white"], {}]}}},
                   "AtelierXDetectCharacterMask": {"input": {"required": {"segmentation_model": [["person.pt"], {}]}}},
                   "AtelierXApplyCharacterAlpha": {}, "AtelierXEncodeSave": {}}
        self.schemas = schemas
        app = web.Application()
        async def info(request):
            key = request.match_info["name"]
            return web.json_response({key: self.schemas[key]} if key in self.schemas else {})
        async def queue(request): return web.json_response({"queue_running": [], "queue_pending": self.pending})
        async def prompt(request):
            value = await request.json(); self.posts.append(value); self.pending = [[0, value["prompt_id"]]]
            return web.json_response({"prompt_id": value["prompt_id"]})
        async def history(request): return web.json_response(self.history)
        async def view(request):
            return web.Response(body=b"RIFFxxxxWEBPfixture" if request.query.get("filename", "").endswith("webp") else b"\x89PNG\r\n\x1a\nfixture")
        app.add_routes([web.get("/object_info/{name}", info), web.get("/queue", queue), web.post("/prompt", prompt),
                        web.get("/history/{id}", history), web.get("/view", view)])
        self.comfy = TestServer(app); await self.comfy.start_server()
        self.client = TestClient(TestServer(create_app(self.temp.name, str(self.comfy.make_url("/")), "token", .01))); await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close(); await self.comfy.close(); self.temp.cleanup()

    def headers(self, key="post"): return {"Authorization": "Bearer token", "Idempotency-Key": key}
    async def state(self, identifier, expected):
        for _ in range(100):
            item = await (await self.client.get(f"/v1/jobs/{identifier}", headers=self.headers())).json()
            if item["state"] == expected: return item
            await asyncio.sleep(.01)
        self.fail(item)

    async def test_fixed_pipeline_snapshot_and_webp_collection(self):
        pipeline = {"upscale": {"upscale_model": "4x-UltraSharp.safetensors", "scale": 1.5},
                    "censor": {"segmentation_model": "nsfw.pt", "labels": "nipples", "treatment": "mosaic", "intensity": 15},
                    "alpha": {"segmentation_model": "person.pt"}, "encode": {"webp_enabled": True, "webp_quality": 88}}
        response = await self.client.post("/v1/nodes/anima/jobs", json={"inputs": INPUT, "postprocess": pipeline}, headers=self.headers())
        self.assertEqual(response.status, 202); job = await response.json(); submitted = await self.state(job["job_id"], "submitted")
        graph = self.posts[0]["prompt"]
        self.assertEqual([graph[str(i)]["class_type"] for i in range(1, 8)], [NODE, "AtelierXUpscale", "AtelierXDetectNsfwMask", "AtelierXCensor", "AtelierXDetectCharacterMask", "AtelierXApplyCharacterAlpha", "AtelierXEncodeSave"])
        self.assertEqual(graph["2"]["inputs"], {"image": ["1", 0], "upscale_model": "4x-UltraSharp.safetensors", "scale": 1.5})
        self.assertEqual(submitted["postprocess"]["encode"]["webp_quality"], 88)
        self.pending = []
        self.history[job["job_id"]] = {"status": {"completed": True}, "outputs": {"7": {"atelierx_files": [
            {"filename": "x.png", "type": "output", "subfolder": "AtelierX", "format": "png"},
            {"filename": "x.webp", "type": "output", "subfolder": "AtelierX", "format": "webp"}]}}}
        done = await self.state(job["job_id"], "completed")
        self.assertEqual([x["media_type"] for x in done["images"]], ["image/png", "image/webp"])
        image = await self.client.get(done["images"][1]["url"], headers=self.headers())
        self.assertEqual(image.headers["Content-Type"], "image/webp")

    async def test_rejects_unknown_graph_and_missing_registered_stage(self):
        for pipeline in ({"alpha": {"segmentation_model": "missing"}}, {"detailer": {}}, {"other": {}}):
            response = await self.client.post("/v1/nodes/anima/jobs", json={"inputs": INPUT, "postprocess": pipeline}, headers=self.headers(str(pipeline)))
            self.assertIn(response.status, {400, 503})

    async def test_upscale_requires_an_installed_selected_model_without_fallback(self):
        response = await self.client.post("/v1/nodes/anima/jobs", json={"inputs": INPUT, "postprocess": {
            "upscale": {"upscale_model": "not-installed.safetensors", "scale": 1.5}}}, headers=self.headers("upscale-missing"))
        self.assertEqual(response.status, 503)
        self.assertEqual((await response.json())["error"]["code"], "GEN_UPSCALE_MODEL_UNAVAILABLE")
        self.assertFalse(self.posts)

    async def test_nodes_reports_upscale_model_readiness(self):
        response = await self.client.get("/v1/nodes", headers=self.headers())
        self.assertEqual(response.status, 200)
        status = next(item for item in (await response.json())["postprocess"] if item["id"] == "upscale")
        self.assertEqual((status["registered"], status["ready"], status["reason"]), (True, True, None))
        self.schemas["AtelierXUpscale"]["input"]["required"]["upscale_model"] = [[], {}]
        response = await self.client.get("/v1/nodes", headers=self.headers())
        status = next(item for item in (await response.json())["postprocess"] if item["id"] == "upscale")
        self.assertEqual((status["registered"], status["ready"]), (True, False))
        self.assertIn("No upscale model", status["reason"])

    def test_upscale_validation_and_final_dimension_contract(self):
        info = {"AtelierXUpscale": {"input": {"required": {"upscale_model": [["4x-UltraSharp.safetensors"], {}]}}}}
        self.assertEqual(validate_pipeline({"upscale": {"upscale_model": "4x-UltraSharp.safetensors", "scale": 1.5}}, info),
                         {"upscale": {"upscale_model": "4x-UltraSharp.safetensors", "scale": 1.5}})
        self.assertEqual(upscale_dimensions(1024, 1024, 1.5), (1536, 1536))
        with self.assertRaises(ApiError) as caught:
            validate_pipeline({"upscale": {"upscale_model": "4x-UltraSharp.safetensors"}}, {"AtelierXUpscale": {"input": {"required": {"upscale_model": [[], {}]}}}})
        self.assertEqual(caught.exception.code, "GEN_UPSCALE_MODEL_UNAVAILABLE")

    def test_detailer_rebuilds_assets_and_ordered_loras(self):
        info = {name: {} for name in ("UNETLoader", "CLIPLoader", "VAELoader", "CLIPTextEncode", "LoraLoaderModelOnly", "UltralyticsDetectorProvider", "SAMLoader", "ToDetailerPipe", "FaceDetailerPipe")}
        info["AtelierXImpactDetailerPipeline"] = {"input": {"required": {"sampler_name": [["euler_ancestral"], {}], "scheduler": [["normal"], {}]}}}
        info["UltralyticsDetectorProvider"] = {"input": {"required": {"model_name": [["bbox/face_yolov8m.pt", "segm/PitEyeDetailer-v2-seg.pt", "bbox/hand_yolov8s.pt"]]}}}
        info["SAMLoader"] = {"input": {"required": {"model_name": [["sam_vit_b_01ec64.pth"]]}}}
        with self.assertRaisesRegex(Exception, "face_detector_model"):
            validate_pipeline({"detailer": {"face_detector_model": "missing.pt"}}, info)
        pipeline = validate_pipeline({"detailer": {"seed": 7, "steps": 12, "denoise": .35}}, info)
        inputs = dict(INPUT, lora_stack='[{"name":"first","strength":0.2},{"name":"second","strength":0.4}]')
        graph, output = build_anima_prompt(inputs, pipeline, "job")
        kinds = [node["class_type"] for node in graph.values()]
        self.assertEqual(kinds[:7], [NODE, "UNETLoader", "CLIPLoader", "VAELoader", "LoraLoaderModelOnly", "LoraLoaderModelOnly", "CLIPTextEncode"])
        self.assertEqual(graph["5"]["inputs"]["lora_name"], "first")
        self.assertEqual(graph["6"]["inputs"]["model"], ["5", 0])
        self.assertEqual(graph[output]["class_type"], "SaveImage")

    def test_detailer_rejects_unregistered_sampler(self):
        info = {name: {} for name in ("UNETLoader", "CLIPLoader", "VAELoader", "CLIPTextEncode", "UltralyticsDetectorProvider", "SAMLoader", "ToDetailerPipe", "FaceDetailerPipe")}
        info["AtelierXImpactDetailerPipeline"] = {"input": {"required": {"sampler_name": [["euler"], {}], "scheduler": [["normal"], {}]}}}
        with self.assertRaisesRegex(Exception, "sampler_name"):
            validate_pipeline({"detailer": {"sampler_name": "missing"}}, info)
