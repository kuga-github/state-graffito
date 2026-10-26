"""Map prime minister generations to bills submitted during their tenure."""

import argparse
import logging
import os
from pathlib import Path
from typing import Sequence

import mysql.connector

LOGGER = logging.getLogger("map_cabinet_diet_bills")


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


def refresh_mappings(
    connection: mysql.connector.MySQLConnection,
    from_number: int,
    to_number: int,
) -> int:
    cursor = connection.cursor()
    try:
        # 回次ごとの最新日が属する内閣を採用し、複数該当時は新しい代を選ぶ
        cursor.execute("DROP TEMPORARY TABLE IF EXISTS diet_cabinet_assignments")
        cursor.execute(
            """
            CREATE TEMPORARY TABLE diet_cabinet_assignments AS
            SELECT
              latest.diet_number,
              MAX(pm.prime_minister_number) AS prime_minister_number
            FROM (
              SELECT diet_number, MAX(date_gregorian) AS latest_date
              FROM diet_bills
              WHERE date_gregorian IS NOT NULL
              GROUP BY diet_number
            ) AS latest
            INNER JOIN prime_ministers AS pm
              ON latest.latest_date BETWEEN
                 pm.tenure_start_date AND pm.tenure_end_date
            GROUP BY latest.diet_number
            """
        )
        cursor.execute(
            """
            DELETE FROM cabinet_diet_bills
            WHERE prime_minister_number BETWEEN %s AND %s
               OR diet_number IN (
                 SELECT diet_number FROM diet_cabinet_assignments
                 WHERE prime_minister_number BETWEEN %s AND %s
               )
            """,
            (from_number, to_number, from_number, to_number),
        )
        cursor.execute(
            """
            INSERT INTO cabinet_diet_bills (
              prime_minister_number, diet_number, category,
              submission_session, bill_number
            )
            SELECT DISTINCT
              assignments.prime_minister_number,
              bills.diet_number,
              bills.category,
              bills.submission_session,
              bills.bill_number
            FROM diet_cabinet_assignments AS assignments
            INNER JOIN diet_bills AS bills
              ON bills.diet_number = assignments.diet_number
            WHERE assignments.prime_minister_number BETWEEN %s AND %s
            """,
            (from_number, to_number),
        )
        mapped_count = cursor.rowcount
        cursor.execute("DROP TEMPORARY TABLE diet_cabinet_assignments")
        connection.commit()
        return mapped_count
    except Exception:
        connection.rollback()
        raise
    finally:
        cursor.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="内閣の在職期間に該当する国会議案をDB内で対応づけます。"
    )
    parser.add_argument("--from-number", type=int, default=1, help="開始代数（既定: 1）")
    parser.add_argument("--to-number", type=int, required=True, help="終了代数")
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    args = build_parser().parse_args(argv)
    if args.from_number < 1 or args.to_number < 1:
        raise ValueError("代数は1以上を指定してください。")
    if args.from_number > args.to_number:
        raise ValueError("開始代数は終了代数以下にしてください。")

    connection = connect_database()
    try:
        ensure_schema(connection)
        mapped_count = refresh_mappings(connection, args.from_number, args.to_number)
        LOGGER.info(
            "第%d代から第%d代の対応表を%d件作成しました。",
            args.from_number,
            args.to_number,
            mapped_count,
        )
    finally:
        connection.close()


if __name__ == "__main__":
    main()
