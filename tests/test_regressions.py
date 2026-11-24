import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pdfplumber
import pandas as pd
import requests

from bvmac import database
from bvmac.download import download_day
from bvmac.extract import (
    FUND_COLUMNS,
    _compact_text, _date, _join_glyphs, bulletin_date, extract_bulletin,
    isin_checksum_valid, number,
)


FIXTURES = Path(__file__).parent / "fixtures"
PDF_FIXTURE_NAMES = (
    "BOC-BVMAC-22-06-2020.pdf",
    "BOC-BVMAC-08-01-2021.pdf",
    "BOC-20231115.pdf",
    "BOC-20251118.pdf",
    "BOC-20261118.pdf",
)
PDF_FIXTURES_AVAILABLE = all((FIXTURES / name).is_file() for name in PDF_FIXTURE_NAMES)


def requires_official_pdf_fixtures(test):
    """Skip real-bulletin tests when the non-redistributable PDFs are absent."""
    return unittest.skipUnless(
        PDF_FIXTURES_AVAILABLE,
        "Official BVMAC PDF fixtures are not distributed with this repository; "
        "see VALIDATION.md.",
    )(test)


class ParsingRegressionTests(unittest.TestCase):
    def test_number_date_text_and_isin_helpers(self):
        self.assertEqual(number("1.234.567"), 1234567)
        self.assertEqual(number("1,234,567"), 1234567)
        self.assertEqual(number("123-"), -123)
        self.assertEqual(number("−1 234,5"), -1234.5)
        self.assertEqual(_date("31-12-24"), "2024-12-31")
        self.assertIsNone(_date("not a date"))
        self.assertEqual(
            _compact_text("Capitalisation BOURSIÈRE ÉTATS PRIVÉES"),
            "CAPITALISATIONBOURSIEREETATSPRIVEES",
        )
        self.assertEqual(_join_glyphs("2020 2021"), "2020 2021")
        self.assertEqual(_join_glyphs("SOCIETE A CAPITAL"), "SOCIETE A CAPITAL")
        self.assertEqual(_join_glyphs("S O C A P A L M"), "SOCAPALM")
        self.assertTrue(isin_checksum_valid("GA0000020560"))
        self.assertFalse(isin_checksum_valid("GA0000020561"))

    @requires_official_pdf_fixtures
    def test_2020_and_2021_layout_counts(self):
        expected = {
            "BOC-BVMAC-22-06-2020.pdf": ("2020-06-22", 4, 12),
            "BOC-BVMAC-08-01-2021.pdf": ("2021-01-08", 4, 10),
        }
        for name, (day, equities, quotes) in expected.items():
            with self.subTest(name=name), pdfplumber.open(FIXTURES / name) as pdf:
                parsed = extract_bulletin(pdf)
                self.assertEqual(bulletin_date(pdf, name), day)
                self.assertEqual(len(parsed["equities"]), equities)
                self.assertEqual(len(parsed["bond_quotes"]), quotes)

    @requires_official_pdf_fixtures
    def test_2025_and_2026_bond_tables_are_complete(self):
        expected = {
            "BOC-20251118.pdf": (29, 29, 6),
            "BOC-20261118.pdf": (33, 33, 7),
        }
        for name, (quotes, issues, snapshots) in expected.items():
            with self.subTest(name=name), pdfplumber.open(FIXTURES / name) as pdf:
                parsed = extract_bulletin(pdf)
                self.assertEqual(len(parsed["bond_quotes"]), quotes)
                self.assertEqual(len(parsed["bond_issues"]), issues)
                self.assertEqual(len(parsed["issuer_snapshots"]), snapshots)
                self.assertIn("isin_valid", parsed["bond_quotes"])
                self.assertGreater(parsed["bond_issues"]["isin_valid"].eq(False).sum(), 0)

    @requires_official_pdf_fixtures
    def test_extractor_failure_does_not_discard_other_datasets(self):
        from bvmac import extract

        sample = FIXTURES / "BOC-BVMAC-22-06-2020.pdf"
        with pdfplumber.open(sample) as pdf, patch.object(
            extract, "extract_funds", side_effect=RuntimeError("layout regression")
        ):
            warnings = []
            parsed = extract.extract_bulletin(pdf, errors=warnings)
        self.assertEqual(len(parsed["equities"]), 4)
        self.assertEqual(len(parsed["bond_quotes"]), 12)
        self.assertTrue(parsed["funds"].empty)
        self.assertTrue(any("funds:" in warning for warning in warnings))

    @requires_official_pdf_fixtures
    def test_2023_layout_regression_counts(self):
        name = "BOC-20231115.pdf"
        with pdfplumber.open(FIXTURES / name) as pdf:
            parsed = extract_bulletin(pdf)
        self.assertEqual(len(parsed["equities"]), 6)
        self.assertEqual(len(parsed["bond_quotes"]), 11)
        self.assertEqual(len(parsed["bond_issues"]), 9)
        self.assertEqual(len(parsed["funds"]), 29)


