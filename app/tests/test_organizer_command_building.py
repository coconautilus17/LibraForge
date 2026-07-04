import unittest

from app.main import OrganizerRunRequest, build_organizer_command


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


if __name__ == "__main__":
    unittest.main()
