"""Export the cabinet Wikipedia table as a UTF-8 CSV file."""

import csv
import os
from pathlib import Path

from main import connect_database, ensure_schema

TABLE_NAME = "cabinet_wiki"
EXPORT_COLUMNS = ("prime_minister_number", "cabinet_name", "wiki_body")


def export_table(connection, output_dir: Path) -> Path:
    cursor = connection.cursor()
    try:
        columns = ", ".join(f"`{column}`" for column in EXPORT_COLUMNS)
        cursor.execute(
            f"SELECT {columns} FROM `{TABLE_NAME}` ORDER BY prime_minister_number"
        )
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"{TABLE_NAME}.csv"
        with output_path.open("w", encoding="utf-8-sig", newline="") as csv_file:
            writer = csv.writer(csv_file)
            writer.writerow([column[0] for column in cursor.description])
            writer.writerows(cursor)
        return output_path
    finally:
        cursor.close()


def main() -> None:
    output_dir = Path(os.getenv("CSV_OUTPUT_DIR", "/exports"))
    connection = connect_database()
    try:
        ensure_schema(connection)
        output_path = export_table(connection, output_dir)
        print(f"CSVを出力しました: {output_path}")
        connection.commit()
    finally:
        connection.close()


if __name__ == "__main__":
    main()
