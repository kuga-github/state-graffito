"""Create a denormalized prime minister mart from cabinet and Diet data."""

import logging
import os
from pathlib import Path

import mysql.connector

LOGGER = logging.getLogger("create_prime_minister_mart")


def connect_database() -> mysql.connector.MySQLConnection:
    return mysql.connector.connect(
        host=os.getenv("DB_HOST", "127.0.0.1"),
        port=int(os.getenv("DB_PORT", "3306")),
        database=os.getenv("DB_NAME", "state_graffito"),
        user=os.getenv("DB_USER", "state_graffito"),
        password=os.getenv("DB_PASSWORD", "state-graffito"),
        charset="utf8mb4",
        autocommit=False,
    )


def ensure_schema(connection: mysql.connector.MySQLConnection) -> None:
    schema_path = Path(__file__).resolve().parent / "db" / "init.sql"
    cursor = connection.cursor()
    try:
        for statement in schema_path.read_text(encoding="utf-8").split(";"):
            if statement.strip():
                cursor.execute(statement)
    finally:
        cursor.close()
    migrate_legacy_name_romaji(connection)


def migrate_legacy_name_romaji(connection: mysql.connector.MySQLConnection) -> None:
    cursor = connection.cursor()
    try:
        cursor.execute("SHOW COLUMNS FROM prime_minister_mart")
        columns = {row[0]: row for row in cursor.fetchall()}
        legacy_column = columns.get("name_romaji")
        if legacy_column is not None and legacy_column[2] == "NO":
            cursor.execute(
                "ALTER TABLE prime_minister_mart "
                "MODIFY COLUMN name_romaji VARCHAR(240) NULL"
            )
    finally:
        cursor.close()


def refresh_mart(connection: mysql.connector.MySQLConnection) -> int:
    cursor = connection.cursor()
    try:
        cursor.execute("DELETE FROM prime_minister_mart")
        cursor.execute(
            """
            INSERT INTO prime_minister_mart (
              prime_minister_number, name, name_kana, tenure_start_date, tenure_end_date,
              tenure_start_date_era, tenure_end_date_era, tenure_days,
              wiki_body, diet
            )
            SELECT
              pm.prime_minister_number,
              pm.name,
              pm.name_kana,
              pm.tenure_start_date,
              pm.tenure_end_date,
              pm.tenure_start_date_era,
              pm.tenure_end_date_era,
              pm.tenure_days,
              COALESCE(cw.wiki_body, ''),
              COALESCE(
                (
                  SELECT JSON_ARRAYAGG(
                    JSON_OBJECT(
                      'id', bills.id,
                      'diet_number', bills.diet_number,
                      'category', bills.category,
                      'submission_session', bills.submission_session,
                      'bill_number', bills.bill_number,
                      'bill_title', bills.bill_title,
                      'deliberation_status', bills.deliberation_status,
                      'date_gregorian', bills.date_gregorian,
                      'date_era', bills.date_era,
                      'bill_body', bills.bill_body,
                      'reference_information', bills.reference_information
                    )
                  )
                  FROM cabinet_diet_bills AS mapping
                  INNER JOIN diet_bills AS bills
                    ON bills.diet_number = mapping.diet_number
                   AND bills.category = mapping.category
                   AND bills.submission_session = mapping.submission_session
                   AND bills.bill_number = mapping.bill_number
                  WHERE mapping.prime_minister_number = pm.prime_minister_number
                ),
                JSON_ARRAY()
              )
            FROM prime_ministers AS pm
            LEFT JOIN cabinet_wiki AS cw
              ON cw.prime_minister_number = pm.prime_minister_number
            ORDER BY pm.prime_minister_number
            """
        )
        row_count = cursor.rowcount
        connection.commit()
        return row_count
    except Exception:
        connection.rollback()
        raise
    finally:
        cursor.close()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    connection = connect_database()
    try:
        ensure_schema(connection)
        row_count = refresh_mart(connection)
        LOGGER.info("%d件の総理大臣マートを作成しました。", row_count)
    finally:
        connection.close()


if __name__ == "__main__":
    main()
