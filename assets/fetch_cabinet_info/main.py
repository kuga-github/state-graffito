"""Fetch Japanese prime minister and cabinet information from the Kantei website."""

import argparse
from dataclasses import dataclass
from datetime import date, datetime
import logging
import os
from pathlib import Path
import re
from typing import Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

import mysql.connector
from bs4 import BeautifulSoup, Comment
from pykakasi import kakasi

INDEX_URL = "https://www.kantei.go.jp/jp/rekidainaikaku/index.html"
USER_AGENT = "state-graffito-fetch-cabinet-info/1.0"
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
ERA_YEAR_PATTERN = re.compile(
    r"(文化|文政|天保|弘化|嘉永|安政|万延|文久|元治|慶應|慶応|明治|大正|昭和|平成|令和)"
    r"\s*(?:元|\d+)年"
)
CURRENT_PERIOD_PATTERN = re.compile(r"現在|在職中")
ERA_STARTS = (
    (date(2019, 5, 1), "令和", 2018),
    (date(1989, 1, 8), "平成", 1988),
    (date(1926, 12, 25), "昭和", 1925),
    (date(1912, 7, 30), "大正", 1911),
    (date(1868, 10, 23), "明治", 1867),
)
LOGGER = logging.getLogger("fetch_cabinet_info")
ROMANIZER = kakasi()


@dataclass(frozen=True)
class PrimeMinister:
    number: int
    name: str
    name_kana: str
    name_romaji: str
    birth_date: date
    birth_place: str
    tenure_start_date: date
    tenure_end_date: date
    tenure_start_date_era: str
    tenure_end_date_era: str
    appointment_age: int | None
    tenure_days: int | None
    cumulative_tenure_days: int | None
    cabinet_members: tuple[tuple[str, str, str], ...]


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.replace("\u3000", " ")).strip()


def fetch_page(url: str) -> str:
    request = Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urlopen(request, timeout=30) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            return response.read().decode(charset)
    except (HTTPError, URLError, TimeoutError) as error:
        raise RuntimeError(f"官邸ページの取得に失敗しました: {url}: {error}") from error


def extract_prime_minister_links(html: str, start_number: int, end_number: int) -> dict[int, str]:
    soup = BeautifulSoup(html, "html.parser")
    links: dict[int, str] = {}
    for anchor in soup.select("a[href]"):
        absolute_url = urljoin(INDEX_URL, anchor["href"]).partition("#")[0]
        match = re.fullmatch(r"/jp/rekidainaikaku/(\d+)\.html", urlparse(absolute_url).path)
        if match is None:
            continue
        number = int(match.group(1))
        if start_number <= number <= end_number:
            links.setdefault(number, absolute_url)

    if not links:
        raise ValueError(
            f"指定範囲（第{start_number}代〜第{end_number}代）の総理大臣リンクが見つかりません。"
        )
    return dict(sorted(links.items()))


def profile_values(soup: BeautifulSoup) -> dict[str, str]:
    values: dict[str, str] = {}
    for term in soup.select("dl.rekidai-profile dt"):
        label = normalize_text(term.get_text(" ", strip=True))
        definition = term.find_next_sibling("dd")
        if definition is not None:
            values[label] = normalize_text(definition.get_text(" ", strip=True))
    return values


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


def format_era_date(value: date) -> str:
    for era_start, era_name, year_offset in ERA_STARTS:
        if value >= era_start:
            era_year = value.year - year_offset
            year = "元" if era_year == 1 else str(era_year)
            return f"{era_name}{year}年{value.month}月{value.day}日"
    raise ValueError(f"和暦に変換できない日付です: {value}")


