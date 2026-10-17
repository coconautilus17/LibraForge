"""The exact command line build_command() hands to the Metadata Fixer for each
RunRequest setting. A flag that is dropped, duplicated or sent with the wrong
value changes what the run does to the library, so every setting is pinned."""
import unittest
from pathlib import Path
from unittest.mock import patch

from app.main import RunRequest, _fixer_major_version, build_command

SCRIPT = "audible-metadata-fixer-v5.py"


def command(**over):
    base = dict(script_name=SCRIPT, target_path="/audiobooks/Book")
    base.update(over)
    with patch("app.main._get_abs_api_key", return_value=""), \
         patch("app.main.live_script_path", side_effect=lambda name, kind: Path("/app/scripts") / name), \
         patch("app.main._load_abs_agg_config", return_value={"url": "http://agg:3000"}), \
         patch("app.main._load_abs_tract_config", return_value={}):
        return build_command(RunRequest(**base))


def pairs(cmd):
    """['--a', '1', '--b'] -> {'--a': '1', '--b': None} for the flags that appear."""
    out = {}
    for index, token in enumerate(cmd):
        if token.startswith("--"):
            nxt = cmd[index + 1] if index + 1 < len(cmd) and not cmd[index + 1].startswith("--") else None
            out.setdefault(token, []).append(nxt)
    return out


class BaseCommandTests(unittest.TestCase):
    def test_the_command_starts_with_python_unbuffered_the_script_and_the_target(self):
        cmd, _ = command()
        self.assertEqual(cmd[:2], ["python", "-u"])
        self.assertTrue(cmd[2].endswith(SCRIPT))
        self.assertEqual(cmd[3], "/audiobooks/Book")

    def test_a_default_request_passes_the_auth_file_score_and_limit_defaults(self):
        flags = pairs(command()[0])
        self.assertEqual(flags["--auth-file"], ["/auth/audible-metadata.json"])
        self.assertEqual(flags["--min-score"], ["0.7"])
        self.assertEqual(flags["--limit"], ["50"])
        self.assertEqual(flags["--duration-review-threshold"], ["10.0"])
        for absent in ("--apply", "--backup", "--force", "--force-original", "--cover-if-missing", "--replace-cover",
                       "--metadata-json-only", "--restore-metadata", "--max-files", "--debug-trace",
                       "--trust-abs-metadata", "--weight-abs-metadata", "--enable-goodreads-fallback"):
            self.assertNotIn(absent, flags)

    def test_each_boolean_setting_adds_exactly_its_flag_once(self):
        for field, flag in (("apply", "--apply"), ("backup", "--backup"), ("force", "--force"),
                            ("force_original", "--force-original"), ("cover_if_missing", "--cover-if-missing"),
                            ("replace_cover", "--replace-cover"), ("metadata_json_only", "--metadata-json-only")):
            with self.subTest(field=field):
                cmd, _ = command(**{field: True})
                self.assertEqual(cmd.count(flag), 1)

    def test_restoring_replaces_the_auth_file_with_the_restore_flag(self):
        flags = pairs(command(restore_metadata=True)[0])
        self.assertIn("--restore-metadata", flags)
        self.assertNotIn("--auth-file", flags)

    def test_an_empty_auth_file_is_not_passed(self):
        self.assertNotIn("--auth-file", pairs(command(auth_file="")[0]))

    def test_numeric_limits_are_passed_only_when_set_and_max_files_only_when_positive(self):
        flags = pairs(command(min_score=None, limit=None, duration_review_threshold=None)[0])
        for absent in ("--min-score", "--limit", "--duration-review-threshold"):
            self.assertNotIn(absent, flags)
        self.assertNotIn("--max-files", pairs(command(max_files=0)[0]))
        self.assertNotIn("--max-files", pairs(command(max_files=-3)[0]))
        self.assertEqual(pairs(command(max_files=7)[0])["--max-files"], ["7"])
        self.assertEqual(pairs(command(min_score=0.0)[0])["--min-score"], ["0.0"])
        self.assertEqual(pairs(command(limit=0)[0])["--limit"], ["0"])

    def test_skip_patterns_and_ignored_folders_are_trimmed_and_blanks_dropped(self):
        flags = pairs(command(skip_patterns=["  casual farming ", "", "   ", "x"], ignored_folders=[" . ", "@eaDir", ""])[0])
        self.assertEqual(flags["--skip-pattern"], ["casual farming", "x"])
        self.assertEqual(flags["--ignore-folder"], [".", "@eaDir"])

    def test_the_returned_threshold_is_the_requests_or_ten(self):
        self.assertEqual(command(duration_review_threshold=25.0)[1], 25.0)
        self.assertEqual(command(duration_review_threshold=None)[1], 10.0)
        self.assertEqual(command(duration_review_threshold=0)[1], 10.0)

    def test_debug_trace_adds_its_flag_and_an_optional_file(self):
        flags = pairs(command(debug_trace=True)[0])
        self.assertIn("--debug-trace", flags)
        self.assertNotIn("--debug-trace-file", flags)
        flags = pairs(command(debug_trace=True, debug_trace_file="/tmp/t.log")[0])
        self.assertEqual(flags["--debug-trace-file"], ["/tmp/t.log"])
        self.assertNotIn("--debug-trace-file", pairs(command(debug_trace_file="/tmp/t.log")[0]))


