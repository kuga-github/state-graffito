import unittest
from unittest.mock import MagicMock

from main import refresh_mart


class CreatePrimeMinisterMartTests(unittest.TestCase):
    def test_rebuilds_mart_with_wiki_and_mapped_diet_bills(self):
        connection = MagicMock()
        connection.cursor.return_value.rowcount = 3

        row_count = refresh_mart(connection)

        self.assertEqual(row_count, 3)
        cursor = connection.cursor.return_value
        self.assertEqual(cursor.execute.call_count, 2)
        self.assertEqual(cursor.execute.call_args_list[0].args[0], "DELETE FROM prime_minister_mart")
        insert_query = cursor.execute.call_args_list[1].args[0]
        self.assertIn("FROM prime_ministers AS pm", insert_query)
        self.assertIn("LEFT JOIN cabinet_wiki AS cw", insert_query)
        self.assertIn("FROM cabinet_diet_bills AS mapping", insert_query)
        self.assertIn("INNER JOIN diet_bills AS bills", insert_query)
        self.assertIn("'reference_information', bills.reference_information", insert_query)
        self.assertIn("COALESCE(cw.wiki_body, '')", insert_query)
        self.assertIn("JSON_ARRAY()", insert_query)
        connection.commit.assert_called_once()
        connection.rollback.assert_not_called()

    def test_rolls_back_failed_mart_refresh(self):
        connection = MagicMock()
        connection.cursor.return_value.execute.side_effect = [
            None,
            RuntimeError("insert failed"),
        ]

        with self.assertRaisesRegex(RuntimeError, "insert failed"):
            refresh_mart(connection)

        connection.rollback.assert_called_once()
        connection.commit.assert_not_called()


if __name__ == "__main__":
    unittest.main()
