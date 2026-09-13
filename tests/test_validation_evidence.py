import unittest

from atelierx.common import ApiError
from atelierx.validation_evidence import clauses, normalize_evidence, requirements


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.checks = requirements({"profile": {"positive_prompt": True, "negative_prompt": True},
                                   "image": {"positive_prompt": "upper body, blue eyes, black boots", "negative_prompt": "watermark",
                                             "negative_sources": {"global": "", "character": "watermark"}}})

    def test_global_negative_never_becomes_failure_requirement(self):
        checks = requirements({"profile": {"positive_prompt": False, "negative_prompt": True},
                               "image": {"negative_prompt": "low quality, glasses, beard",
                                         "negative_sources": {"global": "low quality, glasses", "character": "beard"}}})
        self.assertEqual([item["requirement"] for item in checks], ["beard"])
        result = normalize_evidence({"assessments": [{"id": checks[0]["id"], "status": "mismatch", "observed": "beard on chin", "location": "chin"}]}, checks)
        self.assertEqual(result["outcome"], "failed")

    def answers(self):
        return {"assessments": [{"id": check["id"], "status": "matched", "observed": "visible supporting evidence", "location": "center"} for check in self.checks]}

    def test_missing_explicit_item_fails_even_with_matching_framing(self):
        answer = self.answers()
        answer["assessments"][2].update(status="not_visible", observed="Image ends above legs; no boots visible", location="not in image")
        result = normalize_evidence(answer, self.checks)
        self.assertEqual(result["outcome"], "failed")
        self.assertTrue(result["regeneration"]["required"])
        self.assertEqual(result["findings"][0]["prompt_excerpt"], "black boots")
        self.assertEqual(len(result["evidence"]), 4)

    def test_incomplete_duplicate_extra_and_empty_evidence_are_errors(self):
        for mode in ("missing", "duplicate", "unknown", "blank"):
            with self.subTest(mode=mode):
                answer = self.answers()
                if mode == "missing": answer["assessments"].pop()
                elif mode == "duplicate": answer["assessments"][-1] = answer["assessments"][0]
                elif mode == "unknown": answer["assessments"][-1]["id"] = "not-requested"
                else: answer["assessments"][-1]["observed"] = " "
                with self.assertRaises(ApiError) as exc: normalize_evidence(answer, self.checks)
                self.assertEqual(exc.exception.code, "VAL_PROVIDER_RESPONSE_INVALID")

    def test_uncertain_is_error_and_negative_violation_fails(self):
        answer = self.answers(); answer["assessments"][0]["status"] = "uncertain"
        with self.assertRaises(ApiError) as exc: normalize_evidence(answer, self.checks)
        self.assertEqual(exc.exception.code, "VAL_PROVIDER_INCONCLUSIVE")
        answer = self.answers(); answer["assessments"][-1]["status"] = "mismatch"
        self.assertEqual(normalize_evidence(answer, self.checks)["findings"][0]["code"], "negative_prompt_mismatch")

    def test_literal_coverage_weights_compounds_and_disabled_checks(self):
        self.assertEqual(clauses("(blue eyes, silver hair:1.2), shirt and brooch\nboots"), ["(blue eyes, silver hair:1.2)", "shirt and brooch", "boots"])
        request = {"profile": {"positive_prompt": True, "negative_prompt": False},
                   "image": {"positive_prompt": "blue eyes, blue eyes", "negative_prompt": "private disabled text"}}
        checks = requirements(request)
        self.assertEqual(len(checks), 2)
        self.assertNotEqual(checks[0]["id"], checks[1]["id"])
        self.assertTrue(all(check["kind"] == "positive" for check in checks))

    def test_weighted_group_splits_with_original_source_and_weights(self):
        original = "anime illustration, (eyeglasses, dangling earring:1.2)"
        request = {"profile": {"positive_prompt": True, "negative_prompt": False},
                   "image": {"positive_prompt": original, "negative_prompt": ""}}
        checks = requirements(request)
        self.assertEqual([x["requirement"] for x in checks], ["anime illustration", "eyeglasses", "dangling earring"])
        for check in checks[1:]:
            self.assertEqual(check["source_clause"], "(eyeglasses, dangling earring:1.2)")
            self.assertEqual(check["source_weights"], ["1.2"])
        self.assertEqual(request["image"]["positive_prompt"], original)
        answer = {"assessments": [{"id": x["id"], "status": "matched", "observed": "present", "location": "face"} for x in checks]}
        answer["assessments"][-1].update(status="not_visible", observed="ear occluded", location="not in image")
        result = normalize_evidence(answer, checks)
        self.assertEqual(result["outcome"], "failed")
        self.assertEqual(result["findings"][0]["feature"], "dangling earring")
        self.assertEqual(result["findings"][0]["prompt_excerpt"], "(eyeglasses, dangling earring:1.2)")

    def test_nested_weight_paths_and_ambiguous_syntax_preserved(self):
        def parse(prompt):
            return requirements({"profile": {"positive_prompt": True, "negative_prompt": False},
                                 "image": {"positive_prompt": prompt, "negative_prompt": ""}})
        checks = parse("((blue eyes, silver hair:1.2), hat:0.8)")
        self.assertEqual([x["requirement"] for x in checks], ["blue eyes", "silver hair", "hat"])
        self.assertEqual([x["source_weights"] for x in checks], [["0.8", "1.2"], ["0.8", "1.2"], ["0.8"]])
        for raw in (r"literal\(tag\), eye", "[red:blue:0.5]", "(eye], hair)", "shirt and brooch", "(earring:unknown)"):
            with self.subTest(raw=raw):
                entries = parse(raw)
                self.assertTrue(entries)
                self.assertTrue(all(x["source_clause"] in raw for x in entries))
        self.assertEqual(parse("(eye], hair)")[0]["requirement"], "(eye], hair)")
        self.assertEqual(parse("shirt and brooch")[0]["requirement"], "shirt and brooch")
