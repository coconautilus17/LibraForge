"""Embedded-ASIN lookups answered up to 50 to a request (#497): the book being
looked up and the next books of the run go in one catalog/products?asins=."""
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from app.fixer import search
from app.tests.script_loader import load_script

FIXER = load_script("fixer_asin_lookahead", "audible-metadata-fixer-v5.py")


class FakeCatalog:
    """catalog/products?asins= answers the ASINs it knows; a single lookup is counted apart."""

    def __init__(self, known, gate=None):
        self.known, self.gate = set(known), gate
        self.batches = []

    def get(self, path, params=None):
        if self.gate:
            self.gate.wait(5)
        asins = params["asins"].split(",")
        self.batches.append(asins)
        return {"products": [{"asin": a, "title": a} for a in asins if a in self.known]}


def lookahead(run, batch_size=50):
    """run: the ASIN of each book in run order; index is 1-based, as search_item's."""
    return search.AsinLookahead(lambda index: run[index:], batch_size)


class AsinLookaheadTests(unittest.TestCase):
    def test_the_first_lookup_also_answers_the_next_books(self):
        run = ["B01", "B02", "", "B03"]
        catalog, ahead = FakeCatalog(run), lookahead(run)
        self.assertEqual(ahead.lookup(catalog, "b01", 1)["asin"], "B01")
        self.assertEqual(ahead.lookup(catalog, "B02", 2)["asin"], "B02")
        self.assertEqual(ahead.lookup(catalog, "B03", 4)["asin"], "B03")
        self.assertEqual(catalog.batches, [["B01", "B02", "B03"]])

    def test_a_batch_holds_at_most_its_size(self):
        run = [f"B{i:02}" for i in range(7)]
        catalog, ahead = FakeCatalog(run), lookahead(run, batch_size=3)
        for index, asin in enumerate(run, start=1):
            self.assertEqual(ahead.lookup(catalog, asin, index)["asin"], asin)
        self.assertEqual([len(b) for b in catalog.batches], [3, 3, 1])

    def test_an_asin_the_batch_leaves_out_is_looked_up_on_its_own(self):
        catalog, ahead = FakeCatalog({"B02"}), lookahead(["B01", "B02"])
        with mock.patch.object(search, "audible_lookup_by_asin", return_value={"asin": "B01", "via": "single"}) as one:
            self.assertEqual(ahead.lookup(catalog, "B01", 1)["via"], "single")
            self.assertEqual(ahead.lookup(catalog, "B02", 2)["asin"], "B02")
        one.assert_called_once_with(catalog, "B01")
        self.assertEqual(len(catalog.batches), 1)

    def test_a_failed_batch_falls_back_to_single_lookups(self):
        class Down:
            def get(self, path, params=None):
                raise OSError("down")
        ahead = lookahead(["B01", "B02"])
        with mock.patch.object(search, "audible_lookup_by_asin", return_value=None) as one:
            self.assertIsNone(ahead.lookup(Down(), "B01", 1))
            self.assertIsNone(ahead.lookup(Down(), "B02", 2))
        self.assertEqual(one.call_count, 2)

    def test_a_book_whose_asin_is_on_its_way_waits_for_that_batch(self):
        run = ["B01", "B02"]
        gate = threading.Event()
        catalog, ahead = FakeCatalog(run, gate), lookahead(run)
        first = threading.Thread(target=ahead.lookup, args=(catalog, "B01", 1))
        first.start()
        while not ahead._pending:
            pass
        second = {}
        waiter = threading.Thread(target=lambda: second.update(ahead.lookup(catalog, "B02", 2)))
        waiter.start()
        gate.set()
        first.join(5), waiter.join(5)
        self.assertEqual(second["asin"], "B02")
        self.assertEqual(len(catalog.batches), 1)


class UpcomingAsinsTests(unittest.TestCase):
    def test_parsed_clues_then_the_filename_then_the_sidecar_and_never_a_probe(self):
        with tempfile.TemporaryDirectory() as root:
            parsed, named, plain = Path(root, "a.m4b"), Path(root, "b [B0NAMED001].m4b"), Path(root, "c.m4b")
            contexts = {FIXER.get_search_context_cache_key(parsed, {}): ([], {"existing_asin": "B0PARSED01"})}
            upcoming = FIXER.upcoming_asins_for_run([Path(root, "first.m4b"), parsed, named, plain], {},
                                                    contexts, threading.Lock())
            with mock.patch.object(FIXER, "load_marker", return_value={"audible": {"asin": "B0SIDECAR1"}}), \
                    mock.patch.object(FIXER, "probe_file") as probe:
                self.assertEqual(list(upcoming(1)), ["B0PARSED01", "B0NAMED001", "B0SIDECAR1"])
            probe.assert_not_called()


class PrefillSearchContextsTests(unittest.TestCase):
    def test_only_books_libraforge_has_not_processed_are_read_before_the_search(self):
        root = Path("/lib")
        fresh, processed, named = root / "A" / "a.m4b", root / "B" / "b.m4b", root / "C" / "c [B0NAMED001].m4b"
        duplicate, part1, part2 = root / "D" / "d.m4b", root / "E" / "1.mp3", root / "E" / "2.mp3"
        groups = {part1.parent: [part1, part2]}
        args = mock.Mock(workers=2, force_original=False, reprobe=False, backup=False)
        cache, read = {}, []

        def build(file_path, group_map, **kw):
            read.append(file_path)
            return [f"q {file_path.name}"], {"existing_asin": "B0FROMTAGS"}, ""
        with mock.patch.object(FIXER, "load_marker", side_effect=lambda fp: {"applied": True} if fp == processed else {}), \
                mock.patch.object(FIXER, "build_search_context", side_effect=build), \
                mock.patch.dict(FIXER.DUPLICATE_SET_FOLDERS, {duplicate.parent: "two copies"}, clear=True), \
                mock.patch("builtins.print"):
            FIXER.prefill_search_contexts([fresh, processed, named, duplicate, part1, part2], groups, args,
                                          cache, threading.Lock())
        self.assertEqual(sorted(read), [fresh, part1])
        self.assertEqual(cache[FIXER.get_search_context_cache_key(fresh, groups)][1]["existing_asin"], "B0FROMTAGS")
        self.assertIn(FIXER.get_search_context_cache_key(part2, groups), cache)  # the group, read once

    def test_a_book_whose_tags_fail_to_read_is_left_to_the_search(self):
        cache = {}
        args = mock.Mock(workers=1, force_original=False, reprobe=False, backup=False)
        with mock.patch.object(FIXER, "load_marker", return_value={}), \
                mock.patch.object(FIXER, "build_search_context", side_effect=OSError("unreadable")), \
                mock.patch("builtins.print"):
            FIXER.prefill_search_contexts([Path("/lib/A/a.m4b")], {}, args, cache, threading.Lock())
        self.assertEqual(cache, {})


if __name__ == "__main__":
    unittest.main()
