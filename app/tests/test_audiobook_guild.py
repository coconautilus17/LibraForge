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
from app.fixer.scoring import metadata_from_product, pick_best_match_for_metadata, with_local_series_name
from app.goodreads_shelves import GoodreadsPacer
from app.tests.script_loader import load_module

FIXER = load_module("fixer_v5_audiobook_guild", "scripts/audible-metadata-fixer-v5.py")

BODY = (
    '<h2 class="a-expander-content"><span>OVERVIEW:</span></h2>\n'
    "<p>Colton Davis has made Fablewild history.</p>\n"
    "<p>Can Colton keep his eidolons safe?</p>\n"
    '<p><em>Looking for the ebook?  Find it on <a href="https://ericvall.com">EricVall.com</a></em></p>'
)


def product(title, vendor="Eric Vall", series="Eidolon Master", handle=None, updated_at="2026-01-01"):
    """A products.json product."""
    return {
        "title": title, "vendor": vendor, "product_type": series, "handle": handle or title.lower().replace(" ", "-"),
        "body_html": BODY, "images": [{"src": "https://cdn.shopify.com/s/files/em2.jpg?v=1"}],
        "updated_at": updated_at, "variants": [{"price": "13.95"}],
        "tags": [f"Author_{vendor}", "Genre_Fantasy", "Genre_Portal/Isekai", "Harem_Yes Please",
                 "Narrator_Brian Kozak", "Narrator_Charlie K James", f"Series_{series}"],
    }


def page(duration):
    return f"<p><strong>Narration By:</strong> Brian Kozak<br><strong>Duration:</strong> {duration}\n</p>".encode()


def refused(url):
    return urllib.error.HTTPError(url, 429, "Too Many Requests", {}, None)


class FakeStore:
    """Answers the store's URLs from a canned catalog; records every request."""

    def __init__(self, catalog=(), durations=None, fail=False, refuse=()):
        self.catalog, self.durations, self.fail, self.refuse = list(catalog), durations or {}, fail, set(refuse)
        self.urls = []

    def __call__(self, url, timeout):
        self.urls.append(url)
        if self.fail:
            raise refused(url)
        if "/products.json" in url:
            page_no = int(url.rsplit("page=", 1)[1])
            chunk = self.catalog[(page_no - 1) * guild.PAGE_SIZE:page_no * guild.PAGE_SIZE]
            return json.dumps({"products": chunk}).encode()
        handle = url.rsplit("/products/", 1)[1]
        if handle in self.refuse:
            raise refused(url)
        return page(self.durations.get(handle, "9 Hours, 43 Minutes"))

    def pages(self):
        return [u.rsplit("/products/", 1)[1] for u in self.urls if "/products/" in u]


def setUpModule():
    # A failed request is tried again after a wait: none in tests.
    patcher = mock.patch.object(guild, "RETRY_WAIT_S", 0)
    patcher.start()
    unittest.addModuleCleanup(patcher.stop)


def pacer():
    return GoodreadsPacer(gap_s=0, sleep=lambda _s: None)


class GuildTestCase(unittest.TestCase):
    """A fresh catalog in a temporary cache file for each test."""

    def setUp(self):
        guild._CATALOG = None
        self.addCleanup(setattr, guild, "_CATALOG", None)
        self.cache = Path(tempfile.mkdtemp()) / "catalog.json"

    def search(self, store, title, author="Eric Vall", **kwargs):
        return guild.search_books(title, author, pacer=pacer(), http_get=store, cache_path=self.cache, **kwargs)


