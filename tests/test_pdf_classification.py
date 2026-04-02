import unittest
from pathlib import Path

from affil_classify import classify_from_pdf_with_stats
from pdf_affil import extract_core_author_affiliation_text

FIXTURES = Path(__file__).resolve().parent / "fixtures"


class PdfClassificationTest(unittest.TestCase):
    def test_extract_core_author_affiliation_text_prefers_top_author_block(self):
        pdf_path = FIXTURES / "simple_author_block.pdf"
        text = extract_core_author_affiliation_text(str(pdf_path), ["Alice Zhang", "Bob Li"])
        self.assertIn("Tsinghua University", text)
        self.assertNotIn("Body starts here", text)

    def test_extract_core_author_affiliation_text_handles_robotics_fixture(self):
        pdf_path = FIXTURES / "robotics_lab_block.pdf"
        text = extract_core_author_affiliation_text(str(pdf_path), ["Jane Doe", "John Roe"])
        self.assertIn("Toyota Research Institute", text)

    def test_extract_core_author_affiliation_text_scans_bottom_author_block(self):
        pdf_path = FIXTURES / "bottom_author_block.pdf"
        text = extract_core_author_affiliation_text(str(pdf_path), ["Alice Zhang", "Bob Li"])
        self.assertIn("University of Illinois Urbana-Champaign", text)
        self.assertIn("Corresponding author", text)

    def test_classify_from_pdf_with_stats_reports_matches_and_missing_pdf(self):
        pdf_path = FIXTURES / "simple_author_block.pdf"
        entries = [
            {
                "id": "http://arxiv.org/abs/2501.00001v1",
                "authors": ["Alice Zhang", "Bob Li"],
            },
            {
                "id": "http://arxiv.org/abs/2501.00002v1",
                "authors": ["Missing Author"],
            },
        ]
        buckets, stats = classify_from_pdf_with_stats(
            entries,
            {"2501.00001v1": str(pdf_path)},
        )

        self.assertIn("Tsinghua", buckets)
        self.assertEqual(len(buckets["Tsinghua"]), 1)
        self.assertEqual(stats["matched_entries"], 1)
        self.assertEqual(stats["missing_pdf"], 1)
        self.assertGreaterEqual(len(stats["errors"]), 1)


if __name__ == "__main__":
    unittest.main()
