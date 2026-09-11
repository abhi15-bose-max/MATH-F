import unittest

from math_f.generation.output_cleaner import clean_model_output


class TestOutputCleaner(unittest.TestCase):
    def test_plain_proof_passthrough(self):
        raw = "theorem foo : 1 = 1 := by\n  rfl"
        result = clean_model_output(raw)
        self.assertEqual(result.status, "PASSTHROUGH")
        self.assertEqual(result.cleaned_candidate, raw)

    def test_markdown_fenced_proof(self):
        raw = "Here is the proof:\n```lean4\ntheorem foo : 1 = 1 := by\n  rfl\n```"
        result = clean_model_output(raw)
        self.assertEqual(result.status, "CLEANED")
        self.assertEqual(result.cleaned_candidate, "theorem foo : 1 = 1 := by\n  rfl")

    def test_fenced_proof_no_language_tag(self):
        raw = "```\ntheorem foo : 1 = 1 := by rfl\n```"
        result = clean_model_output(raw)
        self.assertEqual(result.status, "CLEANED")
        self.assertEqual(result.cleaned_candidate, "theorem foo : 1 = 1 := by rfl")

    def test_leading_trailing_whitespace_stripped(self):
        raw = "\n\n   theorem foo : 1 = 1 := by rfl   \n\n"
        result = clean_model_output(raw)
        self.assertEqual(result.status, "PASSTHROUGH")
        self.assertEqual(result.cleaned_candidate, "theorem foo : 1 = 1 := by rfl")

    def test_common_harmless_text_quote_wrapper(self):
        raw = "text'''theorem foo : 1 = 1 := by rfl'''"
        result = clean_model_output(raw)
        self.assertEqual(result.status, "CLEANED")
        self.assertEqual(result.cleaned_candidate, "theorem foo : 1 = 1 := by rfl")

    def test_malformed_no_extractable_proof(self):
        raw = "I think the answer is probably true, but I'm not fully sure how to show it."
        result = clean_model_output(raw)
        self.assertEqual(result.status, "MALFORMED")
        self.assertIsNone(result.cleaned_candidate)

    def test_malformed_apology_containing_the_word_sorry_is_not_mistaken_for_lean(self):
        # Regression guard: "sorry" is common in plain-English refusals and
        # must not be treated as a Lean-syntax signal on its own.
        raw = "I don't know how to prove this, sorry about that."
        result = clean_model_output(raw)
        self.assertEqual(result.status, "MALFORMED")

    def test_empty_output(self):
        result = clean_model_output("")
        self.assertEqual(result.status, "EMPTY")
        self.assertTrue(result.is_malformed)

    def test_whitespace_only_output(self):
        result = clean_model_output("   \n\n   ")
        self.assertEqual(result.status, "EMPTY")

    def test_none_output(self):
        result = clean_model_output(None)
        self.assertEqual(result.status, "EMPTY")
        self.assertTrue(result.is_malformed)

    def test_non_string_output(self):
        result = clean_model_output(12345)
        self.assertEqual(result.status, "MALFORMED")

    def test_unclosed_code_fence_is_malformed(self):
        raw = "```lean4\ntheorem foo : 1 = 1 := by rfl\n"  # never closed
        result = clean_model_output(raw)
        self.assertEqual(result.status, "MALFORMED")
        self.assertIn("Unclosed", result.reason)

    def test_empty_fenced_block_is_malformed(self):
        raw = "```lean4\n\n```"
        result = clean_model_output(raw)
        self.assertEqual(result.status, "MALFORMED")

    def test_does_not_mutate_internal_content(self):
        # Regression guard: exponents, unicode math, and identifiers inside
        # the candidate must never be rewritten (spec section 6).
        raw = "```lean4\ntheorem foo (x : \u211d) : x ^ 2 \u2265 0 := by positivity\n```"
        result = clean_model_output(raw)
        self.assertIn("x ^ 2", result.cleaned_candidate)
        self.assertIn("\u211d", result.cleaned_candidate)
        self.assertIn("positivity", result.cleaned_candidate)

    def test_first_fence_used_when_multiple_present(self):
        raw = (
            "```lean4\ntheorem a : 1 = 1 := by rfl\n```\n"
            "some commentary\n"
            "```lean4\ntheorem b : 2 = 2 := by rfl\n```"
        )
        result = clean_model_output(raw)
        self.assertEqual(result.status, "CLEANED")
        self.assertIn("theorem a", result.cleaned_candidate)
        self.assertNotIn("theorem b", result.cleaned_candidate)

    def test_oversized_candidate_is_malformed(self):
        raw = "```lean4\n" + ("theorem foo := by rfl -- " + "x" * 25_000) + "\n```"
        result = clean_model_output(raw)
        self.assertEqual(result.status, "MALFORMED")


if __name__ == "__main__":
    unittest.main()
