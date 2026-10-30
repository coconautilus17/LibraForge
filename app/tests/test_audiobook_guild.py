"""Audiobook Guild: a store selling a short list of self-published authors'
audiobooks, with series, narrators and runtime. A book by one of its authors
is matched there first, and a full match there is final (no Audible search)."""
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

from app import audiobook_guild as guild
from app.fixer import search
from app.fixer.scoring import metadata_from_product, pick_best_match_for_metadata
from app.goodreads_shelves import GoodreadsPacer
from app.tests.script_loader import load_module

FIXER = load_module("fixer_v5_audiobook_guild", "scripts/audible-metadata-fixer-v5.py")

BODY = (
    '<h2 class="a-expander-content"><span>OVERVIEW:</span></h2>\n'
    "<p>Colton Davis has made Fablewild history.</p>\n"
    "<p>Can Colton keep his eidolons safe?</p>\n"
    '<p><em>Looking for the ebook?  Find it on <a href="https://ericvall.com">EricVall.com</a></em></p>'
)


def product(title, vendor="Eric Vall", series="Eidolon Master", handle=None):
    return {
        "title": title, "vendor": vendor, "type": series, "handle": handle or title.lower().replace(" ", "-"),
        "body": BODY, "image": "https://cdn.shopify.com/s/files/em2.jpg?v=1",
        "tags": [f"Author_{vendor}", "Genre_Fantasy", "Genre_Portal/Isekai", "Harem_Yes Please",
                 "Narrator_Brian Kozak", "Narrator_Charlie K James", f"Series_{series}"],
    }


def page(duration):
    return f"<p><strong>Narration By:</strong> Brian Kozak<br><strong>Duration:</strong> {duration}\n</p>".encode()


class FakeStore:
    """Answers the store's URLs from canned products; records every request."""

    def __init__(self, found=(), catalog=(), durations=None, fail=False):
        self.found, self.catalog, self.durations, self.fail = list(found), list(catalog), durations or {}, fail
        self.urls = []

    def __call__(self, url, timeout):
        self.urls.append(url)
        if self.fail:
            raise urllib.error.HTTPError(url, 429, "Too Many Requests", {}, None)
        if "/search/suggest.json" in url:
            return json.dumps({"resources": {"results": {"products": self.found}}}).encode()
        if "/products.json" in url:
            page_no = int(url.rsplit("page=", 1)[1])
            chunk = self.catalog[(page_no - 1) * guild.PAGE_SIZE:page_no * guild.PAGE_SIZE]
            return json.dumps({"products": chunk}).encode()
        handle = url.rsplit("/products/", 1)[1]
        return page(self.durations.get(handle, "9 Hours, 43 Minutes"))


def setUpModule():
    # A failed request is tried again after a wait: none in tests.
    patcher = mock.patch.object(guild, "RETRY_WAIT_S", 0)
    patcher.start()
    unittest.addModuleCleanup(patcher.stop)


def pacer():
    return GoodreadsPacer(gap_s=0, sleep=lambda _s: None)


class StoreAuthorsTests(unittest.TestCase):
    def setUp(self):
        guild._AUTHORS = None
        self.addCleanup(setattr, guild, "_AUTHORS", None)
        self.cache = Path(tempfile.mkdtemp()) / "authors.json"

    def test_every_vendor_across_the_catalog_pages_except_the_store_itself(self):
        catalog = [product(f"Book {i}", vendor="Eric Vall") for i in range(guild.PAGE_SIZE)]
        catalog += [product("Arena", vendor="Logan Jacobs"), product("Gift Card", vendor="Audiobook Guild")]
        store = FakeStore(catalog=catalog)
        authors = guild.store_authors(pacer=pacer(), http_get=store, cache_path=self.cache)
        self.assertEqual(authors, ["Eric Vall", "Logan Jacobs"])
        self.assertEqual(sum("/products.json" in u for u in store.urls), 2)
        self.assertEqual(json.loads(self.cache.read_text())["authors"], ["Eric Vall", "Logan Jacobs"])

    def test_a_list_under_a_week_old_is_used_without_asking_the_store(self):
        self.cache.write_text(json.dumps({"read_at": 1000.0, "authors": ["Eric Vall"]}))
        store = FakeStore()
        authors = guild.store_authors(pacer=pacer(), http_get=store, cache_path=self.cache,
                                      clock=lambda: 1000.0 + 6 * 24 * 3600)
        self.assertEqual((authors, store.urls), (["Eric Vall"], []))

    def test_an_old_list_is_kept_when_the_store_cannot_be_read(self):
        self.cache.write_text(json.dumps({"read_at": 0.0, "authors": ["Eric Vall"]}))
        store = FakeStore(fail=True)
        authors = guild.store_authors(pacer=pacer(), http_get=store, cache_path=self.cache,
                                      clock=lambda: 30 * 24 * 3600.0)
        self.assertEqual(authors, ["Eric Vall"])
        self.assertTrue(store.urls)

    def test_no_list_at_all_is_no_author(self):
        with mock.patch.object(guild, "AUTHORS_CACHE", self.cache), mock.patch.object(guild, "PACER", pacer()):
            with mock.patch.object(guild, "_default_http_get", FakeStore(fail=True)):
                self.assertFalse(guild.is_store_author("Eric Vall"))
        self.assertIsNone(guild._AUTHORS)  # the next book asks again

    def test_is_store_author_reads_names_the_way_the_matcher_does(self):
        guild._AUTHORS = ["Eric Vall", "Michael-Scott Earle"]
        self.assertTrue(guild.is_store_author("Eric Vall"))
        self.assertTrue(guild.is_store_author("Michael Scott Earle"))
        self.assertFalse(guild.is_store_author("Brandon Sanderson"))
        self.assertFalse(guild.is_store_author(""))


