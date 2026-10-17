"""Direct tests of the scoring rules in app.fixer.scoring (duration bands,
omnibus detection, number identity, year), asserting the returned values."""
import unittest
from unittest import mock

from app.fixer import scoring as s


def product(**over):
    base = {"title": "The Lost Bloodline 5", "series": [{"title": "The Lost Bloodline", "sequence": "5"}]}
    base.update(over)
    return base


class CompareDurationTests(unittest.TestCase):
    def status(self, local, audible):
        return s.compare_duration(local, audible)["status"]

    def test_the_bands_are_three_ten_and_twenty_percent_of_the_longer_side(self):
        for local, audible, expected in (
            (100, 100, "perfect"), (100, 103, "perfect"), (100, 103.1, "strong"), (100, 110, "strong"),
            (100, 111, "strong"), (100, 112, "acceptable"), (100, 125, "acceptable"), (100, 126, "mismatch"),
        ):
            with self.subTest(local=local, audible=audible):
                self.assertEqual(self.status(local, audible), expected)

    def test_the_percentage_is_taken_of_the_larger_side_in_either_direction(self):
        self.assertEqual(s.compare_duration(90, 100)["diff_percent"], 10.0)
        self.assertEqual(s.compare_duration(100, 90)["diff_percent"], 10.0)
        self.assertEqual(self.status(90, 100), "strong")

    def test_the_result_reports_rounded_minutes_and_availability(self):
        got = s.compare_duration(90.123, 100.456)
        self.assertEqual((got["available"], got["local_minutes"], got["audible_minutes"], got["diff_minutes"]),
                         (True, 90.12, 100.46, 10.33))

    def test_a_missing_side_is_unknown_and_unavailable_and_keeps_the_known_side(self):
        for local, audible in ((None, 5), (5, None), (None, None)):
            got = s.compare_duration(local, audible)
            self.assertEqual((got["available"], got["status"], got["diff_minutes"], got["diff_percent"]),
                             (False, "unknown", None, None))
        self.assertEqual(s.compare_duration(None, 5.678)["audible_minutes"], 5.68)
        self.assertIsNone(s.compare_duration(None, 5)["local_minutes"])

    def test_two_zero_durations_are_a_mismatch_not_a_division_error(self):
        self.assertEqual(self.status(0, 0), "mismatch")


class GetYearTests(unittest.TestCase):
    def test_the_first_usable_date_field_wins(self):
        self.assertEqual(s.get_year({"release_date": "2019-05-01", "issue_date": "2020-01-01"}), "2019")
        self.assertEqual(s.get_year({"release_date": "abc", "issue_date": "2020-01-01"}), "2020")
        self.assertEqual(s.get_year({"publication_datetime": "2018-02-03T00:00:00Z"}), "2018")

    def test_values_shorter_than_four_characters_are_skipped_and_nothing_gives_empty_string(self):
        self.assertEqual(s.get_year({"issue_date": "201"}), "")
        self.assertEqual(s.get_year({"issue_date": "201", "publication_datetime": "2017-01-01"}), "2017")
        self.assertEqual(s.get_year({"release_date": "2019"}), "2019")
        self.assertEqual(s.get_year({}), "")


