"""System resource sampling and the resource guard that stops a Chapter Forge run
when the host is under pressure. /proc is replaced with fixed text so the
percentages and breach messages can be asserted exactly."""
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

from app import main

MEMINFO = """MemTotal:       16000000 kB
MemFree:         1000000 kB
MemAvailable:    4000000 kB
SwapTotal:       2000000 kB
SwapFree:        1500000 kB
Dirty:                 0 kB
"""


class ProcFiles(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def patch_proc(self, meminfo=None, stat=None):
        real_read_text = Path.read_text

        def fake(self_path, *args, **kwargs):
            if str(self_path) == "/proc/meminfo":
                if meminfo is None:
                    raise OSError("no meminfo")
                return meminfo
            if str(self_path) == "/proc/stat":
                if stat is None:
                    raise OSError("no stat")
                return stat
            return real_read_text(self_path, *args, **kwargs)
        patcher = mock.patch.object(Path, "read_text", fake)
        patcher.start()
        self.addCleanup(patcher.stop)


class ReadMeminfoTests(ProcFiles):
    def test_values_are_converted_from_kilobytes_to_bytes(self):
        self.patch_proc(meminfo=MEMINFO)
        got = main._read_meminfo()
        self.assertEqual(got["MemTotal"], 16000000 * 1024)
        self.assertEqual(got["MemAvailable"], 4000000 * 1024)
        self.assertEqual(got["SwapFree"], 1500000 * 1024)

    def test_an_unreadable_or_malformed_file_gives_an_empty_dict(self):
        self.patch_proc(meminfo=None)
        self.assertEqual(main._read_meminfo(), {})

    def test_lines_without_a_value_are_skipped_but_valid_ones_kept(self):
        self.patch_proc(meminfo="HugePages_Total:\nMemTotal: 10 kB\n")
        self.assertEqual(main._read_meminfo(), {"MemTotal": 10 * 1024})


class ReadCpuTotalsTests(ProcFiles):
    def test_total_and_idle_include_iowait(self):
        self.patch_proc(stat="cpu  10 20 30 40 5 6 7 0 0 0\ncpu0 1 2 3 4 5 6 7\n")
        total, idle = main._read_cpu_totals()
        self.assertEqual((total, idle), (10 + 20 + 30 + 40 + 5 + 6 + 7, 40 + 5))

    def test_a_short_line_counts_only_idle(self):
        self.patch_proc(stat="cpu  10 20 30 40\n")
        self.assertEqual(main._read_cpu_totals(), (100, 40))

    def test_unreadable_stat_gives_none(self):
        self.patch_proc(stat=None)
        self.assertIsNone(main._read_cpu_totals())


class SnapshotTests(ProcFiles):
    def setUp(self):
        super().setUp()
        patcher = mock.patch.object(main, "_CPU_SAMPLE_PREVIOUS", None)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_memory_and_swap_percentages_and_gigabytes(self):
        self.patch_proc(meminfo=MEMINFO, stat="cpu  0 0 0 100\n")
        snap = main.system_resource_snapshot()
        self.assertEqual(snap["memory_percent"], 75.0)             # (16 - 4) / 16
        self.assertEqual(snap["swap_percent"], 25.0)               # (2.0 - 1.5) / 2.0
        self.assertEqual(snap["memory_total_gb"], round(16000000 * 1024 / 1024 ** 3, 2))
        self.assertEqual(snap["memory_available_gb"], round(4000000 * 1024 / 1024 ** 3, 2))
        self.assertEqual(snap["swap_total_gb"], round(2000000 * 1024 / 1024 ** 3, 2))
        self.assertEqual(snap["swap_free_gb"], round(1500000 * 1024 / 1024 ** 3, 2))
        self.assertGreaterEqual(snap["cpu_cores"], 1)

    def test_no_meminfo_gives_zeros_not_a_division_error(self):
        self.patch_proc(meminfo=None, stat=None)
        snap = main.system_resource_snapshot()
        for key in ("memory_percent", "swap_percent", "memory_total_gb", "memory_available_gb", "swap_total_gb", "swap_free_gb", "cpu_percent"):
            self.assertEqual(snap[key], 0.0, key)

    def test_no_swap_reports_zero_swap_even_when_swapfree_is_listed(self):
        self.patch_proc(meminfo="MemTotal: 100 kB\nMemAvailable: 50 kB\nSwapTotal: 0 kB\nSwapFree: 0 kB\n")
        snap = main.system_resource_snapshot()
        self.assertEqual((snap["swap_percent"], snap["swap_total_gb"], snap["swap_free_gb"]), (0.0, 0.0, 0.0))

    def test_cpu_percent_is_the_busy_share_between_two_samples(self):
        self.patch_proc(meminfo=MEMINFO, stat="cpu  0 0 0 100\n")
        first = main.system_resource_snapshot()
        self.assertEqual(first["cpu_percent"], 0.0)                # nothing to compare with yet
        self.patch_proc(meminfo=MEMINFO, stat="cpu  50 0 0 150\n")  # +50 busy, +50 idle
        self.assertEqual(main.system_resource_snapshot()["cpu_percent"], 50.0)

    def test_cpu_percent_is_clamped_and_ignores_a_sample_with_no_progress(self):
        self.patch_proc(meminfo=MEMINFO, stat="cpu  10 0 0 90\n")
        main.system_resource_snapshot()
        self.patch_proc(meminfo=MEMINFO, stat="cpu  10 0 0 90\n")   # identical: total delta 0
        self.assertEqual(main.system_resource_snapshot()["cpu_percent"], 0.0)


class ResourceGuardMessageTests(unittest.TestCase):
    REQ = types.SimpleNamespace(min_memory_available_gb=2.0, max_swap_growth_percent=10.0, max_swap_percent=80.0, max_cpu_percent=90.0)

    def message(self, snapshot, baseline=None, **req):
        merged = types.SimpleNamespace(**{**vars(self.REQ), **req})
        base = {"memory_available_gb": 8.0, "swap_percent": 0.0, "cpu_percent": 10.0}
        return main.resource_guard_message({**base, **snapshot}, merged, baseline)

    def test_a_healthy_host_gives_an_empty_message(self):
        self.assertEqual(self.message({}), "")

    def test_low_available_memory_is_reported_at_and_below_the_limit(self):
        self.assertEqual(self.message({"memory_available_gb": 2.0}), "available RAM 2.0 GB <= 2.0 GB")
        self.assertEqual(self.message({"memory_available_gb": 2.01}), "")
        self.assertEqual(self.message({"memory_available_gb": 0.5}), "available RAM 0.5 GB <= 2.0 GB")

    def test_swap_growth_is_measured_against_the_baseline(self):
        self.assertEqual(self.message({"swap_percent": 25.0}, baseline={"swap_percent": 15.0}), "swap grew 10.0% >= 10.0%")
        self.assertEqual(self.message({"swap_percent": 24.9}, baseline={"swap_percent": 15.0}), "")
        self.assertEqual(self.message({"swap_percent": 5.0}, baseline={"swap_percent": 50.0}), "")        # shrinking is fine
        self.assertEqual(self.message({"swap_percent": 12.0}), "swap grew 12.0% >= 10.0%")                 # no baseline: from zero

    def test_critical_swap_is_reported_regardless_of_growth(self):
        self.assertEqual(self.message({"swap_percent": 85.0}, baseline={"swap_percent": 85.0}), "critical swap 85.0% >= 80.0%")
        self.assertEqual(self.message({"swap_percent": 80.0}, baseline={"swap_percent": 80.0}), "critical swap 80.0% >= 80.0%")
        self.assertEqual(self.message({"swap_percent": 79.9}, baseline={"swap_percent": 79.9}), "")

    def test_cpu_load_is_reported_unless_the_limit_is_a_hundred_percent(self):
        self.assertEqual(self.message({"cpu_percent": 90.0}), "CPU 90.0% >= 90.0%")
        self.assertEqual(self.message({"cpu_percent": 89.9}), "")
        self.assertEqual(self.message({"cpu_percent": 100.0}, max_cpu_percent=100.0), "")

    def test_several_breaches_are_joined_in_a_fixed_order(self):
        got = self.message({"memory_available_gb": 1.0, "swap_percent": 90.0, "cpu_percent": 95.0}, baseline={"swap_percent": 0.0})
        self.assertEqual(got, "available RAM 1.0 GB <= 2.0 GB; swap grew 90.0% >= 10.0%; critical swap 90.0% >= 80.0%; CPU 95.0% >= 90.0%")

    def test_a_missing_snapshot_key_counts_as_zero_for_the_comparison(self):
        self.assertTrue(main.resource_guard_message({}, self.REQ).startswith("available RAM "))
        self.assertEqual(main.resource_guard_message({"memory_available_gb": 9.0}, self.REQ), "")


if __name__ == "__main__":
    unittest.main()
