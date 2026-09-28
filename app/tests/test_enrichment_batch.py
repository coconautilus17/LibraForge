"""Whole-library Enrichment Forge run: resumable, one unit at a time, results
kept as a review report until the user applies them."""
import tempfile
import unittest
from pathlib import Path

from app import enrichment_batch as eb

UNITS = [{"key": k, "name": k.upper(), "standalone": False, "book_count": 1} for k in ("a", "b", "c")]


def compiled(key):
    return {"main_genres": ["Fantasy"], "sub_genres": ["Epic Fantasy"], "pinned_genres": [], "genre_evidence": {},
            "agreement": "ok", "series_evidence": [], "explicit_summary": {}, "source_status": {
                "audible": {"found": 1}, "goodreads": {"found": 0}, "audiosilo": {"found": 1}},
            "books": [{"id": f"{key}1", "path": f"/audiobooks/{key}", "is_file": False, "title": key, "has_audio": True,
                       "existing_genres": ["Audiobook"], "explicit": {"suggestion": "explicit", "strength": "authoritative"},
                       "sources": {"audible": ["fantasy"]}},
                      {"id": f"{key}2", "path": "", "is_file": False, "title": "placeholder", "has_audio": False,
                       "existing_genres": [], "explicit": {}, "sources": {}}]}


class BatchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.store = eb.BatchStore(Path(self.tmp.name) / "batch.json")

    def test_resume_skips_done_units_and_failures_do_not_stop_the_run(self):
        calls = []

        def compile_fn(key, name):
            calls.append(key)
            if key == "b":
                raise RuntimeError("AudioSilo down")
            return compiled(key)

        eb.run_batch(self.store, UNITS, compile_fn, should_stop=lambda: False)
        data = self.store.load()
        self.assertEqual({k: u["state"] for k, u in data["units"].items()}, {"a": "compiled", "b": "failed", "c": "compiled"})
        self.assertEqual(data["units"]["b"]["error"], "AudioSilo down")
        self.assertEqual(data["status"], "done")
        self.assertEqual(data["units"]["a"]["result"]["coverage"], 2)
        eb.run_batch(self.store, UNITS, compile_fn, should_stop=lambda: False)
        self.assertEqual(calls, ["a", "b", "c", "b"])  # resume: only the failed unit is retried

    def test_stop_between_units(self):
        done = []
        eb.run_batch(self.store, UNITS, lambda k, n: done.append(k) or compiled(k), should_stop=lambda: len(done) >= 1)
        data = self.store.load()
        self.assertEqual(data["status"], "stopped")
        self.assertEqual([k for k, u in data["units"].items() if u["state"] == "compiled"], ["a"])
        self.assertEqual(data["units"]["c"]["state"], "pending")
        self.assertNotIn("current", data)  # nothing is being compiled once stopped

    def test_restart_forgets_previous_results(self):
        eb.run_batch(self.store, UNITS[:1], lambda k, n: compiled(k), should_stop=lambda: False)
        eb.run_batch(self.store, UNITS[1:], lambda k, n: compiled(k), should_stop=lambda: True, restart=True)
        self.assertEqual(sorted(self.store.load()["units"]), ["b", "c"])

    def test_apply_marks_applied_and_never_reapplies(self):
        eb.run_batch(self.store, UNITS, lambda k, n: compiled(k), should_stop=lambda: False)
        applied = []
        out = eb.apply_batch(self.store, [{"key": "a", "genres": ["Fantasy"], "apply_explicit": False}],
                             lambda book, genres, explicit: applied.append((book["id"], genres, explicit)))
        self.assertEqual(applied, [("a1", ["Fantasy"], None)])  # the no-audio placeholder is never written
        self.assertEqual((out["units"], out["books"]), (1, 1))
        self.assertEqual(self.store.load()["units"]["a"]["state"], "applied")
        again = eb.apply_batch(self.store, [{"key": "a", "genres": ["Fantasy"], "apply_explicit": False}],
                               lambda *a: applied.append(a))
        self.assertEqual((len(applied), again["skipped"]), (1, ["a"]))

    def test_apply_explicit_only_when_asked_and_authoritative(self):
        eb.run_batch(self.store, UNITS, lambda k, n: compiled(k), should_stop=lambda: False)
        seen = []
        eb.apply_batch(self.store, [{"key": "b", "genres": ["Fantasy"], "apply_explicit": True}],
                       lambda book, genres, explicit: seen.append(explicit))
        self.assertEqual(seen, [True])

    def test_apply_continues_past_a_failing_book(self):
        data = compiled("a")
        data["books"][1] = dict(data["books"][0], id="a3", title="Three")
        eb.run_batch(self.store, UNITS[:1], lambda k, n: data, should_stop=lambda: False)

        def apply_fn(book, genres, explicit):
            if book["id"] == "a1":
                raise RuntimeError("ABS 502")

        out = eb.apply_batch(self.store, [{"key": "a", "genres": ["Fantasy"], "apply_explicit": False}], apply_fn)
        self.assertEqual(out["books"], 1)
        self.assertEqual(out["failed"], [{"unit": "A", "title": "a", "error": "ABS 502"}])
        # Not "applied": a unit with failed books can be applied again.
        self.assertEqual(self.store.load()["units"]["a"]["state"], "apply_failed")
        calls = []
        eb.apply_batch(self.store, [{"key": "a", "genres": ["Fantasy"], "apply_explicit": False}],
                       lambda book, genres, explicit: calls.append(book["id"]))
        self.assertEqual(calls, ["a1", "a3"])
        self.assertEqual(self.store.load()["units"]["a"]["state"], "applied")

    def test_a_run_left_running_by_a_restart_reads_as_stopped(self):
        self.store.save({"status": "running", "units": {}, "order": []})
        self.assertEqual(eb.effective_status(self.store.load(), thread_alive=False), "stopped")


