"""Request structured cabinet analysis from Gemini and export the raw results."""

import argparse
from enum import Enum
import hashlib
from html.parser import HTMLParser
import json
import logging
import os
from pathlib import Path
import sys
from typing import Any, Callable, Mapping, Sequence

import mysql.connector
from google import genai
from google.genai import types
from pydantic import BaseModel, Field, StrictInt, ValidationError, field_validator
import yaml

LOGGER = logging.getLogger("cabinet_llm")
SERVICE_NAME = "cabinet_llm"
DEFAULT_MODEL_NAME = "gemini-2.5-flash"
TARGET_CATEGORIES = {"閣法", "条約", "予算", "決議"}
TASK1_PROMPT = """\
あなたは日本の近現代政治史・立法過程の専門分析AIです。
入力された議案一覧から重要議案と政権対決型の決議案を抽出してください。

対象カテゴリは「閣法」「条約」「予算」「決議」です。それ以外は除外してください。
重要議案は、財政・軍事・金融・治安・統治のいずれかで、明確な政策転換、
国民負担の増減、国家権限や武力の拡大・抑制、または重大な政治的対立を伴う
「閣法」「条約」「予算」「決議」です。名称変更、定員の微修正、恩給や手当の定例改定、
定型的な実務協定、単純な期限延長は除外してください。

「決議」から抽出する不信任決議案は以下の2種類です。それ以外の不信任決議案は除外してください。
1. 内閣不信任決議案
2. 閣僚不信任決議案（国務大臣不信任決議案）

出力の row_id は入力データの値をそのまま使用し、JSONスキーマに従ってください。
"""
TASK2_PROMPT = """\
あなたは日本の近現代史・政治過程を定量化する専門分析AIです。
入力された重要議案、政権対決型決議、および内閣のWikipedia本文を分析し、
議案・決議・歴史イベントをJSONスキーマに従って出力してください。

分類は以下の5項目から選択し、素点の方向を基準にしてください。
- FINANCE: 減税・生活支援・積極財政は正、大型増税・負担増・歳出削減は負。
- MILITARY: 軍縮・平和協調・文民統制は正、軍備拡張・出兵・防衛活動拡大は負。
- BANKING: 公的資金注入・預金者保護などの信用救済は正、金融恐慌・銀行破綻の放置は負。
- SECURITY: 情報公開・表現の自由・市民の権利保護は正、弾圧立法・検閲・監視強化は負。
- GOVERNANCE: 普通選挙・地方分権・透明化など民主的改革は正、強権的中央集権化・疑獄・
  閣僚の不祥事辞任・内閣分裂は負。
政策・イベントの方向は二値で判定し、正方向が優勢なら 1、負方向が優勢なら -1 としてください。
0や中間値は使わず、必ず 1 または -1 のどちらかを選んでください。
議案の policy_score は政策内容そのものを評価し、成立・未了などの審議結果は
normalized_status にのみ反映してください。
審議状況は「成立」「修正成立」「閉会中審査」「未了」「撤回」「否決」に正規化します。
成立、両院承認、本院可決は「成立」；参議院回付案（同意）、修正議決、本院議了（修正案）は
「修正成立」；継続審査・閉会中審査は「閉会中審査」；未了・廃案は「未了」；
撤回は「撤回」；否決・本院議了（不信任案等の否決）は「否決」とします。
歴史イベントはWikipedia本文に明記された内閣在任中の出来事だけを抽出し、
本文から確認できない出来事を推測・創作しないでください。該当イベントがなければ
scored_events は空配列にしてください。
決議案は可決なら passed=true、それ以外は false としてください。
出力はJSONスキーマに適合させ、入力に含まれる議案は漏れなく評価してください。
各議案の is_carryover は入力で与えられた判定値をそのまま使用してください。
"""


class PolicyCategory(str, Enum):
    FINANCE = "FINANCE"
    MILITARY = "MILITARY"
    BANKING = "BANKING"
    SECURITY = "SECURITY"
    GOVERNANCE = "GOVERNANCE"


class NormalizedStatus(str, Enum):
    PASSED = "成立"
    AMENDED_PASSED = "修正成立"
    CONTINUOUS = "閉会中審査"
    EXPIRED = "未了"
    WITHDRAWN = "撤回"
    REJECTED = "否決"