class SearchBooksTests(unittest.TestCase):
    def test_a_product_becomes_a_match_with_its_series_number_narrators_and_runtime(self):
        store = FakeStore(found=[product("Eidolon Master 2")])
        found = guild.search_books("Eidolon Master 2", "Eric Vall", pacer=pacer(), http_get=store)
        self.assertEqual(found["status"], "found")
        m = found["matches"][0]
        self.assertEqual((m["title"], m["author"]), ("Eidolon Master 2", "Eric Vall"))
        self.assertEqual(m["series"], [{"series": "Eidolon Master", "sequence": "2"}])
        self.assertEqual(m["narrator"], "Brian Kozak, Charlie K James")
        self.assertEqual(m["runtime_minutes"], 583)
        self.assertEqual(m["genres"], ["Fantasy", "Portal/Isekai"])
        self.assertEqual(m["cover"], "https://cdn.shopify.com/s/files/em2.jpg")
        self.assertEqual(m["description"], "Colton Davis has made Fablewild history.\n\nCan Colton keep his eidolons safe?")

    def test_the_title_that_is_the_series_alone_is_book_one(self):
        self.assertEqual(guild._sequence("Eidolon Master", "Eidolon Master"), "1")
        self.assertEqual(guild._sequence("Metal Mage 13", "Metal Mage"), "13")
        self.assertEqual(guild._sequence("King of Superheroes - Book 2", "King of Superheroes"), "2")
        self.assertEqual(guild._sequence("Vampire Lord 6: Conquering a Bloodthirsty Earth",
                                         "Vampire Lord: Conquering a Bloodthirsty Earth"), "6")
        self.assertEqual(guild._sequence("Soulstone: Oblivion", "Soulstone"), "")

    def test_a_series_named_with_its_books_shared_subtitle_is_the_name_alone(self):
        def scholomance(title):
            return product(title, vendor="Logan Jacobs", series="Scholomance: The Devil's Academy")
        store = FakeStore(found=[scholomance("Scholomance: The Devil's Academy"),
                                 scholomance("Scholomance 6: The Devil's Academy"),
                                 product("Tamer: King of Dinosaurs 11", vendor="Logan Jacobs",
                                         series="Tamer: King of Dinosaurs")])
        found = guild.search_books("Devil", "Logan Jacobs", pacer=pacer(), http_get=store)
        self.assertEqual([m["series"] for m in found["matches"]],
                         [[{"series": "Scholomance", "sequence": "1"}],
                          [{"series": "Scholomance", "sequence": "6"}],
                          [{"series": "Tamer: King of Dinosaurs", "sequence": "11"}]])

    def test_a_series_whose_books_carry_no_subtitle_is_the_name_alone(self):
        names = guild.series_names([{"title": "Werepanther 2", "type": "Werepanther: Paranormal Hunter"},
                                    {"title": "The OP MC 11", "type": "The OP MC: God of Winning"}])
        self.assertEqual(names, {"Werepanther: Paranormal Hunter": "Werepanther", "The OP MC: God of Winning": "The OP MC"})

    def test_the_books_own_number_is_fetched_first(self):
        # Every book of the series shares the title searched for.
        found = [product(f"Scholomance {n}: The Devil's Academy", vendor="Logan Jacobs",
                         series="Scholomance: The Devil's Academy") for n in (6, 11, 12, 5)]
        store = FakeStore(found=found)
        result = guild.search_books("The Devil's Academy", "Logan Jacobs", number="5", pacer=pacer(),
                                    http_get=store, limit=1)
        self.assertEqual([m["title"] for m in result["matches"]], ["Scholomance 5: The Devil's Academy"])

    def test_series_and_number_are_searched_before_the_title(self):
        # The store returns 10 results: "Dragon Emperor" alone can miss book 8.
        class ByQuery(FakeStore):
            def __call__(self, url, timeout):
                if "/search/suggest.json" in url:
                    self.found = [product("Dragon Emperor 8", series="Dragon Emperor")] if "8" in url else \
                        [product(f"Dragon Emperor {n}", series="Dragon Emperor") for n in (15, 14, 13)]
                return super().__call__(url, timeout)
        store = ByQuery()
        found = guild.search_books("Dragon Emperor", "Eric Vall", series="Dragon Emperor", number="8",
                                   pacer=pacer(), http_get=store)
        self.assertEqual([m["title"] for m in found["matches"]], ["Dragon Emperor 8"])
        self.assertIn("q=Dragon+Emperor+8", store.urls[0])
        self.assertEqual(sum("/search/suggest.json" in u for u in store.urls), 1)

    def test_another_authors_results_are_never_fetched(self):
        store = FakeStore(found=[product("Eidolon", vendor="Warren Ellis"), product("Eidolon Master 2")])
        found = guild.search_books("Eidolon", "Eric Vall", pacer=pacer(), http_get=store)
        self.assertEqual([m["title"] for m in found["matches"]], ["Eidolon Master 2"])
        self.assertFalse(any("/products/eidolon" == u.rsplit("audiobookguild.com", 1)[1] for u in store.urls))

    def test_a_request_the_store_refuses_once_is_tried_again(self):
        store = FakeStore(found=[product("Eidolon Master 2")])
        answers = iter([urllib.error.HTTPError("u", 429, "Too Many Requests", {}, None)])

        def flaky(url, timeout):
            failure = next(answers, None)
            if failure:
                store.urls.append(url)
                raise failure
            return store(url, timeout)

        found = guild.search_books("Eidolon Master 2", "Eric Vall", pacer=pacer(), http_get=flaky)
        self.assertEqual([m["title"] for m in found["matches"]], ["Eidolon Master 2"])
        self.assertEqual(sum("/search/suggest.json" in u for u in store.urls), 2)

    def test_a_failed_search_is_failed_not_not_found(self):
        found = guild.search_books("Eidolon Master 2", "Eric Vall", pacer=pacer(), http_get=FakeStore(fail=True))
        self.assertEqual(found, {"status": "failed", "matches": []})

    def test_a_book_page_that_cannot_be_read_fails_the_search(self):
        # Without its runtime the right book ("Summoner 6") loses to another
        # series' book 6 that the runtime would have ruled out.
        def refuse_summoner_6(url, timeout):
            if url.endswith("/products/summoner-6"):
                raise urllib.error.HTTPError(url, 429, "Too Many Requests", {}, None)
            return store(url, timeout)
        store = FakeStore(found=[product("Summoner 6", series="Summoner"),
                                 product("Summoner School 6", series="Summoner School")])
        found = guild.search_books("Summoner", "Eric Vall", series="Summoner", number="6", pacer=pacer(),
                                   http_get=refuse_summoner_6)
        self.assertEqual(found, {"status": "failed", "matches": []})

    def test_runtime_in_hours_or_minutes_only(self):
        self.assertEqual(guild._runtime_minutes(page("10 Hours").decode()), 600)
        self.assertEqual(guild._runtime_minutes(page("45 Minutes").decode()), 45)
        self.assertIsNone(guild._runtime_minutes("<p>no runtime here</p>"))


