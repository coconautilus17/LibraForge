"""Chapter Forge's audio preparation: ffprobe duration, per-file offsets and the
limiting/chunking used by preview runs. ffprobe/ffmpeg are replaced so the
planning (which clips, how long, which labels) is asserted without media."""
import unittest
from pathlib import Path
from unittest import mock

from app import chaptering as c


class SourceOffsetsTests(unittest.TestCase):
    def test_each_file_starts_where_the_previous_ones_ended(self):
        durations = {"/b/1.mp3": 100.0, "/b/2.mp3": 50.5, "/b/3.mp3": 10.0}
        with mock.patch.object(c, "ffprobe_duration", side_effect=lambda p: durations.get(str(p), durations.get(Path(p).as_posix()))):
            offsets = c.source_file_offsets([Path(p) for p in durations])
        expected = {str(Path(p)): off for p, off in [("/b/1.mp3", 0.0), ("/b/2.mp3", 100.0), ("/b/3.mp3", 150.5)]}
        self.assertEqual(offsets, expected)

    def test_offsets_derived_from_provided_durations_without_ffprobe(self):
        durations = {"/b/1.mp3": 40.0, "/b/2.mp3": 60.0}
        with mock.patch.object(c, "ffprobe_duration", side_effect=AssertionError("ffprobe should not be called")):
            offsets = c.source_file_offsets([Path("/b/1.mp3"), Path("/b/2.mp3")], durations=durations)
        expected = {str(Path("/b/1.mp3")): 0.0, str(Path("/b/2.mp3")): 40.0}
        self.assertEqual(offsets, expected)

class LimitedAudioFilesTests(unittest.TestCase):
    FILES = [Path("/b/1.mp3"), Path("/b/2.mp3"), Path("/b/3.mp3")]

    def run_limit(self, durations, max_seconds, chunk=0.0):
        runs = []
        with mock.patch.object(c, "ffprobe_duration", side_effect=lambda p: durations.get(str(p), durations.get(Path(p).as_posix()))), \
             mock.patch.object(c.subprocess, "run", side_effect=lambda cmd, **kw: runs.append(cmd)):
            limited, temp_dir, labels = c.limited_audio_files(self.FILES, max_seconds, chunk)
        if temp_dir is not None:
            self.addCleanup(lambda: temp_dir.exists() and __import__("shutil").rmtree(temp_dir, ignore_errors=True))
        return limited, temp_dir, labels, runs

    def args(self, cmd, flag):
        return cmd[cmd.index(flag) + 1]

    def test_whole_files_that_fit_the_budget_are_used_as_is_and_the_first_overflowing_file_is_clipped(self):
        durations = {"/b/1.mp3": 100.0, "/b/2.mp3": 100.0, "/b/3.mp3": 100.0}
        limited, temp_dir, labels, runs = self.run_limit(durations, 150.0)
        self.assertEqual(limited[0], self.FILES[0])
        self.assertEqual(len(limited), 2)
        clip = limited[1]
        self.assertEqual(clip.parent, temp_dir)
        self.assertEqual(clip.name, "clip-002-0001.wav")
        self.assertEqual(labels[str(clip)], str(Path("/b/2.mp3")))
        self.assertEqual(len(runs), 1)
        self.assertEqual(self.args(runs[0], "-t"), "50.0")                       # what remained of the budget
        self.assertEqual(self.args(runs[0], "-ss"), "0.0")
        self.assertEqual((self.args(runs[0], "-ac"), self.args(runs[0], "-ar"), self.args(runs[0], "-c:a")), ("1", "16000", "pcm_s16le"))

    def test_chunking_respects_the_overall_budget(self):
        durations = {"/b/1.mp3": 250.0, "/b/2.mp3": 100.0, "/b/3.mp3": 100.0}
        limited, _, _, runs = self.run_limit(durations, 120.0, chunk=100.0)
        self.assertEqual([self.args(r, "-t") for r in runs], ["100.0", "20.0"])
        self.assertEqual(len(limited), 2)


class AbsIndexForChapteringTests(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(c, "_ABS_CHAPTERING_INDEX_CACHE", None)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_the_index_is_built_once_and_reused_for_thirty_minutes(self):
        with mock.patch("app.enrichment.fetch_all_abs_book_items", return_value=[{"id": "1"}]) as fetch, \
             mock.patch.object(c, "build_item_index", return_value={"by_path": {}}) as build, \
             mock.patch.object(c.time, "monotonic", side_effect=[1000.0, 1000.0, 1000.0 + 1799, 1000.0 + 1801, 1000.0 + 1801]):
            first = c._abs_item_index_for_chaptering("http://abs", "k")
            second = c._abs_item_index_for_chaptering("http://abs", "k")
            third = c._abs_item_index_for_chaptering("http://abs", "k")     # 1799 s later: still fresh
            self.assertEqual(fetch.call_count, 1)
            fourth = c._abs_item_index_for_chaptering("http://abs", "k")    # 1801 s later: expired
        self.assertEqual(first, {"by_path": {}})
        self.assertIs(first, second)
        self.assertIs(first, third)
        self.assertEqual(fetch.call_count, 2)
        self.assertEqual(build.call_count, 2)
        self.assertEqual(fourth, {"by_path": {}})



class MakeFocusClipsDurationProbeTests(unittest.TestCase):
    def test_make_focus_clips_probes_each_source_file_only_once(self):
        files = [Path("/b/1.mp3"), Path("/b/2.mp3"), Path("/b/3.mp3")]
        durations = {"/b/1.mp3": 100.0, "/b/2.mp3": 100.0, "/b/3.mp3": 100.0}
        gaps = [c.SequenceGap(expected_number=1, start=10.0, end=30.0, reason="test")]
        probed_files = []

        def fake_ffprobe(p):
            probed_files.append(str(p))
            return durations.get(str(p), durations.get(Path(p).as_posix(), 100.0))

        with mock.patch.object(c, "ffprobe_duration", side_effect=fake_ffprobe), \
             mock.patch.object(c.subprocess, "run"):
            clips, temp_dir, labels, offsets, expected = c.make_focus_clips(files, gaps)
            if temp_dir is not None:
                self.addCleanup(lambda: temp_dir.exists() and __import__("shutil").rmtree(temp_dir, ignore_errors=True))

        self.assertEqual(len(probed_files), len(files))
        self.assertEqual(probed_files, [str(f) for f in files])

if __name__ == "__main__":
    unittest.main()
