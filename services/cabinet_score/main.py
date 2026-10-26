"""Calculate category scores from a cabinet_llm.json result."""

import argparse
import json
import logging
import math
from pathlib import Path
import sys
from typing import Any, Mapping

LOGGER = logging.getLogger("cabinet_score")
SERVICE_NAME = "cabinet_score"
CATEGORIES = ("FINANCE", "MILITARY", "BANKING", "SECURITY", "GOVERNANCE")
RESULT_WEIGHTS = {
    "成立": 1.0,
    "修正成立": 0.7,
    "閉会中審査": 0.2,
    "未了": 0.0,
    "撤回": 0.0,
    "否決": 0.0,
}
BASIC_FIELDS = (
    "prime_minister_number",
    "name",
    "name_romaji",
    "tenure_start_date",
    "tenure_end_date",
    "tenure_days",
)


def _require_mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} はJSONオブジェクトである必要があります。")
    return value


def _require_list(value: Any, name: str) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError(f"{name} はJSON配列である必要があります。")
    return value


def _require_category(item: Mapping[str, Any], name: str) -> str:
    category = item.get("category")
    if category not in CATEGORIES:
        raise ValueError(f"{name}.category が不正です: {category!r}")
    return category


def _require_binary_score(item: Mapping[str, Any], field: str, name: str) -> int:
    value = item.get(field)
    if type(value) is not int or value not in (-1, 1):
        raise ValueError(f"{name}.{field} は整数の-1または1である必要があります。")
    return value


def compute_final_cabinet_scores(cabinet_data: Mapping[str, Any]) -> dict[str, Any]:
    """Apply the binary scoring weights and tenure-based tanh normalization."""
    for field in BASIC_FIELDS:
        if field not in cabinet_data:
            raise ValueError(f"cabinet_llm.json に基本情報 {field} がありません。")
    tenure_days = cabinet_data["tenure_days"]
    if type(tenure_days) is not int or tenure_days <= 0:
        raise ValueError("tenure_days は1以上の整数である必要があります。")

    task2 = _require_mapping(cabinet_data.get("task2_response"), "task2_response")
    scored_bills = _require_list(task2.get("scored_bills"), "scored_bills")
    scored_resolutions = _require_list(
        task2.get("scored_resolutions"), "scored_resolutions"
    )
    scored_events = _require_list(task2.get("scored_events"), "scored_events")
    raw_sums = {category: 0.0 for category in CATEGORIES}
    governance_penalty = 0.0

    for index, value in enumerate(scored_bills):
        name = f"scored_bills[{index}]"
        bill = _require_mapping(value, name)
        category = _require_category(bill, name)
        policy_score = _require_binary_score(bill, "policy_score", name)
        status = bill.get("normalized_status")
        if not isinstance(status, str) or status not in RESULT_WEIGHTS:
            raise ValueError(f"{name}.normalized_status が不正です: {status!r}")
        raw_sums[category] += policy_score * RESULT_WEIGHTS[status]

        if status == "撤回":
            governance_penalty -= 0.5
        elif status == "未了":
            is_carryover = bill.get("is_carryover")
            if type(is_carryover) is not bool:
                raise ValueError(
                    f"{name}.is_carryover がありません。cabinet_llmを再実行してください。"
                )
            if not is_carryover:
                governance_penalty -= 0.5
        elif status == "否決":
            governance_penalty -= 1.0

    for index, value in enumerate(scored_resolutions):
        resolution = _require_mapping(value, f"scored_resolutions[{index}]")
        passed = resolution.get("passed")
        if type(passed) is not bool:
            raise ValueError(f"scored_resolutions[{index}].passed は真偽値が必要です。")
        governance_penalty -= 2.0 if passed else 1.0

    for index, value in enumerate(scored_events):
        name = f"scored_events[{index}]"
        event = _require_mapping(value, name)
        category = _require_category(event, name)
        raw_sums[category] += _require_binary_score(event, "event_score", name)

    raw_sums["GOVERNANCE"] += governance_penalty
    alpha = 5.0 * max(1.0, (tenure_days / 365.0) ** 0.35)
    final_scores = {
        category: round(math.tanh(raw_sums[category] / alpha), 2)
        for category in CATEGORIES
    }

    result = {field: cabinet_data[field] for field in BASIC_FIELDS}
    if "model" in cabinet_data:
        result["model"] = cabinet_data["model"]
    result.update(
        {
            "alpha": round(alpha, 3),
            "raw_sums": {key: round(value, 3) for key, value in raw_sums.items()},
            "final_scores": final_scores,
        }
    )
    return result


def run(config_path: Path) -> Path:
    if not config_path.is_file():
        raise FileNotFoundError(f"設定ファイルがありません: {config_path}")
    input_path = config_path.parent / "cabinet_llm.json"
    if not input_path.is_file():
        raise FileNotFoundError(
            f"入力ファイルがありません: {input_path}。"
            "先にcabinet_llmを実行してください。"
        )
    input_text = input_path.read_text(encoding="utf-8-sig")
    if not input_text.strip():
        raise ValueError(
            f"入力ファイルが空です: {input_path}。"
            "先にcabinet_llmを実行してcabinet_llm.jsonを作成してください。"
        )
    try:
        parsed_input = json.loads(input_text)
    except json.JSONDecodeError as error:
        raise ValueError(
            f"入力ファイルがJSONとして不正です: {input_path} "
            f"({error.lineno}行{error.colno}列: {error.msg})"
        ) from error
    cabinet_data = _require_mapping(parsed_input, "cabinet_llm.json")
    result = compute_final_cabinet_scores(cabinet_data)
    output_path = input_path.parent / f"{SERVICE_NAME}.json"
    temporary_path = output_path.with_suffix(".tmp")
    temporary_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary_path.replace(output_path)
    LOGGER.info("項目別スコアをJSONに保存しました: %s", output_path)
    return output_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="cabinet_llm.json から項目別の内閣スコアを計算します。"
    )
    parser.add_argument("config_yaml", type=Path, help="作品の config.yaml へのパス")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    run(args.config_yaml.expanduser().resolve())
    return 0


if __name__ == "__main__":
    sys.exit(main())