class EffectiveStatusTests(unittest.TestCase):
    """The thread is the truth: right after Start the file may still say
    idle/done (the thread hasn't saved yet), and Stop is only seen by the
    thread between units."""

    def test_alive_thread_is_running_whatever_the_file_says(self):
        for file_status in ("idle", "done", "stopped", "running"):
            self.assertEqual(eb.effective_status({"status": file_status}, thread_alive=True), "running")

    def test_stop_requested_on_a_live_thread_is_stopping(self):
        self.assertEqual(eb.effective_status({"status": "running"}, thread_alive=True, stop_requested=True), "stopping")


class ApplyCallbackTests(unittest.TestCase):
    def test_each_applied_unit_is_reported_with_the_books_written(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        store = eb.BatchStore(Path(tmp.name) / "b.json")
        eb.run_batch(store, UNITS[:2], lambda k, n: compiled(k), should_stop=lambda: False)
        done = []
        eb.apply_batch(store, [{"key": "a", "genres": ["Fantasy"]}, {"key": "b", "genres": ["Horror"]}],
                       lambda *a: None, on_unit_done=lambda entry, ids, genres: done.append((entry["name"], ids, genres)))
        self.assertEqual(done, [("A", ["a1"], ["Fantasy"]), ("B", ["b1"], ["Horror"])])


class DegradedAndConcurrencyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.store = eb.BatchStore(Path(self.tmp.name) / "batch.json")

    def test_units_compiled_while_a_source_was_paused_are_marked_and_recompiled(self):
        paused = compiled("a")
        paused["source_status"]["goodreads"] = {"found": 0, "skipped": 3, "rate_limited": True}
        results = {"a": paused}
        eb.run_batch(self.store, UNITS[:1], lambda k, n: results[k], should_stop=lambda: False)
        self.assertEqual(self.store.load()["units"]["a"]["result"]["degraded"], ["goodreads"])
        calls = []
        results["a"] = compiled("a")
        eb.run_batch(self.store, UNITS[:1], lambda k, n: calls.append(k) or results[k], should_stop=lambda: False)
        self.assertEqual(calls, ["a"])
        self.assertEqual(self.store.load()["units"]["a"]["result"]["degraded"], [])

    def test_the_run_never_overwrites_state_saved_by_someone_else_meanwhile(self):
        eb.run_batch(self.store, UNITS[:1], lambda k, n: compiled(k), should_stop=lambda: False)

        def compile_fn(key, name):
            if key == "b":  # while the run is busy, "a" gets applied elsewhere
                eb.apply_batch(self.store, [{"key": "a", "genres": ["Fantasy"]}], lambda *a: None)
            return compiled(key)

        eb.run_batch(self.store, UNITS, compile_fn, should_stop=lambda: False)
        self.assertEqual(self.store.load()["units"]["a"]["state"], "applied")
