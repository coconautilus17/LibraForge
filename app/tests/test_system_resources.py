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


class ResourceGuardMessageTests(unittest.TestCase):
    REQ = types.SimpleNamespace(min_memory_available_gb=2.0, max_swap_growth_percent=10.0, max_swap_percent=80.0, max_cpu_percent=90.0)

    def message(self, snapshot, baseline=None, **req):
        merged = types.SimpleNamespace(**{**vars(self.REQ), **req})
        base = {"memory_available_gb": 8.0, "swap_percent": 0.0, "cpu_percent": 10.0}
        return main.resource_guard_message({**base, **snapshot}, merged, baseline)

    def test_several_breaches_are_joined_in_a_fixed_order(self):
        got = self.message({"memory_available_gb": 1.0, "swap_percent": 90.0, "cpu_percent": 95.0}, baseline={"swap_percent": 0.0})
        self.assertEqual(got, "available RAM 1.0 GB <= 2.0 GB; swap grew 90.0% >= 10.0%; critical swap 90.0% >= 80.0%; CPU 95.0% >= 90.0%")

if __name__ == "__main__":
    unittest.main()
