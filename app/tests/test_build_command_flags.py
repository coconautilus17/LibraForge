"""The exact command line build_command() hands to the Metadata Fixer for each
RunRequest setting. A flag that is dropped, duplicated or sent with the wrong
value changes what the run does to the library, so every setting is pinned."""
import unittest
from pathlib import Path
from unittest.mock import patch

from app.main import RunRequest, build_command

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
    def test_each_boolean_setting_adds_exactly_its_flag_once(self):
        for field, flag in (("apply", "--apply"), ("backup", "--backup"), ("force", "--force"),
                            ("force_original", "--force-original"), ("cover_if_missing", "--cover-if-missing"),
                            ("replace_cover", "--replace-cover"), ("metadata_json_only", "--metadata-json-only")):
            with self.subTest(field=field):
                cmd, _ = command(**{field: True})
                self.assertEqual(cmd.count(flag), 1)

    def test_skip_patterns_and_ignored_folders_are_trimmed_and_blanks_dropped(self):
        flags = pairs(command(skip_patterns=["  casual farming ", "", "   ", "x"], ignored_folders=[" . ", "@eaDir", ""])[0])
        self.assertEqual(flags["--skip-pattern"], ["casual farming", "x"])
        self.assertEqual(flags["--ignore-folder"], [".", "@eaDir"])

    def test_debug_trace_adds_its_flag_and_an_optional_file(self):
        flags = pairs(command(debug_trace=True)[0])
        self.assertIn("--debug-trace", flags)
        self.assertNotIn("--debug-trace-file", flags)
        flags = pairs(command(debug_trace=True, debug_trace_file="/tmp/t.log")[0])
        self.assertEqual(flags["--debug-trace-file"], ["/tmp/t.log"])
        self.assertNotIn("--debug-trace-file", pairs(command(debug_trace_file="/tmp/t.log")[0]))


class VersionedFlagTests(unittest.TestCase):
    def test_workers_and_delay_flags_need_version_five_and_a_positive_value(self):
        flags = pairs(command(workers=4, write_workers=2, api_delay_ms=250)[0])
        self.assertEqual((flags["--workers"], flags["--write-workers"], flags["--api-delay-ms"]), (["4"], ["2"], ["250"]))
        flags = pairs(command(workers=0, write_workers=0, api_delay_ms=0)[0])
        for absent in ("--workers", "--write-workers", "--api-delay-ms"):
            self.assertNotIn(absent, flags)
        flags = pairs(command(script_name="fixer-v4.py", workers=4, write_workers=2, api_delay_ms=250)[0])
        for absent in ("--workers", "--write-workers", "--api-delay-ms", "--abs-agg-url"):
            self.assertNotIn(absent, flags)

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
