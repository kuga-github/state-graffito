"""Generate a cabinet analysis, score, and selected prime-minister tag in one run."""

import argparse
from bisect import bisect_right
from enum import Enum
import hashlib
from html.parser import HTMLParser
import json
import logging
import math
import os
from pathlib import Path
import random
import sys
from typing import Any, Callable, Mapping, Sequence

import mysql.connector
from google import genai
from google.genai import types
from PIL import Image, ImageDraw, ImageFont
from pydantic import BaseModel, Field, StrictInt, ValidationError, field_validator
import yaml

LOGGER = logging.getLogger("tag_pipeline")
DEFAULT_MODEL_NAME = "gemini-2.5-flash"
OUTPUT_NAME = "tag.json"
INSTRUCTION_IMAGE_NAME = "instruction.png"
INSTRUCTION_IMAGE_SIZE = (2480, 3508)
INSTRUCTION_IMAGE_DPI = 300
INSTRUCTION_TEXT_COLOR = (15, 23, 25)
INSTRUCTION_MUTED_TEXT_COLOR = (15, 23, 25)
INSTRUCTION_LINE_COLOR = (15, 23, 25)
INSTRUCTION_LINE_WIDTH = 1
INSTRUCTION_SHAPE_HEADINGS = ("linearity", "length", "area", "centroid", "addon")
CATEGORIES = ("FINANCE", "MILITARY", "BANKING", "SECURITY", "GOVERNANCE")
TARGET_CATEGORIES = {"閣法", "条約", "予算", "決議"}
VOWELS = frozenset("aeiou")
RESULT_WEIGHTS = {
    "成立": 1.0,
    "修正成立": 0.75,
    "閉会中審査": 0.5,
    "未了": 0.0,
    "撤回": 0.0,
    "否決": 0.0,
}
GOVERNANCE_BILL_PENALTY_WEIGHTS = {
    "未了": -0.25,
    "撤回": -0.0,
    "否決": -0.5,
}
GOVERNANCE_RESOLUTION_PENALTY_WEIGHTS = {
    "成立": -1.0,
    "修正成立": -0.75,
    "否決": -0.0,
    "未了": -0.25,
    "閉会中審査": -0.5,
    "撤回": 0.0,
}
FILTERS = (
    ("MILITARY", "inverse_curve_ratio"),
    ("SECURITY", "total_length"),
    ("FINANCE", "bbox_area"),
    ("BANKING", "centroid_y"),
)
TASK1_PROMPT = """\
あなたは日本の近現代政治史・立法過程の専門分析AIです。
入力された議案一覧から重要議案と政権対決型の決議案を抽出してください。
対象カテゴリは「閣法」「条約」「予算」「決議」です。それ以外は除外してください。
財政・軍事・金融・治安・統治のいずれかにおいて明確な政策転換、
国民負担の増減、国家権限や武力の拡大・抑制、重大な政治的対立を伴う重要議案を選んでください。
名称変更、定員の微修正、恩給や手当の定例改定、定型的な実務協定、単純な期限延長は除外してください。
「決議」から抽出する不信任決議案は内閣不信任決議案および閣僚不信任決議案
（国務大臣不信任決議案）のみです。それ以外の不信任・問責・解任決議案は除外してください。
出力の row_id は入力データの値をそのまま使用してください。
"""
TASK2_PROMPT = """\
あなたは日本の近現代史・政治過程を定量化する専門分析AIです。
入力された重要議案、政権対決型決議、および内閣のWikipedia本文を分析してください。
分類は以下の5項目から選び、政策・イベントの方向は正なら1、負なら-1としてください。
中間値や0は使わないでください。
- FINANCE: 減税・生活支援・積極財政は正、大型増税・負担増・歳出削減は負。
- MILITARY: 軍事活動の活発化（軍備拡張・出兵・防衛活動の拡大）は正、軍縮・軍事活動の縮小は負。
- BANKING: 公的資金注入・預金者保護などの信用救済は正、金融恐慌・銀行破綻の放置は負。
- SECURITY: 取り締まりの強化（弾圧立法・検閲・監視強化を含む）は正、取り締まりの緩和・
  情報公開・表現の自由・市民の権利保護は負。
- GOVERNANCE: 普通選挙・地方分権・透明化など民主的改革は正、強権的中央集権化・疑獄・
  閣僚の不祥事辞任・内閣分裂は負。
議案の policy_score は政策内容を評価し、審議結果は normalized_status にのみ反映してください。
normalized_status は「成立」「修正成立」「閉会中審査」「未了」「撤回」「否決」のいずれかです。
成立、両院承認、本院可決は「成立」；参議院回付案（同意）、修正議決、本院議了（修正案）は
「修正成立」；継続審査・閉会中審査は「閉会中審査」；未了・廃案は「未了」；
撤回は「撤回」；否決・本院議了（不信任案等の否決）は「否決」としてください。
歴史イベントはWikipedia本文に明記された内閣在任中の出来事だけを抽出し、推測・創作しないでください。
該当イベントがなければ scored_events は空配列にしてください。
決議案も審議結果を normalized_status に出力してください。値は上記の6種類から選び、
可決は「成立」、修正可決は「修正成立」、否決は「否決」、審議未了は「未了」、
審議継続中は「閉会中審査」、撤回は「撤回」としてください。
入力された議案は漏れなく評価し、is_carryover は入力値をそのまま使用してください。
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
    row_id: int
    bill_title: str
    expected_category: PolicyCategory
    filter_reason: str = Field(max_length=50)


class FilteredResolutionItem(BaseModel):
    row_id: int
    bill_title: str


class Task1FilterOutput(BaseModel):
    significant_bills: list[FilteredBillItem] = Field(default_factory=list)
    conflict_resolutions: list[FilteredResolutionItem] = Field(default_factory=list)


class ScoredBillItem(BaseModel):
    row_id: int
    bill_title: str
    is_carryover: bool
    category: PolicyCategory
    policy_score: StrictInt = Field(ge=-1, le=1)
    normalized_status: NormalizedStatus
    score_reason: str = Field(max_length=80)

    @field_validator("policy_score")
    @classmethod
    def validate_policy_score(cls, value: int) -> int:
        if value not in {-1, 1}:
            raise ValueError("policy_score は-1または1である必要があります。")
        return value


class ScoredResolutionItem(BaseModel):
    row_id: int
    bill_title: str
    normalized_status: NormalizedStatus


class ScoredEventItem(BaseModel):
    event_title: str
    category: PolicyCategory
    event_score: StrictInt = Field(ge=-1, le=1)
    score_reason: str = Field(max_length=80)

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


class HtmlTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.ignored_tag: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style"}:
            self.ignored_tag = tag
        elif tag in {"br", "div", "li", "p", "tr", "h1", "h2", "h3"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag == self.ignored_tag:
            self.ignored_tag = None
        elif tag in {"div", "li", "p", "tr", "h1", "h2", "h3"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self.ignored_tag is None:
            self.parts.append(data)


def html_to_text(value: str) -> str:
    extractor = HtmlTextExtractor()
    extractor.feed(value)
    return " ".join(" ".join(extractor.parts).split())


def _require_mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} はJSONオブジェクトである必要があります。")
    return value


def _require_list(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError(f"{label} はJSON配列である必要があります。")
    return value


def _decode_json(value: Any, label: str) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError as error:
            raise ValueError(f"{label} のJSONが不正です。") from error
    return value


def load_config(config_path: Path) -> Mapping[str, Any]:
    if not config_path.is_file():
        raise FileNotFoundError(f"設定ファイルがありません: {config_path}")
    loaded = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    config = _require_mapping(loaded, "config.yaml")
    common = _require_mapping(config.get("common"), "config.yaml.common")
    return common


def config_int(
    common: Mapping[str, Any], names: Sequence[str], default: int | None = None
) -> int:
    present = [common[name] for name in names if name in common]
    if not present:
        if default is None:
            raise ValueError(f"common.{names[0]} を設定してください。")
        return default
    if len(present) == 2 and present[0] != present[1]:
        raise ValueError(f"common の {names[0]} / {names[1]} 設定が一致しません。")
    value = present[0]
    if type(value) is not int:
        raise ValueError(f"common.{names[0]} は整数である必要があります。")
    return value


def config_string(common: Mapping[str, Any], name: str) -> str:
    value = common.get(name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"common.{name} は空でない文字列が必要です。")
    return value.strip()


def tag_from_name_romaji(name_romaji: str) -> str:
    name_parts = name_romaji.split()
    if not name_parts:
        raise ValueError("name_romaji が空です。")
    given_name = name_parts[0].casefold()
    tag = "".join(
        character
        for character in given_name
        if character.isalpha() and character not in VOWELS
    )
    if not tag:
        raise ValueError("name_romaji からタグ文字を生成できません。")
    return tag


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


def ensure_mart_schema(connection: mysql.connector.MySQLConnection) -> None:
    schema_path = Path(os.getenv("MART_SCHEMA_PATH", "/app/source_db/init.sql"))
    if not schema_path.is_file():
        raise FileNotFoundError(f"総理大臣マートのスキーマがありません: {schema_path}")
    cursor = connection.cursor()
    try:
        for statement in schema_path.read_text(encoding="utf-8").split(";"):
            if statement.strip():
                cursor.execute(statement)
    finally:
        cursor.close()


def fetch_cabinet(
    connection: mysql.connector.MySQLConnection, number: int
) -> dict[str, Any]:
    cursor = connection.cursor()
    try:
        cursor.execute(
            """
            SELECT prime_minister_number, name, tenure_start_date, tenure_end_date,
                   tenure_days, wiki_body, diet
            FROM prime_minister_mart
            WHERE prime_minister_number = %s
            """,
            (number,),
        )
        row = cursor.fetchone()
    finally:
        cursor.close()
    if row is None:
        raise LookupError(f"prime_minister_mart に内閣番号 {number} の行がありません。")
    diet = _decode_json(row[6], "prime_minister_mart.diet")
    if not isinstance(diet, list) or any(not isinstance(item, dict) for item in diet):
        raise ValueError(
            "prime_minister_mart.diet はオブジェクト配列である必要があります。"
        )
    if not isinstance(row[5], str):
        raise ValueError("prime_minister_mart.wiki_body は文字列である必要があります。")
    if type(row[4]) is not int or row[4] < 1:
        raise ValueError("prime_minister_mart.tenure_days は1以上の整数が必要です。")
    return {
        "prime_minister_number": int(row[0]),
        "name": str(row[1]),
        "tenure_start_date": row[2].isoformat(),
        "tenure_end_date": row[3].isoformat(),
        "tenure_days": row[4],
        "wiki_body": row[5],
        "diet": diet,
    }


def diet_records(diet: Sequence[Mapping[str, Any]]) -> dict[int, Mapping[str, Any]]:
    result: dict[int, Mapping[str, Any]] = {}
    for item in diet:
        row_id = item.get("id")
        if type(row_id) is not int or row_id in result:
            raise ValueError(f"diet 内の議案idが不正または重複しています: {row_id!r}")
        result[row_id] = item
    return result


def task1_input(diet: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "row_id": row_id,
            "category": str(item.get("category") or ""),
            "bill_number": str(item.get("bill_number") or ""),
            "bill_title": str(item.get("bill_title") or ""),
        }
        for row_id, item in diet_records(diet).items()
        if item.get("category") in TARGET_CATEGORIES
    ]


def task2_input(
    cabinet: Mapping[str, Any],
    task1: Task1FilterOutput,
    records: Mapping[int, Mapping[str, Any]],
) -> dict[str, Any]:
    significant_ids = [item.row_id for item in task1.significant_bills]
    resolution_ids = [item.row_id for item in task1.conflict_resolutions]
    if len(significant_ids) != len(set(significant_ids)) or len(resolution_ids) != len(
        set(resolution_ids)
    ):
        raise ValueError("Task 1 の結果に重複した row_id があります。")
    if not set(significant_ids + resolution_ids).issubset(records):
        raise ValueError("Task 1 が入力に存在しない議案 row_id を返しました。")

    def detail(row_id: int) -> dict[str, Any]:
        row = records[row_id]
        diet_number = row.get("diet_number")
        submission_session = row.get("submission_session")
        return {
            "row_id": row_id,
            "category": row.get("category") or "",
            "bill_title": row.get("bill_title") or "",
            "deliberation_status": row.get("deliberation_status") or "",
            "diet_number": diet_number,
            "submission_session": submission_session,
            "is_carryover": diet_number != submission_session,
            "bill_body_excerpt": str(row.get("bill_body") or "")[:1500],
        }

    return {
        "significant_bills_to_score": [detail(row_id) for row_id in significant_ids],
        "conflict_resolutions_to_score": [detail(row_id) for row_id in resolution_ids],
        "historical_context": html_to_text(str(cabinet["wiki_body"])),
    }


def create_client() -> genai.Client:
    use_vertex = os.getenv("GOOGLE_GENAI_USE_VERTEXAI", "").lower() == "true"
    if use_vertex:
        missing = [
            key
            for key in ("GOOGLE_CLOUD_PROJECT", "GOOGLE_CLOUD_LOCATION")
            if not os.getenv(key)
        ]
        if missing:
            raise RuntimeError("Vertex AIの設定が不足しています: " + ", ".join(missing))
    elif not os.getenv("GEMINI_API_KEY"):
        raise RuntimeError("GEMINI_API_KEYまたはVertex AIの環境設定が必要です。")
    return genai.Client()


def generate_cached(
    *,
    stage: str,
    model_name: str,
    instruction: str,
    payload: Mapping[str, Any],
    schema: type[BaseModel],
    cache_dir: Path,
    client_factory: Callable[[], genai.Client],
) -> BaseModel:
    contents = json.dumps(payload, ensure_ascii=False, indent=2)
    identity = json.dumps(
        {
            "stage": stage,
            "model": model_name,
            "instruction": instruction,
            "contents": contents,
            "schema": schema.model_json_schema(),
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    cache_path = (
        cache_dir / f"{stage}-{hashlib.sha256(identity.encode()).hexdigest()}.json"
    )
    if cache_path.is_file():
        try:
            return schema.model_validate_json(cache_path.read_text(encoding="utf-8"))
        except ValidationError as error:
            raise ValueError(f"LLMキャッシュが不正です: {cache_path}") from error

    response = client_factory().models.generate_content(
        model=model_name,
        contents=contents,
        config=types.GenerateContentConfig(
            system_instruction=instruction,
            response_mime_type="application/json",
            response_schema=schema,
            temperature=0.0,
        ),
    )
    if not response.text:
        raise ValueError(f"{stage} のLLMレスポンスが空です。")
    try:
        parsed = schema.model_validate_json(response.text)
    except ValidationError as error:
        raise ValueError(
            f"{stage} のLLMレスポンスがスキーマに適合しません。"
        ) from error
    cache_dir.mkdir(parents=True, exist_ok=True)
    temporary_path = cache_path.with_suffix(".tmp")
    temporary_path.write_text(parsed.model_dump_json(indent=2), encoding="utf-8")
    temporary_path.replace(cache_path)
    return parsed


def validate_task2(
    output: Task2ScoreOutput,
    task1: Task1FilterOutput,
    records: Mapping[int, Mapping[str, Any]],
) -> None:
    expected_bills = {item.row_id for item in task1.significant_bills}
    expected_resolutions = {item.row_id for item in task1.conflict_resolutions}
    bill_ids = [item.row_id for item in output.scored_bills]
    resolution_ids = [item.row_id for item in output.scored_resolutions]
    if len(bill_ids) != len(set(bill_ids)) or set(bill_ids) != expected_bills:
        raise ValueError(
            "Task 2 の重要議案 row_id が Task 1 の選択結果と一致しません。"
        )
    if (
        len(resolution_ids) != len(set(resolution_ids))
        or set(resolution_ids) != expected_resolutions
    ):
        raise ValueError("Task 2 の決議案 row_id が Task 1 の選択結果と一致しません。")
    for bill in output.scored_bills:
        row = records[bill.row_id]
        if bill.is_carryover != (
            row.get("diet_number") != row.get("submission_session")
        ):
            raise ValueError(
                f"row_id {bill.row_id} の持ち越し判定が入力と一致しません。"
            )


def compute_scores(
    cabinet: Mapping[str, Any], output: Task2ScoreOutput
) -> dict[str, Any]:
    raw_sums = {category: 0.0 for category in CATEGORIES}
    governance_penalty = 0.0
    for bill in output.scored_bills:
        status = bill.normalized_status.value
        raw_sums[bill.category.value] += bill.policy_score * RESULT_WEIGHTS[status]
        if not (status == "未了" and bill.is_carryover):
            governance_penalty += GOVERNANCE_BILL_PENALTY_WEIGHTS.get(status, 0.0)
    for resolution in output.scored_resolutions:
        status = resolution.normalized_status.value
        governance_penalty += GOVERNANCE_RESOLUTION_PENALTY_WEIGHTS.get(status, 0.0)
    for event in output.scored_events:
        raw_sums[event.category.value] += event.event_score
    raw_sums["GOVERNANCE"] += governance_penalty
    tenure_days = cabinet["tenure_days"]
    alpha = 3.0 * max(1.0, (tenure_days / 365.0) ** 0.35)
    return {
        "alpha": round(alpha, 3),
        "raw_sums": {key: round(value, 3) for key, value in raw_sums.items()},
        "final_scores": {
            key: round(math.tanh(value / alpha), 2) for key, value in raw_sums.items()
        },
    }


def parse_character_path(row: Sequence[Any]) -> dict[str, Any]:
    if len(row) != 6:
        raise ValueError("character_pathsの取得列数が不正です。")
    path_id, category, name, strokes, metrics, updated = row
    strokes = _decode_json(strokes, f"character_paths[{path_id}].strokes")
    metrics = _decode_json(metrics, f"character_paths[{path_id}].metrics")
    if not isinstance(strokes, list):
        raise ValueError(f"character_paths[{path_id}].strokesは配列が必要です。")
    if not isinstance(metrics, Mapping):
        raise ValueError(
            f"character_paths[{path_id}].metricsはオブジェクトが必要です。"
        )
    return {
        "id": int(path_id),
        "category": str(category),
        "name": str(name),
        "strokes": strokes,
        "metrics": dict(metrics),
        "updated_at": (
            updated.isoformat() if hasattr(updated, "isoformat") else str(updated)
        ),
    }


def fetch_character_paths(
    connection: mysql.connector.MySQLConnection, initial: str
) -> list[dict[str, Any]]:
    cursor = connection.cursor()
    try:
        cursor.execute(
            """
            SELECT id, category, name, strokes, metrics, updated_at
            FROM character_paths
            WHERE LEFT(name, 1) = %s
            ORDER BY category, name, id
            """,
            (initial,),
        )
        rows = cursor.fetchall()
    finally:
        cursor.close()
    return [
        path
        for path in (parse_character_path(row) for row in rows)
        if path["name"].casefold().startswith(initial.casefold())
    ]


def metric_values(metrics: Mapping[str, Any]) -> dict[str, float]:
    bbox = _require_mapping(metrics.get("boundingBox"), "metrics.boundingBox")
    centroid = _require_mapping(metrics.get("centroid"), "metrics.centroid")
    try:
        width = float(bbox["width"])
        height = float(bbox["height"])
        centroid_y = float(centroid["y"])
        curve_ratio = float(metrics["curveRatio"])
        total_length = float(metrics["totalLength"])
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("文字パスmetricsに必要な項目がありません。") from error
    if any(
        not math.isfinite(value) or value < 0 for value in (width, height, total_length)
    ):
        raise ValueError("文字パスmetricsに不正な負数または非有限値があります。")
    area = width * height
    if not math.isfinite(area) or not math.isfinite(centroid_y):
        raise ValueError("文字パスmetricsに非有限値があります。")
    if not math.isfinite(curve_ratio) or not 0 <= curve_ratio <= 1:
        raise ValueError("metrics.curveRatioは0から1の有限値が必要です。")
    return {
        "bbox_area": area,
        "centroid_y": centroid_y,
        "inverse_curve_ratio": 1.0 - curve_ratio,
        "total_length": total_length,
    }


def score_percentile(score: Any) -> float:
    if isinstance(score, bool) or not isinstance(score, (int, float)):
        raise ValueError("final_scoresの値は-1から1の数値が必要です。")
    value = float(score)
    if not math.isfinite(value) or not -1 <= value <= 1:
        raise ValueError("final_scoresの値は-1から1の有限値が必要です。")
    return 25.0 + (value + 1.0) * 25.0


def filter_percentile_ranges(scores: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    ranges: dict[str, dict[str, Any]] = {}
    for category, metric in FILTERS:
        threshold = score_percentile(scores[category])
        ranges[category] = {
            "metric": metric,
            "threshold_percentile": threshold,
            "percentile_range": [
                max(0.0, threshold - 25.0),
                min(100.0, threshold + 25.0),
            ],
        }
    return ranges


def governance_percent(score: Any) -> float:
    if isinstance(score, bool) or not isinstance(score, (int, float)):
        raise ValueError("GOVERNANCEスコアは-1から1の数値が必要です。")
    value = float(score)
    if not math.isfinite(value) or not -1 <= value <= 1:
        raise ValueError("GOVERNANCEスコアは-1から1の有限値が必要です。")
    return (value + 1.0) * 50.0


def decoration_category(score: Any) -> str:
    percent = governance_percent(score)
    if percent < 20:
        return "arrow"
    if percent < 40:
        return "double quotes"
    if percent < 60:
        return "null"
    if percent < 80:
        return "underline"
    return "halo"


def select_character_path(
    initial: str,
    candidates: Sequence[Mapping[str, Any]],
    scores: Mapping[str, Any],
    rng: random.Random,
) -> dict[str, Any]:
    if not candidates:
        raise LookupError(f"'{initial}'で始まる文字パスがありません。")
    prepared = [
        (
            dict(candidate),
            metric_values(_require_mapping(candidate.get("metrics"), "metrics")),
        )
        for candidate in candidates
    ]
    sorted_values = {
        metric: sorted(values[metric] for _, values in prepared)
        for _, metric in FILTERS
    }
    percentiles = [
        {
            metric: 100.0
            * bisect_right(sorted_values[metric], values[metric])
            / len(prepared)
            for _, metric in FILTERS
        }
        for _, values in prepared
    ]
    filter_ranges = filter_percentile_ranges(scores)
    current = list(range(len(prepared)))
    steps: list[dict[str, Any]] = []
    skipped_filters: list[str] = []
    for category, _metric in FILTERS:
        lower_percentile, upper_percentile = filter_ranges[category]["percentile_range"]
        metric = filter_ranges[category]["metric"]
        filtered = [
            index
            for index in current
            if lower_percentile <= percentiles[index][metric] <= upper_percentile
        ]
        steps.append(
            {
                "filter": category,
                "candidate_count_before": len(current),
                "candidate_count_after": len(filtered),
            }
        )
        if not filtered:
            skipped_filters.append(category)
            continue
        current = filtered
    selected_index = rng.choice(current)
    selected = prepared[selected_index][0]
    selected["filter_percentiles"] = percentiles[selected_index]
    selected["selection"] = {
        "tag_character": initial,
        "candidate_count": len(prepared),
        "remaining_candidate_count": len(current),
        "filter_steps": steps,
        "skipped_filters": skipped_filters,
    }
    return selected


def _bezier_samples(stroke: Sequence[Mapping[str, Any]]) -> list[tuple[float, float]]:
    points = [(float(point["x"]), float(point["y"])) for point in stroke]
    if len(points) < 2:
        return points
    if len(points) == 2:
        return points

    def tangent(index: int) -> tuple[float, float]:
        previous = points[max(0, index - 1)]
        following = points[min(len(points) - 1, index + 1)]
        divisor = 1 if index in (0, len(points) - 1) else 2
        return (
            (following[0] - previous[0]) / divisor,
            (following[1] - previous[1]) / divisor,
        )

    samples: list[tuple[float, float]] = []
    for index in range(len(points) - 1):
        start, end = points[index], points[index + 1]
        start_tangent, end_tangent = tangent(index), tangent(index + 1)
        control1 = (start[0] + start_tangent[0] / 3, start[1] + start_tangent[1] / 3)
        control2 = (end[0] - end_tangent[0] / 3, end[1] - end_tangent[1] / 3)
        for step in range(0 if index == 0 else 1, 81):
            t = step / 80
            inverse = 1 - t
            x = (
                inverse**3 * start[0]
                + 3 * inverse**2 * t * control1[0]
                + 3 * inverse * t**2 * control2[0]
                + t**3 * end[0]
            )
            y = (
                inverse**3 * start[1]
                + 3 * inverse**2 * t * control1[1]
                + 3 * inverse * t**2 * control2[1]
                + t**3 * end[1]
            )
            samples.append((x, y))
    return samples


def render_paths_png(
    paths: Sequence[Mapping[str, Any]], output_path: Path, size: int = 256
) -> None:
    if not paths:
        raise ValueError("PNGに描画する文字パスがありません。")
    tiles: list[Image.Image] = []
    for character_path in paths:
        strokes_value = character_path.get("strokes")
        if not isinstance(strokes_value, list):
            raise ValueError("文字パスstrokesは配列が必要です。")
        samples = [
            _bezier_samples(stroke)
            for stroke in strokes_value
            if isinstance(stroke, list)
        ]
        all_points = [point for stroke in samples for point in stroke]
        if not all_points:
            raise ValueError("描画可能なstroke pointがありません。")
        min_x = min(point[0] for point in all_points)
        max_x = max(point[0] for point in all_points)
        min_y = min(point[1] for point in all_points)
        max_y = max(point[1] for point in all_points)
        span = max(max_x - min_x, max_y - min_y, 1.0)
        scale = (size * 0.82) / span
        offset_x = (size - (max_x - min_x) * scale) / 2 - min_x * scale
        offset_y = (size - (max_y - min_y) * scale) / 2 - min_y * scale
        tile = Image.new("RGBA", (size, size), (255, 255, 255, 255))
        draw = ImageDraw.Draw(tile)
        for stroke in samples:
            if len(stroke) >= 2:
                coordinates = [
                    (round(x * scale + offset_x), round(y * scale + offset_y))
                    for x, y in stroke
                ]
                draw.line(
                    coordinates,
                    fill=(0, 0, 0, 255),
                    width=max(2, size // 80),
                    joint="curve",
                )
        tiles.append(tile)
    combined = Image.new("RGBA", (size * len(tiles), size), (255, 255, 255, 255))
    for index, tile in enumerate(tiles):
        combined.alpha_composite(tile, (index * size, 0))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    combined.save(output_path, format="PNG")


def instruction_header_character(character: str, category: str) -> str:
    return character.upper() if category.casefold() == "capital" else character


def render_instruction_png(
    result: Mapping[str, Any],
    output_path: Path,
) -> None:
    regular_path = Path(
        "/usr/share/fonts/opentype/courier-prime/Courier Prime.otf"
    )
    bold_path = Path(
        "/usr/share/fonts/opentype/courier-prime/Courier Prime Bold.otf"
    )
    if not regular_path.is_file() or not bold_path.is_file():
        raise FileNotFoundError("Courier Primeフォントがインストールされていません。")

    logical_width, logical_height, margin = 1200, 1698, 70
    title_table_gap = 10
    section_gap = 20
    table_gap = 0
    table_row_height = 58
    width, height = INSTRUCTION_IMAGE_SIZE
    scale_x = width / logical_width
    scale_y = height / logical_height
    scale_font = (scale_x + scale_y) / 2
    image = Image.new("RGB", (width, height), (255, 255, 255))
    draw = ImageDraw.Draw(image)
    table_font_size = round(20 * scale_font)
    regular = ImageFont.truetype(str(regular_path), table_font_size)
    bold = ImageFont.truetype(str(bold_path), table_font_size)
    section_font = ImageFont.truetype(str(bold_path), round(23 * scale_font))

    def point(x: int, y: int) -> tuple[int, int]:
        return round(x * scale_x), round(y * scale_y)

    def rectangle(box: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
        return (
            round(box[0] * scale_x),
            round(box[1] * scale_y),
            round(box[2] * scale_x),
            round(box[3] * scale_y),
        )

    def centered(
        box: tuple[int, int, int, int],
        text: str,
        font: Any,
        color: Any = INSTRUCTION_TEXT_COLOR,
    ) -> None:
        left, top, right, bottom = box
        draw.text(
            point((left + right) // 2, (top + bottom) // 2),
            text,
            font=font,
            fill=color,
            anchor="mm",
        )

    line_width = max(1, round(INSTRUCTION_LINE_WIDTH * scale_font))

    def grid_table(
        x_edges: Sequence[int],
        y_edges: Sequence[int],
        merged_first_column_rows: Sequence[int] = (),
    ) -> None:
        for x in x_edges:
            draw.line(
                (*point(x, y_edges[0]), *point(x, y_edges[-1])),
                fill=INSTRUCTION_LINE_COLOR,
                width=line_width,
            )
        for index, y in enumerate(y_edges):
            start_x = x_edges[1] if index in merged_first_column_rows else x_edges[0]
            draw.line(
                (*point(start_x, y), *point(x_edges[-1], y)),
                fill=INSTRUCTION_LINE_COLOR,
                width=line_width,
            )

    def text_value(data: Mapping[str, Any], key: str) -> str:
        value = data.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"tag.json の {key} は空でない文字列が必要です。")
        return value.strip()

    def integer_value(data: Mapping[str, Any], key: str) -> int:
        value = data.get(key)
        if type(value) is not int or value < 0:
            raise ValueError(f"tag.json の {key} は0以上の整数が必要です。")
        return value

    def draw_section_title(top: int, title: str) -> None:
        centered(
            (margin, top + 8, logical_width - margin, top + 48),
            title,
            section_font,
            INSTRUCTION_MUTED_TEXT_COLOR,
        )

    number = integer_value(result, "prime_minister_number")
    name = text_value(result, "name_romaji")
    days = integer_value(result, "tenure_days")
    tag = text_value(result, "tag")
    final_scores = _require_mapping(result.get("final_scores"), "tag.json.final_scores")
    selection = _require_mapping(result.get("selection"), "tag.json.selection")
    filter_ranges = _require_mapping(
        selection.get("filter_ranges"), "tag.json.selection.filter_ranges"
    )
    task2 = _require_mapping(result.get("task2_response"), "tag.json.task2_response")
    bill_count = len(_require_list(task2.get("scored_bills"), "scored_bills"))
    resolution_count = len(
        _require_list(task2.get("scored_resolutions"), "scored_resolutions")
    )
    event_count = len(_require_list(task2.get("scored_events"), "scored_events"))

    title_font = ImageFont.truetype(str(bold_path), round(58 * scale_font))
    centered(
        (margin, margin, logical_width - margin, margin + 95),
        f"StateGraffito{number:03d}",
        title_font,
        INSTRUCTION_MUTED_TEXT_COLOR,
    )
    centered(
        (margin, 148, logical_width - margin, 170),
        "source code: https://github.com/kuga-github/state-graffito",
        regular,
        INSTRUCTION_TEXT_COLOR,
    )

    cabinet_top = 188
    draw_section_title(cabinet_top, "CABINET")
    row_y = cabinet_top + 48 + title_table_gap
    cabinet_rows = (
        ("cabinet number", str(number)),
        ("prime minister", name),
        ("days in office", str(days)),
        ("significant bills", str(bill_count)),
        ("no-confidence resolutions", str(resolution_count)),
        ("significant events", str(event_count)),
    )
    cabinet_width = (logical_width - 2 * margin) / 2
    cabinet_x = (
        margin,
        round(margin + cabinet_width),
        logical_width - margin,
    )
    cabinet_y = tuple(
        row_y + index * table_row_height for index in range(len(cabinet_rows) + 1)
    )
    grid_table(cabinet_x, cabinet_y)
    for index, (label, value) in enumerate(cabinet_rows):
        middle = (cabinet_y[index] + cabinet_y[index + 1]) // 2
        draw.text(
            point(margin + 14, middle),
            label,
            font=bold,
            fill=INSTRUCTION_TEXT_COLOR,
            anchor="lm",
        )
        draw.text(
            point(logical_width - margin - 14, middle),
            value,
            font=regular,
            fill=INSTRUCTION_TEXT_COLOR,
            anchor="rm",
        )

    instruction_top = cabinet_y[-1] + section_gap - 8
    draw_section_title(instruction_top, "INSTRUCTION")
    score_table_top = instruction_top + 48 + title_table_gap
    x_edges = [
        round(margin + (logical_width - 2 * margin) * index / 6) for index in range(7)
    ]
    score_y = tuple(
        score_table_top + table_row_height * index for index in range(3)
    )
    shape_table_top = score_y[-1] + table_gap
    shape_y = tuple(
        shape_table_top + table_row_height * index for index in range(3)
    )
    grid_table(x_edges, score_y, merged_first_column_rows=(1,))
    grid_table(x_edges, shape_y, merged_first_column_rows=(1,))
    centered((x_edges[0], score_y[0], x_edges[1], score_y[2]), "score", bold)
    centered((x_edges[0], shape_y[0], x_edges[1], shape_y[2]), "shape", bold)
    score_headings = ("military", "security", "finance", "banking", "governance")
    categories = ("MILITARY", "SECURITY", "FINANCE", "BANKING", "GOVERNANCE")
    decoration = text_value(result, "decoration_category")
    for index, (score_heading, shape_heading, category) in enumerate(
        zip(score_headings, INSTRUCTION_SHAPE_HEADINGS, categories),
        start=1,
    ):
        centered(
            (x_edges[index], score_y[0], x_edges[index + 1], score_y[1]),
            score_heading,
            bold,
        )
        score = final_scores.get(category)
        if (
            isinstance(score, bool)
            or not isinstance(score, (int, float))
            or not math.isfinite(float(score))
        ):
            raise ValueError(f"tag.json の final_scores.{category} が不正です。")
        centered(
            (x_edges[index], score_y[1], x_edges[index + 1], score_y[2]),
            f"{float(score):.2f}",
            regular,
        )
        centered(
            (x_edges[index], shape_y[0], x_edges[index + 1], shape_y[1]),
            shape_heading,
            bold,
        )
        if category == "GOVERNANCE":
            shape = decoration
        else:
            filter_data = _require_mapping(
                filter_ranges.get(category), f"filter_ranges.{category}"
            )
            value_range = _require_list(
                filter_data.get("percentile_range"),
                f"filter_ranges.{category}.percentile_range",
            )
            if len(value_range) != 2 or any(
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(float(value))
                for value in value_range
            ):
                raise ValueError(
                    f"filter_ranges.{category}.percentile_range が不正です。"
                )
            shape = f"{round(value_range[0]):02d}-{round(value_range[1]):02d}%"
        centered(
            (x_edges[index], shape_y[1], x_edges[index + 1], shape_y[2]),
            shape,
            regular,
        )

    paths = _require_list(selection.get("paths"), "selection.paths")
    if not paths:
        raise ValueError("tag.json.selection.paths が空です。")
    character_paths = [
        _require_mapping(path, "selection.paths[]")
        for path in paths
        if isinstance(path, Mapping) and path.get("role") == "tag_character"
    ]
    if len(character_paths) != len(paths) or len(tag) != len(character_paths):
        raise ValueError("tagの文字数とタグ文字パス数が一致しません。")

    path_table_top = shape_y[-1] + table_gap
    path_width = logical_width - 2 * margin
    path_edges = [
        margin + round(path_width * index / len(character_paths))
        for index in range(len(character_paths) + 1)
    ]
    path_y = tuple(
        path_table_top + table_row_height * index for index in range(3)
    )
    grid_table(path_edges, path_y)
    for index, path in enumerate(character_paths):
        category = text_value(path, "category")
        centered(
            (path_edges[index], path_y[0], path_edges[index + 1], path_y[1]),
            instruction_header_character(tag[index], category),
            bold,
        )
        centered(
            (path_edges[index], path_y[1], path_edges[index + 1], path_y[2]),
            text_value(path, "name"),
            regular,
            INSTRUCTION_MUTED_TEXT_COLOR,
        )

    graffiti_top = path_y[-1] + section_gap - 8
    draw_section_title(graffiti_top, "GRAFFITO")
    graffiti_box = rectangle(
        (
            margin,
            graffiti_top + 48 + title_table_gap,
            logical_width - margin,
            logical_height - margin,
        )
    )
    draw.rectangle(
        graffiti_box,
        outline=INSTRUCTION_LINE_COLOR,
        width=line_width,
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(
        output_path,
        format="PNG",
        dpi=(INSTRUCTION_IMAGE_DPI, INSTRUCTION_IMAGE_DPI),
    )


def run_pipeline(config_path: Path) -> Path:
    common = load_config(config_path)
    cabinet_number = config_int(common, ("cabinet_number", "prime_minister_number"))
    if cabinet_number < 1:
        raise ValueError("内閣番号は1以上の整数である必要があります。")
    name_romaji = config_string(common, "name_romaji")
    tag = tag_from_name_romaji(name_romaji)
    random_seed = config_int(common, ("random_seed",), default=42)
    model_name = common.get("gemini_model", DEFAULT_MODEL_NAME)
    if not isinstance(model_name, str) or not model_name.strip():
        raise ValueError("common.gemini_modelは空でない文字列が必要です。")
    model_name = model_name.strip()

    connection = connect_database()
    try:
        ensure_mart_schema(connection)
        cabinet = fetch_cabinet(connection, cabinet_number)
        records = diet_records(cabinet["diet"])
        cache_dir = config_path.parent / ".cache" / "cabinet_llm"
        client: genai.Client | None = None

        def get_client() -> genai.Client:
            nonlocal client
            if client is None:
                client = create_client()
            return client

        task1 = generate_cached(
            stage="task1-filter",
            model_name=model_name,
            instruction=TASK1_PROMPT,
            payload={"bills": task1_input(cabinet["diet"])},
            schema=Task1FilterOutput,
            cache_dir=cache_dir,
            client_factory=get_client,
        )
        if not isinstance(task1, Task1FilterOutput):
            raise TypeError("Task 1 のレスポンス型が不正です。")
        task2 = generate_cached(
            stage="task2-score",
            model_name=model_name,
            instruction=TASK2_PROMPT,
            payload=task2_input(cabinet, task1, records),
            schema=Task2ScoreOutput,
            cache_dir=cache_dir,
            client_factory=get_client,
        )
        if not isinstance(task2, Task2ScoreOutput):
            raise TypeError("Task 2 のレスポンス型が不正です。")
        validate_task2(task2, task1, records)

        scores = compute_scores(cabinet, task2)
        final_scores = scores["final_scores"]
        for category in CATEGORIES:
            if category not in final_scores:
                raise ValueError(f"final_scoresに{category}がありません。")
        governance_score = final_scores["GOVERNANCE"]
        governance_value = governance_percent(governance_score)
        decoration = decoration_category(governance_score)
        rng = random.Random(random_seed)
        selected_paths: list[dict[str, Any]] = []
        selected_by_char: dict[str, dict[str, Any]] = {}
        for tag_index, initial in enumerate(tag, start=1):
            if initial not in selected_by_char:
                selected_by_char[initial] = select_character_path(
                    initial,
                    fetch_character_paths(connection, initial),
                    final_scores,
                    rng,
                )
            path = dict(selected_by_char[initial])
            path.update({"role": "tag_character", "tag_index": tag_index})
            selected_paths.append(path)
    finally:
        connection.close()

    debug_name = "selected-string.png"
    debug_path = config_path.parent / "debug" / debug_name
    render_paths_png(selected_paths, debug_path)

    result = {
        "prime_minister_number": cabinet["prime_minister_number"],
        "name": cabinet["name"],
        "name_romaji": name_romaji,
        "tenure_start_date": cabinet["tenure_start_date"],
        "tenure_end_date": cabinet["tenure_end_date"],
        "tenure_days": cabinet["tenure_days"],
        "model": model_name,
        "task1_response": task1.model_dump(mode="json"),
        "task2_response": task2.model_dump(mode="json"),
        **scores,
        "tag": tag,
        "random_seed": random_seed,
        "governance_percent": governance_value,
        "decoration_category": decoration,
        "selection": {
            "percentile_method": "100 * count(value <= candidate) / candidate_count",
            "percentile_population": "same initial character",
            "score_to_percentile": "25 + (score + 1) * 25",
            "percentile_window": "score_percentile +/- 25, clamped to [0, 100]",
            "filter_order": [category for category, _ in FILTERS],
            "filter_ranges": filter_percentile_ranges(final_scores),
            "paths": selected_paths,
            "debug_png": f"debug/{debug_name}",
        },
    }
    output_path = config_path.parent / OUTPUT_NAME
    temporary_path = output_path.with_suffix(".tmp")
    temporary_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    temporary_path.replace(output_path)
    render_instruction_png(
        result,
        config_path.parent / INSTRUCTION_IMAGE_NAME,
    )
    for intermediate_name in (
        "cabinet_llm.json",
        "cabinet_score.json",
        "prime_minister_characters.json",
    ):
        (config_path.parent / intermediate_name).unlink(missing_ok=True)
    LOGGER.info("統合パイプライン結果を保存しました: %s", output_path)
    return output_path


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="内閣分析から総理大臣タグまでを一括生成します。"
    )
    parser.add_argument("config_yaml", type=Path, help="作品のconfig.yamlへのパス")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    run_pipeline(args.config_yaml.expanduser().resolve())
    return 0


if __name__ == "__main__":
    sys.exit(main())
