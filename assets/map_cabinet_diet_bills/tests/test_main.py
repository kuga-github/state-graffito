import unittest
from unittest.mock import MagicMock

from main import build_parser, refresh_mappings


class MapCabinetDietBillsTests(unittest.TestCase):
    def test_parser_accepts_requested_cabinet_range(self):
        args = build_parser().parse_args(["--from-number", "2", "--to-number", "5"])

        self.assertEqual((args.from_number, args.to_number), (2, 5))

    def test_refreshes_only_requested_generations_transactionally(self):
        connection = MagicMock()
        connection.cursor.return_value.rowcount = 3

        mapped_count = refresh_mappings(connection, 2, 5)

        self.assertEqual(mapped_count, 3)
        cursor = connection.cursor.return_value
        self.assertEqual(cursor.execute.call_count, 5)
        calls = cursor.execute.call_args_list
        self.assertIn("MAX(date_gregorian)", calls[1].args[0])
        self.assertIn("MAX(pm.prime_minister_number)", calls[1].args[0])
        self.assertEqual(calls[2].args[1], (2, 5, 2, 5))
        self.assertEqual(calls[3].args[1], (2, 5))
        self.assertIn("bills.diet_number = assignments.diet_number", calls[3].args[0])
        connection.commit.assert_called_once()
        connection.rollback.assert_not_called()

    def test_rolls_back_failed_mapping_refresh(self):
        connection = MagicMock()
        connection.cursor.return_value.execute.side_effect = [
            None,
            None,
            None,
            RuntimeError("insert failed"),
        ]

        with self.assertRaisesRegex(RuntimeError, "insert failed"):
            refresh_mappings(connection, 1, 1)

        connection.rollback.assert_called_once()
        connection.commit.assert_not_called()


if __name__ == "__main__":
    unittest.main()
