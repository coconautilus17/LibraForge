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


class ExplicitEvidenceDetailTests(unittest.TestCase):
    def test_haremlit_no_label_reads_not_explicit_and_keeps_other_evidence(self):
        row = dict(ROW, flagged_explicit=True)
        out = book_explicit_evidence(row, {"haremlit": "No"})
        self.assertEqual(out["suggestion"], "not_explicit")
        self.assertEqual(out["evidence"], ["HaremLit wiki: not explicit", "Audible: adult / Erotica"])
        self.assertIs(out["check"], False)

    def test_haremlit_yes_label_reads_explicit(self):
        out = book_explicit_evidence(ROW, {"haremlit": "yes"})
        self.assertEqual(out["evidence"], ["HaremLit wiki: explicit"])
        self.assertIs(out["check"], False)

    def test_goodreads_evidence_reports_the_vote_count(self):
        row = dict(ROW, goodreads_explicit={"significant": True, "votes": 42})
        self.assertEqual(book_explicit_evidence(row, {})["evidence"], ["Goodreads: explicit shelves ×42"])

    def test_goodreads_evidence_without_a_vote_count_reports_zero(self):
        row = dict(ROW, goodreads_explicit={"significant": True})
        self.assertEqual(book_explicit_evidence(row, {})["evidence"], ["Goodreads: explicit shelves ×0"])

    def test_every_supporting_source_is_listed_in_order_and_makes_strength_supporting(self):
        row = dict(ROW, flagged_explicit=True, goodreads_explicit={"significant": True, "votes": 3},
                   sources={"openlibrary": ["erotica"]})
        out = book_explicit_evidence(row, {})
        self.assertEqual(out["evidence"], ["Audible: adult / Erotica", "Goodreads: explicit shelves ×3",
                                           "Open Library: erotica"])
        self.assertEqual((out["suggestion"], out["strength"]), ("unknown", "supporting"))

    def test_no_evidence_means_strength_none(self):
        out = book_explicit_evidence(ROW, {})
        self.assertEqual((out["suggestion"], out["strength"], out["evidence"]), ("unknown", "none", []))

    def test_harem_check_only_when_there_is_no_other_evidence(self):
        harem = dict(ROW, book_main=["Fantasy", "Harem"])
        self.assertIs(book_explicit_evidence(harem, {})["check"], True)
        self.assertIs(book_explicit_evidence(dict(harem, flagged_explicit=True), {})["check"], False)
        self.assertIs(book_explicit_evidence(dict(ROW, book_main=["Fantasy"]), {})["check"], False)
        self.assertIs(book_explicit_evidence(dict(ROW, book_main=None), {})["check"], False)
