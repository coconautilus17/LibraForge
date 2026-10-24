"""The "Audible public catalog" provider: runs search one marketplace's public
catalog with no login, even when an auth file exists."""
import unittest

from app.main import RunRequest, build_command


def _request(**overrides):
    base = dict(script_name="audible-metadata-fixer-v5.py", target_path="/audiobooks")
    base.update(overrides)
    return RunRequest(**base)


class PublicCatalogCommandTests(unittest.TestCase):
    def test_public_provider_passes_the_region_and_no_auth_file(self):
        cmd, _ = build_command(_request(provider="audible-public", audible_region="de"))
        self.assertEqual(cmd[cmd.index("--audible-public-region") + 1], "de")
        self.assertNotIn("--auth-file", cmd)
        self.assertNotIn("--provider", cmd)

    def test_an_unknown_region_falls_back_to_us(self):
        cmd, _ = build_command(_request(provider="audible-public", audible_region="zz"))
        self.assertEqual(cmd[cmd.index("--audible-public-region") + 1], "us")

    def test_account_provider_still_passes_the_auth_file(self):
        cmd, _ = build_command(_request(provider="audible"))
        self.assertIn("--auth-file", cmd)
        self.assertNotIn("--audible-public-region", cmd)


if __name__ == "__main__":
    unittest.main()