def parse_tenure_period(
    value: str, today: date | None = None
) -> tuple[date, date, str, str]:
    matches = list(ERA_DATE_PATTERN.finditer(value))
    if not matches:
        raise ValueError(f"在職期間を解釈できません: {value}")

    start_era = re.sub(r"\s+", "", matches[0].group())
    start_date = parse_era_date(start_era)
    if CURRENT_PERIOD_PATTERN.search(value):
        end_date = today or datetime.now(ZoneInfo("Asia/Tokyo")).date()
        end_era = format_era_date(end_date)
        return start_date, end_date, start_era, end_era

    if len(matches) < 2:
        raise ValueError(f"在職期間の終了日を解釈できません: {value}")
    end_era = re.sub(r"\s+", "", matches[1].group())
    end_date = parse_era_date(end_era)
    return start_date, end_date, start_era, end_era


def parse_count(value: str, label: str) -> int | None:
    if normalize_text(value) in {"ー", "―", "－", "-", "—"}:
        return None
    match = re.search(r"\d[\d,]*", value)
    if match is None:
        raise ValueError(f"{label}を数値として解釈できません: {value}")
    return int(match.group().replace(",", ""))


def kana_to_passport(value: str) -> str:
    kana = normalize_text(value)
    if not kana:
        raise ValueError("かな表記が空です。")
    return "".join(part["passport"] for part in ROMANIZER.convert(kana))


def parse_cabinet_members(soup: BeautifulSoup) -> tuple[tuple[str, str, str], ...]:
    members: list[tuple[str, str, str]] = []
    for item in soup.select(".module-accordion__item"):
        button = item.select_one("button.module-accordion__tab")
        if button is None:
            continue
        label = normalize_text(button.get_text(" ", strip=True))
        if "閣僚名簿" not in label:
            continue

        section = item.find_parent("section")
        heading = (
            section.select_one(".rekidai-cabinet-heading h2")
            if section is not None
            else None
        )
        cabinet_name = (
            normalize_text(heading.get_text(" ", strip=True))
            if heading is not None
            else re.sub(r"\s*閣僚名簿.*$", "", label).strip()
        )
        table = item.select_one(".module-accordion__body table")
        if table is None:
            raise ValueError(f"{cabinet_name}の閣僚名簿テーブルが見つかりません。")

        for row in table.select("tbody tr"):
            if "備考" in normalize_text(row.get_text(" ", strip=True)):
                continue
            role_cell = row.find("th", scope="row")
            name_cell = row.find("td")
            if role_cell is None and name_cell is not None and name_cell.has_attr("colspan"):
                continue
            if role_cell is None or name_cell is None:
                raise ValueError(f"{cabinet_name}の閣僚名簿に不正な行があります。")

            positions = [
                normalize_text(
                    ERA_YEAR_PATTERN.split(
                        normalize_text(position.get_text(" ", strip=True)),
                        maxsplit=1,
                    )[0]
                )
                for position in role_cell.select("li")
            ]
            positions = [position for position in positions if position]
            if not positions:
                position = normalize_text(role_cell.get_text(" ", strip=True))
                if position:
                    position = normalize_text(
                        ERA_YEAR_PATTERN.split(position, maxsplit=1)[0]
                    )
                if position:
                    positions = [position]
            positions = [
                re.sub(r"\s*\[$", "", position).strip() for position in positions
            ]
            person_name = normalize_text(name_cell.get_text(" ", strip=True))
            person_name = re.sub(r"\s*[（(].*[）)]\s*$", "", person_name).strip()
            if not person_name:
                person_name = normalize_text(
                    " ".join(image.get("alt", "") for image in name_cell.select("img[alt]"))
                )
            person_name = re.sub(r"\s*＊+\s*$", "", person_name).strip()
            if not positions or not person_name:
                raise ValueError(f"{cabinet_name}の閣僚名簿に役職または氏名のない行があります。")

            members.extend(
                (cabinet_name, position, person_name) for position in positions
            )

    if not members:
        raise ValueError("閣僚名簿が見つかりません。官邸ページの形式を確認してください。")
    return tuple(members)


