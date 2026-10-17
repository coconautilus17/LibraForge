"""Chapter Forge's audio preparation: ffprobe duration, per-file offsets and the
limiting/chunking used by preview runs. ffprobe/ffmpeg are replaced so the
planning (which clips, how long, which labels) is asserted without media."""
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

from app import chaptering as c


class FfprobeDurationTests(unittest.TestCase):
    def duration(self, stdout):
        with mock.patch.object(c.subprocess, "run", return_value=types.SimpleNamespace(stdout=stdout)):
            return c.ffprobe_duration(Path("/x.mp3"))

    def test_the_printed_seconds_are_returned(self):
        self.assertEqual(self.duration("123.456\n"), 123.456)

    def test_blank_negative_or_garbage_output_is_zero(self):
        for out in ("", None, "abc", "-5", "N/A"):
            with self.subTest(out=out):
                self.assertEqual(self.duration(out), 0.0)


class SourceOffsetsTests(unittest.TestCase):
    def test_each_file_starts_where_the_previous_ones_ended(self):
        durations = {"/b/1.mp3": 100.0, "/b/2.mp3": 50.5, "/b/3.mp3": 10.0}
        with mock.patch.object(c, "ffprobe_duration", side_effect=lambda p: durations[str(p)]):
            offsets = c.source_file_offsets([Path(p) for p in durations])
        self.assertEqual(offsets, {"/b/1.mp3": 0.0, "/b/2.mp3": 100.0, "/b/3.mp3": 150.5})

    def test_no_files_give_no_offsets(self):
        self.assertEqual(c.source_file_offsets([]), {})


class LimitedAudioFilesTests(unittest.TestCase):
    FILES = [Path("/b/1.mp3"), Path("/b/2.mp3"), Path("/b/3.mp3")]

    def run_limit(self, durations, max_seconds, chunk=0.0):
        runs = []
        with mock.patch.object(c, "ffprobe_duration", side_effect=lambda p: durations[str(p)]), \
             mock.patch.object(c.subprocess, "run", side_effect=lambda cmd, **kw: runs.append(cmd)):
            limited, temp_dir, labels = c.limited_audio_files(self.FILES, max_seconds, chunk)
        if temp_dir is not None:
            self.addCleanup(lambda: temp_dir.exists() and __import__("shutil").rmtree(temp_dir, ignore_errors=True))
        return limited, temp_dir, labels, runs

    def args(self, cmd, flag):
        return cmd[cmd.index(flag) + 1]

    def test_without_limits_the_files_are_returned_untouched_with_identity_labels(self):
        limited, temp_dir, labels, runs = self.run_limit({}, 0, 0)
        self.assertEqual((limited, temp_dir, runs), (self.FILES, None, []))
        self.assertEqual(labels, {str(p): str(p) for p in self.FILES})

    def test_whole_files_that_fit_the_budget_are_used_as_is_and_the_first_overflowing_file_is_clipped(self):
        durations = {"/b/1.mp3": 100.0, "/b/2.mp3": 100.0, "/b/3.mp3": 100.0}
        limited, temp_dir, labels, runs = self.run_limit(durations, 150.0)
        self.assertEqual(limited[0], self.FILES[0])
        self.assertEqual(len(limited), 2)
        clip = limited[1]
        self.assertEqual(clip.parent, temp_dir)
        self.assertEqual(clip.name, "clip-002-0001.wav")
        self.assertEqual(labels[str(clip)], "/b/2.mp3")
        self.assertEqual(len(runs), 1)
        self.assertEqual(self.args(runs[0], "-t"), "50.0")                       # what remained of the budget
        self.assertEqual(self.args(runs[0], "-ss"), "0.0")
        self.assertEqual((self.args(runs[0], "-ac"), self.args(runs[0], "-ar"), self.args(runs[0], "-c:a")), ("1", "16000", "pcm_s16le"))

    def test_nothing_after_the_budget_is_used(self):
        durations = {"/b/1.mp3": 100.0, "/b/2.mp3": 100.0, "/b/3.mp3": 100.0}
        limited, _, labels, _ = self.run_limit(durations, 100.0)
        self.assertEqual(limited, [self.FILES[0]])
        self.assertNotIn(str(self.FILES[1]), [v for k, v in labels.items() if k.endswith(".wav")])

    def test_a_clip_is_at_least_one_second_long(self):
        durations = {"/b/1.mp3": 100.0, "/b/2.mp3": 100.0, "/b/3.mp3": 100.0}
        _, _, _, runs = self.run_limit(durations, 100.4)
        self.assertEqual(self.args(runs[0], "-t"), "1.0")

    def test_chunking_splits_every_file_into_wav_pieces_of_the_chunk_length(self):
        durations = {"/b/1.mp3": 250.0, "/b/2.mp3": 100.0, "/b/3.mp3": 100.0}
        limited, _, labels, runs = self.run_limit(durations, 0, chunk=100.0)
        names = [p.name for p in limited]
        self.assertEqual(names[:3], ["clip-001-0001.wav", "clip-001-0002.wav", "clip-001-0003.wav"])
        self.assertEqual([self.args(r, "-ss") for r in runs[:3]], ["0.0", "100.0", "200.0"])
        self.assertEqual([self.args(r, "-t") for r in runs[:3]], ["100.0", "100.0", "50.0"])
        self.assertTrue(all(v == "/b/1.mp3" for k, v in labels.items() if "clip-001" in k))
        self.assertEqual(len(limited), 3 + 1 + 1)

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

    def test_a_failure_gives_none_and_is_not_cached(self):
        with mock.patch("app.enrichment.fetch_all_abs_book_items", side_effect=RuntimeError("down")):
            self.assertIsNone(c._abs_item_index_for_chaptering("http://abs", "k"))
        self.assertIsNone(c._ABS_CHAPTERING_INDEX_CACHE)


if __name__ == "__main__":
    unittest.main()