class FilteredBillItem(BaseModel):
    row_id: int = Field(description="入力議案の row_id")
    bill_title: str = Field(description="議案件名")
    expected_category: PolicyCategory = Field(description="想定される主な評価項目")
    filter_reason: str = Field(max_length=50, description="重要議案として抽出した理由")


class FilteredResolutionItem(BaseModel):
    row_id: int = Field(description="入力議案の row_id")
    bill_title: str = Field(description="決議案件名")


class Task1FilterOutput(BaseModel):
    significant_bills: list[FilteredBillItem] = Field(default_factory=list)
    conflict_resolutions: list[FilteredResolutionItem] = Field(default_factory=list)


class ScoredBillItem(BaseModel):
    row_id: int = Field(description="Task 1 で選択された row_id")
    bill_title: str = Field(description="議案件名")
    is_carryover: bool = Field(
        description="入力にある diet_number と submission_session が異なる場合は true"
    )
    category: PolicyCategory = Field(description="5項目の分類")
    policy_score: StrictInt = Field(
        ge=-1,
        le=1,
        description="政策内容の二値判定（正方向は1、負方向は-1）",
    )
    normalized_status: NormalizedStatus = Field(description="正規化された審議状況")
    score_reason: str = Field(max_length=80, description="分類と素点の根拠")

    @field_validator("policy_score")
    @classmethod
    def validate_policy_score(cls, value: int) -> int:
        if value not in {-1, 1}:
            raise ValueError("policy_score は-1または1である必要があります。")
        return value


class ScoredResolutionItem(BaseModel):
    row_id: int = Field(description="Task 1 で選択された row_id")
    bill_title: str = Field(description="決議案件名")
    passed: bool = Field(description="可決された場合は true")


class ScoredEventItem(BaseModel):
    event_title: str = Field(description="内閣在任中の歴史イベント")
    category: PolicyCategory = Field(description="5項目の分類")
    event_score: StrictInt = Field(
        ge=-1,
        le=1,
        description="歴史イベントの二値判定（正方向は1、負方向は-1）",
    )
    score_reason: str = Field(max_length=80, description="分類と素点の根拠")

    @field_validator("event_score")
    @classmethod
    def validate_event_score(cls, value: int) -> int:
        if value not in {-1, 1}:
            raise ValueError("event_score は-1または1である必要があります。")
        return value


class Task2ScoreOutput(BaseModel):
    scored_bills: list[ScoredBillItem] = Field(default_factory=list)
    scored_resolutions: list[ScoredResolutionItem] = Field(default_factory=list)
    scored_events: list[ScoredEventItem] = Field(default_factory=list)