def parse_prime_minister_page(html: str, expected_number: int) -> PrimeMinister:
    soup = BeautifulSoup(html, "html.parser")
    heading = soup.select_one(".module-meibo-profile h1")
    generation = soup.select_one(".module-meibo-profile .generation")
    if heading is None or generation is None:
        raise ValueError(f"第{expected_number}代のプロフィールが見つかりません。")

    generation_match = re.search(r"第\s*(\d+)\s*代", generation.get_text(" ", strip=True))
    if generation_match is None or int(generation_match.group(1)) != expected_number:
        raise ValueError(f"ページの代数が第{expected_number}代と一致しません。")

    name_kana_node = heading.select_one(".module-text--note")
    if name_kana_node is None:
        raise ValueError(f"第{expected_number}代のかな表記が見つかりません。")
    name = normalize_text(
        "".join(
            str(text)
            for text in heading.find_all(string=True, recursive=False)
            if not isinstance(text, Comment)
        )
    )
    name_kana = normalize_text(name_kana_node.get_text(" ", strip=True))
    if not name:
        raise ValueError(f"第{expected_number}代の氏名が空です。")

    profile = profile_values(soup)
    required_labels = (
        "生年月日",
        "出身地",
        "就任時年齢",
        "在職期間",
        "在職日数",
        "通算在職日数",
    )
    missing_labels = [label for label in required_labels if not profile.get(label)]
    if missing_labels:
        raise ValueError(
            f"第{expected_number}代のプロフィール項目が不足しています: {', '.join(missing_labels)}"
        )

    tenure_start_date, tenure_end_date, tenure_start_date_era, tenure_end_date_era = (
        parse_tenure_period(profile["在職期間"])
    )
    return PrimeMinister(
        number=expected_number,
        name=name,
        name_kana=name_kana,
        name_romaji=kana_to_passport(name_kana),
        birth_date=parse_era_date(profile["生年月日"]),
        birth_place=profile["出身地"],
        tenure_start_date=tenure_start_date,
        tenure_end_date=tenure_end_date,
        tenure_start_date_era=tenure_start_date_era,
        tenure_end_date_era=tenure_end_date_era,
        appointment_age=parse_count(profile["就任時年齢"], "就任時年齢"),
        tenure_days=parse_count(profile["在職日数"], "在職日数"),
        cumulative_tenure_days=parse_count(profile["通算在職日数"], "通算在職日数"),
        cabinet_members=parse_cabinet_members(soup),
    )


def save_prime_minister(connection: mysql.connector.MySQLConnection, prime_minister: PrimeMinister) -> None:
    cursor = connection.cursor()
    try:
        cursor.execute(
            """
            INSERT INTO prime_ministers (
              prime_minister_number, name, name_kana, name_romaji, birth_date,
              birth_place, tenure_start_date, tenure_end_date,
              tenure_start_date_era, tenure_end_date_era, appointment_age,
              tenure_days, cumulative_tenure_days
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
              name = VALUES(name),
              name_kana = VALUES(name_kana),
              name_romaji = VALUES(name_romaji),
              birth_date = VALUES(birth_date),
              birth_place = VALUES(birth_place),
              tenure_start_date = VALUES(tenure_start_date),
              tenure_end_date = VALUES(tenure_end_date),
              tenure_start_date_era = VALUES(tenure_start_date_era),
              tenure_end_date_era = VALUES(tenure_end_date_era),
              appointment_age = VALUES(appointment_age),
              tenure_days = VALUES(tenure_days),
              cumulative_tenure_days = VALUES(cumulative_tenure_days)
            """,
            (
                prime_minister.number,
                prime_minister.name,
                prime_minister.name_kana,
                prime_minister.name_romaji,
                prime_minister.birth_date,
                prime_minister.birth_place,
                prime_minister.tenure_start_date,
                prime_minister.tenure_end_date,
                prime_minister.tenure_start_date_era,
                prime_minister.tenure_end_date_era,
                prime_minister.appointment_age,
                prime_minister.tenure_days,
                prime_minister.cumulative_tenure_days,
            ),
        )
        cursor.execute(
            "DELETE FROM cabinet_members WHERE prime_minister_number = %s",
            (prime_minister.number,),
        )
        cursor.executemany(
            """
            INSERT INTO cabinet_members (
              prime_minister_number, cabinet_name, position, name
            ) VALUES (%s, %s, %s, %s)
            """,
            [
                (prime_minister.number, cabinet_name, position, name)
                for cabinet_name, position, name in prime_minister.cabinet_members
            ],
        )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        cursor.close()