class VersionedFlagTests(unittest.TestCase):
    def test_the_major_version_comes_from_the_script_name(self):
        self.assertEqual(_fixer_major_version("audible-metadata-fixer-v5.py"), 5)
        self.assertEqual(_fixer_major_version("fixer-v12.py"), 12)
        self.assertEqual(_fixer_major_version("fixer.py"), 0)

    def test_workers_and_delay_flags_need_version_five_and_a_positive_value(self):
        flags = pairs(command(workers=4, write_workers=2, api_delay_ms=250)[0])
        self.assertEqual((flags["--workers"], flags["--write-workers"], flags["--api-delay-ms"]), (["4"], ["2"], ["250"]))
        flags = pairs(command(workers=0, write_workers=0, api_delay_ms=0)[0])
        for absent in ("--workers", "--write-workers", "--api-delay-ms"):
            self.assertNotIn(absent, flags)
        flags = pairs(command(script_name="fixer-v4.py", workers=4, write_workers=2, api_delay_ms=250)[0])
        for absent in ("--workers", "--write-workers", "--api-delay-ms", "--abs-agg-url"):
            self.assertNotIn(absent, flags)

    def test_the_write_mode_is_passed_only_when_it_is_not_smart(self):
        self.assertNotIn("--write-mode", pairs(command(write_mode="smart")[0]))
        self.assertNotIn("--write-mode", pairs(command(write_mode="")[0]))
        self.assertEqual(pairs(command(write_mode="always")[0])["--write-mode"], ["always"])

    def test_the_abs_provider_choice_adds_both_provider_flags(self):
        flags = pairs(command(provider="abs", abs_provider="goodreads")[0])
        self.assertEqual((flags["--provider"], flags["--abs-provider"]), (["abs"], ["goodreads"]))
        self.assertNotIn("--provider", pairs(command(provider="audible")[0]))

    def test_the_abs_agg_url_always_comes_from_the_config(self):
        self.assertEqual(pairs(command()[0])["--abs-agg-url"], ["http://agg:3000"])

    def test_the_abs_agg_url_has_a_default_when_the_config_has_none(self):
        with patch("app.main._get_abs_api_key", return_value=""), patch("app.main._load_abs_agg_config", return_value={}), \
             patch("app.main._load_abs_tract_config", return_value={}):
            cmd, _ = build_command(RunRequest(script_name=SCRIPT))
        self.assertEqual(pairs(cmd)["--abs-agg-url"], ["http://abs-agg:3000"])

    def test_trusting_abs_wins_over_weighting_it(self):
        flags = pairs(command(trust_abs_metadata=True, weight_abs_metadata=True)[0])
        self.assertIn("--trust-abs-metadata", flags)
        self.assertNotIn("--weight-abs-metadata", flags)

    def test_abs_tract_flags_follow_the_config_and_the_fallback_switch(self):
        def run(cfg, **over):
            with patch("app.main._get_abs_api_key", return_value=""), patch("app.main._load_abs_agg_config", return_value={}), \
                 patch("app.main._load_abs_tract_config", return_value=cfg):
                return pairs(build_command(RunRequest(script_name=SCRIPT, **over))[0])
        none = run({})
        self.assertNotIn("--abs-tract-url", none)
        self.assertNotIn("--enable-goodreads-fallback", none)
        configured = run({"url": " http://tract:5555 ", "kindle_region": " uk "}, enable_goodreads_fallback=True)
        self.assertEqual(configured["--abs-tract-url"], ["http://tract:5555"])
        self.assertEqual(configured["--abs-tract-kindle-region"], ["uk"])
        self.assertIn("--enable-goodreads-fallback", configured)
        no_region = run({"url": "http://tract:5555", "kindle_region": "  "})
        self.assertNotIn("--abs-tract-kindle-region", no_region)
        self.assertNotIn("--enable-goodreads-fallback", no_region)
        fallback_without_url = run({}, enable_goodreads_fallback=True)
        self.assertIn("--enable-goodreads-fallback", fallback_without_url)
        self.assertNotIn("--abs-tract-url", fallback_without_url)


if __name__ == "__main__":
    unittest.main()
