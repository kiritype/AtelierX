import sqlite3
import tempfile
from pathlib import Path
import unittest

from atelierx.common import ApiError
from atelierx.core_validation_settings import ValidationSettings
from atelierx.validation_registry import RevisionRegistry

PROFILE = {"profile_id":"single","revision":1,"output_conditions":True,"positive_prompt":True,"negative_prompt":False,"body_parts":[],"metadata":False,"consistency":False}
PROVIDER = {"provider_id":"vision","revision":1,"model":"vision-a","timeout_seconds":5,"url":"http://localhost:1234","api_key_env":"ATELIERX_KEY"}

class ValidationSettingsTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(":memory:")
        self.settings=ValidationSettings(self.db, {"profiles":{"single":PROFILE},"providers":{"vision":PROVIDER}})
    def tearDown(self): self.db.close()
    def test_revision_history_archive_and_restart(self):
        original=self.settings.freeze({"profile_id":"single","provider_id":"vision"})
        updated=self.settings.update("provider","vision",1,{**PROVIDER,"model":"vision-b"})
        self.assertEqual(updated["revision"],2)
        self.assertEqual(self.settings.freeze({"profile_id":"single","provider_id":"vision"})["provider"]["model"],"vision-b")
        self.assertEqual(original["provider"], {"provider_id":"vision","revision":1,"model":"vision-a","timeout_seconds":5})
        self.assertEqual([x["revision"] for x in self.settings.history("provider","vision")],[2,1])
        archived=self.settings.archive("provider","vision",2)
        self.assertTrue(archived["archived"])
        with self.assertRaises(ApiError) as raised: self.settings.freeze({"profile_id":"single","provider_id":"vision"})
        self.assertEqual(raised.exception.code,"CORE_VALIDATION_SELECTION_ARCHIVED")
        restarted=ValidationSettings(self.db)
        self.assertTrue(restarted.current("provider","vision")["archived"])
    def test_clone_secret_rejection_and_group_profile(self):
        cloned=self.settings.clone("provider","vision","vision-copy")
        self.assertEqual((cloned["provider_id"],cloned["revision"]),("vision-copy",1))
        self.assertNotIn("api_key",str(self.settings.list("provider",True)))
        with self.assertRaises(ApiError): self.settings.create("provider",dict(PROVIDER,provider_id="bad",api_key="never"))
        group={"profile_id":"identity","revision":1,"consistency":True}
        self.assertEqual(self.settings.create("group_profile",group)["profile_id"],"identity")
        snapshots=self.settings.registry()
        self.assertIn(group,snapshots["profiles"])
        frozen=self.settings.freeze_group({"profile_id":"identity","provider_id":"vision"})
        self.assertEqual(frozen["profile"],group)
        with self.assertRaises(ApiError): self.settings.create("profile",dict(PROFILE,profile_id="identity"))
    def test_optional_max_tokens_is_revisioned_and_legacy_snapshots_remain_omitted(self):
        legacy = self.settings.freeze({"profile_id":"single","provider_id":"vision"})["provider"]
        bounded = dict(PROVIDER, revision=2, max_tokens=1024)
        self.settings.update("provider", "vision", 1, bounded)
        frozen = self.settings.freeze({"profile_id":"single","provider_id":"vision"})["provider"]
        self.assertEqual(frozen["max_tokens"], 1024)
        self.assertNotIn("max_tokens", legacy)
        self.assertEqual(self.settings.history("provider", "vision")[1]["revision"], 1)
        for invalid in (0, True, 1.5):
            with self.assertRaises(ApiError):
                self.settings.create("provider", dict(PROVIDER, provider_id=f"invalid-{invalid}", max_tokens=invalid))
    def test_legacy_consistency_profile_migrates_to_group_namespace_and_bad_shapes_are_422(self):
        db=sqlite3.connect(":memory:")
        settings=ValidationSettings(db,{"profiles":{"legacy-group":{"profile_id":"legacy-group","revision":1,"consistency":True}},"providers":{"vision":PROVIDER}})
        self.assertEqual(settings.freeze_group({"profile_id":"legacy-group","provider_id":"vision"})["profile"]["consistency"],True)
        with self.assertRaises(ApiError) as invalid_id: settings.current("profile",["not-an-id"])
        self.assertEqual(invalid_id.exception.status,422)
        with self.assertRaises(ApiError) as invalid_update: settings.update("provider","vision",1,[])
        self.assertEqual(invalid_update.exception.status,422)
        db.close()
    def test_invalid_unimplemented_single_checks_are_rejected(self):
        with self.assertRaises(ApiError): self.settings.create("profile",dict(PROFILE,profile_id="hands",body_parts=["hands"]))

class RegistryTests(unittest.TestCase):
    def test_old_revision_remains_after_new_snapshot_and_conflict_is_atomic(self):
        registry=RevisionRegistry()
        first={"profiles":[PROFILE],"providers":[{k:v for k,v in PROVIDER.items() if k != "api_key_env"}]}
        registry.apply(first)
        second_profile=dict(PROFILE,revision=2,negative_prompt=True)
        second_provider=dict(first["providers"][0],revision=2,model="vision-b")
        registry.apply({"profiles":[second_profile],"providers":[second_provider]})
        self.assertEqual(registry.provider({"provider_id":"vision","revision":1,"model":"vision-a","timeout_seconds":5})["model"],"vision-a")
        with self.assertRaises(ApiError) as raised: registry.apply({"profiles":[dict(PROFILE,positive_prompt=False)],"providers":[]})
        self.assertEqual(raised.exception.code,"VAL_REGISTRY_CONFLICT")
        self.assertEqual(registry.profile(second_profile),second_profile)
    def test_registry_preserves_optional_cap_and_rejects_invalid_values(self):
        registry=RevisionRegistry()
        bounded={k:v for k,v in dict(PROVIDER, max_tokens=1024).items() if k != "api_key_env"}
        registry.apply({"profiles":[PROFILE],"providers":[bounded]})
        snapshot={"provider_id":"vision","revision":1,"model":"vision-a","timeout_seconds":5,"max_tokens":1024}
        self.assertEqual(registry.provider(snapshot)["max_tokens"],1024)
        for invalid in (0, True, 1.5):
            with self.assertRaises(ApiError):
                registry.apply({"profiles":[],"providers":[dict(bounded, provider_id=f"invalid-{invalid}", max_tokens=invalid)]})
    def test_persisted_public_revision_never_copies_key_to_new_endpoint(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/"registry.json"
            configured={**PROVIDER,"api_key":"secret"}
            registry=RevisionRegistry({"vision":configured},{"single":PROFILE},path)
            registry.apply({"profiles":[PROFILE],"providers":[{k:v for k,v in configured.items() if k not in {"api_key","api_key_env"}}]})
            newer={"provider_id":"vision","revision":2,"model":"vision-b","timeout_seconds":5,"url":"http://another-host"}
            registry.apply({"profiles":[],"providers":[newer]})
            self.assertEqual(registry.providers[("vision",2)]["api_key"],"")
            restored=RevisionRegistry({"vision":configured},{"single":PROFILE},path)
            self.assertEqual(restored.providers[("vision",2)]["api_key"],"")
            self.assertNotIn("secret",path.read_text(encoding="utf-8"))

if __name__ == "__main__": unittest.main()
