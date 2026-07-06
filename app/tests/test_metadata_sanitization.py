import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).parents[2]

try:
    import audible  # noqa: F401
except ModuleNotFoundError:
    audible_stub = types.ModuleType("audible")
    audible_stub.Client = type("Client", (), {})
    sys.modules["audible"] = audible_stub


def load_module(name: str, relative_path: str):
    path = ROOT / relative_path
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


FIXER = load_module(
    "fixer_v5_sanitization",
    "scripts/audible-metadata-fixer-v5.py",
)
ORGANIZER = load_module(
    "organizer_v3_13_sanitization",
    "scripts/organize-audiobooks-by-metadata-v3_13.py",
)


class FixerMultipartGroupingTests(unittest.TestCase):
    def test_zero_padded_numeric_m4b_parts_are_grouped(self):
        files = [
            Path("/book/Example Book 3 - 01.m4b"),
            Path("/book/Example Book 3 - 02.m4b"),
            Path("/book/Example Book 3 - 03.m4b"),
            Path("/book/Example Book 3.m4b"),
        ]

        groups = FIXER.build_multi_part_group_map(
            files,
            chapter_count_reader=lambda path: 30 if path.name == "Example Book 3.m4b" else 0,
        )

        self.assertEqual(groups[Path("/book")], files[:3])
        self.assertEqual(
            FIXER.build_processing_items(files, groups),
            [files[0], files[3]],
        )

    def test_complete_m4bs_with_different_prefixes_remain_separate(self):
        files = [
            Path("/book/Example Book 1 - 01.m4b"),
            Path("/book/Example Book 2 - 02.m4b"),
        ]

        groups = FIXER.build_multi_part_group_map(
            files,
            chapter_count_reader=lambda _path: 0,
        )

        self.assertEqual(groups, {})


class TechnicalLabelSanitizationTests(unittest.TestCase):
    def test_author_credits_are_canonicalized_consistently(self):
        cases = [
            ("リュート", "Ryuto"),
            ("Cássio Ferreira", "Cassio Ferreira"),
            ("C.J. Thompson, J.M. Clarke", "J.M. Clarke, C.J. Thompson"),
            ("Mashton X X, Mashton X Y", "Mashton XX, Mashton XY"),
            ("Sean Oswald, Joshua Mason - editor", "Sean Oswald"),
        ]

        for value, expected in cases:
            with self.subTest(value=value):
                self.assertEqual(FIXER.canonicalize_author_credits(value), expected)
                self.assertEqual(ORGANIZER.clean_author_credits(value), expected)

    def test_unambiguous_codec_labels_are_removed(self):
        value = "Dashing Devil xHE-AAC LLC - Bold Beginnings"
        self.assertEqual(
            FIXER.sanitize_technical_labels(value),
            "Dashing Devil - Bold Beginnings",
        )
        self.assertEqual(
            ORGANIZER.cleanup_title_artifacts(value),
            "Dashing Devil - Bold Beginnings",
        )

    def test_bracketed_common_codec_block_is_removed(self):
        value = "Bold Beginnings [AAC 128 kbps 44.1 kHz Stereo]"
        self.assertEqual(FIXER.sanitize_technical_labels(value), "Bold Beginnings")
        self.assertEqual(ORGANIZER.cleanup_title_artifacts(value), "Bold Beginnings")

    def test_trailing_common_format_segment_is_removed(self):
        self.assertEqual(
            ORGANIZER.cleanup_title_artifacts("Bold Beginnings - FLAC"),
            "Bold Beginnings",
        )

    def test_ambiguous_codec_word_is_preserved_as_title_text(self):
        self.assertEqual(ORGANIZER.cleanup_title_artifacts("The Opus"), "The Opus")
        self.assertEqual(FIXER.sanitize_technical_labels("The Opus"), "The Opus")

    def test_meaningful_edition_label_is_preserved(self):
        value = "Bold Beginnings [Booktrack Edition]"
        self.assertEqual(ORGANIZER.cleanup_title_artifacts(value), value)

    def test_generic_marketing_descriptor_is_not_a_title(self):
        for value in [
            "A LitRPG Adventure",
            "A Progression Fantasy Epic",
            "A Progression LitRPG Epic",
            "An Isekai Epic",
            "A Harem Adventure",
        ]:
            self.assertEqual(FIXER.sanitize_book_title(value), "")
            self.assertEqual(ORGANIZER.cleanup_title_artifacts(value), "")

    def test_trailing_marketing_descriptor_is_removed(self):
        self.assertEqual(
            FIXER.sanitize_book_title(
                "1% Lifesteal: A LitRPG Adventure"
            ),
            "1% Lifesteal",
        )
        self.assertEqual(
            ORGANIZER.cleanup_title_artifacts(
                "The Fabric of Reality - A LitRPG Adventure"
            ),
            "The Fabric of Reality",
        )

    def test_real_title_with_genre_word_is_preserved(self):
        self.assertEqual(
            ORGANIZER.cleanup_title_artifacts("The Harem"),
            "The Harem",
        )


