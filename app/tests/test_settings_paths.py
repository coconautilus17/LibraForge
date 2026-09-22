import os
import unittest
from pathlib import Path
from unittest import mock

from app import settings_paths


class SettingsPathsTests(unittest.TestCase):
    def test_defaults_to_the_config_folder_next_to_the_shipped_defaults(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("LIBRAFORGE_SETTINGS_DIR", None)
            self.assertEqual(settings_paths.user_settings_file("abs.json"), settings_paths.PROJECT_ROOT / "config" / "abs.json")

    def test_settings_dir_override_moves_every_user_file(self):
        with mock.patch.dict(os.environ, {"LIBRAFORGE_SETTINGS_DIR": "/app/settings"}):
            for name in ("abs.json", "abs-agg.json", "abs-tract.json", "retention.json", "publishers.local.json", "title-noise.local.json", "author-names.local.json"):
                self.assertEqual(settings_paths.user_settings_file(name), Path("/app/settings") / name)

    def test_blank_override_is_ignored(self):
        with mock.patch.dict(os.environ, {"LIBRAFORGE_SETTINGS_DIR": "  "}):
            self.assertEqual(settings_paths.settings_dir(), settings_paths.PROJECT_ROOT / "config")

    def test_policy_and_app_modules_use_the_shared_location(self):
        import importlib
        with mock.patch.dict(os.environ, {"LIBRAFORGE_SETTINGS_DIR": "/app/settings"}):
            for name, attr, filename in (
                ("app.publisher_policy", "LOCAL_POLICY_FILE", "publishers.local.json"),
                ("app.title_noise_policy", "LOCAL_POLICY_FILE", "title-noise.local.json"),
                ("app.author_names", "LOCAL_POLICY_FILE", "author-names.local.json"),
            ):
                with mock.patch.dict(os.environ, {"PUBLISHERS_LOCAL_FILE": "", "TITLE_NOISE_LOCAL_FILE": "", "AUTHOR_NAMES_LOCAL_FILE": ""}):
                    for var in ("PUBLISHERS_LOCAL_FILE", "TITLE_NOISE_LOCAL_FILE", "AUTHOR_NAMES_LOCAL_FILE"):
                        os.environ.pop(var, None)
                    module = importlib.reload(importlib.import_module(name))
                    self.assertEqual(getattr(module, attr), Path("/app/settings") / filename, name)
        for name in ("app.publisher_policy", "app.title_noise_policy", "app.author_names"):
            importlib.reload(importlib.import_module(name))


if __name__ == "__main__":
    unittest.main()
