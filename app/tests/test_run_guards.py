"""Run guards (issues #321, #322).

#322: two POST /api/runs requests in the same second started two identical
runs on the same folder. A run over the same or an overlapping folder is
refused while another is still live, including a cancelled one whose process
hasn't exited yet.

#321: a cancelled Metadata Forge run went on to probe every file in the
library for duplicate ASINs before noticing the cancel.
"""
import importlib.util
import sys
import types
import unittest
from pathlib import Path
import unittest.mock
from unittest.mock import MagicMock

ROOT = Path(__file__).parents[2]


class _Proc:
    def __init__(self, alive):
        self._alive = alive

    def poll(self):
        return None if self._alive else 0


def _state(status, target, alive=None):
    from app.main import RunState

    state = RunState(id=f"{status}-{target}")
    state.status = status
    state.target_path = target
    if alive is not None:
        state.process = _Proc(alive)
    return state


class ConflictingRunTests(unittest.TestCase):
    def conflict(self, states, target):
        from app.main import find_conflicting_run

        return find_conflicting_run({s.id: s for s in states}, target)

    def test_same_folder_while_running_conflicts(self):
        running = _state("running", "/audiobooks/_unorganized", alive=True)
        self.assertIs(self.conflict([running], "/audiobooks/_unorganized"), running)

    def test_queued_run_conflicts(self):
        queued = _state("queued", "/audiobooks/_unorganized")
        self.assertIs(self.conflict([queued], "/audiobooks/_unorganized"), queued)

    def test_overlapping_folders_conflict_both_ways(self):
        parent = _state("running", "/audiobooks", alive=True)
        self.assertIs(self.conflict([parent], "/audiobooks/_unorganized/Book"), parent)
        child = _state("running", "/audiobooks/_unorganized/Book", alive=True)
        self.assertIs(self.conflict([child], "/audiobooks"), child)

    def test_cancelled_run_still_alive_conflicts(self):
        stopping = _state("cancelled", "/audiobooks/_unorganized", alive=True)
        self.assertIs(self.conflict([stopping], "/audiobooks/_unorganized"), stopping)

    def test_finished_and_unrelated_runs_do_not_conflict(self):
        done = _state("done", "/audiobooks/_unorganized", alive=False)
        exited = _state("cancelled", "/audiobooks/_unorganized", alive=False)
        other = _state("running", "/audiobooks/Dean Koontz", alive=True)
        sibling = _state("running", "/audiobooks/_unorganized2", alive=True)
        self.assertIsNone(self.conflict([done, exited, other, sibling], "/audiobooks/_unorganized"))


try:
    import audible  # noqa: F401
except ModuleNotFoundError:
    stub = types.ModuleType("audible")
    stub.Client = type("Client", (), {})
    stub.Authenticator = type("Authenticator", (), {})
    sys.modules["audible"] = stub


def _load_fixer():
    spec = importlib.util.spec_from_file_location("fixer_v5_run_guards", ROOT / "scripts/audible-metadata-fixer-v5.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class CancelSkipsDuplicateScanTests(unittest.TestCase):
    def setUp(self):
        self.fixer = _load_fixer()
        matched = MagicMock(status="matched", asin_conflict=False, metadata={"asin": "B0TEST0001"})
        self.results = [matched]

    def tearDown(self):
        self.fixer._cancel_requested = False

    def test_matched_results_need_the_duplicate_scan(self):
        self.assertTrue(self.fixer.needs_duplicate_asin_check(self.results))

    def test_cancelled_run_skips_the_duplicate_scan(self):
        self.fixer._cancel_requested = True
        self.assertFalse(self.fixer.needs_duplicate_asin_check(self.results))


class CancelExitTests(unittest.TestCase):
    """A dry run writes nothing, so a cancel ends it at once instead of
    waiting out the folder scan (103 s in a live test); a writing run still
    stops cleanly after its in-flight writes."""

    def setUp(self):
        self.fixer = _load_fixer()

    def tearDown(self):
        self.fixer._cancel_requested = False
        self.fixer._exit_on_cancel = False

    def test_dry_run_exits_immediately_on_cancel(self):
        self.fixer._exit_on_cancel = True
        with unittest.mock.patch.object(self.fixer.os, "_exit") as exit_mock:
            self.fixer._handle_sigterm(15, None)
        exit_mock.assert_called_once()

    def test_writing_run_only_flags_the_cancel(self):
        self.fixer._exit_on_cancel = False
        with unittest.mock.patch.object(self.fixer.os, "_exit") as exit_mock:
            self.fixer._handle_sigterm(15, None)
        exit_mock.assert_not_called()
        self.assertTrue(self.fixer._cancel_requested)


if __name__ == "__main__":
    unittest.main()