class DatabaseRegressionTests(unittest.TestCase):
    def test_fund_frequency_is_part_of_key(self):
        with tempfile.TemporaryDirectory() as temp:
            db_path = Path(temp) / "funds.db"
            con = database.connect(db_path)
            empty = {name: pd.DataFrame(columns=columns)
                     for name, columns in database.DATASETS.items()}
            empty["funds"] = pd.DataFrame([
                {"management_company": "Manager", "custodian": "Bank", "fund_name": "Fund",
                 "frequency": frequency, "nav_current_date": "2026-11-18"}
                for frequency in ("daily", "weekly")
            ], columns=FUND_COLUMNS)
            database.save_bulletin(con, empty, "2026-11-18", "sample.pdf")
            self.assertEqual(con.execute("SELECT count(*) FROM funds").fetchone()[0], 2)
            self.assertIn("frequency", {row[1] for row in con.execute('PRAGMA table_info("funds")') if row[5]})
            con.close()

    def test_old_fund_key_is_backed_up_and_migrated(self):
        with tempfile.TemporaryDirectory() as temp:
            db_path = Path(temp) / "old.db"
            con = sqlite3.connect(db_path)
            try:
                con.execute("CREATE TABLE funds (date TEXT, management_company TEXT, custodian TEXT, "
                            "fund_name TEXT, frequency TEXT, nav_current_date TEXT, source_file TEXT, "
                            "PRIMARY KEY(date, management_company, custodian, fund_name, nav_current_date))")
                con.execute("INSERT INTO funds VALUES ('2026-11-18','M','C','F','daily','2026-11-18','old.pdf')")
                con.commit()
            finally:
                con.close()
            con = database.connect(db_path)
            try:
                pks = {row[1] for row in con.execute('PRAGMA table_info("funds")') if row[5]}
                self.assertIn("frequency", pks)
                self.assertEqual(con.execute("SELECT count(*) FROM funds").fetchone()[0], 1)
            finally:
                con.close()
            self.assertEqual(len(list(Path(temp).glob("old.pre-migration-*.bak"))), 1)

    def test_date_filters_accept_pandas_timestamps(self):
        with tempfile.TemporaryDirectory() as temp:
            db_path = Path(temp) / "data.db"
            con = database.connect(db_path)
            con.execute("INSERT INTO equities (date, mnemo, source_file) VALUES (?,?,?)",
                        ("2026-11-18", "SOCAP", "sample.pdf"))
            con.commit()
            con.close()
            result = database.load_equities(
                start=pd.Timestamp("2026-11-18"), end=pd.Timestamp("2026-11-18"), db_path=db_path
            )
            self.assertEqual(len(result), 1)


class DownloadRegressionTests(unittest.TestCase):
    def test_corrupt_cached_pdf_is_replaced_atomically(self):
        with tempfile.TemporaryDirectory() as temp:
            day = "2026-11-18"
            path = Path(temp) / "BOC-20261118.pdf"
            path.write_bytes(b"%PDF-truncated")
            response = requests.Response()
            response.status_code = 200
            response.url = "https://example.invalid/BOC-20261118.pdf"
            response._content = b"%PDF-1.4\n%%EOF"
            with patch("bvmac.download._SESSION.get", return_value=response) as get:
                result = download_day(day, folder=temp)
            self.assertEqual(result, path)
            self.assertEqual(path.read_bytes(), b"%PDF-1.4\n%%EOF")
            self.assertFalse(path.with_suffix(".pdf.part").exists())
            get.assert_called_once()


if __name__ == "__main__":
    unittest.main()

