import unittest

from atelierx.common import ApiError
from atelierx.validation_evidence import EVALUATION_VERSION, RUBRIC, check_items, clauses, evidence_schema, normalize_evidence, requirements


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
        self.assertEqual([x["requirement"] for x in parse("(eye], hair)\nred hat, boots")], ["(eye], hair)", "red hat", "boots"])


class CheckScopeTests(unittest.TestCase):
    PROSE = ("slim. A tall elegant woman in her late twenties with pale milky-white skin and an upright, unflappable posture. "
             "She has long platinum blonde hair with a single stray ahoge strand sticking up from the top of her head.")

    def request(self, positive_check=None, positive="year_2025, absurdres, upper body, silver hair"):
        image = {"positive_prompt": positive, "negative_prompt": "", "negative_sources": {"global": "", "character": ""}}
        if positive_check is not None:
            image["positive_check"] = positive_check
        return {"profile": {"positive_prompt": True, "negative_prompt": False}, "image": image}

    def answer(self, checks, statuses=None):
        statuses = statuses or {}
        return {"assessments": [{"id": c["id"], "status": statuses.get(c["id"], "matched"), "observed": "seen", "location": "center"} for c in checks]}

    def test_positive_check_itemizes_only_entries_with_sources(self):
        checks = requirements(self.request([{"text": "silver hair, heterochromia", "source": "character_features"},
                                            {"text": "white blouse", "source": "outfit_upper"},
                                            {"text": "(earring, choker:1.1)", "source": "fragment"}]))
        self.assertEqual([(c["requirement"], c["source"]) for c in checks],
                         [("silver hair", "character_features"), ("heterochromia", "character_features"),
                          ("white blouse", "outfit_upper"), ("earring", "fragment"), ("choker", "fragment")])
        self.assertNotIn("absurdres", [c["requirement"] for c in checks])
        result = normalize_evidence(self.answer(checks, {checks[2]["id"]: "mismatch"}), checks)
        self.assertEqual((result["findings"][0]["source"], result["findings"][0]["feature"]), ("outfit_upper", "white blouse"))

    def test_legacy_prompt_itemized_with_null_source(self):
        checks = requirements(self.request())
        self.assertEqual([c["requirement"] for c in checks], ["year_2025", "absurdres", "upper body", "silver hair"])
        self.assertTrue(all(c["source"] is None for c in checks))

    def test_not_assessable_passes_and_is_listed(self):
        checks = requirements(self.request([{"text": self.PROSE, "source": "character_appearance"}]))
        result = normalize_evidence(self.answer(checks, {checks[0]["id"]: "not_assessable"}), checks)
        self.assertEqual(result["outcome"], "passed")
        self.assertEqual(result["findings"], [])
        self.assertEqual(result["not_assessable"], [{"prompt_excerpt": "slim.", "source": "character_appearance", "observed": "seen"}])
        self.assertFalse(result["regeneration"]["required"])
        failed = normalize_evidence(self.answer(checks, {checks[0]["id"]: "not_assessable", checks[2]["id"]: "not_visible"}), checks)
        self.assertEqual((failed["outcome"], len(failed["findings"]), len(failed["not_assessable"])), ("failed", 1, 1))
        mismatch = normalize_evidence(self.answer(checks, {checks[1]["id"]: "mismatch"}), checks)
        self.assertEqual(mismatch["outcome"], "failed")

    def test_negative_not_assessable_counts_as_absent_but_listed(self):
        checks = requirements({"profile": {"positive_prompt": False, "negative_prompt": True},
                               "image": {"negative_prompt": "beard", "negative_sources": {"global": "", "character": "beard"}}})
        result = normalize_evidence(self.answer(checks, {checks[0]["id"]: "not_assessable"}), checks)
        self.assertEqual((result["outcome"], result["not_assessable"][0]["source"]), ("passed", None))

    def test_prose_splits_by_sentence_and_tags_unchanged(self):
        checks = requirements(self.request(positive=self.PROSE))
        self.assertEqual([c["requirement"] for c in checks], [
            "slim.", "A tall elegant woman in her late twenties with pale milky-white skin and an upright, unflappable posture.",
            "She has long platinum blonde hair with a single stray ahoge strand sticking up from the top of her head."])
        self.assertEqual([c["requirement"] for c in check_items("키가 크다. 은발에 붉은 눈을 가졌다.")], ["키가 크다.", "은발에 붉은 눈을 가졌다."])
        tags = "masterpiece, best quality, 1girl, solo, looking at viewer, smile."
        self.assertEqual([c["requirement"] for c in check_items(tags)], [c.strip() for c in tags.split(",")])
        mixed = check_items("upper body, (silver hair:1.2)\nShe wears a red ribbon. Her eyes are blue and calm.")
        self.assertEqual([c["requirement"] for c in mixed], ["upper body", "silver hair", "She wears a red ribbon.", "Her eyes are blue and calm."])

    def test_schema_and_rubric_include_not_assessable(self):
        checks = requirements(self.request())
        schema = evidence_schema(checks)
        self.assertIn("not_assessable", schema["properties"]["assessments"]["items"]["properties"]["status"]["enum"])
        self.assertIn("not_assessable", RUBRIC)
        self.assertNotIn("does not excuse", RUBRIC)
        self.assertEqual(EVALUATION_VERSION, 6)