class _HtmlTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._ignored_tag: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style"}:
            self._ignored_tag = tag
        elif tag in {"br", "div", "li", "p", "tr", "h1", "h2", "h3"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag == self._ignored_tag:
            self._ignored_tag = None
        elif tag in {"div", "li", "p", "tr", "h1", "h2", "h3"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._ignored_tag is None:
            self.parts.append(data)


def html_to_text(value: str) -> str:
    extractor = _HtmlTextExtractor()
    extractor.feed(value)
    return " ".join(" ".join(extractor.parts).split())


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


def ensure_schema(
    connection: mysql.connector.MySQLConnection,
    schema_path: Path | None = None,
) -> None:
    if schema_path is None:
        configured_path = os.getenv("MART_SCHEMA_PATH")
        schema_path = (
            Path(configured_path)
            if configured_path
            else Path(__file__).resolve().parents[1]
            / "create_prime_minister_mart"
            / "db"
            / "init.sql"
        )
    if not schema_path.is_file():
        raise FileNotFoundError(
            f"総理大臣マートのスキーマが見つかりません: {schema_path}"
        )

    cursor = connection.cursor()
    try:
        for statement in schema_path.read_text(encoding="utf-8").split(";"):
            if statement.strip():
                cursor.execute(statement)
    finally:
        cursor.close()


def _load_common_config(config_path: Path) -> Mapping[str, Any]:
    if not config_path.is_file():
        raise FileNotFoundError(f"設定ファイルが見つかりません: {config_path}")
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if not isinstance(config, Mapping):
        raise ValueError("config.yaml のトップレベルはマッピングである必要があります。")
    common = config.get("common")
    if not isinstance(common, Mapping):
        raise ValueError("config.yaml に common 設定がありません。")
    return common


def load_cabinet_number(config_path: Path) -> int:
    common = _load_common_config(config_path)
    candidates = [
        common[key]
        for key in ("cabinet_number", "prime_minister_number")
        if key in common
    ]
    if not candidates:
        raise ValueError(
            "common.cabinet_number または common.prime_minister_number を設定してください。"
        )
    if len(candidates) == 2 and candidates[0] != candidates[1]:
        raise ValueError("common の内閣番号設定が一致しません。")
    cabinet_number = candidates[0]
    if type(cabinet_number) is not int or cabinet_number < 1:
        raise ValueError("common の内閣番号は1以上の整数である必要があります。")
    return cabinet_number


def load_model_name(config_path: Path) -> str:
    common = _load_common_config(config_path)
    model_name = common.get("gemini_model", DEFAULT_MODEL_NAME)
    if not isinstance(model_name, str) or not model_name.strip():
        raise ValueError("common.gemini_model は空でない文字列である必要があります。")
    return model_name.strip()


def _decode_diet(value: Any) -> list[dict[str, Any]]:
    diet = json.loads(value) if isinstance(value, str) else value
    if not isinstance(diet, list) or any(not isinstance(item, dict) for item in diet):
        raise ValueError(
            "prime_minister_mart.diet はオブジェクト配列である必要があります。"
        )
    return diet


def fetch_cabinet(
    connection: mysql.connector.MySQLConnection,
    cabinet_number: int,
) -> dict[str, Any]:
    cursor = connection.cursor()
    try:
        cursor.execute(
            """
            SELECT
                prime_minister_number,
                name,
                name_romaji,
                tenure_start_date,
                tenure_end_date,
                tenure_days,
                wiki_body,
                diet
            FROM prime_minister_mart
            WHERE prime_minister_number = %s
            """,
            (cabinet_number,),
        )
        row = cursor.fetchone()
    finally:
        cursor.close()
    if row is None:
        raise LookupError(
            f"prime_minister_mart に内閣番号 {cabinet_number} の行がありません。"
        )
    return {
        "prime_minister_number": row[0],
        "name": row[1],
        "name_romaji": row[2],
        "tenure_start_date": row[3].isoformat(),
        "tenure_end_date": row[4].isoformat(),
        "tenure_days": row[5],
        "wiki_body": row[6] or "",
        "diet": _decode_diet(row[7]),
    }


def _diet_records(diet: Sequence[Mapping[str, Any]]) -> dict[int, Mapping[str, Any]]:
    records: dict[int, Mapping[str, Any]] = {}
    for item in diet:
        row_id = item.get("id")
        if type(row_id) is not int:
            raise ValueError("diet 内の各議案には整数の id が必要です。")
        if row_id in records:
            raise ValueError(f"diet に重複した議案 id があります: {row_id}")
        records[row_id] = item
    return records


def _task1_input(diet: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    records = _diet_records(diet)
    return [
        {
            "row_id": row_id,
            "category": str(item.get("category") or ""),
            "bill_number": str(item.get("bill_number") or ""),
            "bill_title": str(item.get("bill_title") or ""),
            "deliberation_status": str(item.get("deliberation_status") or ""),
        }
        for row_id, item in records.items()
        if item.get("category") in TARGET_CATEGORIES
    ]


def _task2_input(
    cabinet: Mapping[str, Any],
    task1_result: Task1FilterOutput,
    records: Mapping[int, Mapping[str, Any]],
) -> dict[str, Any]:
    significant_ids = {item.row_id for item in task1_result.significant_bills}
    resolution_ids = {item.row_id for item in task1_result.conflict_resolutions}
    if len(significant_ids) != len(task1_result.significant_bills):
        raise ValueError("Task 1 の重要議案出力に重複した row_id があります。")
    if len(resolution_ids) != len(task1_result.conflict_resolutions):
        raise ValueError("Task 1 の決議案出力に重複した row_id があります。")
    if not significant_ids.issubset(records) or not resolution_ids.issubset(records):
        raise ValueError("Task 1 が入力に存在しない議案 row_id を返しました。")

    def bill_detail(row_id: int) -> dict[str, Any]:
        item = records[row_id]
        diet_number = item.get("diet_number")
        submission_session = item.get("submission_session")
        return {
            "row_id": row_id,
            "category": item.get("category") or "",
            "bill_title": item.get("bill_title") or "",
            "deliberation_status": item.get("deliberation_status") or "",
            "diet_number": diet_number,
            "submission_session": submission_session,
            "is_carryover": diet_number != submission_session,
            "bill_body_excerpt": str(item.get("bill_body") or "")[:1500],
        }

    return {
        "significant_bills_to_score": [
            bill_detail(item.row_id) for item in task1_result.significant_bills
        ],
        "conflict_resolutions_to_score": [
            bill_detail(item.row_id) for item in task1_result.conflict_resolutions
        ],
        "historical_context": html_to_text(str(cabinet["wiki_body"])),
    }


def create_genai_client() -> genai.Client:
    use_vertex = os.getenv("GOOGLE_GENAI_USE_VERTEXAI", "").lower() == "true"
    if use_vertex:
        missing = [
            name
            for name in ("GOOGLE_CLOUD_PROJECT", "GOOGLE_CLOUD_LOCATION")
            if not os.getenv(name)
        ]
        if missing:
            raise RuntimeError(
                "Vertex AI を使うには以下の環境変数が必要です: " + ", ".join(missing)
            )
    elif not os.getenv("GEMINI_API_KEY"):
        raise RuntimeError(
            "GEMINI_API_KEY を設定するか、Vertex AI 用の "
            "GOOGLE_GENAI_USE_VERTEXAI=true と Google Cloud 設定を指定してください。"
        )
    return genai.Client()


def generate_cached(
    *,
    stage: str,
    model_name: str,
    system_instruction: str,
    payload: Mapping[str, Any],
    response_schema: type[BaseModel],
    cache_dir: Path,
    client_factory: Callable[[], genai.Client],
) -> BaseModel:
    user_content = json.dumps(payload, ensure_ascii=False, indent=2)
    cache_identity = json.dumps(
        {
            "stage": stage,
            "model": model_name,
            "system_instruction": system_instruction,
            "user_content": user_content,
            "schema": response_schema.model_json_schema(),
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    cache_key = hashlib.sha256(cache_identity.encode("utf-8")).hexdigest()
    cache_path = cache_dir / f"{stage}-{cache_key}.json"
    if cache_path.is_file():
        try:
            return response_schema.model_validate_json(
                cache_path.read_text(encoding="utf-8")
            )
        except ValidationError as error:
            raise ValueError(
                f"LLMレスポンスキャッシュが不正です: {cache_path}"
            ) from error

    response = client_factory().models.generate_content(
        model=model_name,
        contents=user_content,
        config=types.GenerateContentConfig(
            system_instruction=system_instruction,
            response_mime_type="application/json",
            response_schema=response_schema,
            temperature=0.0,
        ),
    )
    response_text = response.text
    if not response_text:
        raise ValueError(f"{stage} のLLMレスポンスが空です。")
    try:
        parsed = response_schema.model_validate_json(response_text)
    except ValidationError as error:
        raise ValueError(
            f"{stage} のLLMレスポンスがスキーマに適合しません。"
        ) from error

    cache_dir.mkdir(parents=True, exist_ok=True)
    temporary_path = cache_path.with_suffix(".tmp")
    temporary_path.write_text(parsed.model_dump_json(indent=2), encoding="utf-8")
    temporary_path.replace(cache_path)
    return parsed


def validate_task2_ids(
    result: Task2ScoreOutput,
    task1_result: Task1FilterOutput,
    records: Mapping[int, Mapping[str, Any]],
) -> None:
    significant_ids = {item.row_id for item in task1_result.significant_bills}
    resolution_ids = {item.row_id for item in task1_result.conflict_resolutions}
    returned_bill_ids = [item.row_id for item in result.scored_bills]
    returned_resolution_ids = [item.row_id for item in result.scored_resolutions]
    if len(returned_bill_ids) != len(set(returned_bill_ids)):
        raise ValueError("Task 2 の評価出力に重複した議案 row_id があります。")
    if len(returned_resolution_ids) != len(set(returned_resolution_ids)):
        raise ValueError("Task 2 の評価出力に重複した決議案 row_id があります。")
    if set(returned_bill_ids) != significant_ids:
        raise ValueError(
            "Task 2 が重要議案の一部を漏らしたか、対象外の議案を返しました。"
        )
    if set(returned_resolution_ids) != resolution_ids:
        raise ValueError(
            "Task 2 が決議案の一部を漏らしたか、対象外の決議案を返しました。"
        )
    for bill in result.scored_bills:
        record = records[bill.row_id]
        expected_carryover = record.get("diet_number") != record.get(
            "submission_session"
        )
        if bill.is_carryover != expected_carryover:
            raise ValueError(
                f"Task 2 の議案 row_id {bill.row_id} の持ち越し判定が入力と一致しません。"
            )


def export_result(
    cabinet: Mapping[str, Any],
    model_name: str,
    task1_result: Task1FilterOutput,
    task2_result: Task2ScoreOutput,
    output_path: Path,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    result = {
        "prime_minister_number": cabinet["prime_minister_number"],
        "name": cabinet["name"],
        "name_romaji": cabinet["name_romaji"],
        "tenure_start_date": cabinet["tenure_start_date"],
        "tenure_end_date": cabinet["tenure_end_date"],
        "tenure_days": cabinet["tenure_days"],
        "model": model_name,
        "task1_response": task1_result.model_dump(mode="json"),
        "task2_response": task2_result.model_dump(mode="json"),
    }
    output_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def run(config_path: Path) -> Path:
    cabinet_number = load_cabinet_number(config_path)
    model_name = load_model_name(config_path)
    connection = connect_database()
    try:
        ensure_schema(connection)
        cabinet = fetch_cabinet(connection, cabinet_number)
    finally:
        connection.close()

    records = _diet_records(cabinet["diet"])
    light_records = _task1_input(cabinet["diet"])
    cache_dir = config_path.parent / ".cache" / SERVICE_NAME
    client: genai.Client | None = None

    def get_client() -> genai.Client:
        nonlocal client
        if client is None:
            client = create_genai_client()
        return client

    task1_result = generate_cached(
        stage="task1-filter",
        model_name=model_name,
        system_instruction=TASK1_PROMPT,
        payload={"bills": light_records},
        response_schema=Task1FilterOutput,
        cache_dir=cache_dir,
        client_factory=get_client,
    )
    if not isinstance(task1_result, Task1FilterOutput):
        raise TypeError("Task 1 のレスポンス型が不正です。")
    task2_result = generate_cached(
        stage="task2-score",
        model_name=model_name,
        system_instruction=TASK2_PROMPT,
        payload=_task2_input(cabinet, task1_result, records),
        response_schema=Task2ScoreOutput,
        cache_dir=cache_dir,
        client_factory=get_client,
    )
    if not isinstance(task2_result, Task2ScoreOutput):
        raise TypeError("Task 2 のレスポンス型が不正です。")
    validate_task2_ids(task2_result, task1_result, records)

    output_path = config_path.parent / f"{SERVICE_NAME}.json"
    export_result(cabinet, model_name, task1_result, task2_result, output_path)
    LOGGER.info("LLMの結果をJSONに保存しました: %s", output_path)
    LOGGER.info(
        "内閣番号 %s (%s): 重要議案 %d 件、対立決議 %d 件、歴史イベント %d 件",
        cabinet_number,
        cabinet["name"],
        len(task2_result.scored_bills),
        len(task2_result.scored_resolutions),
        len(task2_result.scored_events),
    )
    return output_path


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="内閣マートをGeminiで分析し、未集計の結果をCSVに保存します。"
    )
    parser.add_argument("config", type=Path, help="作品の config.yaml へのパス")
    args = parser.parse_args(argv)
    config_path = args.config.expanduser().resolve()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    run(config_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