class OmnibusTests(unittest.TestCase):
    def test_a_book_range_in_the_title_or_subtitle_marks_an_omnibus(self):
        for title, subtitle in (("Cradle Books 1 to 3", ""), ("Cradle", "Books 2 through 4")):
            with self.subTest(title=title, subtitle=subtitle):
                self.assertIs(s.is_omnibus_product(product(title=title, subtitle=subtitle, series=[])), True)

    @unittest.expectedFailure
    def test_hyphen_and_ampersand_ranges_in_the_title_should_mark_an_omnibus(self):
        # KNOWN BUG (see docs/test-audit-2026-10-16.md): is_omnibus_product runs its
        # range regex on normalize_for_match() output, which has already turned "1-3"
        # into "1 3" and dropped "&", so only "to"/"through" ranges are recognised.
        # Remove the decorator when the function reads the raw text.
        for title, subtitle in (("Cradle Book 1 & 2", ""), ("Cradle Books 1-3 Collection", ""), ("Cradle", "Books 5-7")):
            with self.subTest(title=title, subtitle=subtitle):
                self.assertIs(s.is_omnibus_product(product(title=title, subtitle=subtitle, series=[])), True)

    def test_a_series_sequence_that_is_a_range_marks_an_omnibus(self):
        self.assertIs(s.is_omnibus_product(product(title="Cradle", series=[{"title": "Cradle", "sequence": "1-3"}])), True)

    def test_ordinary_books_are_not_omnibuses(self):
        for title in ("Unsouled", "The Lost Bloodline 5", "Book 3: The Return"):
            with self.subTest(title=title):
                self.assertIs(s.is_omnibus_product(product(title=title, series=[])), False)

    def test_equal_local_and_audible_spans_match_and_different_ones_conflict(self):
        pack = product(title="Pack Books 11-12", series=[])
        self.assertEqual(s.omnibus_range_relation({"title": "Books 11-12"}, pack), "match")
        self.assertEqual(s.omnibus_range_relation({"title": "Books 13-14"}, pack), "conflict")

    def test_a_span_on_only_one_side_is_no_relation(self):
        pack = product(title="Pack Books 11-12", series=[])
        self.assertEqual(s.omnibus_range_relation({"title": "Plain"}, pack), "none")
        self.assertEqual(s.omnibus_range_relation({"title": "Books 1-2"}, product(title="Plain", series=[])), "none")

    def test_has_matching_omnibus_range_is_true_only_for_a_match(self):
        pack = product(title="Pack Books 11-12", series=[])
        self.assertIs(s.has_matching_omnibus_range({"title": "Books 11-12"}, pack), True)
        self.assertIs(s.has_matching_omnibus_range({"title": "Books 13-14"}, pack), False)


class NumberIdentityTests(unittest.TestCase):
    def test_a_title_number_the_candidate_lacks_is_a_conflict(self):
        self.assertIs(s.has_number_identity_conflict({"title": "The Lost Bloodline 2"}, product()), True)

    def test_a_shared_number_is_not_a_conflict(self):
        self.assertIs(s.has_number_identity_conflict({"title": "The Lost Bloodline 5"}, product()), False)

    def test_numbers_on_only_one_side_cannot_conflict(self):
        self.assertIs(s.has_number_identity_conflict({"title": "Plain"}, product()), False)
        self.assertIs(s.has_number_identity_conflict({"title": "The Lost Bloodline 2"}, {"title": "Plain"}), False)

    def test_a_matching_omnibus_range_overrides_a_differing_pack_number(self):
        pack = product(title="Pack Books 11-12", series=[{"title": "S", "sequence": "6"}])
        self.assertIs(s.has_number_identity_conflict({"title": "Books 11-12", "book_number": "11",
                                                      "book_number_source": "path"}, pack), False)

    def test_a_different_omnibus_range_is_always_a_conflict(self):
        pack = product(title="Pack Books 11-12", series=[])
        self.assertIs(s.has_number_identity_conflict({"title": "Books 13-14"}, pack), True)


class SeriesNumberTitleTests(unittest.TestCase):
    CLUES = {"title": "All the Skills - Book 003", "series": "All the Skills", "book_number": "3"}

    def test_series_plus_plain_n_is_generic(self):
        self.assertIs(s.is_generic_series_number_title({**self.CLUES, "title": "All the Skills 3"}), True)
        self.assertIs(s.is_generic_series_number_title({**self.CLUES, "title": "All the Skills 003"}), True)

    @unittest.expectedFailure
    def test_series_plus_book_n_should_be_generic_too(self):
        # KNOWN BUG (see docs/test-audit-2026-10-16.md): the docstring example
        # "All the Skills - Book 003" never matches, because normalize_for_match()
        # strips "Book N" from the title before the "<series> book N" pattern runs,
        # leaving only the series name. Only the "<series> N" pattern can ever fire.
        self.assertIs(s.is_generic_series_number_title(self.CLUES), True)

    def test_a_real_subtitle_or_wrong_number_or_missing_field_is_not(self):
        self.assertIs(s.is_generic_series_number_title({**self.CLUES, "title": "All the Skills Redux"}), False)
        self.assertIs(s.is_generic_series_number_title({**self.CLUES, "book_number": "4"}), False)
        for field in ("title", "series", "book_number"):
            self.assertIs(s.is_generic_series_number_title({**self.CLUES, field: ""}), False)

    def test_a_title_equal_to_the_series_is_detected_on_the_product(self):
        self.assertIs(s.product_title_equals_series({"title": "Cradle", "series": [{"title": "Cradle", "sequence": "1"}]}), True)
        self.assertIs(s.product_title_equals_series({"title": "Unsouled", "series": [{"title": "Cradle", "sequence": "1"}]}), False)
        self.assertIs(s.product_title_equals_series({"title": "Unsouled"}), False)


