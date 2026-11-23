"""Fail-closed weekly/IRI forecast publication regression tests."""
import unittest
from publication_integrity import require_complete_frames


class PublishIntegrityTests(unittest.TestCase):
    def test_full_existing_run_is_successful_without_new_uploads(self):
        require_complete_frames(
            "ecwk", ["me/wta_2026113000.webp", "me/wpa_2026113000.webp"],
            ["me/wta_2026113000.webp", "me/wpa_2026113000.webp"], [])

    def test_partial_existing_plus_staged_is_successful(self):
        require_complete_frames(
            "cfswk", ["me/wta_2026113000.webp", "me/wpa_2026113000.webp"],
            ["me/wta_2026113000.webp"], ["me/wpa_2026113000.webp"])

    def test_no_frames_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "expected-frame inventory"):
            require_complete_frames("iri", [], [], [])

    def test_missing_one_iri_variable_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "1/2 required"):
            require_complete_frames(
                "iri", ["me/tpp_2026120100.webp", "me/tpt_2026120100.webp"],
                ["me/tpp_2026120100.webp"], [])

    def test_wrong_run_or_wrong_valid_time_not_accepted(self):
        with self.assertRaisesRegex(RuntimeError, "unavailable"):
            require_complete_frames("ecwk", ["me/wta_2026113000.webp"],
                                    ["me/wta_2026120700.webp"], [])

    def test_unverified_staged_file_not_accepted(self):
        with self.assertRaisesRegex(RuntimeError, "unavailable"):
            require_complete_frames("ecwk", ["me/wpa_2026113000.webp"],
                                    [], ["me/wpa_2026112900.webp"])


if __name__ == "__main__":
    unittest.main()
