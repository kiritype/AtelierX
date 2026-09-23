from __future__ import annotations

import asyncio
import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


NODE_PATH = Path(__file__).resolve().parents[1] / "nodes.py"
MODULE_NAME = "atelierx_anima_nodes_under_test"


class FakeTensor:
    def __init__(self, shape):
        self.shape = shape
        self.reshape_calls = []

    def reshape(self, *shape):
        self.reshape_calls.append(shape)
        return FakeTensor(shape)


class FakeNodeOutput:
    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs

    def __getitem__(self, index):
        return self.args[index]


class FakeField:
    @staticmethod
    def Input(identifier, **kwargs):
        return {"id": identifier, **kwargs}

    @staticmethod
    def Output(**kwargs):
        return kwargs


class FakeSchema:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class FakeClip:
    def __init__(self):
        self.tokenized = []
        self.tokenizer = AnimaTokenizer()

    def tokenize(self, prompt):
        self.tokenized.append(prompt)
        return f"tokens:{prompt}"

    def encode_from_tokens_scheduled(self, tokens):
        return f"conditioning:{tokens}"


class FakeVAE:
    latent_channels = 16

    def __init__(self):
        self.decode_input = None

    def decode(self, samples):
        self.decode_input = samples
        return FakeTensor((1, 1, 64, 64, 3))


class Anima:
    pass


class AnimaTokenizer:
    pass


class SDXL:
    pass


class FakeModel:
    def __init__(self, base_model, application_log=None):
        self.model = base_model
        self.application_log = [] if application_log is None else application_log
        self.attachments = {}

    def clone(self):
        return FakeModel(self.model, self.application_log)

    def add_patches(self, patches, strength):
        self.application_log.append((patches, strength))
        return set(patches)

    def set_attachments(self, name, value):
        self.attachments[name] = value


def fake_modules():
    folder_paths = types.ModuleType("folder_paths")
    folder_paths.get_filename_list = Mock(side_effect=lambda kind: {
        "diffusion_models": ["anima.safetensors"],
        "text_encoders": ["anima_te.safetensors"],
        "vae": ["anima_vae.safetensors"],
        "loras": ["first.safetensors", "second.safetensors"],
    }[kind])
    folder_paths.get_full_path_or_raise = Mock(side_effect=lambda kind, name: f"C:/registered/{kind}/{name}")
    folder_paths.get_folder_paths = Mock(return_value=["C:/registered/embeddings"])

    torch = types.ModuleType("torch")
    torch.zeros = Mock(return_value=FakeTensor((1, 16, 1, 64, 64)))

    comfy = types.ModuleType("comfy")
    comfy.__path__ = []
    comfy_sd = types.ModuleType("comfy.sd")
    comfy_sd.load_diffusion_model = Mock(return_value=FakeModel(Anima()))
    comfy_sd.load_clip = Mock(return_value=FakeClip())
    comfy_samplers = types.ModuleType("comfy.samplers")
    comfy_samplers.KSampler = types.SimpleNamespace(
        SAMPLERS=["euler_ancestral"], SCHEDULERS=["normal"]
    )
    comfy_management = types.ModuleType("comfy.model_management")
    comfy_management.intermediate_device = Mock(return_value="cpu")
    comfy_management.intermediate_dtype = Mock(return_value="float32")
    comfy.sd = comfy_sd
    comfy.samplers = comfy_samplers
    comfy.model_management = comfy_management
    comfy_lora = types.ModuleType("comfy.lora")
    comfy_lora.model_lora_keys_unet = Mock(return_value={"adapter": "model.weight"})
    comfy_lora.load_lora = Mock(side_effect=lambda lora, key_map, log_missing=True: lora)
    comfy_lora_convert = types.ModuleType("comfy.lora_convert")
    comfy_lora_convert.convert_lora = Mock(side_effect=lambda lora: lora)
    comfy_utils = types.ModuleType("comfy.utils")
    comfy_utils.load_torch_file = Mock(
        side_effect=lambda path, **kwargs: ({path: "patch"}, {"path": path})
    )
    comfy.lora = comfy_lora
    comfy.lora_convert = comfy_lora_convert
    comfy.utils = comfy_utils

    standard_nodes = types.ModuleType("nodes")
    standard_nodes.common_ksampler = Mock(return_value=({"samples": "sampled-latent"},))
    standard_nodes.VAELoader = Mock(return_value=types.SimpleNamespace(load_vae=Mock(return_value=(FakeVAE(),))))
    standard_nodes.NODE_CLASS_MAPPINGS = {}

    comfy_api = types.ModuleType("comfy_api")
    comfy_api.__path__ = []
    latest = types.ModuleType("comfy_api.latest")
    latest.ComfyExtension = type("ComfyExtension", (), {})
    latest.io = types.SimpleNamespace(
        ComfyNode=type("ComfyNode", (), {}),
        Schema=FakeSchema,
        NodeOutput=FakeNodeOutput,
        Combo=FakeField,
        String=FakeField,
        Int=FakeField,
        Float=FakeField,
        Image=FakeField,
    )

    return {
        "folder_paths": folder_paths,
        "torch": torch,
        "comfy": comfy,
        "comfy.sd": comfy_sd,
        "comfy.samplers": comfy_samplers,
        "comfy.model_management": comfy_management,
        "comfy.lora": comfy_lora,
        "comfy.lora_convert": comfy_lora_convert,
        "comfy.utils": comfy_utils,
        "nodes": standard_nodes,
        "comfy_api": comfy_api,
        "comfy_api.latest": latest,
    }


