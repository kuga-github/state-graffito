"""Export the Diet bills table as a UTF-8 CSV file."""

import csv
import os
from pathlib import Path
import tempfile

from main import connect_database, ensure_schema

EXPORT_TABLES = ("diet_bills",)
EXPORT_COLUMNS = (
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
)


def export_table(
    connection,
    table_name: str,
    output_dir: Path,
) -> list[Path]:
    cursor = connection.cursor()
    temporary_paths: list[Path] = []
    try:
        columns = ", ".join(f"`{column}`" for column in EXPORT_COLUMNS)
        cursor.execute(
            f"SELECT {columns} FROM `{table_name}` ORDER BY 1, 2, 3, 4"
        )
        header = [column[0] for column in cursor.description]
        table_output_dir = output_dir / table_name
        table_output_dir.mkdir(parents=True, exist_ok=True)
        output_paths: list[Path] = []
        current_diet_number = None
        csv_file = None
        writer = None

        for row in cursor:
            diet_number = row[0]
            if diet_number != current_diet_number:
                if csv_file is not None:
                    csv_file.close()
                output_path = table_output_dir / f"{table_name}-{diet_number}.csv"
                file_descriptor, temporary_path_text = tempfile.mkstemp(
                    dir=table_output_dir,
                    prefix=f".{output_path.name}.",
                    suffix=".tmp",
                )
                csv_file = os.fdopen(
                    file_descriptor, "w", encoding="utf-8-sig", newline=""
                )
                temporary_path = Path(temporary_path_text)
                temporary_paths.append(temporary_path)
                writer = csv.writer(csv_file)
                writer.writerow(header)
                output_paths.append(output_path)
                current_diet_number = diet_number
            writer.writerow(row)

        if csv_file is not None:
            csv_file.close()

        for output_path, temporary_path in zip(output_paths, temporary_paths):
            temporary_path.chmod(0o644)
            temporary_path.replace(output_path)

        for stale_path in table_output_dir.glob(f"{table_name}-*.csv"):
            if stale_path not in output_paths:
                stale_path.unlink()
        for legacy_path in (
            output_dir / f"{table_name}.csv",
            *output_dir.glob(f"{table_name}-*.csv"),
        ):
            legacy_path.unlink(missing_ok=True)
        return output_paths
    finally:
        if csv_file is not None and not csv_file.closed:
            csv_file.close()
        for temporary_path in temporary_paths:
            temporary_path.unlink(missing_ok=True)
        cursor.close()


def main() -> None:
    output_dir = Path(os.getenv("CSV_OUTPUT_DIR", "/exports"))
    output_dir.mkdir(parents=True, exist_ok=True)

    connection = connect_database()
    try:
        ensure_schema(connection)
        for table_name in EXPORT_TABLES:
            output_paths = export_table(connection, table_name, output_dir)
            for output_path in output_paths:
                print(f"CSVを出力しました: {output_path}")
        connection.commit()
    finally:
        connection.close()


if __name__ == "__main__":
    main()