class SeriesDeduplicationTests(unittest.TestCase):
    def test_plain_metadata_confirmed_series_prefix_is_removed(self):
        title = ORGANIZER.clean_book_title(
            "Dashing Devil Bold Beginnings [xHE-AAC LLC]",
            "Dashing Devil",
            "5",
        )
        self.assertEqual(title, "Bold Beginnings")

    def test_punctuation_differences_in_series_prefix_are_tolerated(self):
        title = ORGANIZER.clean_book_title(
            "Reborn-as-a-Space-Mercenary A New Voyage",
            "Reborn as a Space Mercenary",
            "10",
        )
        self.assertEqual(title, "A New Voyage")

    def test_short_legitimate_prefix_is_not_removed(self):
        title = ORGANIZER.clean_book_title("It Ends with Us", "It", "1")
        self.assertEqual(title, "It Ends with Us")

    def test_generated_book_folder_has_no_series_or_codec_duplication(self):
        metadata = {
            "title": ORGANIZER.clean_book_title(
                "Dashing Devil Bold Beginnings - AAC",
                "Dashing Devil",
                "5",
            ),
            "series": "Dashing Devil xHE-AAC LLC",
            "book_number": "005",
            "sequence_label": "Book",
        }
        metadata["series"] = ORGANIZER.clean_series_name(metadata["series"])
        self.assertEqual(metadata["series"], "Dashing Devil")
        self.assertEqual(
            ORGANIZER.build_book_folder_name(metadata),
            "Book 5 - Bold Beginnings",
        )

    def test_series_plus_number_only_collapses_to_sequence_folder(self):
        metadata = {
            "title": ORGANIZER.clean_book_title(
                "Accidental Champion 5",
                "Accidental Champion",
                "005",
            ),
            "series": "Accidental Champion",
            "book_number": "005",
            "sequence_label": "Book",
        }
        self.assertEqual(ORGANIZER.build_book_folder_name(metadata), "Book 5")

    def test_series_only_title_collapses_to_sequence_folder(self):
        metadata = {
            "title": "Accidental Champion",
            "series": "Accidental Champion",
            "book_number": "002",
            "sequence_label": "Book",
        }
        self.assertEqual(ORGANIZER.build_book_folder_name(metadata), "Book 2")

    def test_series_plus_word_number_collapses_to_sequence_folder(self):
        metadata = {
            "title": ORGANIZER.clean_book_title(
                "Azarinth Healer, Book Six",
                "Azarinth Healer",
                "006",
            ),
            "series": "Azarinth Healer",
            "book_number": "006",
            "sequence_label": "Book",
        }
        self.assertEqual(ORGANIZER.build_book_folder_name(metadata), "Book 6")

    def test_percentage_title_keeps_leading_number(self):
        title = ORGANIZER.clean_book_title(
            "1% Lifesteal",
            "1% Lifesteal",
            "001",
        )
        self.assertEqual(title, "1% Lifesteal")


