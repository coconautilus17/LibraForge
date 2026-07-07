import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app import main


class SidecarBookGenreTests(unittest.TestCase):
    """_read_sidecar_book's single-file fallback (marker.audible, used when
    there's no sidecar.book) used to hardcode genre to "" regardless of what
    was actually embedded in the file -- Manual Review would show a blank
    "Current" genre for a previously-processed single-file book even though
    its real genre was written correctly."""

    def test_single_file_marker_surfaces_real_genre(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            folder = Path(temp_dir)
            audio = folder / "Book.m4b"
            audio.write_bytes(b"")
            # _read_sidecar_book always reads the flat "libraforge.json" in the
            # parent folder -- a file alone in its own dedicated folder (not
            # sharing it with siblings) gets its marker written there directly.
            marker_path = folder / "libraforge.json"
            marker_path.write_text(json.dumps({
                "marker": {
                    "audible": {
                        "chosen_title": "Book",
                        "author": "Jane Doe",
                        "genre": "Fantasy",
                    },
                },
            }), encoding="utf-8")

            fixer_module = main.load_fixer_module(main.default_fixer_script())
            result = main._read_sidecar_book(audio, fixer_module)

        self.assertEqual(result["genre"], "Fantasy")

    def test_single_file_marker_surfaces_real_subtitle_summary_isbn(self):
        # Same hardcoded-blank bug as genre had, for three more fields that
        # write_marker now persists into marker.audible.
        with tempfile.TemporaryDirectory() as temp_dir:
            folder = Path(temp_dir)
            audio = folder / "Book.m4b"
            audio.write_bytes(b"")
            marker_path = folder / "libraforge.json"
            marker_path.write_text(json.dumps({
                "marker": {
                    "audible": {
                        "chosen_title": "Book",
                        "author": "Jane Doe",
                        "subtitle": "A Subtitle",
                        "summary": "A summary.",
                        "isbn": "9781234567890",
                    },
                },
            }), encoding="utf-8")

            fixer_module = main.load_fixer_module(main.default_fixer_script())
            result = main._read_sidecar_book(audio, fixer_module)

        self.assertEqual(result["subtitle"], "A Subtitle")
        self.assertEqual(result["summary"], "A summary.")
        self.assertEqual(result["isbn"], "9781234567890")

    def test_per_file_sidecar_surfaces_in_shared_dumping_ground_folder(self):
        # _unorganized-style folders hold many unrelated loose files sharing
        # one directory. The fixer writes each book's marker to its own
        # "<name>.libraforge.json" in that case, never the folder-level
        # "libraforge.json" (which would be ambiguous -- it could belong to
        # any of the sibling files). _read_sidecar_book used to only ever
        # check the folder-level path, so Manual Review's "Current" column
        # silently showed pre-apply data for every book in such a folder.
        with tempfile.TemporaryDirectory() as temp_dir:
            folder = Path(temp_dir)
            audio = folder / "Anarchism.mp3"
            audio.write_bytes(b"")
            (folder / "Some Other Book.mp3").write_bytes(b"")

            per_file_marker = folder / "Anarchism.mp3.libraforge.json"
            per_file_marker.write_text(json.dumps({
                "marker": {
                    "audible": {
                        "chosen_title": "Anarchism",
                        "author": "Ruth Kinna",
                        "narrator": "Miranda Nation",
                        "genre": "Politics",
                    },
                },
            }), encoding="utf-8")

            fixer_module = main.load_fixer_module(main.default_fixer_script())
            result = main._read_sidecar_book(audio, fixer_module)

        self.assertIsNotNone(result)
        self.assertEqual(result["title"], "Anarchism")
        self.assertEqual(result["author"], "Ruth Kinna")
        self.assertEqual(result["genre"], "Politics")


class PickGenreTests(unittest.TestCase):
    """_pick_genre used to return only the first non-generic genre, silently
    dropping the rest of a provider's multi-genre response."""

    def test_keeps_every_non_generic_genre(self):
        self.assertEqual(
            main._pick_genre(["Fantasy", "Romance", "Mystery"]),
            "Fantasy, Romance, Mystery",
        )

    def test_drops_only_the_blocklisted_generic_label(self):
        self.assertEqual(
            main._pick_genre(["Audiobook", "Fantasy", "Romance"]),
            "Fantasy, Romance",
        )

    def test_deduplicates_case_insensitively(self):
        self.assertEqual(main._pick_genre(["Fantasy", "fantasy", "Romance"]), "Fantasy, Romance")

    def test_all_generic_returns_empty(self):
        self.assertEqual(main._pick_genre(["Audiobook", "Audiobooks"]), "")


class ManualReviewApplyTests(unittest.TestCase):
    def test_grouped_manual_apply_writes_sidecar_with_existing_group(self):
        chapter_files = [
            "/library/Book/Part 01.m4a",
            "/library/Book/Part 02.mp3",
        ]
        group_search = {
            "applied": True,
            "folder": "/library/Book",
            "file_count": 2,
            "files": chapter_files,
        }
        context = {
            "source_path": chapter_files[0],
            "display_path": "/library/Book",
            "is_grouped": True,
            "group_search": group_search,
            "metadata": {
                "title": "Existing Title",
                "author": "Existing Author",
                "series": "Existing Series",
                "sequence": "2",
            },
        }
        written = {}

        def write_sidecar(source, metadata, clues, score, field_policy="legacy"):
            written["source"] = source
            written["metadata"] = metadata
            written["clues"] = clues
            written["score"] = score
            written["sidecar_field_policy"] = field_policy
            return Path("/library/Book/Book.m4b-tool-metadata.json")

        def write_meta_json(source, metadata, clues, alone, fill_missing=False, skip_blank_fields=False):
            written["meta_json_alone"] = alone
            return Path("/library/Book/metadata.json")

        def write_marker(**kwargs):
            written["marker_alone"] = kwargs.get("alone")

        fixer = SimpleNamespace(
            clean_text=lambda value: value,
            clean_author_value=lambda value: value,
            normalize_book_number=lambda value: value,
            should_write_json_sidecar=lambda source, clues: bool(
                clues.get("group_search", {}).get("applied")
            ),
            write_m4b_tool_metadata_sidecar=write_sidecar,
            write_audiobookshelf_metadata_json=write_meta_json,
            write_original_metadata_backup=lambda *a, **k: Path("/library/Book/libraforge.json"),
            write_tags=lambda *args, **kwargs: self.fail("grouped apply wrote tags"),
            write_marker=write_marker,
        )
        selected_result = {
            "score": 1.0,
            "title": "Matched Title",
            "sequence": "2",
            "year": "2024",
            "duration_minutes": 600,
            "allowed_edit_modes": ["full"],
            "chosen_metadata_by_mode": {
                "full": {
                    "asin": "B012345678",
                    "title": "Matched Title",
                    "author": "Matched Author",
                    "series": "Matched Series",
                    "sequence": "2",
                }
            },
        }
        request = main.ManualReviewApplyRequest(
            path="/library/Book",
            selected_result=selected_result,
            edit_mode="full",
        )

        with (
            patch.object(main, "inspect_manual_review_target", return_value=context),
            patch.object(main, "load_fixer_module", return_value=fixer),
        ):
            result = main.apply_manual_review_result(request)

        self.assertEqual(result["output_kind"], "json_sidecar")
        self.assertEqual(written["source"], Path(chapter_files[0]))
        self.assertEqual(written["clues"]["group_search"], group_search)
        self.assertEqual(
            written["clues"]["group_search"]["files"],
            chapter_files,
        )
        # A grouped book routes folder-level (alone=False; the group_search clue
        # forces folder placement) and still writes a metadata.json.
        self.assertFalse(written["marker_alone"])
        self.assertFalse(written["meta_json_alone"])
        self.assertEqual(result["metadata_json_path"], "/library/Book/metadata.json")
        # write_policy threads through to the sidecar builder too, so its
        # ASIN survivor-fallback can be policy-aware (see
        # M4bToolSidecarAsinFieldPolicyTests in test_fixer_v5_field_policy.py).
        self.assertEqual(written["sidecar_field_policy"], "fill")


class WritePolicyTests(unittest.TestCase):
    """Reproduces the reported bug: matching a book against the wrong catalog
    entry, clearing every dialog field but one, and applying -- must not
    silently write the match's own values for the cleared fields. Once the
    frontend sends an explicit "" override for a cleared field (fixed in
    app/static/app.js), apply_manual_review_result must (a) actually use that
    blank instead of the match's original value, and (b) thread write_policy
    through to every writer so "fill" leaves it untouched on disk and
    "overwrite" clears it. See docs/design/manual-review-apply-rewrite-rules.md.
    """

    def _context(self):
        return {
            "source_path": "/library/Dragon Conjurer 8/book.m4b",
            "display_path": "/library/Dragon Conjurer 8",
            "is_grouped": False,
            "metadata": {
                "title": "Dragon Conjurer 8",
                "author": "Eric Vall",
                "narrator": "Real Narrator",
                "series": "Dragon Conjurer",
                "sequence": "8",
                "genre": "Fantasy",
            },
        }

    def _selected_result(self):
        # The wrong match: Audible only has book 1.
        return {
            "score": 0.4,
            "title": "Dragon Conjurer",
            "sequence": "1",
            "year": "2019",
            "duration_minutes": 400,
            "allowed_edit_modes": ["full"],
            "chosen_metadata_by_mode": {
                "full": {
                    "asin": "B0WRONGBOOK1",
                    "title": "Dragon Conjurer",
                    "author": "Eric Vall",
                    "series": "Dragon Conjurer",
                    "sequence": "1",
                    "narrator": "Real Narrator",
                }
            },
        }

    def _fixer(self, written: dict, mutagen_candidate: bool = True):
        return SimpleNamespace(
            FILL_FIELDS=("title", "author", "series", "sequence", "narrator", "year", "asin", "genre", "subtitle"),
            clean_text=lambda value: value,
            clean_author_value=lambda value: value,
            normalize_book_number=lambda value: value,
            should_write_json_sidecar=lambda source, clues: False,
            is_mutagen_mp4_candidate=lambda source: mutagen_candidate,
            is_mutagen_mp3_candidate=lambda source: False,
            write_audiobookshelf_metadata_json=lambda source, metadata, clues, alone, fill_missing=False, skip_blank_fields=False: (
                written.setdefault("meta_json_skip_blank", skip_blank_fields),
                Path("/library/Dragon Conjurer 8/metadata.json"),
            )[1],
            write_tags=lambda source, metadata, **kwargs: written.update(
                tags_metadata=metadata, tags_field_policy=kwargs.get("field_policy")
            ),
            write_marker=lambda **kwargs: written.update(marker_kwargs=kwargs),
        )

    def _request(self, write_policy: str, metadata_override: dict):
        return main.ManualReviewApplyRequest(
            path="/library/Dragon Conjurer 8",
            selected_result=self._selected_result(),
            edit_mode="full",
            write_policy=write_policy,
            metadata_override=metadata_override,
        )

    def test_explicit_blank_override_is_not_silently_ignored(self):
        # Simulates the fixed frontend: clearing a field sends an explicit ""
        # override rather than omitting the key (which would fall back to
        # the wrong match's own value). Title/author are required by
        # apply_manual_review_result's own validation (a book needs a title),
        # so this mirrors the realistic case: series/sequence/asin/genre
        # cleared, title/author/narrator left as the match provided.
        written = {}
        req = self._request(
            "fill",
            {"series": "", "sequence": "", "asin": "", "genre": ""},
        )
        with (
            patch.object(main, "inspect_manual_review_target", return_value=self._context()),
            patch.object(main, "load_fixer_module", return_value=self._fixer(written)),
        ):
            main.apply_manual_review_result(req)

        metadata = written["tags_metadata"]
        self.assertEqual(metadata["series"], "")
        self.assertEqual(metadata["sequence"], "")
        self.assertEqual(metadata["asin"], "")
        self.assertEqual(metadata["genre"], "")
        # Narrator was never overridden -- keeps the match's (correct) value.
        self.assertEqual(metadata["narrator"], "Real Narrator")

    def test_fill_and_overwrite_thread_field_policy_to_every_writer(self):
        written = {}
        req = self._request("fill", {"series": "", "sequence": ""})
        with (
            patch.object(main, "inspect_manual_review_target", return_value=self._context()),
            patch.object(main, "load_fixer_module", return_value=self._fixer(written)),
        ):
            main.apply_manual_review_result(req)
        self.assertEqual(written["tags_field_policy"], "fill")
        self.assertEqual(written["marker_kwargs"]["field_policy"], "fill")
        self.assertTrue(written["meta_json_skip_blank"])

        written2 = {}
        req2 = self._request("overwrite", {"series": "", "sequence": ""})
        with (
            patch.object(main, "inspect_manual_review_target", return_value=self._context()),
            patch.object(main, "load_fixer_module", return_value=self._fixer(written2)),
        ):
            main.apply_manual_review_result(req2)
        self.assertEqual(written2["tags_field_policy"], "overwrite")
        self.assertEqual(written2["marker_kwargs"]["field_policy"], "overwrite")
        self.assertFalse(written2["meta_json_skip_blank"])

    def test_written_fields_recorded_so_marker_skip_is_clean_on_next_scan(self):
        # Bug: apply_manual_review_result never passed written_fields to
        # write_marker, so every manual apply produced written_fields=[] even
        # though tags were actually written. marker_skip_is_clean() treats a
        # non-blank real ASIN missing from written_fields as "not clean",
        # routing the book into the scan's recovery path on the very next
        # run -- surfacing a "would write" badge in the report for a book
        # that was already correctly applied. Mirrors the CLI's own
        # written_fields computation (audible-metadata-fixer-v5.py, WRITE_ACTION_JSON).
        written = {}
        req = self._request("fill", {})
        with (
            patch.object(main, "inspect_manual_review_target", return_value=self._context()),
            patch.object(main, "load_fixer_module", return_value=self._fixer(written)),
        ):
            main.apply_manual_review_result(req)

        written_fields = set(written["marker_kwargs"]["written_fields"])
        self.assertIn("asin", written_fields)
        self.assertIn("title", written_fields)
        self.assertIn("author", written_fields)
        self.assertIn("series", written_fields)
        self.assertIn("sequence", written_fields)
        self.assertIn("narrator", written_fields)
        # Fields the match never supplied stay unrecorded.
        self.assertNotIn("genre", written_fields)
        self.assertNotIn("year", written_fields)

    def test_written_fields_is_none_when_only_json_sidecar_was_written(self):
        # A json-sidecar-only apply never touches embedded tags, so nothing
        # should be claimed as "written" for marker_skip_is_clean purposes.
        written = {}
        req = self._request("fill", {})
        fixer = self._fixer(written)
        fixer.should_write_json_sidecar = lambda source, clues: True
        fixer.write_m4b_tool_metadata_sidecar = lambda source, metadata, clues, score, **kwargs: Path(
            "/library/Dragon Conjurer 8/sidecar.json"
        )
        with (
            patch.object(main, "inspect_manual_review_target", return_value=self._context()),
            patch.object(main, "load_fixer_module", return_value=fixer),
        ):
            main.apply_manual_review_result(req)

        self.assertIsNone(written["marker_kwargs"]["written_fields"])

    def test_clues_current_is_populated_from_context_metadata(self):
        # Previously always {} on the manual-apply path -- silently broke
        # write_marker's survivor-fallback for every manual apply.
        written = {}
        req = self._request("fill", {})
        with (
            patch.object(main, "inspect_manual_review_target", return_value=self._context()),
            patch.object(main, "load_fixer_module", return_value=self._fixer(written)),
        ):
            main.apply_manual_review_result(req)

        clues = written["marker_kwargs"]["clues"]
        self.assertEqual(clues["current"], self._context()["metadata"])

    def test_ffmpeg_fallback_surfaces_warning_instead_of_silent_or_reject(self):
        written = {}
        req = self._request("overwrite", {})
        with (
            patch.object(main, "inspect_manual_review_target", return_value=self._context()),
            patch.object(main, "load_fixer_module", return_value=self._fixer(written, mutagen_candidate=False)),
        ):
            result = main.apply_manual_review_result(req)

        self.assertIn("warning", result)
        self.assertIn("ffmpeg", result["warning"].lower())

    def test_invalid_write_policy_is_rejected(self):
        req = self._request("fill", {})
        req.write_policy = "delete_everything"
        with self.assertRaises(Exception):
            main.apply_manual_review_result(req)


if __name__ == "__main__":
    unittest.main()
