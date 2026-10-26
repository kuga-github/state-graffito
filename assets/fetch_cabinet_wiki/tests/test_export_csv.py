import csv
from pathlib import Path
import tempfile
import unittest

from export_csv import export_table


class FakeCursor:
    description = (("prime_minister_number",), ("cabinet_name",), ("wiki_body",))

    def execute(self, query):
        self.query = query

    def __iter__(self):
        return iter(((1, "第1次内閣", "<body>本文</body>"),))

    def close(self):
        pass


class FakeConnection:
    def cursor(self):
        self.last_cursor = FakeCursor()
        return self.last_cursor


class ExportCsvTests(unittest.TestCase):
    def test_exports_cabinet_wiki_columns_as_utf8_csv(self):
        connection = FakeConnection()
        with tempfile.TemporaryDirectory() as temporary_dir:
            output_path = export_table(connection, Path(temporary_dir))

            with output_path.open(encoding="utf-8-sig", newline="") as csv_file:
                rows = list(csv.reader(csv_file))

        self.assertEqual(output_path.name, "cabinet_wiki.csv")
        self.assertEqual(
            connection.last_cursor.query,
            "SELECT `prime_minister_number`, `cabinet_name`, `wiki_body` "
            "FROM `cabinet_wiki` ORDER BY prime_minister_number",
        )
        self.assertEqual(
            rows,
            [
                ["prime_minister_number", "cabinet_name", "wiki_body"],
                ["1", "第1次内閣", "<body>本文</body>"],
            ],
        )


if __name__ == "__main__":
    unittest.main()
