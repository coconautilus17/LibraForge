import unittest
from unittest.mock import patch

from app.main import OrganizerRunRequest, build_organizer_command


class OrganizerCommandTrustAbsMetadataTests(unittest.TestCase):
    def test_trust_abs_metadata_passes_flag_and_credentials_when_configured(self):
        req = OrganizerRunRequest(root_path="/audiobooks/_unorganized", trust_abs_metadata=True)
        with patch("app.main._get_abs_api_key", return_value="key"), \
             patch("app.main._get_abs_url", return_value="http://abs"):
            cmd = build_organizer_command(req)
        self.assertIn("--trust-abs-metadata", cmd)
        self.assertIn("--abs-url", cmd)
        self.assertIn("http://abs", cmd)
        self.assertIn("--abs-api-key", cmd)
        self.assertIn("key", cmd)

    def test_trust_abs_metadata_off_by_default(self):
        req = OrganizerRunRequest(root_path="/audiobooks/_unorganized")
        with patch("app.main._get_abs_api_key", return_value="key"):
            cmd = build_organizer_command(req)
        self.assertNotIn("--trust-abs-metadata", cmd)
        self.assertNotIn("--abs-url", cmd)

    def test_trust_abs_metadata_requested_but_not_configured_omits_everything(self):
        req = OrganizerRunRequest(root_path="/audiobooks/_unorganized", trust_abs_metadata=True)
        with patch("app.main._get_abs_api_key", return_value=""):
            cmd = build_organizer_command(req)
        self.assertNotIn("--trust-abs-metadata", cmd)
        self.assertNotIn("--abs-url", cmd)


class OrganizerCommandSkipPatternsTests(unittest.TestCase):
    def test_no_skip_patterns_adds_no_flags(self):
        req = OrganizerRunRequest(root_path="/audiobooks/_unorganized")
        cmd = build_organizer_command(req)
        self.assertNotIn("--skip-pattern", cmd)

    def test_each_skip_pattern_becomes_its_own_flag(self):
        req = OrganizerRunRequest(
            root_path="/audiobooks/_unorganized",
            skip_patterns=["Casual Farming", "Some Other Series"],
        )
        cmd = build_organizer_command(req)
        skip_flag_indices = [i for i, arg in enumerate(cmd) if arg == "--skip-pattern"]
        self.assertEqual(len(skip_flag_indices), 2)
        values = [cmd[i + 1] for i in skip_flag_indices]
        self.assertEqual(values, ["Casual Farming", "Some Other Series"])


class OrganizerCommandFlagTests(unittest.TestCase):
    """Every OrganizerRunRequest setting maps to exactly one flag, with the value
    the organizer script expects. Moving files is the riskiest thing Folder Forge
    does, so --apply and friends are pinned individually."""

    def build(self, **over):
        req = OrganizerRunRequest(root_path="/audiobooks/_unorganized", **over)
        with patch("app.main._get_abs_api_key", return_value=""):
            return build_organizer_command(req)

    def test_the_base_command_is_python_the_script_the_root_and_the_destination(self):
        cmd = self.build()
        self.assertEqual(cmd[:2], ["python3", "-u"])
        self.assertEqual(cmd[3], "/audiobooks/_unorganized")
        self.assertEqual(cmd[4:6], ["--destination-root", "/audiobooks"])

    def test_a_blank_destination_adds_no_destination_flag(self):
        self.assertNotIn("--destination-root", self.build(destination_root=""))

    def test_the_defaults_never_apply_anything(self):
        cmd = self.build()
        for flag in ("--apply", "--m4b-only", "--allow-unknown-author", "--include-existing-book-folders", "--no-companions",
                     "--remove-empty-dirs", "--rebuild-structure-cache", "--consolidate-structures", "--index-only",
                     "--acknowledge-no-sidecars", "--max-items", "--naming-template"):
            self.assertNotIn(flag, cmd)
        self.assertIn("--use-default-scheme", cmd)
        self.assertEqual(cmd[cmd.index("--progress-every") + 1], "1")

    def test_each_switch_adds_exactly_its_own_flag(self):
        for field, flag in (("apply", "--apply"), ("m4b_only", "--m4b-only"), ("allow_unknown_author", "--allow-unknown-author"),
                            ("include_existing_book_folders", "--include-existing-book-folders"), ("no_companions", "--no-companions"),
                            ("remove_empty_dirs", "--remove-empty-dirs"), ("rebuild_structure_cache", "--rebuild-structure-cache"),
                            ("consolidate_structures", "--consolidate-structures"), ("index_only", "--index-only"),
                            ("acknowledge_no_sidecars", "--acknowledge-no-sidecars")):
            with self.subTest(field=field):
                cmd = self.build(**{field: True})
                self.assertEqual(cmd.count(flag), 1)
                others = [f for f in cmd if f.startswith("--") and f not in (flag, "--destination-root", "--use-default-scheme", "--progress-every")]
                self.assertEqual(others, [], field)

    def test_max_items_is_passed_only_when_positive(self):
        self.assertNotIn("--max-items", self.build(max_items=0))
        self.assertNotIn("--max-items", self.build(max_items=-1))
        cmd = self.build(max_items=25)
        self.assertEqual(cmd[cmd.index("--max-items") + 1], "25")

    def test_progress_every_is_passed_for_zero_and_up_but_not_negative(self):
        cmd = self.build(progress_every=0)
        self.assertEqual(cmd[cmd.index("--progress-every") + 1], "0")
        self.assertNotIn("--progress-every", self.build(progress_every=-1))
        cmd = self.build(progress_every=50)
        self.assertEqual(cmd[cmd.index("--progress-every") + 1], "50")

    def test_blank_skip_patterns_are_dropped_and_the_rest_trimmed(self):
        cmd = self.build(skip_patterns=[" a ", "", "   ", "b"])
        values = [cmd[i + 1] for i, token in enumerate(cmd) if token == "--skip-pattern"]
        self.assertEqual(values, ["a", "b"])

    def test_the_default_scheme_wins_over_a_custom_template(self):
        cmd = self.build(use_default_scheme=True, naming_template="{author}/{title}")
        self.assertIn("--use-default-scheme", cmd)
        self.assertNotIn("--naming-template", cmd)

    def test_a_custom_template_is_passed_verbatim_when_the_default_scheme_is_off(self):
        cmd = self.build(use_default_scheme=False, naming_template="  {author}/{title}  ")
        self.assertNotIn("--use-default-scheme", cmd)
        self.assertEqual(cmd[cmd.index("--naming-template") + 1], "  {author}/{title}  ")

    def test_neither_scheme_nor_template_passes_neither_flag(self):
        cmd = self.build(use_default_scheme=False, naming_template="   ")
        self.assertNotIn("--use-default-scheme", cmd)
        self.assertNotIn("--naming-template", cmd)


if __name__ == "__main__":
    unittest.main()
