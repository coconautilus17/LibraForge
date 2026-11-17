"""Opus transcode (DEV / WIP): dev flag, request -> command, output parsing, planning decisions."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from app import main, opus_transcode
from app.tests.script_loader import load_script

client = TestClient(main.app)
script = load_script("opus_transcode_script", "opus-transcode.py")


def probe(**kw):
    base = {"codec": "aac", "profile": "LC", "channels": 2, "sample_rate": 44100, "kbps": 128.0,
            "duration": 36000.0, "size": int(128_000 / 8 * 36000)}
    base.update(kw)
    return base


class DevFlagTests(unittest.TestCase):
    def test_off_by_default(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(opus_transcode.DEV_FEATURES_ENV, None)
            self.assertFalse(opus_transcode.opus_transcode_enabled())
            self.assertEqual(client.get("/api/config").json()["dev_features"], [])

    def test_named_or_all_turns_it_on(self):
        for value in ("opus_transcode", " Opus_Transcode , other", "all"):
            with mock.patch.dict(os.environ, {opus_transcode.DEV_FEATURES_ENV: value}):
                self.assertTrue(opus_transcode.opus_transcode_enabled(), value)

    def test_endpoint_is_hidden_when_off(self):
        with mock.patch.dict(os.environ, {opus_transcode.DEV_FEATURES_ENV: ""}):
            res = client.post("/api/opus/runs", json={"root_path": "/x", "staging_path": "/y"})
        self.assertEqual(res.status_code, 404)

    def test_endpoint_refuses_staging_inside_the_scanned_folder(self):
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.dict(os.environ, {opus_transcode.DEV_FEATURES_ENV: "opus_transcode"}), \
                mock.patch.object(main, "AUDIOBOOKS_ROOT", Path(tmp)):
            book_dir = Path(tmp) / "books"
            book_dir.mkdir()
            res = client.post("/api/opus/runs", json={"root_path": str(book_dir), "staging_path": str(book_dir / "out")})
        self.assertEqual(res.status_code, 400)
        self.assertIn("outside", res.json()["detail"])


class CommandTests(unittest.TestCase):
    def test_defaults_are_the_tested_settings_and_dry_run(self):
        req = opus_transcode.OpusTranscodeRunRequest(root_path="/audiobooks/_unorganized", staging_path="/staging")
        cmd = opus_transcode.build_command(req, Path("/app/scripts"))
        self.assertEqual(cmd[:4], ["python3", "-u", "/app/scripts/opus-transcode.py", "/audiobooks/_unorganized"])
        args = dict(zip(cmd[4::2], cmd[5::2]))
        self.assertEqual(args["--mode"], "celt")
        self.assertEqual(args["--mono-kbps"], "32")
        self.assertEqual(args["--stereo-kbps"], "48")
        self.assertEqual(args["--src-cap-ratio"], "0.8")
        self.assertEqual(args["--frame-ms"], "60")
        self.assertNotIn("--apply", cmd)

    def test_apply_and_only_filters(self):
        req = opus_transcode.OpusTranscodeRunRequest(root_path="/a", staging_path="/s", apply=True, only=["Book 3", " ", "Dragon"])
        cmd = opus_transcode.build_command(req, Path("/app/scripts"))
        self.assertEqual(cmd[-1], "--apply")
        self.assertEqual([cmd[i + 1] for i, c in enumerate(cmd) if c == "--only"], ["Book 3", "Dragon"])

    def test_validate_rejects_bad_mode_and_frame(self):
        root, staging = Path("/a"), Path("/s")
        with self.assertRaises(ValueError):
            opus_transcode.validate_request(opus_transcode.OpusTranscodeRunRequest(root_path="/a", staging_path="/s", mode="hybrid"), root, staging)
        with self.assertRaises(ValueError):
            opus_transcode.validate_request(opus_transcode.OpusTranscodeRunRequest(root_path="/a", staging_path="/s", frame_ms=30), root, staging)

    def test_script_maps_modes_to_libopus_application(self):
        self.assertEqual(script.MODES, {"celt": "lowdelay", "auto": "audio", "voip": "voip"})
        self.assertEqual(set(script.MODES), set(opus_transcode.MODES))


class ParseLineTests(unittest.TestCase):
    def test_plan_result_and_summary_lines_fold_into_stats(self):
        stats = {}
        plan = {"key": 0, "kind": "single", "folder": "/b", "files": ["/b/x.m4b"], "action": "CONVERT", "reason": "",
                "flags": [], "source_mb": 700, "predicted_mb": 260, "sidecar": "/b/x.m4b.libraforge.json"}
        self.assertEqual(opus_transcode.parse_line(stats, "OPUS_PLAN_JSON: " + json.dumps(plan))["line"], "plan")
        self.assertNotIn("sidecar", stats["opus"]["plan"][0])
        res = {"key": 0, "folder": "/b", "out": "/s/x.m4b", "status": "verify-failed",
               "verify": {"ok": False, "duration_ok": True, "chapter_count_ok": False}}
        opus_transcode.parse_line(stats, "OPUS_RESULT_JSON: " + json.dumps(res))
        self.assertEqual(stats["opus"]["results"][0]["failed_checks"], ["chapter_count_ok", "ok"])
        opus_transcode.parse_line(stats, 'OPUS_SUMMARY_JSON: {"books": 1}')
        self.assertEqual(stats["opus"]["summary"], {"books": 1})

    def test_plain_and_broken_lines_are_ignored(self):
        stats = {}
        self.assertIsNone(opus_transcode.parse_line(stats, "PLAN CONVERT /b/x.m4b"))
        self.assertIsNone(opus_transcode.parse_line(stats, "OPUS_PLAN_JSON: {not json"))
        self.assertEqual(stats, {})


class DecideTests(unittest.TestCase):
    unit = {"files": [Path("/b/x.m4b")]}

    def decide(self, probes, sidecar=None, **settings):
        return script.decide(self.unit, probes, sidecar or {}, {**script.DEFAULTS, **settings})

    def test_ordinary_stereo_aac_is_converted_with_the_stereo_target(self):
        action, _, notes = self.decide([probe()])
        self.assertEqual(action, "CONVERT")
        self.assertEqual(notes["target_kbps"], 48)

    def test_target_is_capped_at_the_source_ratio(self):
        self.assertEqual(script.target_kbps(1, 36.0, script.DEFAULTS), 28)  # 0.8 x 36
        self.assertEqual(script.target_kbps(1, 128.0, script.DEFAULTS), 32)
        self.assertEqual(script.target_kbps(2, 5.0, script.DEFAULTS), 8)  # floor

    def test_low_bitrate_sources_are_left_alone(self):
        size = int(40_000 / 8 * 36000)
        action, reason, _ = self.decide([probe(size=size, kbps=40.0)])
        self.assertEqual(action, "LEAVE-ALONE")
        self.assertIn("40.0 kbps", reason)

    def test_small_gain_is_skipped(self):
        size = int(60_000 / 8 * 36000)  # 60 kbps source, 48k target -> 80% of the size
        self.assertEqual(self.decide([probe(size=size, kbps=60.0)])[0], "SKIP-SMALL-GAIN")
        self.assertEqual(self.decide([probe(size=size, kbps=60.0)], max_size_ratio=0.9)[0], "CONVERT")

    def test_same_policy_marker_is_done_but_new_settings_convert_again(self):
        marker = {"opus_conversion": {"status": "verified", "policy": script.policy_name(script.DEFAULTS)}}
        self.assertEqual(self.decide([probe()], marker)[0], "SKIP-DONE")
        self.assertEqual(self.decide([probe()], marker, mono_kbps=40)[0], "CONVERT")

    def test_xhe_aac_and_unreadable_files_go_to_review(self):
        self.assertEqual(self.decide([probe(profile="xHE-AAC")])[0], "REVIEW")
        self.assertEqual(self.decide([{"codec": None}])[0], "REVIEW")

    def test_opus_in_m4b_is_already_done(self):
        self.assertEqual(self.decide([probe(codec="opus")])[0], "SKIP-DONE")


if __name__ == "__main__":
    unittest.main()