class MatchingTests(unittest.TestCase):
    """The store's books go through the matcher's own scoring, runtime included."""

    def products(self, durations):
        store = FakeStore(found=[product("Eidolon Master 2"), product("Eidolon Master")], durations=durations)
        with mock.patch.object(guild, "_default_http_get", store), mock.patch.object(guild, "PACER", pacer()):
            return search.audiobook_guild_search("Eidolon Master 2", "Eric Vall", limit=10, existing_asin="")

    def test_book_two_matches_book_two_in_full_with_the_store_fields(self):
        products = self.products({"eidolon-master-2": "9 Hours, 43 Minutes", "eidolon-master": "10 Hours, 20 Minutes"})
        clues = {"title": "Eidolon Master 2", "author": "Eric Vall", "series": "Eidolon Master",
                 "book_number": "2", "book_number_source": "path"}
        candidate, score, _ambiguity = pick_best_match_for_metadata(clues, products, 582.2)
        self.assertEqual(candidate["title"], "Eidolon Master 2")
        self.assertGreaterEqual(score, 0.7)
        metadata = metadata_from_product(candidate, clues, score)
        self.assertEqual(metadata["edit_mode"], "full")
        self.assertEqual((metadata["series"], metadata["sequence"]), ("Eidolon Master", "2"))
        self.assertEqual(metadata["narrator"], "Brian Kozak, Charlie K James")
        self.assertEqual(metadata["year"], "")  # the store has no release year

    def test_unlisted_asin_and_year_do_not_count_as_a_change(self):
        current = {"title": "Eidolon Master 2", "artist": "Eric Vall", "grouping": "Eidolon Master",
                   "date": "2024", "asin": "", "track": "2", "composer": "Brian Kozak, Charlie K James",
                   "genre": "Fantasy, Portal/Isekai"}
        planned = {"title": "Eidolon Master 2", "author": "Eric Vall", "series": "Eidolon Master", "sequence": "2",
                   "narrator": "Brian Kozak, Charlie K James", "genre": "Fantasy, Portal/Isekai", "year": "", "asin": ""}
        self.assertEqual(FIXER.compare_tags_for_write(current, planned, "full", "audiobookguild"), (True, []))
        self.assertEqual(FIXER.compare_tags_for_write(current, planned, "full", "")[1], ["year"])


if __name__ == "__main__":
    unittest.main()