class StoreCatalogTests(GuildTestCase):
    def catalog(self, store, **kwargs):
        return guild.store_catalog(pacer=pacer(), http_get=store, cache_path=self.cache, **kwargs)

    def test_every_book_across_the_catalog_pages_except_the_stores_own(self):
        catalog = [product(f"Book {i}", vendor="Eric Vall") for i in range(guild.PAGE_SIZE)]
        catalog += [product("Arena", vendor="Logan Jacobs"), product("Gift Card", vendor="Audiobook Guild")]
        store = FakeStore(catalog=catalog)
        self.assertEqual(guild.store_authors(pacer=pacer(), http_get=store, cache_path=self.cache),
                         ["Eric Vall", "Logan Jacobs"])
        self.assertEqual(sum("/products.json" in u for u in store.urls), 2)
        kept = json.loads(self.cache.read_text())["products"]
        self.assertEqual(len(kept), guild.PAGE_SIZE + 1)
        self.assertNotIn("variants", kept[0])  # only what the matcher reads

    def test_a_catalog_under_a_week_old_is_used_without_asking_the_store(self):
        self.cache.write_text(json.dumps({"read_at": 1000.0, "products": [guild._slim(product("Eidolon Master"))]}))
        store = FakeStore()
        found = self.catalog(store, clock=lambda: 1000.0 + 6 * 24 * 3600)
        self.assertEqual(([p["title"] for p in found["products"]], store.urls), (["Eidolon Master"], []))

    def test_an_old_catalog_is_kept_when_the_store_cannot_be_read(self):
        self.cache.write_text(json.dumps({"read_at": 0.0, "products": [guild._slim(product("Eidolon Master"))]}))
        store = FakeStore(fail=True)
        found = self.catalog(store, clock=lambda: 30 * 24 * 3600.0)
        self.assertEqual([p["title"] for p in found["products"]], ["Eidolon Master"])
        self.assertTrue(store.urls)

    def test_a_refresh_keeps_the_runtimes_of_the_books_the_store_has_not_changed(self):
        old = [product("Metal Mage 1", series="Metal Mage"), product("Metal Mage 2", series="Metal Mage")]
        self.cache.write_text(json.dumps({
            "read_at": 0.0, "products": [guild._slim(p) for p in old],
            "runtimes": {"metal-mage-1": {"updated_at": "2026-01-01", "minutes": 500},
                         "metal-mage-2": {"updated_at": "2026-01-01", "minutes": 400}}}))
        store = FakeStore(catalog=[old[0], product("Metal Mage 2", series="Metal Mage", updated_at="2026-02-01")])
        found = self.catalog(store, clock=lambda: 30 * 24 * 3600.0)
        self.assertEqual(found["runtimes"], {"metal-mage-1": {"updated_at": "2026-01-01", "minutes": 500}})

    def test_no_catalog_at_all_is_no_author(self):
        with mock.patch.object(guild, "CATALOG_CACHE", self.cache), mock.patch.object(guild, "PACER", pacer()):
            with mock.patch.object(guild, "_default_http_get", FakeStore(fail=True)):
                self.assertFalse(guild.is_store_author("Eric Vall"))
        self.assertIsNone(guild._CATALOG)  # the next book asks again

    def test_is_store_author_reads_names_the_way_the_matcher_does(self):
        guild._CATALOG = {"products": [guild._slim(product("A", vendor="Eric Vall")),
                                       guild._slim(product("B", vendor="Michael-Scott Earle"))], "runtimes": {}}
        self.assertTrue(guild.is_store_author("Eric Vall"))
        self.assertTrue(guild.is_store_author("Michael Scott Earle"))
        self.assertFalse(guild.is_store_author("Brandon Sanderson"))
        self.assertFalse(guild.is_store_author(""))


