"""Fetch Japanese Diet bills from the House of Representatives website."""

import argparse
from dataclasses import dataclass
from datetime import date
import logging
import os
from pathlib import Path
import re
import time
from typing import Callable, Iterator, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen

import mysql.connector
from bs4 import BeautifulSoup

INDEX_URL = (
    "https://www.shugiin.go.jp/internet/itdb_gian.nsf/html/gian/kaiji{number}.htm"
)
USER_AGENT = "state-graffito-fetch-diet-bills/1.0"
FETCH_TIMEOUT_SECONDS = 60
FETCH_MAX_ATTEMPTS = 3
RETRYABLE_HTTP_STATUS_CODES = {408, 425, 429, 500, 502, 503, 504}
CATEGORIES = {"閣法", "条約", "予算", "決議"}
ERA_OFFSETS = {
    "文化": 1803,
    "文政": 1817,
    "天保": 1829,
    "弘化": 1843,
    "嘉永": 1847,
    "安政": 1853,
    "万延": 1859,
    "文久": 1860,
    "元治": 1863,
    "慶応": 1864,
    "慶應": 1864,
    "明治": 1867,
    "大正": 1911,
    "昭和": 1925,
    "平成": 1988,
    "令和": 2018,
}
ERA_DATE_PATTERN = re.compile(
    r"(文化|文政|天保|弘化|嘉永|安政|万延|文久|元治|慶應|慶応|明治|大正|昭和|平成|令和)"
    r"\s*(元|\d+)年\s*(\d{1,2})月\s*(\d{1,2})日"
)
LOGGER = logging.getLogger("fetch_diet_bills")


@dataclass(frozen=True)
class BillRow:
    diet_number: int
    category: str
    submission_session: int
    bill_number: str
    bill_title: str | None
    deliberation_status: str | None
    history_url: str | None
    body_url: str | None


@dataclass(frozen=True)
class DietBill:
    diet_number: int
    category: str
    submission_session: int
    bill_number: str
    bill_title: str | None
    deliberation_status: str | None
    date_gregorian: date | None
    date_era: str | None
    bill_body: str | None
    reference_information: str | None


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.replace("\u3000", " ")).strip()


def decode_page(data: bytes, charset: str, url: str) -> str:
    try:
        return data.decode(charset)
    except UnicodeDecodeError as error:
        normalized_charset = charset.lower().replace("_", "-")
        if normalized_charset in {"shift-jis", "shiftjis", "sjis", "x-sjis"}:
            try:
                return data.decode("cp932")
            except UnicodeDecodeError as fallback_error:
                raise RuntimeError(
                    f"衆議院ページの文字コードを解釈できません: {url}: "
                    f"{charset} / cp932: {fallback_error}"
                ) from fallback_error
        raise RuntimeError(
            f"衆議院ページの文字コードを解釈できません: {url}: "
            f"{charset}: {error}"
        ) from error


def fetch_page(url: str) -> str:
    request = Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(1, FETCH_MAX_ATTEMPTS + 1):
        try:
            with urlopen(request, timeout=FETCH_TIMEOUT_SECONDS) as response:
                charset = response.headers.get_content_charset() or "utf-8"
                return decode_page(response.read(), charset, url)
        except HTTPError as error:
            if error.code not in RETRYABLE_HTTP_STATUS_CODES:
                raise RuntimeError(
                    f"衆議院ページの取得に失敗しました: {url}: {error}"
                ) from error
            last_error = error
        except (URLError, TimeoutError) as error:
            last_error = error

        if attempt == FETCH_MAX_ATTEMPTS:
            raise RuntimeError(
                f"衆議院ページの取得に{FETCH_MAX_ATTEMPTS}回失敗しました: "
                f"{url}: {last_error}"
            ) from last_error

        delay = 2 ** (attempt - 1)
        LOGGER.warning(
            "ページ取得に失敗しました。%d/%d回目を再試行します（%d秒後）: %s: %s",
            attempt,
            FETCH_MAX_ATTEMPTS,
            delay,
            url,
            last_error,
        )
        time.sleep(delay)


def parse_era_date(value: str) -> date:
    match = ERA_DATE_PATTERN.search(value)
    if match is None:
        raise ValueError(f"和暦の日付を解釈できません: {value}")

    era, year_text, month_text, day_text = match.groups()
    year = 1 if year_text == "元" else int(year_text)
    return date(
        ERA_OFFSETS[era] + year,
        int(month_text),
        int(day_text),
    )