def side_story(title="Dominion", seq="0", dur=600, authors=("Jane Doe",), narrators=("Bob Roe",), series="Saga"):
    return {"title": title, "series": [{"title": series, "sequence": seq}], "runtime_length_min": dur,
            "authors": [{"name": a} for a in authors], "narrators": [{"name": n} for n in narrators]}


class StrongIdentityOverrideTests(unittest.TestCase):
    CLUES = {"title": "0.5 - Dominion", "author": "Jane Doe", "narrator": "Bob Roe", "series": "Saga", "book_number": "0.5"}

    def override(self, product, clues=None, minutes=600):
        return s.strong_identity_overrides_number_conflict(clues or self.CLUES, product, minutes)

    def test_matching_title_duration_and_people_overrides_the_number_conflict(self):
        self.assertIs(self.override(side_story()), True)

    def test_only_perfect_and_strong_durations_count(self):
        self.assertIs(self.override(side_story(dur=640)), True)       # strong
        self.assertIs(self.override(side_story(dur=700)), False)      # acceptable
        self.assertIs(self.override(side_story(dur=1200)), False)     # mismatch
        self.assertIs(self.override(side_story(), minutes=None), False)

    def test_one_matching_person_is_enough_and_none_is_not(self):
        self.assertIs(self.override(side_story(authors=("Zed Q",))), True)
        self.assertIs(self.override(side_story(narrators=("Yan Z",))), True)
        self.assertIs(self.override(side_story(authors=("Zed Q",), narrators=("Yan Z",))), False)

    def test_without_any_local_people_there_is_nothing_to_confirm(self):
        self.assertIs(self.override(side_story(), clues={**self.CLUES, "author": "", "narrator": ""}), False)

    def test_a_weak_title_match_never_overrides(self):
        self.assertIs(self.override(side_story(), clues={**self.CLUES, "title": "Totally Other"}), False)

    def test_two_different_explicit_title_numbers_are_different_books(self):
        self.assertIs(self.override(side_story(title="Dominion 6"), clues={**self.CLUES, "title": "Dominion 4"}), False)
        self.assertIs(self.override(side_story(title="Dominion 4", seq="3"), clues={**self.CLUES, "title": "Dominion 4"}), True)

    def test_a_local_number_far_from_the_catalog_sequence_is_a_different_book(self):
        self.assertIs(self.override(side_story(seq="2")), False)
        self.assertIs(self.override(side_story(seq="1.5")), False)     # exactly one apart already differs
        self.assertIs(self.override(side_story(seq="1")), True)        # 0.5 vs 1 is a prequel offset
        self.assertIs(self.override(side_story(seq="0")), True)


class SequenceConflictTests(unittest.TestCase):
    def clues(self, **over):
        return {"title": "Of Dawn and Darkness", "author": "Jane Doe", "narrator": "Bob Roe",
                "book_number": "3", "book_number_source": "path", **over}

    def prod(self, seq="2", title="Of Dawn and Darkness", dur=600):
        return {"title": title, "series": [{"title": "Elder Empire Sea", "sequence": seq}], "runtime_length_min": dur,
                "authors": [{"name": "Jane Doe"}], "narrators": [{"name": "Bob Roe"}]}

    def conflict(self, clues, product, minutes=600):
        return s.has_sequence_conflict(clues, product, minutes)

    def test_different_numbers_conflict_and_equal_numbers_do_not(self):
        self.assertIs(self.conflict(self.clues(title="Other", author="", narrator=""), self.prod(seq="5", title="Zzz")), True)
        self.assertIs(self.conflict(self.clues(title="Other", author="", narrator="", book_number="5"), self.prod(seq="5", title="Zzz")), False)

    def test_no_local_number_or_a_non_numeric_catalog_sequence_cannot_conflict(self):
        self.assertIs(self.conflict(self.clues(book_number=""), self.prod(seq="5")), False)
        self.assertIs(self.conflict(self.clues(), self.prod(seq="1-3")), False)
        self.assertIs(self.conflict(self.clues(), {"title": "x"}), False)

    def test_a_track_number_is_too_weak_to_conflict(self):
        self.assertIs(self.conflict(self.clues(book_number_source="track", title="Other", author="", narrator=""),
                                    self.prod(seq="9", title="Zzz")), False)

    def test_a_confirmed_one_apart_numbering_scheme_difference_is_tolerated(self):
        # title identical, durations agree, author matches, and the gap is 1
        self.assertIs(self.conflict(self.clues(), self.prod(seq="2")), False)

    def test_the_tolerance_ends_at_a_gap_of_two(self):
        self.assertIs(self.conflict(self.clues(), self.prod(seq="1")), True)

    def test_the_tolerance_needs_a_person_to_match(self):
        self.assertIs(self.conflict(self.clues(author="Nobody", narrator="Else"), self.prod(seq="2")), True)

    def test_the_tolerance_needs_a_plausible_duration(self):
        self.assertIs(self.conflict(self.clues(), self.prod(seq="2", dur=2000)), True)
        self.assertIs(self.conflict(self.clues(), self.prod(seq="2", dur=700)), False)    # acceptable still counts

    def test_the_tolerance_needs_a_strong_title_match(self):
        self.assertIs(self.conflict(self.clues(title="Something Unrelated Entirely"), self.prod(seq="2")), True)

    def test_explicit_title_numbers_that_differ_defeat_the_tolerance(self):
        clues = self.clues(title="Power Mage 5", book_number="5")
        self.assertIs(self.conflict(clues, self.prod(seq="6", title="Power Mage 6")), True)


