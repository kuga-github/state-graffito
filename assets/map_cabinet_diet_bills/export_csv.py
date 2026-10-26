"""Export the cabinet-to-bill mapping table as a UTF-8 CSV file."""

import csv
import os
from pathlib import Path

from main import connect_database, ensure_schema


def main() -> None:
    output_dir = Path(os.getenv("CSV_OUTPUT_DIR", "/exports"))
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "cabinet_diet_bills.csv"

    connection = connect_database()
    try:
        ensure_schema(connection)
        cursor = connection.cursor()
        try:
            cursor.execute(
                """
                SELECT prime_minister_number, diet_number, category,
                       submission_session, bill_number
                FROM cabinet_diet_bills
                ORDER BY prime_minister_number, diet_number, category,
                         submission_session, bill_number
                """
            )
            with output_path.open("w", encoding="utf-8-sig", newline="") as csv_file:
                writer = csv.writer(csv_file)
                writer.writerow([column[0] for column in cursor.description])
                writer.writerows(cursor)
        finally:
            cursor.close()
    finally:
        connection.close()
    print(f"CSVを出力しました: {output_path}")


if __name__ == "__main__":
    main()
