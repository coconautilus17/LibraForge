"""Explicit evidence for Enrichment Forge: the HaremLit wiki is the authority;
Audible adult/Erotica, Goodreads explicit shelves and Open Library erotica are
supporting evidence only; 'harem' alone is a check, not evidence."""
import unittest

from app.explicit_evidence import book_explicit_evidence, series_explicit_summary

ROW = {"flagged_explicit": False, "goodreads_explicit": None, "sources": {}, "book_main": [], "existing_explicit": False}


class ExplicitEvidenceTests(unittest.TestCase):
    def test_haremlit_yes_is_authoritative(self):
        e = book_explicit_evidence(ROW, {"haremlit": "Yes"})
        self.assertEqual((e["suggestion"], e["strength"]), ("explicit", "authoritative"))

    def test_haremlit_no_is_authoritative_not_explicit(self):
        e = book_explicit_evidence({**ROW, "flagged_explicit": True}, {"haremlit": "No"})
        self.assertEqual((e["suggestion"], e["strength"]), ("not_explicit", "authoritative"))

    def test_unrecognised_haremlit_value_is_not_a_verdict(self):
        self.assertEqual(book_explicit_evidence(ROW, {"haremlit": "Mild"})["suggestion"], "unknown")

    def test_supporting_signals_never_make_a_suggestion(self):
        e = book_explicit_evidence({**ROW, "flagged_explicit": True, "goodreads_explicit": {"significant": True, "votes": 9},
                                    "sources": {"openlibrary": ["erotica"]}}, {})
        self.assertEqual((e["suggestion"], e["strength"]), ("unknown", "supporting"))
        self.assertEqual(len(e["evidence"]), 3)

    def test_insignificant_goodreads_shelving_is_not_evidence(self):
        e = book_explicit_evidence({**ROW, "goodreads_explicit": {"significant": False, "votes": 2}}, {})
        self.assertEqual((e["strength"], e["evidence"]), ("none", []))

    def test_harem_alone_is_a_check_not_evidence(self):
        e = book_explicit_evidence({**ROW, "book_main": ["Fantasy", "Harem"]}, {})
        self.assertEqual((e["suggestion"], e["strength"], e["check"]), ("unknown", "none", True))

    def test_series_summary_flags_inconsistency(self):
        rows = [{**ROW, "existing_explicit": True}, {**ROW}, {**ROW}]
        s = series_explicit_summary([{**r, "explicit": book_explicit_evidence(r, {})} for r in rows])
        self.assertEqual((s["flagged_now"], s["total"], s["inconsistent"]), (1, 3, True))

    def test_series_summary_counts_suggestions(self):
        rows = [{**ROW, "explicit": book_explicit_evidence(ROW, {"haremlit": "Yes"})} for _ in range(2)]
        s = series_explicit_summary(rows)
        self.assertEqual((s["suggested_explicit"], s["suggested_not"], s["inconsistent"]), (2, 0, False))