class AuthorIdentityConflictTests(unittest.TestCase):
    def conflict(self, local, *product_authors):
        product = {"authors": [{"name": a} for a in product_authors]}
        return s.has_author_identity_conflict({"author": local}, product)

    def test_zero_overlap_between_two_real_names_is_a_conflict(self):
        self.assertIs(self.conflict("Arthur C. Clarke", "Will Wight"), True)

    def test_missing_or_generic_authors_never_conflict(self):
        for local, remote in (("", "Will Wight"), ("Will Wight", ""), ("Unknown", "Will Wight"), ("Various Authors", "Will Wight"),
                              ("Will Wight", "Anonymous"), ("Audiobook Audio", "Will Wight")):
            with self.subTest(local=local, remote=remote):
                self.assertIs(self.conflict(local, remote) if remote else self.conflict(local), False)

    def test_formatting_variants_containment_and_shared_tokens_never_conflict(self):
        for local, remote in (("J R R Tolkien", "J.R.R. Tolkien"), ("Clarke", "Arthur C. Clarke"),
                              ("Arthur C. Clarke", "Arthur C. Clarke, Gentry Lee"), ("Ann Marie Lee", "Zed Lee"),
                              ("Will Wight", "Will Wight")):
            with self.subTest(local=local, remote=remote):
                self.assertIs(self.conflict(local, remote), False)

    def test_names_shorter_than_three_letters_do_not_count_as_a_shared_token(self):
        self.assertIs(self.conflict("Al Bo", "Cy Bo Di"), True)      # only the 2-letter "Bo" is shared
        self.assertIs(self.conflict("Al Bob", "Cy Bob Di"), False)   # a 3-letter shared token is enough


class ReorderedTitleConflictTests(unittest.TestCase):
    def conflict(self, local, remote, **clues):
        return s.has_reordered_title_conflict({"title": local, **clues}, {"title": remote})

    def test_the_same_words_in_a_different_order_is_a_different_book(self):
        self.assertIs(self.conflict("Of Dawn and Darkness", "Of Darkness and Dawn"), True)
        self.assertIs(self.conflict("Of Shadow and Sea", "Of Sea and Shadow"), True)

    def test_identical_titles_and_different_words_are_not_reordered(self):
        self.assertIs(self.conflict("Of Dawn and Darkness", "Of Dawn and Darkness"), False)
        self.assertIs(self.conflict("Of Dawn and Darkness", "Of Dusk and Light"), False)

    def test_titles_with_fewer_than_two_meaningful_words_are_not_compared(self):
        self.assertIs(self.conflict("Dune", "Dune"), False)
        self.assertIs(self.conflict("Dune Messiah", "Dune"), False)

    def test_a_series_name_title_is_exempt(self):
        product = {"title": "Dawn Darkness", "series": [{"title": "Dawn Darkness", "sequence": "1"}]}
        self.assertIs(s.has_reordered_title_conflict({"title": "Darkness Dawn"}, product), False)

    def test_a_generic_series_number_local_title_is_exempt(self):
        clues = {"title": "Dawn Darkness 3", "series": "Dawn Darkness", "book_number": "3"}
        self.assertIs(s.has_reordered_title_conflict(clues, {"title": "Darkness Dawn 3"}), False)


