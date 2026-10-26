"""Fetch Wikipedia cabinet pages and save their HTML by prime minister number."""

import argparse
from dataclasses import dataclass
import logging
import os
from pathlib import Path
import re
import time
from typing import Callable, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urljoin, urlparse
from urllib.request import Request, urlopen

import mysql.connector
from bs4 import BeautifulSoup, Tag

INDEX_URL = "https://ja.wikipedia.org/wiki/日本国歴代内閣"
WIKIPEDIA_BASE_URL = "https://ja.wikipedia.org"
USER_AGENT = "state-graffito-fetch-cabinet-wiki/1.0"
FETCH_TIMEOUT_SECONDS = 60
FETCH_MAX_ATTEMPTS = 3
RETRYABLE_HTTP_STATUS_CODES = {408, 425, 429, 500, 502, 503, 504}
REQUEST_INTERVAL_SECONDS = 0.2
LOGGER = logging.getLogger("fetch_cabinet_wiki")


@dataclass(frozen=True)
class CabinetPage:
    cabinet_name: str
    url: str


@dataclass(frozen=True)
class CabinetWiki:
    prime_minister_number: int
    cabinet_pages: tuple[CabinetPage, ...]
    wiki_bodies: tuple[str, ...]


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.replace("\u3000", " ")).strip()


def fetch_page(url: str) -> str:
    last_error: Exception | None = None
    for attempt in range(1, FETCH_MAX_ATTEMPTS + 1):
        request_url = quote(url, safe=":/%?=&")
        request = Request(request_url, headers={"User-Agent": USER_AGENT})
        try:
            with urlopen(request, timeout=FETCH_TIMEOUT_SECONDS) as response:
                charset = response.headers.get_content_charset() or "utf-8"
                return response.read().decode(charset)
        except HTTPError as error:
            if error.code not in RETRYABLE_HTTP_STATUS_CODES:
                raise RuntimeError(f"Wikipediaページの取得に失敗しました: {url}: {error}") from error
            last_error = error
        except (URLError, TimeoutError) as error:
            last_error = error

        if attempt < FETCH_MAX_ATTEMPTS:
            time.sleep(attempt)

    raise RuntimeError(
        f"Wikipediaページの取得に{FETCH_MAX_ATTEMPTS}回失敗しました: {url}: {last_error}"
    ) from last_error


def _expanded_table_rows(table: Tag) -> list[list[Tag | None]]:
    active_rowspans: dict[int, tuple[int, Tag]] = {}
    expanded: list[list[Tag | None]] = []
    for row in table.find_all("tr"):
        cells_by_column = {
            column: cell for column, (_rows_left, cell) in active_rowspans.items()
        }
        next_rowspans = {
            column: (rows_left - 1, cell)
            for column, (rows_left, cell) in active_rowspans.items()
            if rows_left > 1
        }
        column = 0
        for cell in row.find_all(["th", "td"], recursive=False):
            colspan = max(1, int(cell.get("colspan", 1)))
            while any(index in cells_by_column for index in range(column, column + colspan)):
                column += 1
            rowspan = max(1, int(cell.get("rowspan", 1)))
            for covered_column in range(column, column + colspan):
                cells_by_column[covered_column] = cell
                if rowspan > 1:
                    next_rowspans[covered_column] = (rowspan - 1, cell)
            column += colspan

        if cells_by_column:
            expanded.append(
                [cells_by_column.get(index) for index in range(max(cells_by_column) + 1)]
            )
        active_rowspans = next_rowspans
    return expanded


def _is_wikipedia_article_link(href: str) -> bool:
    parsed = urlparse(href)
    if parsed.netloc and parsed.netloc.lower() not in {
        "ja.wikipedia.org",
        "www.ja.wikipedia.org",
    }:
        return False
    return parsed.path.startswith("/wiki/") and not parsed.path.startswith(
        ("/wiki/特別:", "/wiki/ファイル:")
    )


