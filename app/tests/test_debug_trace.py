import io
import threading
import unittest

from app import debug_trace as dt
from app.debug_trace import ALTER, CHOOSE, SCORE


class DebugTraceTest(unittest.TestCase):
    def tearDown(self):
        # Always leave tracing off so other tests / live imports are unaffected.
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
        self.assertEqual(clean("  hi "), "hi")

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

    def test_category_filter(self):
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

    def test_long_values_are_truncated(self):
        buf = self._capture(max_value_len=20)

        @dt.trace(ALTER)
        def echo(value):
            return value

        echo("x" * 500)
        out = buf.getvalue()
        self.assertIn("...", out)
        # The giant string must not be emitted in full.
        self.assertNotIn("x" * 100, out)

    def test_subject_tagging(self):
        buf = self._capture()

        @dt.trace(SCORE)
        def score():
            return 1

        with dt.subject("Dune (2021)"):
            score()
        self.assertIn("[Dune (2021)]", buf.getvalue())

    def test_dict_result_summarized_by_shape(self):
        buf = self._capture(max_value_len=200)

        @dt.trace(CHOOSE)
        def pick():
            return {f"k{i}": i for i in range(20)}

        pick()
        out = buf.getvalue()
        self.assertIn("more}", out)  # collapsed, not all 20 keys

    def test_trace_block_and_log(self):
        buf = self._capture()
        with dt.trace_block(CHOOSE, "pick winner", n=3):
            dt.log(CHOOSE, "considering", best="B0XYZ")
        out = buf.getvalue()
        self.assertIn("-> {pick winner}(n=3)", out)
        self.assertIn(".. considering best='B0XYZ'", out)
        self.assertIn("<- {pick winner} done", out)

    def test_show_result_false_hides_return(self):
        buf = self._capture()

        @dt.trace(ALTER, show_result=False)
        def writer():
            return "huge-bytes-object"

        writer()
        out = buf.getvalue()
        self.assertIn("<- writer done", out)
        self.assertNotIn("huge-bytes-object", out)

    def test_thread_safe_no_interleaved_partial_lines(self):
        buf = self._capture()

        @dt.trace(SCORE)
        def work(n):
            return n * 2

        threads = [threading.Thread(target=work, args=(i,)) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        lines = [ln for ln in buf.getvalue().splitlines() if ln and not ln.startswith("#")]
        # Each call emits an enter and an exit line; none should be blank/partial.
        self.assertEqual(len(lines), 40)
        for ln in lines:
            self.assertTrue("-> work(" in ln or "<- work =" in ln)


if __name__ == "__main__":
    unittest.main()
