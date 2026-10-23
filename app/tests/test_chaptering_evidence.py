"""enrich_chapter_evidence attaches the transcript lines, word timings and
silences around each chapter start, which the AI review and the UI show as the
reason a chapter break was placed there."""
import unittest

from app.chaptering import TranscriptSegment, enrich_chapter_evidence


def chapter(start, **extra):
    return {"id": 1, "start": start, "source_text": "", **extra}


def seg(start, end, text, words=None):
    return TranscriptSegment(start=start, end=end, text=text, words=words or [])


class CapTests(unittest.TestCase):
    def test_the_lists_are_capped_at_120_lines_180_anchors_500_words_and_80_silences(self):
        ch = chapter(5000.0)
        segments = [seg(4900.0 + i * 0.5, 4900.2 + i * 0.5, f"line {i}",
                        [{"word": f"w{i}-{j}", "start": 4900.0 + i * 0.5 + j * 0.01, "end": 4900.0 + i * 0.5 + j * 0.01 + 0.005}
                         for j in range(4)])
                    for i in range(300)]
        silences = [(4900.0 + i, 4900.4 + i) for i in range(100)]
        enrich_chapter_evidence([ch], segments, silences)
        self.assertEqual(len(ch["evidence_text"].splitlines()), 120)
        self.assertEqual(len(ch["evidence_anchors"]), 180)
        self.assertEqual(len(ch["evidence_words"]), 500)
        self.assertEqual(len(ch["evidence_silences"]), 80)

if __name__ == "__main__":
    unittest.main()
