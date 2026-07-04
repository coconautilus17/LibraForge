import unittest

from app.main import (
    OrganizerRunRequest,
    RunState,
    build_organizer_command,
    initial_organizer_stats,
    parse_organizer_line,
)


class OrganizerNoSidecarsPlumbingTests(unittest.TestCase):
    def test_command_omits_flag_by_default(self):
        req = OrganizerRunRequest(root_path="/audiobooks/_unorganized")
        cmd = build_organizer_command(req)
        self.assertNotIn("--acknowledge-no-sidecars", cmd)

    def test_command_includes_flag_when_acknowledged(self):
        req = OrganizerRunRequest(
            root_path="/audiobooks/_unorganized", acknowledge_no_sidecars=True
        )
        cmd = build_organizer_command(req)
        self.assertIn("--acknowledge-no-sidecars", cmd)

    def test_initial_stats_default_no_sidecars_warning_false(self):
        stats = initial_organizer_stats()
        self.assertFalse(stats["no_sidecars_warning"])

    def test_sentinel_line_sets_no_sidecars_warning(self):
        state = RunState("test")
        state.stats = initial_organizer_stats()

        parse_organizer_line(state, "NO_SIDECARS_FOUND")

        self.assertTrue(state.stats["no_sidecars_warning"])


if __name__ == "__main__":
    unittest.main()
