import tempfile
import unittest
from pathlib import Path

from atelierx.generation import Generation
from atelierx.common import ApiError


class IndependentPostprocessTests(unittest.TestCase):
    def test_only_known_image_id_and_preserved_context_are_accepted(self):
        with tempfile.TemporaryDirectory() as directory:
            service=Generation(directory,"http://comfy","token")
            image_id="source-0"; path=service.images_dir / (image_id+".png"); path.write_bytes(b"png")
            service.jobs["source"]={"job_id":"source","images":[{"image_id":image_id,"sha256":"abc","media_type":"image/png"}],"node_inputs":{"lora_stack":"[]"},"inputs":{}}
            source,image,found=service.image_source(image_id)
            self.assertEqual((source["job_id"],image["sha256"],found), ("source","abc",path))
            with self.assertRaises(ApiError): service.image_source("C:/arbitrary.png")
            del source["node_inputs"]
            self.assertIsNone(source.get("node_inputs"))
            service.owner.close()


if __name__ == "__main__": unittest.main()
