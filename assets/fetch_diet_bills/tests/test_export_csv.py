import csv
from pathlib import Path
import tempfile
import unittest

from export_csv import export_table


class FakeCursor:
    description = (
        ("diet_number",),
        ("category",),
        ("submission_session",),
        ("bill_number",),
        ("bill_title",),
        ("deliberation_status",),
        ("date_gregorian",),
        ("date_era",),
        ("bill_body",),
        ("reference_information",),
    )

    def __init__(self, rows=None):
        self.rows = rows or (
            (142, "閣法", 142, "1", "国会議案", "成立", None, None, None, None),
        )

    def execute(self, query):
        self.query = query

    def __iter__(self):
        return iter(self.rows)

    def close(self):
        pass


class FakeConnection:
    def __init__(self, rows=None):
        self.rows = rows

    def cursor(self):
        self.last_cursor = FakeCursor(self.rows)
        return self.last_cursor


class ExportCsvTests(unittest.TestCase):
    def test_exports_header_and_rows_as_utf8_csv(self):
        connection = FakeConnection()
        with tempfile.TemporaryDirectory() as temporary_dir:
            output_path = export_table(
                connection, "diet_bills", Path(temporary_dir)
            )[0]

            with output_path.open(encoding="utf-8-sig", newline="") as csv_file:
                rows = list(csv.reader(csv_file))

        self.assertEqual(
            connection.last_cursor.query,
            "SELECT `diet_number`, `category`, `submission_session`, `bill_number`, "
            "`bill_title`, `deliberation_status`, `date_gregorian`, `date_era`, "
            "`bill_body`, `reference_information` FROM `diet_bills` "
            "ORDER BY 1, 2, 3, 4",
        )
        self.assertEqual(
            rows,
            [
                [
                    "diet_number",
                    "category",
                    "submission_session",
                    "bill_number",
                    "bill_title",
                    "deliberation_status",
                    "date_gregorian",
                    "date_era",
                    "bill_body",
                    "reference_information",
                ],
                ["142", "閣法", "142", "1", "国会議案", "成立", "", "", "", ""],
            ],
        )

    def test_exports_each_diet_number_to_its_own_file(self):
        row_142 = (142, "閣法", 142, "1", "国会議案", "成立", None, None, None, None)
        row_143 = (143, "条約", 143, "2", "条約議案", "審議中", None, None, None, None)
        connection = FakeConnection((row_142, row_143))
        with tempfile.TemporaryDirectory() as temporary_dir:
            output_paths = export_table(
                connection,
                "diet_bills",
                Path(temporary_dir),
            )

            rows_by_file = []
            for output_path in output_paths:
                with output_path.open(encoding="utf-8-sig", newline="") as csv_file:
                    rows_by_file.append(list(csv.reader(csv_file)))

        self.assertEqual(
            [str(output_path.relative_to(temporary_dir)) for output_path in output_paths],
            ["diet_bills/diet_bills-142.csv", "diet_bills/diet_bills-143.csv"],
        )
        self.assertEqual(rows_by_file, [
            [
                [
                    "diet_number",
                    "category",
                    "submission_session",
                    "bill_number",
                    "bill_title",
                    "deliberation_status",
                    "date_gregorian",
                    "date_era",
                    "bill_body",
                    "reference_information",
                ],
                ["142", "閣法", "142", "1", "国会議案", "成立", "", "", "", ""],
            ],
            [
                [
                    "diet_number",
                    "category",
                    "submission_session",
                    "bill_number",
                    "bill_title",
                    "deliberation_status",
                    "date_gregorian",
                    "date_era",
                    "bill_body",
                    "reference_information",
                ],
                ["143", "条約", "143", "2", "条約議案", "審議中", "", "", "", ""],
            ],
        ])
if __name__ == "__main__":
    unittest.main()