def score_prod(**over):
    base = {"title": "Qwerty Alpha", "series": [], "runtime_length_min": 600, "authors": [{"name": "Jane Doe"}],
            "narrators": [{"name": "Bob Roe"}], "language": "english", "asin": "B0AAAAAAAA"}
    base.update(over)
    return base


UNRELATED = {"title": "Totally Different", "author": "", "narrator": "", "series": "", "book_number": ""}


class ScoreComponentTests(unittest.TestCase):
    """Each evidence source moves the score by its documented weight."""

    def score(self, clues=None, product=None, minutes=None):
        return s.score_product_for_metadata({**UNRELATED, **(clues or {})}, product or score_prod(), minutes)

    def delta(self, base_kwargs, changed_kwargs):
        return round(self.score(**changed_kwargs) - self.score(**base_kwargs), 4)

    def test_duration_bands_add_thirty_eight_thirty_eighteen_and_nothing_when_unknown(self):
        base = self.score()
        for minutes, bonus in ((600, 0.38), (640, 0.30), (700, 0.18)):
            with self.subTest(minutes=minutes):
                self.assertAlmostEqual(self.score(minutes=minutes) - base, bonus, places=4)

    def test_a_duration_mismatch_costs_thirty_five_points(self):
        rich = {"abs_asin": "B0AAAAAAAA", "author": "Jane Doe", "narrator": "Bob Roe"}
        self.assertAlmostEqual(self.score(rich, minutes=600 * 2) - self.score(rich), -0.35, places=4)

    def test_the_score_never_goes_below_zero(self):
        self.assertEqual(self.score(minutes=1200), 0.0)

    def test_abs_agreement_adds_a_fixed_bonus_only_for_the_same_asin(self):
        base = self.score()
        self.assertAlmostEqual(self.score({"abs_asin": "b0aaaaaaaa"}) - base, 0.20, places=4)
        self.assertAlmostEqual(self.score({"abs_asin": "B0OTHER"}) - base, 0.0, places=4)

    def test_a_matching_author_adds_seventeen_points_and_a_matching_narrator_ten(self):
        base = self.score()
        self.assertAlmostEqual(self.score({"author": "Jane Doe"}) - base, 0.17, places=4)
        self.assertAlmostEqual(self.score({"narrator": "Bob Roe"}) - base, 0.10, places=4)

    def test_title_evidence_adds_twelve_percent_of_its_score(self):
        base = self.score()
        full = self.score({"title": "Qwerty Alpha"})
        title_score = s.title_evidence_score({**UNRELATED, "title": "Qwerty Alpha"}, score_prod())
        self.assertAlmostEqual(full - base, 0.12 * (title_score - s.title_evidence_score(UNRELATED, score_prod())), places=4)

    def test_a_series_match_adds_a_quarter_and_a_matching_number_adds_eighteen_plus_ten(self):
        saga = score_prod(series=[{"title": "Saga", "sequence": "1"}])
        base = self.score(product=saga)
        with_series = self.score({"series": "Saga"}, saga)
        self.assertAlmostEqual(with_series - base, 0.25, places=4)
        with_number = self.score({"series": "Saga", "book_number": "1", "book_number_source": "path"}, saga)
        self.assertAlmostEqual(with_number - with_series, 0.18 + 0.10, places=4)

    def test_a_substring_series_without_shared_content_earns_no_series_credit(self):
        school = score_prod(series=[{"title": "Summoner School", "sequence": "1"}])
        self.assertAlmostEqual(self.score({"series": "Summoner"}, school) - self.score(product=school), 0.0, places=4)

    def test_a_non_english_edition_loses_thirty_points_unless_the_language_is_english_or_blank(self):
        base = self.score(minutes=600)
        self.assertAlmostEqual(self.score(minutes=600, product=score_prod(language="french")) - base, -0.30, places=4)
        self.assertAlmostEqual(self.score(minutes=600, product=score_prod(language="English")) - base, 0.0, places=4)
        self.assertAlmostEqual(self.score(minutes=600, product=score_prod(language="")) - base, 0.0, places=4)

    def test_the_score_is_rounded_to_four_places_and_capped_at_one(self):
        value = self.score({"author": "Jane Doe"})
        self.assertEqual(value, round(value, 4))
        self.assertLessEqual(self.score({"title": "Qwerty Alpha", "author": "Jane Doe", "narrator": "Bob Roe"}, minutes=600), 1.0)


