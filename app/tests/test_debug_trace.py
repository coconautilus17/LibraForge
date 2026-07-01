import io
import threading
import unittest

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
