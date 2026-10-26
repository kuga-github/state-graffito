import csv
from pathlib import Path
import tempfile
import unittest

from export_csv import export_table


class FakeCursor:
    description = (("id",), ("name",))

    def execute(self, query):
        self.query = query

    def __iter__(self):
        return iter(((1, "首相, 氏名"),))

    def close(self):
        pass


class FakeConnection:
    def cursor(self):
        self.last_cursor = FakeCursor()
        return self.last_cursor


class ExportCsvTests(unittest.TestCase):
    def test_exports_header_and_quoted_rows_as_utf8_csv(self):
        connection = FakeConnection()
        with tempfile.TemporaryDirectory() as temporary_dir:
            output_path = export_table(
                connection, "prime_ministers", Path(temporary_dir)
            )

            with output_path.open(encoding="utf-8-sig", newline="") as csv_file:
                rows = list(csv.reader(csv_file))

        self.assertEqual(connection.last_cursor.query, "SELECT * FROM `prime_ministers` ORDER BY 1")
        self.assertEqual(rows, [["id", "name"], ["1", "首相, 氏名"]])


if __name__ == "__main__":
    unittest.main()