class MetadataTitleFallbackTests(unittest.TestCase):
    def test_identity_rich_original_folder_name_orders(self):
        cases = [
            (
                "Shane Walker - All Trades 04 - International Shipping",
                {
                    "title": "International Shipping",
                    "author": "Shane Walker",
                    "series": "All Trades",
                    "book_number": "4",
                },
            ),
            (
                "The Beastlands - Arcane Pathfinder Book 2 - Mashton XX",
                {
                    "title": "The Beastlands",
                    "author": "Mashton XX",
                    "series": "Arcane Pathfinder",
                    "book_number": "2",
                },
            ),
            (
                "Paths of Akashic Book 3 - A New Home - Bainin",
                {
                    "title": "A New Home",
                    "author": "Bainin",
                    "series": "Paths of Akashic",
                    "book_number": "3",
                },
            ),
            (
                "Icalos - Terminate the Other World!, Book 2 - "
                "A Glitch in the Protocols",
                {
                    "title": "A Glitch in the Protocols",
                    "author": "Icalos",
                    "series": "Terminate the Other World!",
                    "book_number": "2",
                },
            ),
            (
                "Wolfe Locke - Tower Reborn A LitRPG Adventure "
                "(Realm Grinder Book 1)",
                {
                    "title": "Tower Reborn",
                    "author": "Wolfe Locke",
                    "series": "Realm Grinder",
                    "book_number": "1",
                },
            ),
            (
                "Restarting the Apocalypse, Book 1 - Michael Chatfield",
                {
                    "title": "Restarting the Apocalypse",
                    "author": "Michael Chatfield",
                    "series": "Restarting the Apocalypse",
                    "book_number": "1",
                },
            ),
            (
                "Rune Seeker 5 - J.M. Clarke",
                {
                    "title": "Rune Seeker",
                    "author": "J.M. Clarke",
                    "series": "Rune Seeker",
                    "book_number": "5",
                },
            ),
            (
                "Extra26, T C Liyanage - Magus Reborn 01",
                {
                    "title": "Extra26",
                    "author": "T C Liyanage",
                    "series": "Magus Reborn",
                    "book_number": "1",
                },
            ),
        ]

        for value, expected in cases:
            with self.subTest(value=value):
                parsed = FIXER.parse_identity_rich_book_text(value)
                for key, expected_value in expected.items():
                    self.assertEqual(parsed.get(key), expected_value)

    def test_ambiguous_original_folder_name_is_not_split_by_guessing(self):
        self.assertEqual(
            FIXER.parse_identity_rich_book_text(
                "Shane Walker - Corporate Warfare All Trades, Book 3"
            ),
            {},
        )
        self.assertEqual(
            ORGANIZER.parse_explicit_identity_folder_name(
                "Shane Walker - Corporate Warfare All Trades, Book 3"
            ),
            {},
        )

    def test_organizer_matches_fixer_for_identity_rich_folder_names(self):
        cases = [
            (
                "Shane Walker - All Trades 04 - International Shipping",
                "International Shipping",
                "Shane Walker",
                "All Trades",
                "004",
            ),
            (
                "The Beastlands - Arcane Pathfinder Book 2 - Mashton XX",
                "The Beastlands",
                "Mashton XX",
                "Arcane Pathfinder",
                "002",
            ),
            (
                "Paths of Akashic Book 3 - A New Home - Bainin",
                "A New Home",
                "Bainin",
                "Paths of Akashic",
                "003",
            ),
            (
                "Icalos - Terminate the Other World!, Book 2 - "
                "A Glitch in the Protocols",
                "A Glitch in the Protocols",
                "Icalos",
                "Terminate the Other World!",
                "002",
            ),
            (
                "Wolfe Locke - Tower Reborn A LitRPG Adventure "
                "(Realm Grinder Book 1)",
                "Tower Reborn",
                "Wolfe Locke",
                "Realm Grinder",
                "001",
            ),
            (
                "Restarting the Apocalypse, Book 1 - Michael Chatfield",
                "Restarting the Apocalypse",
                "Michael Chatfield",
                "Restarting the Apocalypse",
                "001",
            ),
            (
                "Rune Seeker 5 - J.M. Clarke",
                "Rune Seeker",
                "J.M. Clarke",
                "Rune Seeker",
                "005",
            ),
            (
                "Extra26, T C Liyanage - Magus Reborn 01",
                "Extra26",
                "T C Liyanage",
                "Magus Reborn",
                "001",
            ),
        ]

        for value, title, author, series, number in cases:
            with self.subTest(value=value):
                parsed = ORGANIZER.parse_explicit_identity_folder_name(value)
                self.assertEqual(parsed.get("title"), title)
                self.assertEqual(parsed.get("author"), author)
                self.assertEqual(parsed.get("series"), series)
                self.assertEqual(parsed.get("number"), number)

    def test_unlabeled_series_number_does_not_turn_subtitle_into_author(self):
        value = "Dashing Devil 5 - Bold Beginnings"
        self.assertEqual(FIXER.parse_identity_rich_book_text(value), {})
        self.assertEqual(ORGANIZER.parse_explicit_identity_folder_name(value), {})

    def test_grouped_original_folder_uses_all_explicit_identity_fields(self):
        files = [
            Path(
                "/library/_unorganized/"
                "The Beastlands - Arcane Pathfinder Book 2 - Mashton XX/"
                "01 Chapter.opus"
            ),
            Path(
                "/library/_unorganized/"
                "The Beastlands - Arcane Pathfinder Book 2 - Mashton XX/"
                "02 Chapter.opus"
            ),
        ]
        chapter_clues = {
            "raw_title": "Chapter 1",
            "title": "Chapter 1",
            "series": "",
            "book_number": "",
            "book_number_source": "",
            "author": "",
            "narrator": "",
            "album": "",
        }

        with (
            patch.object(
                FIXER,
                "build_search_clues_from_file",
                return_value=chapter_clues,
            ),
            patch.object(FIXER, "probe_file", return_value=({}, 100.0)),
            patch.object(FIXER, "validate_multi_part_group_files", return_value={}),
        ):
            queries, clues = FIXER.build_multi_file_search_context(files)

        self.assertEqual(clues["title"], "The Beastlands")
        self.assertEqual(clues["author"], "Mashton XX")
        self.assertEqual(clues["series"], "Arcane Pathfinder")
        self.assertEqual(clues["book_number"], "2")
        self.assertEqual(queries[0], "The Beastlands Mashton XX")

    def test_grouped_volume_recovers_author_and_series_from_organized_path(self):
        files = [
            Path(
                "/library/Isuna Hasekura/Spice and Wolf/"
                "Volume 7 - Side Colors/01 Chapter.opus"
            ),
            Path(
                "/library/Isuna Hasekura/Spice and Wolf/"
                "Volume 7 - Side Colors/02 Chapter.opus"
            ),
        ]
        chapter_clues = {
            "raw_title": "Chapter 1",
            "title": "Chapter 1",
            "series": "",
            "book_number": "",
            "book_number_source": "",
            "author": "",
            "narrator": "",
            "album": "",
        }

        with (
            patch.object(
                FIXER,
                "build_search_clues_from_file",
                return_value=chapter_clues,
            ),
            patch.object(FIXER, "probe_file", return_value=({}, 160.0)),
            patch.object(FIXER, "validate_multi_part_group_files", return_value={}),
        ):
            queries, clues = FIXER.build_multi_file_search_context(files)

        self.assertEqual(clues["title"], "Side Colors")
        self.assertEqual(clues["author"], "Isuna Hasekura")
        self.assertEqual(clues["series"], "Spice and Wolf")
        self.assertEqual(clues["book_number"], "7")
        self.assertEqual(queries[0], "Side Colors Isuna Hasekura")
        self.assertIn("Spice and Wolf Isuna Hasekura", queries)

        product = {
            "title": "Spice and Wolf, Vol. 7",
            "subtitle": "Side Colors",
            "series": [{"title": "Spice and Wolf", "sequence": "7"}],
            "authors": [
                {"name": "Isuna Hasekura"},
                {"name": "Paul Starr - translator"},
            ],
            "narrators": [],
            "runtime_length_min": 320,
        }
        duration = FIXER.compare_duration(
            clues["local_duration_minutes"],
            product["runtime_length_min"],
        )
        score = FIXER.score_product_for_metadata(
            clues,
            product,
            clues["local_duration_minutes"],
        )

        self.assertEqual(score, 1.0)
        self.assertEqual(
            FIXER.determine_edit_mode(product, clues, score, duration),
            "full",
        )

    def test_series_number_title_path_recovers_business_as_usual(self):
        path = Path(
            "/library/All Trades 02 - Business as Usual/"
            "Shane Walker - All Trades 02 - Business as Usual.mp3"
        )
        tags = {
            "title": "All Trades 02 - Business as Usual",
            "album": "All Trades 02",
            "artist": "Shane Walker",
            "track": "1",
        }

        with patch.object(FIXER, "read_file_tags", return_value=tags):
            clues = FIXER.build_search_clues_from_file(path)
            queries = FIXER.build_search_queries_from_clues(clues)

        self.assertEqual(clues["title"], "Business as Usual")
        self.assertEqual(clues["series"], "All Trades")
        self.assertEqual(clues["book_number"], "2")
        self.assertEqual(queries[0], "Business as Usual Shane Walker")

    def test_title_series_book_author_path_recovers_manipulation(self):
        path = Path(
            "/library/Manipulation - Magic Eater, Book 1 - Sean Oswald/"
            "Manipulation - Magic Eater, Book 1 - Sean Oswald.m4b"
        )
        tags = {
            "title": "Sean Oswald",
            "album": "Sean Oswald",
            "album_artist": "Sean Oswald",
            "grouping": "Magic Eater",
        }

        with patch.object(FIXER, "read_file_tags", return_value=tags):
            clues = FIXER.build_search_clues_from_file(path)

        self.assertEqual(clues["title"], "Manipulation")
        self.assertEqual(clues["series"], "Magic Eater")
        self.assertEqual(clues["book_number"], "1")

    def test_author_series_book_title_path_keeps_author_and_title_oriented(self):
        path = Path(
            "/library/Bruce Sentar - Ard's Oath, Book 1 - Magic's Mantle/"
            "Ard's Oath, Book 1 - Magic's Mantle.m4b"
        )
        tags = {
            "title": "Magic's Mantle",
            "album_artist": "Bruce Sentar",
            "grouping": "Ard's Oath",
            "track": "1",
        }

        with patch.object(FIXER, "read_file_tags", return_value=tags):
            clues = FIXER.build_search_clues_from_file(path)

        self.assertEqual(clues["title"], "Magic's Mantle")
        self.assertEqual(clues["author"], "Bruce Sentar")
        self.assertEqual(clues["series"], "Ard's Oath")
        self.assertEqual(clues["book_number"], "1")

    def test_trailing_known_author_does_not_replace_embedded_title(self):
        path = Path(
            "/library/Voidknight Ascension - Book 2 - James T. Callum/"
            "Voidknight Ascension - Book 2 - James T. Callum.m4b"
        )
        tags = {
            "title": "Voidknight Ascension",
            "album_artist": "James T. Callum",
            "grouping": "Voidknight Ascension",
            "track": "2",
        }

        with patch.object(FIXER, "read_file_tags", return_value=tags):
            clues = FIXER.build_search_clues_from_file(path)

        self.assertEqual(clues["title"], "Voidknight Ascension")
        self.assertEqual(clues["author"], "James T. Callum")
        self.assertEqual(clues["series"], "Voidknight Ascension")
        self.assertEqual(clues["book_number"], "2")

    def test_search_queries_include_title_without_leading_sequence(self):
        clues = {
            "title": "02 - When True Night Falls",
            "raw_title": "02 - When True Night Falls",
            "series": "The Coldfire Trilogy",
            "author": "",
            "book_number": "2",
        }

        queries = FIXER.build_search_queries_from_clues(clues)

        self.assertIn("When True Night Falls", queries)
        self.assertNotEqual(queries[-1], "02 When True Night Falls")

    def test_sequence_folder_uses_parent_series_and_sequence_number(self):
        path = Path(
            "/library/The Coldfire Trilogy/02 - When True Night Falls/"
            "02 - When True Night Falls.m4a"
        )
        tags = {
            "title": "02 - When True Night Falls",
            "album": "02 - When True Night Falls",
            "album_artist": "C.S. Friedman",
            "track": "1",
        }

        with patch.object(FIXER, "read_file_tags", return_value=tags):
            clues = FIXER.build_search_clues_from_file(path)

        self.assertEqual(clues["series"], "The Coldfire Trilogy")
        self.assertEqual(clues["book_number"], "2")
        self.assertEqual(clues["book_number_source"], "path")
        self.assertIn(
            "When True Night Falls C.S. Friedman",
            FIXER.build_search_queries_from_clues(clues),
        )

    def test_filename_identity_number_beats_parent_version_number(self):
        path = Path(
            "/library/Bruce Sentar - Dungeon Diving v2/"
            "Dungeon Diving 103.m4b"
        )
        tags = {
            "title": "Dungeon Diving 103",
            "album_artist": "Bruce Sentar",
            "grouping": "Dungeon Diving",
            "track": "2",
        }

        with patch.object(FIXER, "read_file_tags", return_value=tags):
            clues = FIXER.build_search_clues_from_file(path)

        self.assertEqual(clues["book_number"], "103")
        self.assertEqual(clues["book_number_source"], "path")

    def test_generic_unabridged_value_is_not_a_series(self):
        self.assertEqual(FIXER.clean_series_value("Unabridged"), "")
        self.assertEqual(FIXER.clean_series_value("(Unabridged)"), "")
        self.assertEqual(
            FIXER.sanitize_book_title(
                "Condition Evolution 4: A LitRPG Adventure (Unabridged)"
            ),
            "Condition Evolution 4",
        )

    def test_trailing_series_book_segment_is_split_from_metadata_title(self):
        parsed = FIXER.parse_title_series_number_from_metadata(
            {
                "title": (
                    "Shade's First Rule: A Fantasy LitRPG Adventure: "
                    "Divine Apostasy, Book 1"
                ),
                "album_artist": "A. F. Kay",
            }
        )

        self.assertEqual(parsed["title"], "Shade's First Rule")
        self.assertEqual(parsed["series"], "Divine Apostasy")
        self.assertEqual(parsed["book_number"], "1")

    def test_album_fallback_series_is_not_tag_series(self):
        # No dedicated series tag -- the album fallback commonly just echoes
        # the title (e.g. "Pocket Dungeon 4"), so it's a fine search clue but
        # must never be presented as if the book actually has a series tag.
        parsed = FIXER.parse_title_series_number_from_metadata(
            {"title": "Pocket Dungeon 4", "album": "Pocket Dungeon 4", "album_artist": "Eric Vall"}
        )
        self.assertEqual(parsed["series"], "Pocket Dungeon 4")
        self.assertEqual(parsed["tag_series"], "")

    def test_dedicated_grouping_tag_is_real_tag_series(self):
        parsed = FIXER.parse_title_series_number_from_metadata(
            {
                "title": "Pocket Dungeon 4",
                "album": "Pocket Dungeon 4",
                "grouping": "Pocket Dungeon",
                "album_artist": "Eric Vall",
            }
        )
        self.assertEqual(parsed["tag_series"], "Pocket Dungeon")

    def test_series_parsed_from_title_tag_counts_as_real_tag_series(self):
        # A series name embedded within the title tag itself (not a dedicated
        # grouping tag, and not the album fallback) is still real tag data.
        parsed = FIXER.parse_title_series_number_from_metadata(
            {
                "title": (
                    "Shade's First Rule: A Fantasy LitRPG Adventure: "
                    "Divine Apostasy, Book 1"
                ),
                "album_artist": "A. F. Kay",
            }
        )
        self.assertEqual(parsed["tag_series"], "Divine Apostasy")

    def test_genre_tag_is_captured_as_a_clue(self):
        # Local genre was never extracted into clues at all -- the "Local"
        # column in match-report cards always showed blank regardless of what
        # was actually embedded in the file.
        parsed = FIXER.parse_title_series_number_from_metadata(
            {"title": "Some Book", "album_artist": "Author", "genre": "Fantasy, Romance"}
        )
        self.assertEqual(parsed["genre"], "Fantasy, Romance")

    def test_release_bitrate_suffix_is_not_used_as_book_number(self):
        path = Path(
            "/library/Defiance of the Fall 15/"
            "Defiance_of_the_Fall_15_A_LitRPG_Adventure-AAX_44_128.m4b"
        )

        self.assertEqual(FIXER.extract_book_number_from_path(path), "15")

    def test_audible_subtitle_number_fills_missing_series_sequence(self):
        product = {
            "title": "Shade's First Rule",
            "subtitle": "Divine Apostasy, Book 1",
            "series": [{"title": "Divine Apostasy", "sequence": ""}],
        }

        self.assertEqual(FIXER.preferred_audible_sequence(product), "1")

    def test_exact_side_story_identity_can_override_catalog_numbering_difference(self):
        product = {
            "title": "Dominion",
            "subtitle": "A Coldfire Novella",
            "authors": [{"name": "C. S. Friedman"}],
            "narrators": [],
            "series": [{"title": "Coldfire", "sequence": "0"}],
            "runtime_length_min": 125,
        }
        clues = {
            "title": "0.5 - Dominion",
            "raw_title": "0.5 - Dominion",
            "author": "C.S. Friedman",
            "narrator": "",
            "series": "The Coldfire Trilogy",
            "book_number": "0.5",
            "book_number_source": "path",
            "local_duration_minutes": 126.09,
        }

        score = FIXER.score_product_for_metadata(
            clues,
            product,
            clues["local_duration_minutes"],
        )

        self.assertGreaterEqual(score, 0.8)

    def test_group_folder_removes_sequence_and_trailing_author(self):
        self.assertEqual(
            FIXER.clean_group_folder_title(
                "0 Feedback Dennis E. Taylor",
                "Dennis E. Taylor",
            ),
            "Feedback",
        )

    def test_series_number_title_pattern_does_not_use_known_author_as_title(self):
        path = Path("/library/Courts Magic Eater 4 - Sean Oswald.m4b")
        tags = {
            "title": "Courts",
            "album": "Courts",
            "album_artist": "Sean Oswald, Joshua Mason - editor",
            "grouping": "Magic Eater",
            "track": "4",
        }

        with patch.object(FIXER, "read_file_tags", return_value=tags):
            clues = FIXER.build_search_clues_from_file(path)

        self.assertEqual(clues["title"], "Courts")
        self.assertEqual(clues["series"], "Magic Eater")
        self.assertEqual(clues["book_number"], "4")

    def test_generic_book_folder_preserves_distinct_embedded_title_and_series(self):
        path = Path(
            "/library/Arcane Galaxy/Book 1 - Arcane Galaxy/Chaos Protocols.m4b"
        )
        tags = {
            "title": "Chaos Protocols",
            "album": "Chaos Protocols",
            "album_artist": "Troy Osgood, Jake Malory",
            "grouping": "Arcane Galaxy",
            "track": "1",
        }

        with patch.object(FIXER, "read_file_tags", return_value=tags):
            clues = FIXER.build_search_clues_from_file(path)

        self.assertEqual(clues["title"], "Chaos Protocols")
        self.assertEqual(clues["series"], "Arcane Galaxy")
        self.assertEqual(clues["book_number"], "1")

    def test_ranged_books_folder_does_not_replace_embedded_omnibus_identity(self):
        path = Path(
            "/library/The Beginning After The End/"
            "Books 1-2 - Early Years, New Heights/book.m4b"
        )
        tags = {
            "title": "The Beginning After the End: Publisher's Pack",
            "album_artist": "TurtleMe",
            "grouping": "The Beginning After the End",
        }

        with patch.object(FIXER, "read_file_tags", return_value=tags):
            clues = FIXER.build_search_clues_from_file(path)

        self.assertEqual(
            clues["title"],
            "The Beginning After the End: Publisher's Pack",
        )
        self.assertEqual(clues["series"], "The Beginning After the End")

    def test_embedded_book_list_file_stem_is_not_parsed_as_single_book(self):
        parsed = FIXER.parse_structured_book_text(
            "The Beginning After The End - Book 001, 002 - "
            "Early Years, New Heights",
            known_author="TurtleMe",
        )

        self.assertEqual(parsed, {})

    def test_author_series_book_title_path_recovers_swapped_metadata(self):
        path = Path(
            "/library/Icalos - Terminate the Other World!, Book 2 - "
            "A Glitch in the Protocols/"
            "Terminate the Other World!, Book 2 - A Glitch in the Protocols.m4b"
        )
        tags = {
            "title": "Icalos",
            "album_artist": "A Glitch in the Protocols",
            "grouping": "Terminate the Other World!",
            "track": "2",
        }

        with patch.object(FIXER, "read_file_tags", return_value=tags):
            clues = FIXER.build_search_clues_from_file(path)

        self.assertEqual(clues["title"], "A Glitch in the Protocols")
        self.assertEqual(clues["author"], "Icalos")
        self.assertEqual(clues["series"], "Terminate the Other World!")

    def test_series_only_rejects_unrelated_author_and_series(self):
        product = {
            "title": "The Shadow of the Torturer",
            "subtitle": "The Book of the New Sun, Book 1",
            "series": [{"title": "The Book of the New Sun", "sequence": "1"}],
            "authors": [{"name": "Gene Wolfe"}],
            "narrators": [{"name": "Jeff Hays"}],
            "runtime_length_min": 727,
        }
        clues = {
            "title": "The Apocalypse Will be Televised",
            "raw_title": "The Apocalypse Will be Televised",
            "author": "Matt Dinniman",
            "narrator": "Jeff Hays",
            "series": "Dungeon Crawler Carl",
            "book_number": "1",
            "book_number_source": "path",
            "local_duration_minutes": 811.57,
        }
        duration = FIXER.compare_duration(811.57, 727)

        self.assertEqual(
            FIXER.determine_edit_mode(product, clues, 0.8092, duration),
            "none",
        )

    def test_year_title_part_path_does_not_override_embedded_title(self):
        path = Path(
            "/library/2024 - Heart of the Machine A Humorous Isekai LitRPG (4)/"
            "Heart of the Machine A Humorous Isekai LitRPG (2024) - pt00.m4b"
        )
        tags = {
            "title": "Heart of the Machine: A Humorous Isekai LitRPG",
            "album": "Heart of the Machine: A Humorous Isekai LitRPG",
            "album_artist": "Icalos",
            "grouping": "Terminate the Other World!",
            "track": "4",
        }

        with patch.object(FIXER, "read_file_tags", return_value=tags):
            clues = FIXER.build_search_clues_from_file(path)

        self.assertEqual(
            clues["title"],
            "Heart of the Machine",
        )
        self.assertEqual(clues["series"], "Terminate the Other World!")
        self.assertEqual(clues["book_number"], "4")

    def test_series_only_never_preserves_author_as_title(self):
        product = {
            "asin": "TEST",
            "title": "Manipulation",
            "subtitle": "Magic Eater, Book 1",
            "series": [{"title": "Magic Eater", "sequence": "1"}],
            "authors": [{"name": "Sean Oswald"}],
            "narrators": [],
            "runtime_length_min": 100,
        }
        clues = {
            "title": "Sean Oswald",
            "raw_title": "Sean Oswald",
            "author": "Sean Oswald",
            "narrator": "",
            "series": "Magic Eater",
            "book_number": "1",
            "book_number_source": "path",
            "local_duration_minutes": 100,
        }

        metadata = FIXER.metadata_from_product(
            product,
            clues,
            1.0,
            requested_edit_mode="series_only",
        )

        self.assertEqual(metadata["title"], "Manipulation")

    def test_distinct_metadata_subtitle_replaces_series_only_path_title(self):
        with patch.object(
            ORGANIZER,
            "metadata_from_sidecar",
            return_value={
                "title": "1% Lifesteal: A LitRPG Adventure",
                "author": "Robert Blaise",
                "series": "1% Lifesteal",
                "book_number": "001",
                "sequence_label": "Book",
                "narrator": "",
                "source": "marker:test",
            },
        ), patch.object(
            ORGANIZER,
            "path_clues",
            return_value={
                "title": "1% Lifesteal",
                "book_number": "001",
                "sequence_label": "Book",
            },
        ):
            item = ORGANIZER.BookItem(
                "folder",
                Path("/library/1% Lifesteal Book 1"),
                [Path("/library/1% Lifesteal Book 1/book.m4b")],
                Path("/library/1% Lifesteal Book 1/book.m4b"),
            )
            metadata = ORGANIZER.infer_metadata(item, Path("/library"))

        self.assertEqual(metadata["title"], "1% Lifesteal")
        self.assertEqual(
            ORGANIZER.build_book_folder_name(metadata),
            "Book 1",
        )

    def test_fixer_prefers_series_title_over_marketing_only_difference(self):
        self.assertEqual(
            FIXER.choose_best_title(
                audible_title="1% Lifesteal",
                audible_series="1% Lifesteal",
                local_title="1% Lifesteal: A LitRPG Adventure",
            ),
            "1% Lifesteal",
        )

    def test_manual_mode_override_builds_distinct_previews(self):
        product = {
            "asin": "TEST",
            "title": "Audible Title",
            "subtitle": "",
            "series": [{"title": "Test Series", "sequence": "2"}],
            "authors": [{"name": "Test Author"}],
            "narrators": [{"name": "Test Narrator"}],
            "runtime_length_min": 100,
        }
        clues = {
            "title": "Local Title",
            "raw_title": "Local Title",
            "author": "Test Author",
            "narrator": "Local Narrator",
            "series": "Test Series",
            "book_number": "2",
            "book_number_source": "path",
            "local_duration_minutes": 100,
        }

        full = FIXER.metadata_from_product(
            product,
            clues,
            1.0,
            requested_edit_mode="full",
        )
        series_only = FIXER.metadata_from_product(
            product,
            clues,
            1.0,
            requested_edit_mode="series_only",
        )

        self.assertEqual(full["edit_mode"], "full")
        self.assertEqual(full["title"], "Audible Title")
        self.assertEqual(full["sequence"], "2")
        self.assertEqual(series_only["edit_mode"], "series_only")
        self.assertEqual(series_only["title"], "Local Title")
        self.assertEqual(series_only["sequence"], "")

    def test_metadata_series_plus_number_recovers_missing_sequence(self):
        self.assertEqual(
            ORGANIZER.metadata_series_suffix_number(
                "1% Lifesteal 03",
                "1% Lifesteal",
            ),
            "003",
        )

    def test_zero_padded_series_number_is_not_treated_as_subtitle(self):
        metadata = {
            "title": "1% Lifesteal 03",
            "series": "1% Lifesteal",
            "book_number": "003",
            "sequence_label": "Volume",
        }
        self.assertFalse(
            ORGANIZER.has_distinct_book_title(
                metadata["title"],
                metadata["series"],
                metadata["book_number"],
            )
        )
        self.assertEqual(
            ORGANIZER.build_book_folder_name(metadata),
            "Volume 3",
        )

    def test_series_sequence_metadata_is_not_treated_as_subtitle(self):
        self.assertFalse(
            ORGANIZER.has_distinct_book_title(
                "1% Lifesteal, Volume 2",
                "1% Lifesteal",
                "002",
            )
        )

    def test_loose_root_file_title_is_not_corrupted_by_scan_root_folder_name(self):
        """Regression (2026-07-04 matcher run): a loose file sitting directly
        in the scan root (no book-specific subfolder) ended up with
        clues["title"] == "unorganized" -- the literal scan-root folder name.

        Root cause was two stacked bugs:
        1. The descriptive-path title/author merge trusted a mis-parsed path
           author ("Anarchism Audiobook") as grounds to override the title
           whenever it happened to be a substring of the real title, even
           though it did not match the already-known real author
           ("Ruth Kinna"). That swapped title -> "Ruth Kinna", author stayed
           "Ruth Kinna" -- title == author, tripping is_invalid_local_title.
        2. recover_invalid_local_title()'s candidate list then tried
           file_path.parent.name ("_unorganized") unguarded against generic
           scan-root/staging folder names, and it passed every check.
        """
        path = Path(
            "/audiobooks/_unorganized/"
            "Ruth Kinna - Anarchism Audiobook - Bolinda Beginner Guides.mp3"
        )
        tags = {
            "album": "Anarchism: Bolinda Beginner Guides",
            "artist": "Ruth Kinna",
            "title": "Anarchism Audiobook - Bolinda Beginner Guides",
        }

        with patch.object(FIXER, "read_file_tags", return_value=tags):
            clues = FIXER.build_search_clues_from_file(path)

        self.assertNotEqual(clues["title"].strip().lower(), "unorganized")
        self.assertIn("anarchism", clues["title"].lower())
        self.assertEqual(clues["author"], "Ruth Kinna")

    def test_recover_invalid_local_title_skips_generic_scan_root_folder_name(self):
        """Direct unit test for bug 2 above, independent of bug 1's trigger."""
        clues = {
            "title": "",
            "author": "Ruth Kinna",
            "album": "",
        }
        path = Path("/audiobooks/_unorganized/some-book.mp3")

        recovered = FIXER.recover_invalid_local_title(dict(clues), path)

        self.assertNotEqual(recovered["title"].strip().lower(), "unorganized")


if __name__ == "__main__":
    unittest.main()
