"""Export application database tables as UTF-8 CSV files."""

import csv
import os
from pathlib import Path

from main import connect_database, ensure_schema

EXPORT_TABLES = ("character_paths", "prime_ministers", "cabinet_members")


def export_table(connection, table_name: str, output_dir: Path) -> Path:
    cursor = connection.cursor()
    try:
        cursor.execute(f"SELECT * FROM `{table_name}` ORDER BY 1")
        columns = [column[0] for column in cursor.description]
        excluded_columns = {"name_romaji"} if table_name == "prime_ministers" else set()
        included_indexes = [
            index
            for index, column in enumerate(columns)
            if column not in excluded_columns
        ]
        output_path = output_dir / f"{table_name}.csv"
        with output_path.open("w", encoding="utf-8-sig", newline="") as csv_file:
            writer = csv.writer(csv_file)
            writer.writerow([columns[index] for index in included_indexes])
            writer.writerows(
                tuple(row[index] for index in included_indexes) for row in cursor
            )
        return output_path
    finally:
        cursor.close()


def main() -> None:
    output_dir = Path(os.getenv("CSV_OUTPUT_DIR", "/exports"))
    output_dir.mkdir(parents=True, exist_ok=True)

    connection = connect_database()
    try:
        ensure_schema(connection)
        for table_name in EXPORT_TABLES:
            output_path = export_table(connection, table_name, output_dir)
            print(f"CSVを出力しました: {output_path}")
        connection.commit()
    finally:
        connection.close()


if __name__ == "__main__":
    main()