class ScoreHardRejectTests(unittest.TestCase):
    def score(self, clues, product=None, minutes=None):
        return s.score_product_for_metadata(clues, product or score_prod(), minutes)

    def test_a_different_author_scores_zero_whatever_else_matches(self):
        self.assertEqual(self.score({"title": "Qwerty Alpha", "author": "Zed Q"}, minutes=600), 0.0)

    def test_the_same_words_in_a_different_order_score_zero(self):
        self.assertEqual(self.score({"title": "Alpha Qwerty"}, minutes=600), 0.0)

    def test_a_conflicting_book_number_scores_zero(self):
        saga = score_prod(series=[{"title": "Saga", "sequence": "5"}])
        clues = {"title": "Totally Different", "series": "Saga", "book_number": "2", "book_number_source": "path"}
        self.assertEqual(self.score(clues, saga, 600), 0.0)

    def test_a_track_derived_number_never_rejects(self):
        saga = score_prod(series=[{"title": "Saga", "sequence": "5"}])
        clues = {"title": "Totally Different", "series": "Saga", "book_number": "2", "book_number_source": "track"}
        self.assertGreater(self.score(clues, saga, 600), 0.0)

    def test_asin_identity_bypasses_the_guards_and_has_a_floor(self):
        saga = score_prod(series=[{"title": "Saga", "sequence": "1"}])
        clues = {"title": "Qwerty Alpha", "author": "Jane Doe", "existing_asin": "b0aaaaaaaa", "series": "X",
                 "book_number": "9", "book_number_source": "path"}
        self.assertEqual(self.score(clues, saga, 1200), 0.75)

    def test_an_asin_match_needs_the_title_and_author_to_agree_too(self):
        saga = score_prod(series=[{"title": "Saga", "sequence": "1"}])
        clues = {"title": "Qwerty Alpha", "author": "Jane Doe", "existing_asin": "b0aaaaaaaa", "series": "X",
                 "book_number": "9", "book_number_source": "path"}
        self.assertEqual(self.score({**clues, "title": "Something Else Entirely"}, saga, 1200), 0.0)
        self.assertEqual(self.score({**clues, "existing_asin": "B0BBBBBBBB"}, saga, 1200), 0.0)


class ScoreFloorTests(unittest.TestCase):
    def score(self, clues, product=None, minutes=None):
        return s.score_product_for_metadata({**UNRELATED, **clues}, product or score_prod(), minutes)

    def test_series_plus_a_matching_person_guarantees_at_least_seventy_two(self):
        saga = score_prod(series=[{"title": "Saga", "sequence": "1"}])
        self.assertEqual(self.score({"series": "Saga", "author": "Jane Doe"}, saga), 0.72)
        self.assertEqual(self.score({"series": "Saga", "narrator": "Bob Roe"}, saga), 0.72)

    def test_duration_plus_series_plus_a_person_raises_the_floor_to_eighty_two(self):
        saga = score_prod(series=[{"title": "Saga", "sequence": "1"}])
        self.assertEqual(self.score({"series": "Saga", "author": "Jane Doe"}, saga, 700), 0.82)

    def test_a_perfect_duration_with_the_title_and_a_person_is_certain(self):
        self.assertEqual(self.score({"title": "Qwerty Alpha", "author": "Jane Doe"}, minutes=600), 1.0)

    def test_a_strong_duration_with_the_title_and_a_person_floors_at_ninety(self):
        self.assertEqual(self.score({"title": "Qwerty Alpha", "author": "Jane Doe"}, minutes=640), 0.9)

    def test_an_acceptable_duration_with_the_title_and_a_person_floors_at_eighty(self):
        self.assertEqual(self.score({"title": "Qwerty Alpha", "author": "Jane Doe"}, minutes=700), 0.8)

    def test_a_mismatched_duration_gets_none_of_the_duration_floors(self):
        self.assertLess(self.score({"title": "Qwerty Alpha", "author": "Jane Doe"}, minutes=1500), 0.8)

    def test_a_strong_local_number_the_candidate_cannot_confirm_blocks_the_duration_floors(self):
        clues = {"title": "Qwerty Alpha", "author": "Jane Doe", "book_number": "3", "book_number_source": "path"}
        self.assertLess(self.score(clues, minutes=600), 1.0)