def extract_cabinet_pages(html: str) -> dict[int, tuple[CabinetPage, ...]]:
    soup = BeautifulSoup(html, "html.parser")
    article = soup.select_one("#mw-content-text .mw-parser-output")
    if article is None:
        raise ValueError("Wikipediaの内閣一覧本文が見つかりません。")

    pages_by_number: dict[int, list[CabinetPage]] = {}

    for table in article.select("table"):
        rows = _expanded_table_rows(table)
        if not rows:
            continue
        headers = [
            normalize_text(cell.get_text(" ", strip=True)) if cell is not None else ""
            for cell in rows[0]
        ]
        generation_column = next(
            (index for index, header in enumerate(headers) if header == "代"), None
        )
        cabinet_columns = [
            index
            for index, header in enumerate(headers)
            if header == "内閣"
        ]
        prime_minister_column = next(
            (
                index
                for index, header in enumerate(headers)
                if "内閣総理大臣" in header
            ),
            None,
        )
        if generation_column is None or not cabinet_columns or prime_minister_column is None:
            continue

        for row in rows[1:]:
            if max(generation_column, *cabinet_columns) >= len(row):
                continue
            generation_cell = row[generation_column]
            if generation_cell is None:
                continue

            cabinet_link = None
            for cabinet_column in cabinet_columns:
                cabinet_cell = row[cabinet_column]
                if cabinet_cell is None:
                    continue
                cabinet_link = next(
                    (
                        anchor
                        for anchor in cabinet_cell.select("a[href]")
                        if _is_wikipedia_article_link(anchor["href"])
                    ),
                    None,
                )
                if cabinet_link is not None:
                    break
            if cabinet_link is None:
                continue
            cabinet_name = normalize_text(cabinet_link.get_text(" ", strip=True))
            cabinet_url = urljoin(WIKIPEDIA_BASE_URL, cabinet_link["href"])
            generation_match = re.search(
                r"\d+", normalize_text(generation_cell.get_text(" ", strip=True))
            )
            if generation_match is None:
                continue
            if not cabinet_name:
                raise ValueError(
                    "内閣一覧の代数はありますが、内閣名を解釈できません。"
                )
            prime_minister_number = int(generation_match.group())
            pages = pages_by_number.setdefault(prime_minister_number, [])
            page = CabinetPage(cabinet_name=cabinet_name, url=cabinet_url)
            if page not in pages:
                pages.append(page)

    if not pages_by_number:
        raise ValueError("内閣一覧から内閣ページを取得できませんでした。")
    return {number: tuple(pages) for number, pages in pages_by_number.items()}


def extract_body_html(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    article = soup.select_one("#mw-content-text .mw-parser-output")
    if article is None:
        raise ValueError("Wikipediaページの本文が見つかりません。")

    for element in article.select(
        "script, style, link, noscript, .mw-editsection, .mw-jump-link"
    ):
        element.decompose()
    for element in article.find_all(True):
        for attribute in ("class", "id", "style", "tabindex"):
            element.attrs.pop(attribute, None)

    body = BeautifulSoup("<body></body>", "html.parser")
    for child in list(article.contents):
        body.body.append(child)
    return str(body.body)


def fetch_cabinet_wiki(
    cabinet_pages: dict[int, tuple[CabinetPage, ...]],
    page_fetcher: Callable[[str], str] = fetch_page,
) -> list[CabinetWiki]:
    cabinet_wikis: list[CabinetWiki] = []
    for prime_minister_number, pages in cabinet_pages.items():
        bodies: list[str] = []
        for page in pages:
            LOGGER.info("第%d代 %s を取得しています: %s", prime_minister_number, page.cabinet_name, page.url)
            bodies.append(extract_body_html(page_fetcher(page.url)))
            time.sleep(REQUEST_INTERVAL_SECONDS)
        cabinet_wikis.append(
            CabinetWiki(
                prime_minister_number=prime_minister_number,
                cabinet_pages=pages,
                wiki_bodies=tuple(bodies),
            )
        )
    return cabinet_wikis


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


def save_cabinet_wiki(
    connection: mysql.connector.MySQLConnection, cabinet_wiki: CabinetWiki
) -> None:
    cabinet_name = "\n\n".join(
        page.cabinet_name for page in cabinet_wiki.cabinet_pages
    )
    wiki_body = "\n\n".join(cabinet_wiki.wiki_bodies)
    cursor = connection.cursor()
    try:
        cursor.execute(
            """
            INSERT INTO cabinet_wiki (
              prime_minister_number, cabinet_name, wiki_body
            ) VALUES (%s, %s, %s)
            ON DUPLICATE KEY UPDATE
              cabinet_name = VALUES(cabinet_name),
              wiki_body = VALUES(wiki_body)
            """,
            (cabinet_wiki.prime_minister_number, cabinet_name, wiki_body),
        )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        cursor.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="日本国歴代内閣ページから内閣のHTML本文を取得してDBに保存します。"
    )
    parser.add_argument(
        "--from-number", type=int, default=1, help="取得範囲の開始代数（既定: 1）"
    )
    parser.add_argument(
        "--to-number",
        type=int,
        help="取得範囲の終了代数（省略時は一覧にある最新代まで）",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    args = build_parser().parse_args(argv)
    if args.from_number < 1 or (args.to_number is not None and args.to_number < 1):
        raise ValueError("代数は1以上を指定してください。")
    if args.to_number is not None and args.from_number > args.to_number:
        raise ValueError("開始代数は終了代数以下にしてください。")

    pages_by_number = extract_cabinet_pages(fetch_page(INDEX_URL))
    end_number = args.to_number or max(pages_by_number)
    if end_number > max(pages_by_number):
        raise ValueError(
            f"指定された第{end_number}代は一覧にありません。最新は第{max(pages_by_number)}代です。"
        )
    selected_pages = {
        number: pages
        for number, pages in pages_by_number.items()
        if args.from_number <= number <= end_number
    }
    cabinet_wikis = fetch_cabinet_wiki(selected_pages)

    connection = connect_database()
    try:
        ensure_schema(connection)
        for cabinet_wiki in cabinet_wikis:
            save_cabinet_wiki(connection, cabinet_wiki)
            LOGGER.info(
                "第%d代の内閣%d件を保存しました。",
                cabinet_wiki.prime_minister_number,
                len(cabinet_wiki.cabinet_pages),
            )
    finally:
        connection.close()


if __name__ == "__main__":
    main()
