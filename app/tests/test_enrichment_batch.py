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


class SlimResultTests(unittest.TestCase):
    def test_every_field_is_carried_over_when_present(self):
        out = eb.slim_result(compiled("a") | {"pinned_genres": ["Zed"], "genre_evidence": {"Fantasy": {"audible": 1}},
                                              "series_evidence": ["pf"], "explicit_summary": {"x": 1}, "agreement": "none"})
        self.assertEqual(out["main_genres"], ["Fantasy"])
        self.assertEqual(out["sub_genres"], ["Epic Fantasy"])
        self.assertEqual(out["pinned_genres"], ["Zed"])
        self.assertEqual(out["genre_evidence"], {"Fantasy": {"audible": 1}})
        self.assertEqual(out["series_evidence"], ["pf"])
        self.assertEqual(out["explicit_summary"], {"x": 1})
        self.assertEqual(out["agreement"], "none")

    def test_missing_or_none_fields_become_empty_containers_and_agreement_defaults_ok(self):
        out = eb.slim_result({"main_genres": None, "sub_genres": None, "pinned_genres": None, "genre_evidence": None,
                              "series_evidence": None, "explicit_summary": None, "source_status": None, "books": None})
        self.assertEqual((out["main_genres"], out["sub_genres"], out["pinned_genres"]), ([], [], []))
        self.assertEqual((out["genre_evidence"], out["series_evidence"], out["explicit_summary"]), ({}, [], {}))
        self.assertEqual((out["agreement"], out["coverage"], out["degraded"], out["books"]), ("ok", 0, [], []))

    def test_coverage_counts_sources_that_found_something(self):
        out = eb.slim_result({"source_status": {"a": {"found": 3}, "b": {"found": 0}, "c": None, "d": {"found": "2"}, "e": {}}})
        self.assertEqual(out["coverage"], 2)

    def test_degraded_lists_paused_skipped_or_failed_sources_sorted(self):
        out = eb.slim_result({"source_status": {
            "z": {"rate_limited": True}, "m": {"skipped": 2}, "a": {"state": "failed"},
            "ok": {"found": 1}, "zero": {"skipped": 0}, "none": None}})
        self.assertEqual(out["degraded"], ["a", "m", "z"])

    def test_books_keep_only_the_review_fields(self):
        out = eb.slim_result(compiled("a"))
        self.assertEqual(set(out["books"][0]), {"id", "path", "is_file", "title", "has_audio", "existing_genres", "explicit"})
        self.assertEqual(out["books"][0]["id"], "a1")
        self.assertNotIn("sources", out["books"][0])


class StoreAndStateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.store = eb.BatchStore(Path(self.tmp.name) / "deep" / "batch.json")

    def test_a_missing_file_loads_as_idle_and_empty(self):
        self.assertEqual(self.store.load(), {"status": "idle", "units": {}, "order": []})

    def test_a_corrupt_file_loads_as_idle_and_empty(self):
        self.store.path.parent.mkdir(parents=True)
        self.store.path.write_text("{nope")
        self.assertEqual(self.store.load(), {"status": "idle", "units": {}, "order": []})

    def test_a_file_missing_units_or_order_gets_them_added(self):
        self.store.path.parent.mkdir(parents=True)
        self.store.path.write_text('{"status": "done"}')
        data = self.store.load()
        self.assertEqual((data["status"], data["units"], data["order"]), ("done", {}, []))

    def test_save_creates_folders_stamps_the_time_and_leaves_no_temp_file(self):
        self.store.save({"status": "idle", "units": {}, "order": []})
        self.assertEqual([p.name for p in self.store.path.parent.iterdir()], ["batch.json"])
        self.assertGreater(self.store.load()["updated_at"], 0)

    def test_save_keeps_non_ascii_names_readable(self):
        self.store.save({"units": {"k": {"name": "Böse"}}, "order": []})
        self.assertIn("Böse", self.store.path.read_text(encoding="utf-8"))

    def test_effective_status_for_a_dead_thread_follows_the_file_except_for_interrupted_runs(self):
        for saved, expected in (("running", "stopped"), ("stopping", "stopped"), ("done", "done"),
                                ("idle", "idle"), ("stopped", "stopped")):
            self.assertEqual(eb.effective_status({"status": saved}, thread_alive=False), expected)
        self.assertEqual(eb.effective_status({}, thread_alive=False), "idle")


class RunBatchDetailTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.store = eb.BatchStore(Path(self.tmp.name) / "batch.json")

    def test_progress_is_reported_one_based_with_the_unit_name(self):
        seen = []
        eb.run_batch(self.store, UNITS, lambda k, n: compiled(k), should_stop=lambda: False,
                     on_progress=lambda n, total, name: seen.append((n, total, name)))
        self.assertEqual(seen, [(1, 3, "A"), (2, 3, "B"), (3, 3, "C")])

    def test_unit_names_standalone_flag_and_counts_are_recorded(self):
        units = [{"key": "s", "name": "Solo", "standalone": True, "book_count": 4}, {"key": "t", "name": "Two"}]
        eb.run_batch(self.store, units, lambda k, n: compiled(k), should_stop=lambda: True)
        data = self.store.load()
        self.assertEqual((data["units"]["s"]["name"], data["units"]["s"]["standalone"], data["units"]["s"]["book_count"]),
                         ("Solo", True, 4))
        self.assertEqual((data["units"]["t"]["standalone"], data["units"]["t"]["book_count"]), (False, 0))
        self.assertEqual(data["order"], ["s", "t"])

    def test_a_stop_request_before_the_first_unit_compiles_nothing_and_clears_current(self):
        called = []
        eb.run_batch(self.store, UNITS, lambda k, n: called.append(k) or compiled(k), should_stop=lambda: True)
        data = self.store.load()
        self.assertEqual((called, data["status"]), ([], "stopped"))
        self.assertNotIn("current", data)

    def test_an_error_without_a_message_records_the_exception_type(self):
        def boom(k, n):
            raise KeyError()
        eb.run_batch(self.store, UNITS[:1], boom, should_stop=lambda: False)
        self.assertEqual(self.store.load()["units"]["a"]["error"], "KeyError")

    def test_a_retry_that_succeeds_clears_the_old_error(self):
        state = {"fail": True}
        def flaky(k, n):
            if state["fail"]:
                raise RuntimeError("down")
            return compiled(k)
        eb.run_batch(self.store, UNITS[:1], flaky, should_stop=lambda: False)
        state["fail"] = False
        eb.run_batch(self.store, UNITS[:1], flaky, should_stop=lambda: False)
        entry = self.store.load()["units"]["a"]
        self.assertEqual(entry["state"], "compiled")
        self.assertNotIn("error", entry)

    def test_a_unit_applied_while_the_run_was_compiling_it_is_left_alone(self):
        def compile_and_apply_meanwhile(key, name):
            eb._update(self.store, lambda d: d["units"][key].update({"state": "applied", "applied_genres": ["X"]}))
            return compiled(key)
        eb.run_batch(self.store, UNITS[:1], compile_and_apply_meanwhile, should_stop=lambda: False)
        entry = self.store.load()["units"]["a"]
        self.assertEqual((entry["state"], entry["applied_genres"]), ("applied", ["X"]))
        self.assertNotIn("result", entry)

    def test_an_apply_failed_unit_is_not_recompiled_but_a_failed_one_is(self):
        self.store.save({"status": "done", "order": ["a", "b"], "units": {
            "a": {"state": "apply_failed", "name": "A"}, "b": {"state": "failed", "name": "B"}}})
        calls = []
        eb.run_batch(self.store, UNITS[:2], lambda k, n: calls.append(k) or compiled(k), should_stop=lambda: False)
        self.assertEqual(calls, ["b"])

    def test_restart_drops_old_units_not_in_the_new_list(self):
        eb.run_batch(self.store, UNITS, lambda k, n: compiled(k), should_stop=lambda: False)
        eb.run_batch(self.store, UNITS[:1], lambda k, n: compiled(k), should_stop=lambda: False, restart=True)
        data = self.store.load()
        self.assertEqual(list(data["units"]), ["a"])
        self.assertEqual(data["order"], ["a"])


class ApplyBatchDetailTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.store = eb.BatchStore(Path(self.tmp.name) / "batch.json")
        eb.run_batch(self.store, UNITS, lambda k, n: compiled(k), should_stop=lambda: False)

    def test_placeholder_books_are_never_written_and_real_ones_get_the_genres(self):
        written = []
        out = eb.apply_batch(self.store, [{"key": "a", "genres": ["Fantasy"]}], lambda b, g, e: written.append((b["id"], g, e)))
        self.assertEqual(written, [("a1", ["Fantasy"], None)])
        self.assertEqual((out["units"], out["books"], out["failed"], out["skipped"]), (1, 1, [], []))

    def test_a_book_defaults_to_having_audio_when_the_field_is_missing(self):
        entry = self.store.load()["units"]["a"]
        entry["result"]["books"] = [{"id": "x", "title": "no flag"}]
        data = self.store.load(); data["units"]["a"] = entry; self.store.save(data)
        written = []
        eb.apply_batch(self.store, [{"key": "a", "genres": []}], lambda b, g, e: written.append(b["id"]))
        self.assertEqual(written, ["x"])

    def test_explicit_is_true_or_false_from_the_suggestion_only_when_authoritative_and_asked(self):
        def run(strength, suggestion, ask):
            data = self.store.load()
            data["units"]["a"]["state"] = "compiled"
            data["units"]["a"]["result"]["books"] = [{"id": "x", "has_audio": True,
                                                      "explicit": {"strength": strength, "suggestion": suggestion}}]
            self.store.save(data)
            got = []
            eb.apply_batch(self.store, [{"key": "a", "genres": [], "apply_explicit": ask}], lambda b, g, e: got.append(e))
            return got[0]
        self.assertIs(run("authoritative", "explicit", True), True)
        self.assertIs(run("authoritative", "not_explicit", True), False)
        self.assertIsNone(run("supporting", "explicit", True))
        self.assertIsNone(run("authoritative", "explicit", False))

    def test_failures_are_listed_with_unit_title_and_error_and_the_unit_can_be_retried(self):
        def boom(b, g, e):
            raise RuntimeError("disk full")
        out = eb.apply_batch(self.store, [{"key": "a", "genres": ["G"]}], boom)
        self.assertEqual(out["failed"], [{"unit": "A", "title": "a", "error": "disk full"}])
        self.assertEqual(self.store.load()["units"]["a"]["state"], "apply_failed")
        again = eb.apply_batch(self.store, [{"key": "a", "genres": ["G"]}], lambda b, g, e: None)
        self.assertEqual((again["units"], again["skipped"]), (1, []))
        self.assertEqual(self.store.load()["units"]["a"]["state"], "applied")

    def test_applied_genres_and_time_are_recorded(self):
        eb.apply_batch(self.store, [{"key": "a", "genres": ["G1", "G2"]}], lambda b, g, e: None)
        entry = self.store.load()["units"]["a"]
        self.assertEqual((entry["applied_genres"], entry["failures"]), (["G1", "G2"], []))
        self.assertGreater(entry["applied_at"], 0)

    def test_an_applied_unit_is_skipped_unless_forced_and_unknown_or_pending_units_are_skipped(self):
        eb.apply_batch(self.store, [{"key": "a", "genres": []}], lambda b, g, e: None)
        out = eb.apply_batch(self.store, [{"key": "a", "genres": []}, {"key": "nope", "genres": []}], lambda b, g, e: None)
        self.assertEqual((out["units"], out["skipped"]), (0, ["a", "nope"]))
        forced = eb.apply_batch(self.store, [{"key": "a", "genres": []}], lambda b, g, e: None, force=True)
        self.assertEqual(forced["units"], 1)


class MarkAppliedTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.store = eb.BatchStore(Path(self.tmp.name) / "batch.json")
        eb.run_batch(self.store, UNITS, lambda k, n: compiled(k), should_stop=lambda: False)

    def test_a_compiled_unit_becomes_applied_via_the_series_page(self):
        self.assertIs(eb.mark_applied(self.store, "a", ["G"]), True)
        entry = self.store.load()["units"]["a"]
        self.assertEqual((entry["state"], entry["applied_genres"], entry["applied_via"], entry["failures"]),
                         ("applied", ["G"], "series page", []))

    def test_every_unfinished_state_can_be_marked(self):
        for state in ("compiled", "apply_failed", "failed", "pending"):
            data = self.store.load(); data["units"]["b"]["state"] = state; self.store.save(data)
            self.assertIs(eb.mark_applied(self.store, "b", []), True, state)

    def test_an_already_applied_or_unknown_unit_is_not_changed(self):
        eb.mark_applied(self.store, "a", ["first"])
        self.assertIs(eb.mark_applied(self.store, "a", ["second"]), False)
        self.assertEqual(self.store.load()["units"]["a"]["applied_genres"], ["first"])
        self.assertIs(eb.mark_applied(self.store, "ghost", []), False)