def candidate(asin, minutes=600, narrators=("Bob Roe",), title="The Book", authors=("Jane Doe",), **extra):
    return {"asin": asin, "title": title, "runtime_length_min": minutes, "authors": [{"name": a} for a in authors],
            "narrators": [{"name": n} for n in narrators], **extra}


class PickBestMatchTests(unittest.TestCase):
    """Tie-breaking, with every candidate scoring the same so only the rules under test decide."""

    def pick(self, clues, products, minutes=600.0, score=0.8):
        with mock.patch.object(s, "score_product_for_metadata", return_value=score):
            return s.pick_best_match_for_metadata(clues, products, minutes)

    def test_nothing_scoring_above_zero_gives_no_match(self):
        self.assertEqual(self.pick({}, [candidate("A")], score=0.0), (None, 0.0, None))
        self.assertEqual(self.pick({}, []), (None, 0.0, None))

    def test_the_higher_score_wins_without_any_ambiguity(self):
        scores = {"A": 0.5, "B": 0.9}
        with mock.patch.object(s, "score_product_for_metadata", side_effect=lambda c, p, m: scores[p["asin"]]):
            best, score, ambiguity = s.pick_best_match_for_metadata({}, [candidate("A"), candidate("B")], 600.0)
        self.assertEqual((best["asin"], score, ambiguity), ("B", 0.9, None))

    def test_scores_within_the_epsilon_count_as_a_tie_and_beyond_it_do_not(self):
        scores = {"A": 0.81, "B": 0.80}
        with mock.patch.object(s, "score_product_for_metadata", side_effect=lambda c, p, m: scores[p["asin"]]):
            _, _, ambiguity = s.pick_best_match_for_metadata({}, [candidate("A", 600), candidate("B", 640)], 600.0)
        self.assertEqual(ambiguity["count"], 2)
        scores = {"A": 0.83, "B": 0.80}
        with mock.patch.object(s, "score_product_for_metadata", side_effect=lambda c, p, m: scores[p["asin"]]):
            _, _, ambiguity = s.pick_best_match_for_metadata({}, [candidate("A", 600), candidate("B", 640)], 600.0)
        self.assertIsNone(ambiguity)

    def test_a_better_duration_status_resolves_a_tie_silently(self):
        best, _, amb = self.pick({}, [candidate("B", 640), candidate("A", 600)])
        self.assertEqual(best["asin"], "A")
        self.assertIs(amb["resolved"], True)
        self.assertIn("on duration", amb["reason"])
        self.assertEqual(amb["alternatives"], ["The Book [B]"])
        self.assertEqual(amb["chosen"], "The Book [A]")

    def test_the_same_status_is_resolved_by_a_clear_exact_gap_of_half_a_minute(self):
        best, _, amb = self.pick({}, [candidate("B", 606), candidate("A", 600)])
        self.assertEqual((best["asin"], amb["resolved"]), ("A", True))
        best, _, amb = self.pick({"narrator": ""}, [candidate("B", 600.4, narrators=("Zed",)), candidate("A", 600)])
        self.assertIs(amb["resolved"], False)
        self.assertIn("no clear duration, narrator or edition winner", amb["reason"])

    def test_the_gap_must_reach_the_margin_exactly(self):
        best, _, amb = self.pick({}, [candidate("B", 600.5), candidate("A", 600)])
        self.assertIs(amb["resolved"], True)

    def test_the_narrator_decides_when_only_one_tied_candidate_fits(self):
        best, _, amb = self.pick({"narrator": "Bob Roe"},
                                 [candidate("B", 600.1, narrators=("Other Reader",)), candidate("A", 600.1)])
        self.assertEqual((best["asin"], amb["resolved"]), ("A", True))
        self.assertIn("on narrator", amb["reason"])

    def test_two_fitting_narrators_do_not_decide(self):
        _, _, amb = self.pick({"narrator": "Bob Roe"}, [candidate("A", 600.1), candidate("B", 600.1, title="A Different Book")])
        self.assertIs(amb["resolved"], False)

    def test_the_audible_sku_decides_next(self):
        best, _, amb = self.pick({"sku": "BK_AAAA_000001"},
                                 [candidate("B", 600.1, narrators=("Z",), sku="BK_BBBB_000002"),
                                  candidate("A", 600.1, narrators=("Y",), sku="bk_aaaa_000001")])
        self.assertEqual((best["asin"], amb["resolved"]), ("A", True))
        self.assertIn("on sku", amb["reason"])

    def test_the_publisher_decides_after_the_sku(self):
        best, _, amb = self.pick({"publisher": "Tantor Audio"},
                                 [candidate("B", 600.1, narrators=("Z",), publisher_name="Podium Audio"),
                                  candidate("A", 600.1, narrators=("Y",), publisher_name="Tantor Audio")])
        self.assertEqual((best["asin"], amb["resolved"]), ("A", True))
        self.assertIn("on publisher", amb["reason"])

    def test_the_same_recording_under_two_asins_is_resolved_to_the_first(self):
        _, _, amb = self.pick({}, [candidate("A", 600.1), candidate("B", 600.1)])
        self.assertIs(amb["resolved"], True)
        self.assertIn("on same recording", amb["reason"])

    def test_different_recordings_stay_unresolved(self):
        _, _, amb = self.pick({}, [candidate("A", 600.1), candidate("B", 600.1, narrators=("Someone Else",))])
        self.assertIs(amb["resolved"], False)

    def test_the_best_duration_is_chosen_among_equal_scores_even_without_resolution(self):
        best, _, _ = self.pick({}, [candidate("B", 600.4), candidate("A", 600.1)])
        self.assertEqual(best["asin"], "A")


