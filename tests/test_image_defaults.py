import tempfile
import unittest
from pathlib import Path

from atelierx.core import CORE, create_app
from atelierx.core_validation import CoreValidation
from atelierx.common import ApiError


class ImageDefaultTests(unittest.TestCase):
    def test_default_preview_and_explicit_overrides(self):
        with tempfile.TemporaryDirectory() as directory:
            app = create_app(Path(directory) / "core.db", "http://generation.fixture", "token")
            core = app[CORE]
            try:
                work = core.store.create_entity("works", "w", None)
                character = core.store.create_entity("characters", "c", work["id"])
                outfit = core.store.create_entity("outfits", "o", character["id"], {"appearance": "silver hair", "upper": "shirt", "lower": ""})
                group = core.store.create_group(outfit["id"])
                inputs = dict(diffusion_model="anima", text_encoder="encoder", vae="vae", seed=1, steps=24, cfg=4.5, sampler="euler", scheduler="normal")
                payload = {"group_id": group["id"], "framing": "upper_body", "generation_inputs": inputs}
                snapshot = core.preview(payload)["snapshot"]
                self.assertEqual((snapshot["generation_inputs"]["width"], snapshot["generation_inputs"]["height"]), (1024, 1024))
                self.assertEqual(snapshot["postprocess"]["upscale"], {"upscale_model": "4x-UltraSharp.safetensors", "scale": 1.5})
                self.assertEqual([CoreValidation.output_dimension({"snapshot": snapshot}, axis) for axis in ("width", "height")], [1536, 1536])
                explicit = core.preview(dict(payload, generation_inputs=dict(inputs, width=768, height=1024), postprocess={}))['snapshot']
                self.assertNotIn("postprocess", explicit)
                self.assertEqual([CoreValidation.output_dimension({"snapshot": explicit}, axis) for axis in ("width", "height")], [768, 1024])
                self.assertNotIn("width", inputs)
                with self.assertRaises(ApiError):
                    core.preview(dict(payload, postprocess={"upscale": {"upscale_model": "model", "scale": float('nan')}}))
            finally:
                core.store.close()
