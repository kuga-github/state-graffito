import csv
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from export_csv import EXPORT_COLUMNS, export_table


class ExportPrimeMinisterMartTests(unittest.TestCase):
    def test_exports_one_csv_per_cabinet_and_removes_stale_cabinet_exports(self):
        connection = MagicMock()
        cursor = connection.cursor.return_value
        cursor.description = [(column,) for column in EXPORT_COLUMNS]
        cursor.__iter__.return_value = iter(
            [
                (1, "総理大臣1", "そうり", "Prime Minister 1", "2020-01-01",
                 "2020-12-31", "令和2年1月1日", "令和2年12月31日", 365,
                 "<body>本文</body>", "[]"),
                (2, "総理大臣2", "そうり", "Prime Minister 2", "2021-01-01",
                 "2021-12-31", "令和3年1月1日", "令和3年12月31日", None,
                 "", "[]"),
            ]
        )

        with tempfile.TemporaryDirectory() as temporary_directory:
            output_dir = Path(temporary_directory)
            stale_path = output_dir / "cabinet-3.csv"
            stale_path.write_text("old", encoding="utf-8")
            unrelated_path = output_dir / "other.csv"
            unrelated_path.write_text("keep", encoding="utf-8")

            output_paths = export_table(connection, output_dir)

            self.assertEqual(
                [path.name for path in output_paths],
                ["cabinet-1.csv", "cabinet-2.csv"],
            )
            with output_paths[0].open(encoding="utf-8-sig", newline="") as csv_file:
                rows = list(csv.reader(csv_file))
            self.assertEqual(rows[0], list(EXPORT_COLUMNS))
            self.assertEqual(rows[1][0:2], ["1", "総理大臣1"])
            self.assertFalse(stale_path.exists())
            self.assertTrue(unrelated_path.exists())

        cursor.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