class SameRecordingTests(unittest.TestCase):
    def test_title_authors_narrators_and_runtime_must_all_agree(self):
        a = candidate("A", 600)
        self.assertIs(s._same_recording(a, candidate("B", 600.9)), True)
        self.assertIs(s._same_recording(a, candidate("B", 602)), False)
        self.assertIs(s._same_recording(a, candidate("B", 600, title="Other")), False)
        self.assertIs(s._same_recording(a, candidate("B", 600, authors=("Zed",))), False)
        self.assertIs(s._same_recording(a, candidate("B", 600, narrators=("Zed",))), False)

    def test_sparse_providers_are_compared_on_title_and_authors_only(self):
        a = candidate("A", None, narrators=(), _abs_provider="goodreads")
        b = candidate("B", None, narrators=(), _abs_provider="openlibrary")
        self.assertIs(s._same_recording(a, b), True)
        self.assertIs(s._same_recording(a, {**b, "title": "Other"}), False)

    def test_one_sparse_and_one_full_listing_still_need_runtime_and_narrators(self):
        a = candidate("A", None, narrators=(), _abs_provider="goodreads")
        self.assertIs(s._same_recording(a, candidate("B", 600)), False)

    def test_books_without_authors_are_never_the_same_recording(self):
        self.assertIs(s._same_recording(candidate("A", authors=()), candidate("B", authors=())), False)


class SkuAndPublisherMatchTests(unittest.TestCase):
    def test_a_sku_matches_either_product_sku_field_case_insensitively(self):
        self.assertIs(s._sku_matches({"sku": "bk_a_1"}, {"sku": "BK_A_1"}), True)
        self.assertIs(s._sku_matches({"sku": "BK_A_1"}, {"sku_lite": "bk_a_1"}), True)
        self.assertIs(s._sku_matches({"sku": "BK_A_1"}, {"sku": "BK_B_2"}), False)

    def test_a_missing_local_sku_never_matches_a_missing_product_sku(self):
        self.assertIs(s._sku_matches({}, {}), False)
        self.assertIs(s._sku_matches({"sku": ""}, {"sku": ""}), False)

    def test_catalog_publishers_match_by_catalog_entry_not_spelling(self):
        self.assertIs(s._publisher_matches({"publisher": "Tantor"}, {"publisher_name": "Tantor Audio"}), True)
        self.assertIs(s._publisher_matches({"publisher": "Tantor Audio"}, {"publisher_name": "Graphic Audio"}), False)

    def test_unknown_publishers_match_when_one_contains_the_other(self):
        self.assertIs(s._publisher_matches({"publisher": "Obscure Press Zed"}, {"publisher_name": "Obscure Press Zed LLC"}), True)
        self.assertIs(s._publisher_matches({"publisher": "Obscure Press Zed"}, {"publisher_name": "Entirely Different Co"}), False)

    def test_a_missing_publisher_on_either_side_never_matches(self):
        self.assertIs(s._publisher_matches({}, {"publisher_name": "Tantor Audio"}), False)
        self.assertIs(s._publisher_matches({"publisher": "Tantor Audio"}, {}), False)


if __name__ == "__main__":
    unittest.main()