def ensure_schema(connection: mysql.connector.MySQLConnection) -> None:
    schema_path = Path(__file__).resolve().parent / "db" / "init.sql"
    statements = schema_path.read_text(encoding="utf-8").split(";")
    cursor = connection.cursor()
    try:
        for statement in statements:
            if statement.strip():
                cursor.execute(statement)
    finally:
        cursor.close()
    migrate_legacy_tenure_period(connection)


def migrate_legacy_tenure_period(connection: mysql.connector.MySQLConnection) -> None:
    cursor = connection.cursor()
    try:
        cursor.execute("SHOW COLUMNS FROM prime_ministers")
        columns = {row[0] for row in cursor.fetchall()}
        if "tenure_period" not in columns:
            return

        new_columns = {
            "tenure_start_date": "DATE",
            "tenure_end_date": "DATE",
            "tenure_start_date_era": "VARCHAR(32)",
            "tenure_end_date_era": "VARCHAR(32)",
        }
        for column, data_type in new_columns.items():
            if column not in columns:
                cursor.execute(
                    f"ALTER TABLE prime_ministers ADD COLUMN {column} {data_type} NULL"
                )

        cursor.execute(
            "SELECT prime_minister_number, tenure_period FROM prime_ministers"
        )
        for prime_minister_number, tenure_period in cursor.fetchall():
            start_date, end_date, start_era, end_era = parse_tenure_period(
                tenure_period
            )
            cursor.execute(
                """
                UPDATE prime_ministers
                SET tenure_start_date = %s,
                    tenure_end_date = %s,
                    tenure_start_date_era = %s,
                    tenure_end_date_era = %s
                WHERE prime_minister_number = %s
                """,
                (
                    start_date,
                    end_date,
                    start_era,
                    end_era,
                    prime_minister_number,
                ),
            )

        cursor.execute(
            """
            ALTER TABLE prime_ministers
              MODIFY COLUMN tenure_start_date DATE NOT NULL,
              MODIFY COLUMN tenure_end_date DATE NOT NULL,
              MODIFY COLUMN tenure_start_date_era VARCHAR(32) NOT NULL,
              MODIFY COLUMN tenure_end_date_era VARCHAR(32) NOT NULL
            """
        )
        cursor.execute("ALTER TABLE prime_ministers DROP COLUMN tenure_period")
    finally:
        cursor.close()


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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="指定した代数の範囲の総理大臣・閣僚情報を官邸サイトから取得してDBに保存します。"
    )
    parser.add_argument("--from-number", type=int, default=1, help="取得範囲の開始代数（既定: 1）")
    parser.add_argument("--to-number", type=int, required=True, help="取得範囲の終了代数")
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    args = build_parser().parse_args(argv)
    if args.from_number < 1 or args.to_number < 1:
        raise ValueError("代数は1以上を指定してください。")
    if args.from_number > args.to_number:
        raise ValueError("開始代数は終了代数以下にしてください。")

    links = extract_prime_minister_links(
        fetch_page(INDEX_URL), args.from_number, args.to_number
    )
    prime_ministers = []
    for number, url in links.items():
        LOGGER.info("第%d代の情報を取得しています: %s", number, url)
        prime_ministers.append(parse_prime_minister_page(fetch_page(url), number))

    connection = connect_database()
    try:
        ensure_schema(connection)
        for prime_minister in prime_ministers:
            save_prime_minister(connection, prime_minister)
            LOGGER.info(
                "第%d代 %s: 閣僚名簿%d行を保存しました。",
                prime_minister.number,
                prime_minister.name,
                len(prime_minister.cabinet_members),
            )
    finally:
        connection.close()


if __name__ == "__main__":
    main()
