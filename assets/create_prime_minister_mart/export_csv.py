"""Export each prime minister mart row as a UTF-8 CSV file."""

import csv
import os
from pathlib import Path

from main import connect_database, ensure_schema

TABLE_NAME = "prime_minister_mart"
EXPORT_COLUMNS = (
    "prime_minister_number",
    "name",
    "name_kana",
    "name_romaji",
    "tenure_start_date",
    "tenure_end_date",
    "tenure_start_date_era",
    "tenure_end_date_era",
    "tenure_days",
    "wiki_body",
    "diet",
)


def export_table(connection, output_dir: Path) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    cursor = connection.cursor()
    output_paths: list[Path] = []
    try:
        columns = ", ".join(f"`{column}`" for column in EXPORT_COLUMNS)
        cursor.execute(
            f"""
            SELECT {columns}
            FROM `{TABLE_NAME}`
            ORDER BY prime_minister_number
            """
        )
        header = [column[0] for column in cursor.description]
        for row in cursor:
            output_path = output_dir / f"cabinet-{row[0]}.csv"
            with output_path.open("w", encoding="utf-8-sig", newline="") as csv_file:
                writer = csv.writer(csv_file)
                writer.writerow(header)
                writer.writerow(row)
            output_paths.append(output_path)

        current_paths = set(output_paths)
        for stale_path in output_dir.glob("cabinet-*.csv"):
            if stale_path not in current_paths:
                stale_path.unlink()
        return output_paths
    finally:
        cursor.close()


def main() -> None:
    output_dir = Path(os.getenv("CSV_OUTPUT_DIR", "/exports")) / "mart"

    connection = connect_database()
    try:
        ensure_schema(connection)
        output_paths = export_table(connection, output_dir)
    finally:
        connection.close()
    for output_path in output_paths:
        print(f"CSVを出力しました: {output_path}")


if __name__ == "__main__":
    main()