class AtelierXAnimaGenerateTests(unittest.TestCase):
    def setUp(self):
        self.mocks = fake_modules()
        self.module_patch = patch.dict(sys.modules, self.mocks)
        self.module_patch.start()
        spec = importlib.util.spec_from_file_location(MODULE_NAME, NODE_PATH)
        self.node_module = importlib.util.module_from_spec(spec)
        sys.modules[MODULE_NAME] = self.node_module
        assert spec.loader is not None
        spec.loader.exec_module(self.node_module)
        self.file_patch = patch.object(self.node_module.os.path, "isfile", return_value=True)
        self.file_patch.start()

    def tearDown(self):
        self.file_patch.stop()
        sys.modules.pop(MODULE_NAME, None)
        self.module_patch.stop()

    def test_request_validation_rejects_unsupported_values(self):
        validate = self.node_module._validate_request
        for kwargs in ((510, 512, 24, 4.5), (512, 1921, 24, 4.5), (512, 512, 101, 4.5), (512, 512, 24, 20.1), (True, 512, 24, 4.5), (512, 512, 24.0, 4.5), (512, 512, 24, float("nan"))):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                validate(*kwargs)

    def test_registered_model_name_refuses_path_or_unknown_name(self):
        with self.assertRaisesRegex(ValueError, "not registered"):
            self.node_module._registered_filename("diffusion_models", "C:/outside/model.safetensors")
        self.mocks["folder_paths"].get_full_path_or_raise.assert_not_called()

    def test_non_anima_diffusion_model_is_rejected_before_sampling(self):
        self.mocks["comfy.sd"].load_diffusion_model.return_value = FakeModel(SDXL())
        with self.assertRaisesRegex(ValueError, "not an Anima"):
            self._generate()
        self.mocks["nodes"].common_ksampler.assert_not_called()

    def test_non_anima_text_encoder_is_rejected_before_sampling(self):
        self.mocks["comfy.sd"].load_clip.return_value.tokenizer = object()
        with self.assertRaisesRegex(ValueError, "not an Anima text encoder"):
            self._generate()
        self.mocks["nodes"].common_ksampler.assert_not_called()

    def test_sampling_validation_rejects_invalid_seed_sampler_and_scheduler(self):
        validate = self.node_module._validate_sampling
        for args in ((-1, "euler_ancestral", "normal"), (True, "euler_ancestral", "normal"), (1, "bad", "normal"), (1, "euler_ancestral", "bad"), (1, 3, "normal")):
            with self.subTest(args=args), self.assertRaises(ValueError):
                validate(*args)

    def test_prompt_validation_requires_literal_strings_and_nonempty_positive_prompt(self):
        validate = self.node_module._validate_prompts
        for args in (("", ""), (None, ""), ("valid", None)):
            with self.subTest(args=args), self.assertRaises(ValueError):
                validate(*args)

    def test_incompatible_vae_is_rejected_before_prompt_encoding(self):
        invalid_vae = FakeVAE()
        invalid_vae.latent_channels = 4
        self.mocks["nodes"].VAELoader.return_value.load_vae.return_value = (invalid_vae,)
        with self.assertRaisesRegex(ValueError, "16 latent channels"):
            self._generate()
        self.mocks["nodes"].common_ksampler.assert_not_called()

    def test_multiple_loras_apply_in_slot_order_with_their_weights(self):
        self._generate(
            lora_stack='[{"name":"first.safetensors","strength":0.35},{"name":"second.safetensors","strength":0.8}]',
        )

        loaded_paths = [call.args[0] for call in self.mocks["comfy.utils"].load_torch_file.call_args_list]
        self.assertEqual(
            loaded_paths,
            ["C:/registered/loras/first.safetensors", "C:/registered/loras/second.safetensors"],
        )
        source_model = self.mocks["comfy.sd"].load_diffusion_model.return_value
        self.assertEqual(
            [strength for _, strength in source_model.application_log], [0.35, 0.8]
        )

    def test_empty_dynamic_stack_leaves_existing_generation_path_unchanged(self):
        self._generate(lora_stack="[]")
        self.mocks["comfy.utils"].load_torch_file.assert_not_called()

    def test_legacy_three_slot_inputs_remain_compatible(self):
        self._generate(lora_1_name="second.safetensors", lora_1_strength=0.6)
        self.mocks["comfy.utils"].load_torch_file.assert_called_once_with(
            "C:/registered/loras/second.safetensors", safe_load=True, return_metadata=True
        )

    def test_lora_validation_rejects_invalid_selection_strength_and_incompatible_adapter(self):
        for args in (("C:/outside.safetensors", 1.0), ("first.safetensors", True), ("first.safetensors", float("nan")), ("first.safetensors", 100.1)):
            with self.subTest(args=args), self.assertRaises(ValueError):
                self.node_module._validate_lora_selection(*args, 1)

        self.mocks["comfy.lora"].load_lora.side_effect = None
        self.mocks["comfy.lora"].load_lora.return_value = {}
        with self.assertRaisesRegex(ValueError, "no patches compatible"):
            self._generate(lora_stack='[{"name":"first.safetensors","strength":1.0}]')
        self.mocks["nodes"].common_ksampler.assert_not_called()

    def test_lora_stack_rejects_invalid_json_shape_and_mixed_legacy_inputs(self):
        parse = self.node_module._parse_lora_stack
        for stack in ("not json", "{}", '[{"name":"first.safetensors"}]', '[{"name":"first.safetensors","strength":true}]'):
            with self.subTest(stack=stack), self.assertRaises(ValueError):
                parse(stack, {})
        with self.assertRaisesRegex(ValueError, "either lora_stack or legacy"):
            parse("[]", {"lora_1_name": "first.safetensors"})

    def test_execute_wires_both_prompts_seed_dimensions_sampling_and_decode(self):
        output = self._generate()

        clip = self.mocks["comfy.sd"].load_clip.return_value
        self.assertEqual(clip.tokenized, ["positive", "negative"])
        self.mocks["torch"].zeros.assert_called_once_with(
            [1, 16, 1, 64, 64], device="cpu", dtype="float32"
        )
        sampler_args, sampler_kwargs = self.mocks["nodes"].common_ksampler.call_args
        self.assertEqual(sampler_args[1:7], (42, 24, 4.5, "euler_ancestral", "normal", "conditioning:tokens:positive"))
        self.assertEqual(sampler_args[7], "conditioning:tokens:negative")
        self.assertEqual(sampler_args[8]["samples"].shape, (1, 16, 1, 64, 64))
        self.assertEqual(sampler_kwargs, {"denoise": 1.0})
        self.assertEqual(output[0].shape, (-1, 64, 64, 3))

    def test_schema_lists_registered_model_types_and_extension_registers_node(self):
        schema = self.node_module.AtelierXAnimaGenerate.define_schema()
        self.assertEqual(schema.node_id, "AtelierXAnimaGenerate")
        self.assertEqual(schema.inputs[0]["options"], ["anima.safetensors"])
        self.assertEqual(
            schema.inputs[12]["extra_dict"],
            {"atelierx_lora_stack": {"options": ["first.safetensors", "second.safetensors"]}},
        )
        self.assertTrue(schema.inputs[12]["optional"])
        self.assertTrue(schema.accept_all_inputs)
        self.assertNotIn("dynamic_prompts", schema.inputs[3])
        extension = self.node_module.AtelierXAnimaExtension()
        self.assertEqual(asyncio.run(extension.get_node_list()), [self.node_module.AtelierXAnimaGenerate])

    def test_parse_consistency_treats_empty_as_none_and_validates_shape(self):
        parse = self.node_module._parse_consistency
        self.assertIsNone(parse("", None, None))
        self.assertIsNone(parse(None, None, None))
        with self.assertRaisesRegex(ValueError, "valid JSON"):
            parse("not json", "full", "face")
        with self.assertRaisesRegex(ValueError, "method and optional params"):
            parse('{"params":{}}', "full", "face")
        with self.assertRaisesRegex(ValueError, "Unknown consistency method"):
            parse('{"method":"other"}', "full", "face")

    def test_consistency_requires_both_references(self):
        parse = self.node_module._parse_consistency
        with self.assertRaisesRegex(ValueError, "requires both reference_full and reference_face"):
            parse('{"method":"anima-incontext-character"}', "full-only", None)
        with self.assertRaisesRegex(ValueError, "requires both reference_full and reference_face"):
            parse('{"method":"anima-incontext-character"}', None, "face-only")

    def test_consistency_param_validation_rejects_out_of_range_and_unknown_fields(self):
        parse = self.node_module._parse_consistency
        with self.assertRaisesRegex(ValueError, "consistency.strength"):
            parse('{"method":"anima-incontext-character","params":{"strength":10}}', "full", "face")
        with self.assertRaisesRegex(ValueError, "consistency.strength"):
            parse('{"method":"anima-incontext-character","params":{"strength":true}}', "full", "face")
        with self.assertRaisesRegex(ValueError, "consistency.end_percent"):
            parse('{"method":"anima-incontext-character","params":{"end_percent":0.1}}', "full", "face")
        with self.assertRaisesRegex(ValueError, "Unsupported consistency param"):
            parse('{"method":"anima-incontext-character","params":{"extra":1}}', "full", "face")

    def test_consistency_defaults_are_strength_one_and_end_percent_half(self):
        selection = self.node_module._parse_consistency(
            '{"method":"anima-incontext-character"}', "full", "face"
        )
        self.assertEqual(selection, {"method": "anima-incontext-character", "params": {"strength": 1.0, "end_percent": 0.5}})

    def test_backward_compatible_generation_never_touches_node_registry(self):
        self._generate()
        self.assertEqual(self.mocks["nodes"].NODE_CLASS_MAPPINGS, {})
        self.mocks["nodes"].common_ksampler.assert_called_once()

    def test_missing_incontext_node_raises_clear_error_before_sampling(self):
        with self.assertRaisesRegex(ValueError, "AnimaRefEncode.*not registered"):
            self._generate(
                reference_full="full-image",
                reference_face="face-image",
                consistency='{"method":"anima-incontext-character","params":{"strength":1.0,"end_percent":0.5}}',
            )
        self.mocks["nodes"].common_ksampler.assert_not_called()

    def test_incontext_character_applies_lora_encodes_batches_and_wires_model_into_sampler(self):
        encode_calls, batch_calls, apply_calls = [], [], []

        class FakeRefEncode:
            FUNCTION = "encode"

            def encode(self, vae, image, mask=None, target_width=0, target_height=0):
                encode_calls.append((vae, image, target_width, target_height))
                return (f"latent:{image}",)

        class FakeRefBatch:
            FUNCTION = "batch"

            def batch(self, ref_latent_1, ref_latent_2, fit_mode):
                batch_calls.append((ref_latent_1, ref_latent_2, fit_mode))
                return ("batched-latent",)

        class FakeInContextApply:
            FUNCTION = "apply"

            def apply(self, model, ref_latent, strength, start_percent, end_percent,
                      cond_only=True, fit_mode="pad", ref_timestep=0.0):
                apply_calls.append((model, ref_latent, strength, start_percent, end_percent, cond_only, fit_mode, ref_timestep))
                return ("model-with-reference",)

        self.mocks["nodes"].NODE_CLASS_MAPPINGS = {
            "AnimaRefEncode": FakeRefEncode,
            "AnimaRefLatentBatch": FakeRefBatch,
            "AnimaInContextApply": FakeInContextApply,
        }
        self.mocks["folder_paths"].get_filename_list.side_effect = lambda kind: {
            "diffusion_models": ["anima.safetensors"],
            "text_encoders": ["anima_te.safetensors"],
            "vae": ["anima_vae.safetensors"],
            "loras": ["first.safetensors", "second.safetensors", "anima-incontext-character.safetensors"],
        }[kind]

        self._generate(
            reference_full="full-image",
            reference_face="face-image",
            consistency='{"method":"anima-incontext-character","params":{"strength":1.2,"end_percent":0.6}}',
        )

        vae_instance = self.mocks["nodes"].VAELoader.return_value.load_vae.return_value[0]
        self.assertEqual(encode_calls, [
            (vae_instance, "full-image", 512, 512),
            (vae_instance, "face-image", 512, 512),
        ])
        self.assertEqual(batch_calls, [("latent:full-image", "latent:face-image", "pad")])
        self.assertEqual(len(apply_calls), 1)
        _, ref_latent, strength, start_percent, end_percent, cond_only, fit_mode, ref_timestep = apply_calls[0]
        self.assertEqual(
            (ref_latent, strength, start_percent, end_percent, cond_only, fit_mode, ref_timestep),
            ("batched-latent", 1.2, 0.0, 0.6, True, "pad", 0.0),
        )
        loaded_paths = [call.args[0] for call in self.mocks["comfy.utils"].load_torch_file.call_args_list]
        self.assertIn("C:/registered/loras/anima-incontext-character.safetensors", loaded_paths)
        sampler_args = self.mocks["nodes"].common_ksampler.call_args.args
        self.assertEqual(sampler_args[0], "model-with-reference")

    def _generate(self, **overrides):
        inputs = dict(
            diffusion_model="anima.safetensors",
            text_encoder="anima_te.safetensors",
            vae="anima_vae.safetensors",
            positive_prompt="positive",
            negative_prompt="negative",
            width=512,
            height=512,
            seed=42,
            steps=24,
            cfg=4.5,
            sampler="euler_ancestral",
            scheduler="normal",
        )
        inputs.update(overrides)
        return self.node_module.AtelierXAnimaGenerate.execute(**inputs)


if __name__ == "__main__":
    unittest.main()
