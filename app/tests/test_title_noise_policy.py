import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import title_noise_policy


class TitleNoisePolicyTests(unittest.TestCase):
    def test_defaults_match_and_remove_generic_subtitles(self):
        title_noise_policy.clear_title_noise_cache()

        self.assertTrue(title_noise_policy.is_title_noise("A Humorous Isekai LitRPG"))
        self.assertEqual(
            title_noise_policy.remove_trailing_title_noise(
                "Arrival - A Humorous Isekai LitRPG"
            ),
            "Arrival",
        )
        self.assertFalse(title_noise_policy.is_title_noise("The Opus"))

    def test_local_policy_can_disable_defaults_and_add_custom_pattern(self):
        with tempfile.TemporaryDirectory() as temporary:
            local_file = Path(temporary) / "title-noise.local.json"
            with patch.object(title_noise_policy, "LOCAL_POLICY_FILE", local_file):
                saved = title_noise_policy.save_title_noise_policy(
                    disabled_defaults=["generic-genre-marketing-subtitle"],
                    custom_patterns=[
                        {
                            "id": "custom-academy",
                            "label": "Academy subtitle",
                            "pattern": r"(?:a|an)\s+academy\s+litrpg",
                            "enabled": True,
                        }
                    ],
                )

                self.assertIn(
                    "generic-genre-marketing-subtitle",
                    saved["disabled_defaults"],
                )
                self.assertTrue(title_noise_policy.is_title_noise("An Academy LitRPG"))
                payload = json.loads(local_file.read_text(encoding="utf-8"))
                self.assertEqual(payload["custom_patterns"][0]["id"], "custom-academy")
        title_noise_policy.clear_title_noise_cache()

    def test_descriptor_that_completes_a_title_is_kept(self):
        # Regression (#352): "a LitRPG Apocalypse" is the object of "of", so
        # dropping it leaves a sentence fragment.
        title_noise_policy.clear_title_noise_cache()
        for title in (
            "Apocalypse BREAKER 2: Book 2 of a LitRPG Apocalypse",
            "Apocalypse BREAKER: Book 1 of a LitRPG Apocalypse",
            "Book 3 of a LitRPG Apocalypse",
        ):
            self.assertEqual(title_noise_policy.remove_trailing_title_noise(title), title)

    def test_descriptor_after_a_complete_title_is_still_removed(self):
        title_noise_policy.clear_title_noise_cache()
        self.assertEqual(
            title_noise_policy.remove_trailing_title_noise("Slime Keeper a LitRPG Adventure"),
            "Slime Keeper",
        )

    def test_dangling_end_word_detection(self):
        self.assertTrue(title_noise_policy.ends_with_dangling_word("Book 2 of"))
        self.assertTrue(title_noise_policy.ends_with_dangling_word("Carter &"))
        self.assertFalse(title_noise_policy.ends_with_dangling_word("Book 2"))
        self.assertFalse(title_noise_policy.ends_with_dangling_word(""))


if __name__ == "__main__":
    unittest.main()