class SearchBooksTests(GuildTestCase):
    def test_a_product_becomes_a_match_with_its_series_number_narrators_and_runtime(self):
        found = self.search(FakeStore(catalog=[product("Eidolon Master 2")]), "Eidolon Master 2")
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
        store = FakeStore(catalog=[scholomance("Scholomance: The Devil's Academy"),
                                   scholomance("Scholomance 6: The Devil's Academy"),
                                   product("Tamer: King of Dinosaurs 11", vendor="Logan Jacobs",
                                           series="Tamer: King of Dinosaurs")])
        found = self.search(store, "Devil's Academy", author="Logan Jacobs")
        self.assertEqual([m["series"] for m in found["matches"]],
                         [[{"series": "Scholomance", "sequence": "1"}],
                          [{"series": "Scholomance", "sequence": "6"}]])

    def test_a_series_whose_books_carry_no_subtitle_is_the_name_alone(self):
        names = guild.series_names([{"title": "Werepanther 2", "product_type": "Werepanther: Paranormal Hunter"},
                                    {"title": "The OP MC 11", "product_type": "The OP MC: God of Winning"}])
        self.assertEqual(names, {"Werepanther: Paranormal Hunter": "Werepanther", "The OP MC: God of Winning": "The OP MC"})

    def test_the_books_own_number_is_fetched_first(self):
        # Every book of the series shares the title searched for.
        store = FakeStore(catalog=[product(f"Scholomance {n}: The Devil's Academy", vendor="Logan Jacobs",
                                           series="Scholomance: The Devil's Academy") for n in (6, 11, 12, 5)])
        found = self.search(store, "The Devil's Academy", author="Logan Jacobs", number="5", limit=1)
        self.assertEqual([m["title"] for m in found["matches"]], ["Scholomance 5: The Devil's Academy"])
        self.assertEqual(store.pages(), ["scholomance-5%3A-the-devil%27s-academy"])

    def test_the_whole_series_is_searched_not_the_first_ten_results(self):
        store = FakeStore(catalog=[product(f"Dragon Emperor {n}", series="Dragon Emperor") for n in range(22, 0, -1)])
        found = self.search(store, "Dragon Emperor", series="Dragon Emperor", number="8")
        self.assertEqual([m["title"] for m in found["matches"]], ["Dragon Emperor 8"])

    def test_the_series_finds_a_book_its_title_does_not(self):
        store = FakeStore(catalog=[product("Protect. Procreate. Prevail", series="The Alpha"),
                                   product("Dungeon Master 2", series="Dungeon Master")])
        found = self.search(store, "The Alpha", series="The Alpha", number="1")
        self.assertEqual([m["title"] for m in found["matches"]], ["Protect. Procreate. Prevail"])

    def test_another_authors_books_and_unrelated_titles_are_never_fetched(self):
        store = FakeStore(catalog=[product("Eidolon", vendor="Warren Ellis", series="Eidolon"),
                                   product("Eidolon Master 2"), product("Succubus Lord 3", series="Succubus Lord")])
        found = self.search(store, "Eidolon Master 2")
        self.assertEqual([m["title"] for m in found["matches"]], ["Eidolon Master 2"])
        self.assertEqual(store.pages(), ["eidolon-master-2"])

    def test_nothing_close_is_not_found_without_a_page_read(self):
        store = FakeStore(catalog=[product("Succubus Lord 3", series="Succubus Lord")])
        self.assertEqual(self.search(store, "Eidolon Master 2"), {"status": "not_found", "matches": []})
        self.assertEqual(store.pages(), [])

    def test_a_runtime_is_read_once_and_kept_with_the_catalog(self):
        store = FakeStore(catalog=[product("Eidolon Master 2")])
        self.search(store, "Eidolon Master 2")
        guild._CATALOG = None  # a new run reads the cache file
        again = FakeStore(catalog=[product("Eidolon Master 2")])
        found = self.search(again, "Eidolon Master 2")
        self.assertEqual((found["matches"][0]["runtime_minutes"], again.urls), (583, []))

    def test_a_request_the_store_refuses_once_is_tried_again(self):
        store = FakeStore(catalog=[product("Eidolon Master 2")])
        answers = iter([refused("u")])

        def flaky(url, timeout):
            failure = next(answers, None)
            if failure:
                store.urls.append(url)
                raise failure
            return store(url, timeout)

        found = self.search(flaky, "Eidolon Master 2")
        self.assertEqual([m["title"] for m in found["matches"]], ["Eidolon Master 2"])
        self.assertEqual(sum("/products.json" in u for u in store.urls), 2)

    def test_an_unreadable_catalog_fails_the_search(self):
        self.assertEqual(self.search(FakeStore(fail=True), "Eidolon Master 2"), {"status": "failed", "matches": []})

    def test_a_book_page_that_cannot_be_read_fails_the_search(self):
        # Without its runtime the right book ("Summoner 6") loses to another
        # series' book 6 that the runtime would have ruled out.
        store = FakeStore(catalog=[product("Summoner 6", series="Summoner"),
                                   product("Summoner School 6", series="Summoner School")], refuse={"summoner-6"})
        found = self.search(store, "Summoner", series="Summoner", number="6")
        self.assertEqual(found, {"status": "failed", "matches": []})

    def test_runtime_in_hours_or_minutes_only(self):
        self.assertEqual(guild._runtime_minutes(page("10 Hours").decode()), 600)
        self.assertEqual(guild._runtime_minutes(page("45 Minutes").decode()), 45)
        self.assertIsNone(guild._runtime_minutes("<p>no runtime here</p>"))


class MatchingTests(GuildTestCase):
    """The store's books go through the matcher's own scoring, runtime included."""

    def products(self, durations):
        store = FakeStore(catalog=[product("Eidolon Master 2"), product("Eidolon Master")], durations=durations)
        with mock.patch.object(guild, "_default_http_get", store), mock.patch.object(guild, "PACER", pacer()), \
                mock.patch.object(guild, "CATALOG_CACHE", self.cache):
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

    def test_the_files_series_name_is_kept_with_the_stores_number(self):
        store_book = {"title": "Monster Girl Islands 2", "series": [{"title": "Monster Girl Islands", "sequence": "2"}]}
        for file_series, number, kept in (
            ("Monster Girl Islands Series", "2", "Monster Girl Islands Series"),
            ("Summoner 6", "6", "Summoner"),  # the file's series carries the book's number
            ("Okay, But Try Not to Murder Anyone, Book #8", "8", "Okay, But Try Not to Murder Anyone"),
            ("Warhammer 40000", "2", "Warhammer 40000"),  # a number of its own is the name
            ("", "2", "Monster Girl Islands"),  # nothing in the file: the store's name
        ):
            with self.subTest(file_series):
                renamed = with_local_series_name(store_book, {"series": file_series, "book_number": number})
                self.assertEqual(renamed["series"], [{"title": kept, "sequence": "2"}])

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