def extract_body_html(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    body = soup.body
    if body is None:
        raise ValueError("取得したHTMLにbody要素がありません。")

    for element in body.select("script, style, link, noscript"):
        element.decompose()

    content_start = body.find(id="TopContents")
    source_nodes = (
        [content_start, *content_start.find_next_siblings()]
        if content_start is not None
        else list(body.contents)
    )
    content = BeautifulSoup("<body></body>", "html.parser")
    for node in source_nodes:
        fragment = BeautifulSoup(str(node), "html.parser")
        for child in list(fragment.contents):
            content.body.append(child)

    for element in content.find_all(True):
        for attribute in ("id", "class", "style", "tabindex"):
            element.attrs.pop(attribute, None)

    return str(content.body)


def extract_bill_rows(html: str, diet_number: int, index_url: str) -> list[BillRow]:
    soup = BeautifulSoup(html, "html.parser")
    rows: list[BillRow] = []

    for table in soup.find_all("table"):
        caption = table.find("caption")
        if caption is None:
            continue
        caption_text = normalize_text(caption.get_text(" ", strip=True))
        category_match = re.fullmatch(r"(.+?)の一覧", caption_text)
        if category_match is None or category_match.group(1) not in CATEGORIES:
            continue
        category = category_match.group(1)

        headers = [
            normalize_text(cell.get_text(" ", strip=True))
            for cell in table.find_all("th")
        ]
        required_headers = ("提出回次", "番号", "議案件名", "審議状況")
        if any(header not in headers for header in required_headers):
            raise ValueError(f"{category}の一覧に必要な列がありません。")
        positions = {header: headers.index(header) for header in headers}

        for table_row in table.find_all("tr"):
            cells = table_row.find_all(["th", "td"], recursive=False)
            if not cells or any(cell.name == "th" for cell in cells):
                continue
            if len(cells) < len(headers):
                raise ValueError(f"{category}の一覧に列数が不足する行があります。")

            def cell_text(header: str) -> str:
                return normalize_text(cells[positions[header]].get_text(" ", strip=True))

            def cell_url(header: str) -> str | None:
                link = cells[positions[header]].find("a", href=True)
                return urljoin(index_url, link["href"]) if link else None

            try:
                submission_session = int(cell_text("提出回次"))
            except ValueError as error:
                raise ValueError(f"{category}の一覧に提出回次が不正な行があります。") from error
            bill_number = cell_text("番号")

            title = cell_text("議案件名")
            status = cell_text("審議状況")

            rows.append(
                BillRow(
                    diet_number=diet_number,
                    category=category,
                    submission_session=submission_session,
                    bill_number=bill_number,
                    bill_title=title or None,
                    deliberation_status=status or None,
                    history_url=cell_url("経過情報") if "経過情報" in positions else None,
                    body_url=cell_url("本文情報") if "本文情報" in positions else None,
                )
            )

    return rows


def latest_date_from_history(html: str) -> tuple[date | None, str | None]:
    soup = BeautifulSoup(html, "html.parser")
    history_table = None
    for table in soup.find_all("table"):
        first_row = table.find("tr")
        if first_row is None:
            continue
        first_row_text = {
            normalize_text(cell.get_text(" ", strip=True))
            for cell in first_row.find_all(["th", "td"], recursive=False)
        }
        if {"項目", "内容"}.issubset(first_row_text):
            history_table = table
            break
    if history_table is None:
        raise ValueError("議案の経過情報テーブルが見つかりません。")

    dates: list[tuple[date, str]] = []
    for cell in history_table.find_all(["th", "td"]):
        text = normalize_text(cell.get_text(" ", strip=True))
        for match in ERA_DATE_PATTERN.finditer(text):
            era_text = re.sub(r"\s+", "", match.group())
            dates.append((parse_era_date(era_text), era_text))
    if not dates:
        return None, None
    return max(dates, key=lambda item: item[0])


def extract_reference_urls(body_html: str, body_url: str) -> list[str]:
    soup = BeautifulSoup(body_html, "html.parser")
    heading = soup.find(
        lambda tag: tag.name in {"h2", "h3"}
        and "照会できる情報の一覧" in normalize_text(tag.get_text(" ", strip=True))
    )
    if heading is None:
        return []
    reference_list = heading.find_next("ul")
    if reference_list is None:
        return []
    return [
        urljoin(body_url, link["href"])
        for link in reference_list.select("a[href]")
        if link["href"].strip()
    ]


def iter_diet_bills(
    diet_number: int, page_fetcher: Callable[[str], str] = fetch_page
) -> Iterator[DietBill]:
    index_url = INDEX_URL.format(number=diet_number)
    rows = extract_bill_rows(page_fetcher(index_url), diet_number, index_url)

    for row in rows:
        if row.history_url is None:
            date_gregorian, date_era = None, None
        else:
            date_gregorian, date_era = latest_date_from_history(
                page_fetcher(row.history_url)
            )

        bill_body = None
        reference_information = None
        if row.body_url is not None:
            body_page = page_fetcher(row.body_url)
            bill_body = extract_body_html(body_page)
            reference_bodies = [
                extract_body_html(page_fetcher(reference_url))
                for reference_url in extract_reference_urls(bill_body, row.body_url)
            ]
            if reference_bodies:
                reference_information = "\n\n".join(reference_bodies)

        yield DietBill(
            diet_number=row.diet_number,
            category=row.category,
            submission_session=row.submission_session,
            bill_number=row.bill_number,
            bill_title=row.bill_title,
            deliberation_status=row.deliberation_status,
            date_gregorian=date_gregorian,
            date_era=date_era,
            bill_body=bill_body,
            reference_information=reference_information,
        )


def collect_diet_bills(
    diet_number: int, page_fetcher: Callable[[str], str] = fetch_page
) -> list[DietBill]:
    return list(iter_diet_bills(diet_number, page_fetcher))


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
    migrate_schema(connection)


def migrate_schema(connection: mysql.connector.MySQLConnection) -> None:
    cursor = connection.cursor()
    try:
        cursor.execute("SHOW COLUMNS FROM diet_bills")
        columns = {row[0]: row for row in cursor.fetchall()}
        if "id" not in columns:
            cursor.execute(
                """
                ALTER TABLE diet_bills
                  ADD COLUMN id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT UNIQUE FIRST
                """
            )

        cursor.execute("SHOW INDEX FROM diet_bills")
        indexes = cursor.fetchall()
        primary_columns = [
            row[4]
            for row in sorted(
                (row for row in indexes if row[2] == "PRIMARY"),
                key=lambda row: row[3],
            )
        ]
        if primary_columns != ["id"]:
            if primary_columns:
                cursor.execute("ALTER TABLE diet_bills DROP PRIMARY KEY")
            cursor.execute("ALTER TABLE diet_bills ADD PRIMARY KEY (id)")

        nullable_changes = [
            f"MODIFY COLUMN {name} {column_type} NULL"
            for name, column_type in (
                ("bill_title", "VARCHAR(600)"),
                ("deliberation_status", "VARCHAR(255)"),
            )
            if columns[name][2] != "YES"
        ]
        if nullable_changes:
            cursor.execute(f"ALTER TABLE diet_bills {', '.join(nullable_changes)}")

        if not any(row[2] == "idx_diet_bills_lookup" for row in indexes):
            cursor.execute(
                """
                ALTER TABLE diet_bills
                  ADD KEY idx_diet_bills_lookup (
                    diet_number, category, submission_session, bill_number
                  )
                """
            )
    finally:
        cursor.close()


def save_bill(connection: mysql.connector.MySQLConnection, bill: DietBill) -> None:
    cursor = connection.cursor()
    try:
        identity = """
            diet_number = %s
            AND category = %s
            AND submission_session = %s
            AND bill_number = %s
        """
        identity_values: tuple[object, ...] = (
            bill.diet_number,
            bill.category,
            bill.submission_session,
            bill.bill_number,
        )
        if not bill.bill_number:
            identity += " AND bill_title <=> %s AND deliberation_status <=> %s"
            identity_values += (bill.bill_title, bill.deliberation_status)
        cursor.execute(
            f"SELECT id FROM diet_bills WHERE {identity} ORDER BY id LIMIT 1",
            identity_values,
        )
        existing = cursor.fetchone()
        values = (
            bill.bill_title,
            bill.deliberation_status,
            bill.date_gregorian,
            bill.date_era,
            bill.bill_body,
            bill.reference_information,
        )
        if existing:
            cursor.execute(
                """
                UPDATE diet_bills
                SET bill_title = %s,
                    deliberation_status = %s,
                    date_gregorian = %s,
                    date_era = %s,
                    bill_body = %s,
                    reference_information = %s
                WHERE id = %s
                """,
                (*values, existing[0]),
            )
        else:
            cursor.execute(
                """
                INSERT INTO diet_bills (
                  diet_number, category, submission_session, bill_number,
                  bill_title, deliberation_status, date_gregorian, date_era,
                  bill_body, reference_information
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    bill.diet_number,
                    bill.category,
                    bill.submission_session,
                    bill.bill_number,
                    *values,
                ),
            )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        cursor.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="指定した国会回次の閣法・条約・予算・決議を取得してDBに保存します。"
    )
    parser.add_argument("--from-number", type=int, default=1, help="取得範囲の開始回次（既定: 1）")
    parser.add_argument("--to-number", type=int, required=True, help="取得範囲の終了回次")
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    args = build_parser().parse_args(argv)
    if args.from_number < 1 or args.to_number < 1:
        raise ValueError("国会回次は1以上を指定してください。")
    if args.from_number > args.to_number:
        raise ValueError("開始回次は終了回次以下にしてください。")

    connection = connect_database()
    try:
        ensure_schema(connection)
        bill_count = 0
        for diet_number in range(args.from_number, args.to_number + 1):
            LOGGER.info("第%d回国会の議案を取得しています。", diet_number)
            for bill in iter_diet_bills(diet_number):
                save_bill(connection, bill)
                bill_count += 1
                LOGGER.info(
                    "第%d回国会 %s %s: 議案を保存しました。",
                    bill.diet_number,
                    bill.category,
                    bill.bill_number,
                )
        LOGGER.info("%d件の議案を保存しました。", bill_count)
    finally:
        connection.close()


if __name__ == "__main__":
    main()
