import io
import threading
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app import debug_trace as dt
from app.debug_trace import ALTER, CHOOSE, SCORE


class DebugTraceTest(unittest.TestCase):
    def tearDown(self):
        dt.configure(enabled=False)
        dt.set_subject(None)

    def _capture(self, **kw):
        buf = io.StringIO()
        dt.configure(enabled=True, stream=buf, **kw)
        return buf

    # --- disabled by default ---------------------------------------------------

    def test_disabled_is_passthrough_and_silent(self):
        buf = io.StringIO()
        dt.configure(enabled=False, stream=buf)

        @dt.trace(SCORE)
        def add(a, b):
            return a + b

        self.assertEqual(add(2, 3), 5)
        self.assertEqual(buf.getvalue(), "")

    def test_decorator_preserves_identity(self):
        @dt.trace(ALTER)
        def clean(value):
            "docstring stays"
            return value.strip()

        self.assertEqual(clean.__name__, "clean")
        self.assertEqual(clean.__doc__, "docstring stays")
        self.assertEqual(clean("  hi  "), "hi")

    # --- enabled ---------------------------------------------------------------

    def test_enabled_logs_enter_and_exit(self):
        buf = self._capture()

        @dt.trace(SCORE)
        def score(product, weight=1.0):
            return 0.5 * weight

        result = score("B0ABC", weight=2.0)
        out = buf.getvalue()
        self.assertEqual(result, 1.0)
        self.assertIn("-> score(", out)
        self.assertIn("product='B0ABC'", out)
        self.assertIn("weight=2.0", out)
        self.assertIn("<- score = 1.0", out)
        self.assertIn("[score]", out)

    def test_capture_limits_logged_args(self):
        buf = self._capture()

        @dt.trace(ALTER, capture=["value"])
        def transform(value, secret):
            return value

        transform("keep", "hide")
        out = buf.getvalue()
        self.assertIn("value='keep'", out)
        self.assertNotIn("hide", out)

    def test_capture_empty_logs_no_args(self):
        buf = self._capture()

        @dt.trace(ALTER, capture=[])
        def noop():
            return 42

        noop()
        out = buf.getvalue()
        self.assertIn("-> noop()", out)
        self.assertIn("<- noop = 42", out)

    def test_category_filter_include(self):
        buf = self._capture(categories=["score"])

        @dt.trace(SCORE)
        def scored():
            return 1

        @dt.trace(ALTER)
        def altered():
            return 2

        scored()
        altered()
        out = buf.getvalue()
        self.assertIn("scored", out)
        self.assertNotIn("altered", out)

    def test_exception_is_logged_and_reraised(self):
        buf = self._capture()

        @dt.trace(CHOOSE)
        def boom():
            raise ValueError("nope")

        with self.assertRaises(ValueError):
            boom()
        self.assertIn("!! boom raised", buf.getvalue())

    def test_long_string_is_truncated(self):
        buf = self._capture(max_value_len=20)

        @dt.trace(ALTER, capture=["v"])
        def fn(v):
            return v

        fn("a" * 100)
        out = buf.getvalue()
        self.assertIn("...(+", out)
        self.assertNotIn("a" * 100, out)

    def test_show_result_false_hides_return(self):
        buf = self._capture()

        @dt.trace(ALTER, show_result=False)
        def fn():
            return {"big": "data"}

        fn()
        out = buf.getvalue()
        self.assertIn("fn done", out)
        self.assertNotIn("big", out)

    # --- subject correlation ---------------------------------------------------

    def test_subject_appears_in_lines(self):
        buf = self._capture()

        @dt.trace(ALTER)
        def fn():
            return 1

        with dt.subject("MyBook"):
            fn()
        self.assertIn("[MyBook]", buf.getvalue())

    def test_subject_nests_and_restores(self):
        buf = self._capture()

        @dt.trace(ALTER)
        def fn():
            return dt.get_subject()

        with dt.subject("outer"):
            r1 = fn()
            with dt.subject("inner"):
                r2 = fn()
            r3 = fn()

        self.assertEqual(r1, "outer")
        self.assertEqual(r2, "inner")
        self.assertEqual(r3, "outer")
        self.assertIsNone(dt.get_subject())

    # --- trace_block -----------------------------------------------------------

    def test_trace_block_emits_enter_exit(self):
        buf = self._capture()

        with dt.trace_block(CHOOSE, "pick winner", n=5):
            pass

        out = buf.getvalue()
        self.assertIn("{pick winner}", out)
        self.assertIn("n=5", out)
        self.assertIn("done", out)

    def test_trace_block_logs_exception(self):
        buf = self._capture()

        with self.assertRaises(RuntimeError):
            with dt.trace_block(SCORE, "risky"):
                raise RuntimeError("oops")

        self.assertIn("!! {risky}", buf.getvalue())

    def test_trace_block_silent_when_disabled(self):
        buf = io.StringIO()
        dt.configure(enabled=False, stream=buf)

        with dt.trace_block(CHOOSE, "silent"):
            pass

        self.assertEqual(buf.getvalue(), "")

    # --- log() -----------------------------------------------------------------

    def test_log_emits_checkpoint(self):
        buf = self._capture()
        dt.log(CHOOSE, "picked query", query="some text", score=0.8)
        out = buf.getvalue()
        self.assertIn("picked query", out)
        self.assertIn("query='some text'", out)
        self.assertIn("score=0.8", out)

    def test_log_silent_when_disabled(self):
        buf = io.StringIO()
        dt.configure(enabled=False, stream=buf)
        dt.log(SCORE, "should not appear")
        self.assertEqual(buf.getvalue(), "")

    # --- summarize edge cases --------------------------------------------------

    def test_summarize_dict(self):
        buf = self._capture()

        @dt.trace(ALTER, capture=["d"])
        def fn(d):
            return d

        fn({"a": 1, "b": 2})
        self.assertIn("'a': 1", buf.getvalue())

    def test_summarize_list(self):
        buf = self._capture()

        @dt.trace(ALTER, capture=["lst"])
        def fn(lst):
            return lst

        fn([1, 2, 3])
        out = buf.getvalue()
        self.assertIn("list(len=3)", out)

    def test_summarize_none_and_bool(self):
        buf = self._capture()

        @dt.trace(ALTER, capture=["v"])
        def fn(v):
            return v

        fn(None)
        self.assertIn("v=None", buf.getvalue())

    # --- thread safety --------------------------------------------------------

    def test_thread_name_in_output(self):
        buf = self._capture()

        @dt.trace(SCORE)
        def fn():
            return 1

        results = []
        def run():
            results.append(fn())

        t = threading.Thread(target=run, name="Worker-99")
        t.start()
        t.join()

        self.assertIn("[Worker-99]", buf.getvalue())

    def test_concurrent_writes_dont_interleave(self):
        buf = self._capture()

        @dt.trace(ALTER)
        def fn(v):
            return v

        threads = [threading.Thread(target=fn, args=(i,)) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        lines = [l for l in buf.getvalue().splitlines() if l.strip()]
        # Each call emits 2 lines (enter + exit); header is 1 line
        self.assertGreaterEqual(len(lines), 40)

    # --- file sink ------------------------------------------------------------

    def test_file_sink_writes(self):
        import tempfile, os
        with tempfile.NamedTemporaryFile(mode="r", suffix=".log", delete=False) as f:
            path = f.name
        try:
            dt.configure(enabled=True, file_path=path)

            @dt.trace(SCORE)
            def fn():
                return 42

            fn()
            dt.configure(enabled=False)
            content = open(path).read()
            self.assertIn("fn", content)
        finally:
            os.unlink(path)


class SummarizeTests(unittest.TestCase):
    def test_scalars_use_repr(self):
        for value in (None, True, 3, 2.5):
            self.assertEqual(dt._summarize(value, 50), repr(value))

    def test_a_string_over_the_limit_is_cut_with_the_overflow_count(self):
        self.assertEqual(dt._summarize("abcdefghij", 10), "'abcdefghij'")
        self.assertEqual(dt._summarize("abcdefghijk", 10), "'abcdefghij...(+1)'")
        self.assertEqual(dt._summarize("x" * 25, 10), "'" + "x" * 10 + "...(+15)'")

    def test_a_dict_shows_at_most_eight_keys_with_a_more_count(self):
        eight = {i: i for i in range(8)}
        self.assertNotIn("more", dt._summarize(eight, 100))
        nine = {i: i for i in range(9)}
        self.assertTrue(dt._summarize(nine, 100).endswith(", +1 more}"))
        twelve = {i: i for i in range(12)}
        out = dt._summarize(twelve, 100)
        self.assertTrue(out.endswith(", +4 more}"))
        self.assertIn("7: 7", out)
        self.assertNotIn("8: 8", out)

    def test_nested_values_get_half_the_length_budget(self):
        out = dt._summarize({"k": "x" * 30}, 20)
        self.assertIn("'" + "x" * 10 + "...(+20)'", out)

    def test_a_list_shows_five_items_its_length_and_a_more_count(self):
        self.assertEqual(dt._summarize([1, 2, 3], 100), "list(len=3)[1, 2, 3]")
        self.assertEqual(dt._summarize([1, 2, 3, 4, 5], 100), "list(len=5)[1, 2, 3, 4, 5]")
        self.assertEqual(dt._summarize(list(range(6)), 100), "list(len=6)[0, 1, 2, 3, 4, +1 more]")
        self.assertEqual(dt._summarize(list(range(9)), 100), "list(len=9)[0, 1, 2, 3, 4, +4 more]")
        self.assertTrue(dt._summarize((1, 2), 100).startswith("tuple(len=2)"))
        self.assertTrue(dt._summarize({1}, 100).startswith("set(len=1)"))

    def test_list_items_get_half_the_length_budget(self):
        self.assertEqual(dt._summarize(["y" * 12], 20), "list(len=1)['" + "y" * 10 + "...(+2)']")

    def test_other_objects_use_a_length_limited_repr(self):
        class Thing:
            def __repr__(self):
                return "T" * 30
        self.assertEqual(dt._summarize(Thing(), 40), "T" * 30)
        self.assertEqual(dt._summarize(Thing(), 10), "T" * 10 + "...")

    def test_an_unreprable_object_never_raises(self):
        class Bad:
            def __repr__(self):
                raise RuntimeError("no")
        self.assertEqual(dt._summarize(Bad(), 40), "<unreprable Bad>")


class ConfigureEnvironmentTests(unittest.TestCase):
    def tearDown(self):
        dt.configure(enabled=False)

    def _env(self, **env):
        base = {k: v for k, v in os.environ.items() if not k.startswith("LIBRAFORGE_DEBUG")}
        base.update(env)
        return mock.patch.dict(os.environ, base, clear=True)

    def test_off_by_default(self):
        with self._env():
            dt.configure()
            self.assertIs(dt.is_enabled(), False)
            self.assertIs(dt.is_enabled(SCORE), False)

    def test_the_environment_switch_enables_tracing(self):
        for value in ("1", "true", "yes", "on"):
            with self.subTest(value=value), self._env(LIBRAFORGE_DEBUG=value):
                dt.configure(stream=io.StringIO())
                self.assertTrue(dt.is_enabled())

    def test_environment_values_meaning_off_do_not_enable(self):
        for value in ("", "0", "false", "False", "  "):
            with self.subTest(value=value), self._env(LIBRAFORGE_DEBUG=value):
                dt.configure(stream=io.StringIO())
                self.assertFalse(dt.is_enabled())

    def test_an_explicit_enable_wins_over_an_off_environment(self):
        with self._env(LIBRAFORGE_DEBUG="0"):
            dt.configure(enabled=True, stream=io.StringIO())
            self.assertTrue(dt.is_enabled())

    def test_the_categories_environment_variable_filters_when_none_are_passed(self):
        with self._env(LIBRAFORGE_DEBUG_CATEGORIES=" score , choose ,"):
            dt.configure(enabled=True, stream=io.StringIO())
            self.assertTrue(dt.is_enabled(SCORE))
            self.assertTrue(dt.is_enabled(CHOOSE))
            self.assertFalse(dt.is_enabled(ALTER))

    def test_passed_categories_beat_the_environment(self):
        with self._env(LIBRAFORGE_DEBUG_CATEGORIES="score"):
            dt.configure(enabled=True, stream=io.StringIO(), categories=[ALTER])
            self.assertTrue(dt.is_enabled(ALTER))
            self.assertFalse(dt.is_enabled(SCORE))

    def test_no_categories_means_everything_is_enabled(self):
        with self._env():
            dt.configure(enabled=True, stream=io.StringIO())
            self.assertTrue(dt.is_enabled(SCORE))
            self.assertTrue(dt.is_enabled("anything"))
            self.assertTrue(dt.is_enabled())

    def test_a_category_filter_still_enables_calls_with_no_category(self):
        with self._env():
            dt.configure(enabled=True, stream=io.StringIO(), categories=[SCORE])
            self.assertTrue(dt.is_enabled(None))

    def test_the_environment_file_receives_the_trace_and_the_header_lists_categories(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "trace.log"
            with self._env(LIBRAFORGE_DEBUG_FILE=str(target)):
                dt.configure(enabled=True, stream=io.StringIO(), categories=[SCORE, CHOOSE])
                dt.log(SCORE, "hello")
                dt.configure(enabled=False)
            text = target.read_text()
        self.assertIn("categories=['choose', 'score']", text)
        self.assertIn("hello", text)

    def test_the_header_says_all_when_unfiltered(self):
        buf = io.StringIO()
        with self._env():
            dt.configure(enabled=True, stream=buf)
        self.assertIn("categories=all", buf.getvalue())

    def test_reconfiguring_closes_the_previous_file_sink(self):
        with tempfile.TemporaryDirectory() as tmp, self._env():
            dt.configure(enabled=True, stream=io.StringIO(), file_path=str(Path(tmp) / "a.log"))
            first = dt._config.sink._fh
            dt.configure(enabled=False)
            self.assertTrue(first.closed)
            self.assertIsNone(dt._config.sink)


class SinkTests(unittest.TestCase):
    def test_an_unwritable_file_falls_back_to_stderr_only_without_a_stream(self):
        sink = dt._Sink(stream=None, file_path="/nonexistent-dir/x.log")
        self.assertIs(sink._stream, __import__("sys").stderr)
        self.assertIsNone(sink._fh)
        buf = io.StringIO()
        sink2 = dt._Sink(stream=buf, file_path="/nonexistent-dir/x.log")
        self.assertIs(sink2._stream, buf)

    def test_a_file_sink_writes_lines_and_close_releases_it_idempotently(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "t.log"
            sink = dt._Sink(stream=None, file_path=str(path))
            sink.write("one")
            sink.write("two")
            fh = sink._fh
            sink.close()
            sink.close()
            self.assertTrue(fh.closed)
            self.assertIsNone(sink._fh)
            self.assertEqual(path.read_text(), "one\ntwo\n")

    def test_a_broken_stream_never_blocks_the_file_copy(self):
        class Broken:
            def write(self, *_): raise OSError("closed")
            def flush(self): pass
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "t.log"
            sink = dt._Sink(stream=Broken(), file_path=str(path))
            sink.write("still here")
            sink.close()
            self.assertEqual(path.read_text(), "still here\n")


class TraceOutputTests(unittest.TestCase):
    def setUp(self):
        self.buf = io.StringIO()
        dt.configure(enabled=True, stream=self.buf)

    def tearDown(self):
        dt.configure(enabled=False)
        dt.set_subject(None)

    def _lines(self):
        return [line for line in self.buf.getvalue().splitlines() if not line.startswith("#")]

    def test_elapsed_time_is_reported_in_milliseconds(self):
        @dt.trace(SCORE)
        def work():
            return 1
        with mock.patch("app.debug_trace.time.perf_counter", side_effect=[10.0, 11.5]):
            work()
        self.assertTrue(self._lines()[-1].endswith("= 1  (1500.0ms)"), self._lines()[-1])

    def test_a_raising_function_logs_the_error_with_elapsed_ms_and_reraises(self):
        @dt.trace(SCORE)
        def boom():
            raise ValueError("bad")
        with mock.patch("app.debug_trace.time.perf_counter", side_effect=[1.0, 1.25]):
            with self.assertRaises(ValueError):
                boom()
        self.assertTrue(self._lines()[-1].endswith("!! boom raised ValueError('bad')  (250.0ms)"), self._lines()[-1])

    def test_show_result_false_logs_done_instead_of_the_value(self):
        @dt.trace(SCORE, show_result=False)
        def big():
            return list(range(1000))
        big()
        self.assertIn("<- big done", self._lines()[-1])
        self.assertNotIn("range", self._lines()[-1])

    def test_a_call_without_a_category_is_labelled_trace(self):
        @dt.trace()
        def f():
            return 0
        f()
        self.assertIn("[trace] -> f()", self._lines()[0])

    def test_blocks_report_elapsed_ms_for_success_and_failure(self):
        with mock.patch("app.debug_trace.time.perf_counter", side_effect=[2.0, 2.5]):
            with dt.trace_block(CHOOSE, "pick"):
                pass
        self.assertTrue(self._lines()[-1].endswith("<- {pick} done  (500.0ms)"), self._lines()[-1])
        with mock.patch("app.debug_trace.time.perf_counter", side_effect=[2.0, 2.25]):
            with self.assertRaises(KeyError):
                with dt.trace_block(CHOOSE, "pick"):
                    raise KeyError("k")
        self.assertTrue(self._lines()[-1].endswith("!! {pick} raised KeyError('k')  (250.0ms)"), self._lines()[-1])

    def test_a_block_without_a_category_is_labelled_trace_and_shows_its_fields(self):
        with dt.trace_block(None, "step", n=3, text="x" * 400):
            pass
        first = self._lines()[0]
        self.assertIn("[trace] -> {step}(n=3, text='", first)
        self.assertIn("...(+250)'", first)   # 300 default / 2 = 150 budget

    def test_log_lines_carry_the_category_message_and_summarised_fields(self):
        dt.log(SCORE, "checkpoint", a=1, b="x" * 400)
        line = self._lines()[-1]
        self.assertIn("[score] .. checkpoint a=1, b='", line)
        self.assertIn("...(+250)'", line)

    def test_log_without_fields_has_no_trailing_text(self):
        dt.log(None, "just a note")
        self.assertTrue(self._lines()[-1].endswith("[trace] .. just a note"))

    def test_captured_argument_values_share_the_length_budget(self):
        @dt.trace(ALTER, capture=["value"])
        def clean(value, other):
            return value
        clean("q" * 400, "o")
        entry = self._lines()[0]
        self.assertIn("value='", entry)
        self.assertNotIn("other", entry)
        self.assertIn("...(+250)'", entry)

    def test_lines_are_prefixed_with_the_thread_and_subject(self):
        @dt.trace(SCORE)
        def f():
            return 0
        with dt.subject("My Book"):
            f()
        self.assertIn("][My Book] [score] -> f()", self._lines()[0])
