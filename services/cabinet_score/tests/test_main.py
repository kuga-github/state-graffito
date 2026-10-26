import json
import math
import tempfile
import unittest
from pathlib import Path

from main import compute_final_cabinet_scores, run


def sample_input():
    return {
        "prime_minister_number": 42,
        "name": "総理大臣",
        "name_romaji": "Prime Minister",
        "tenure_start_date": "2020-01-01",
        "tenure_end_date": "2020-12-31",
        "tenure_days": 365,
        "model": "gemini-test",
        "task2_response": {
            "scored_bills": [
                {
                    "category": "FINANCE",
                    "policy_score": 1,
                    "normalized_status": "成立",
                    "is_carryover": False,
                },
                {
                    "category": "MILITARY",
                    "policy_score": -1,
                    "normalized_status": "修正成立",
                    "is_carryover": False,
                },
                {
                    "category": "BANKING",
                    "policy_score": 1,
                    "normalized_status": "閉会中審査",
                    "is_carryover": False,
                },
                {
                    "category": "SECURITY",
                    "policy_score": -1,
                    "normalized_status": "未了",
                    "is_carryover": True,
                },
                {
                    "category": "GOVERNANCE",
                    "policy_score": 1,
                    "normalized_status": "撤回",
                    "is_carryover": False,
                },
                {
                    "category": "GOVERNANCE",
                    "policy_score": 1,
                    "normalized_status": "否決",
                    "is_carryover": False,
                },
            ],
            "scored_resolutions": [
                {"passed": True},
                {"passed": False},
            ],
            "scored_events": [
                {"category": "GOVERNANCE", "event_score": 1},
                {"category": "SECURITY", "event_score": -1},
            ],
        },
    }


class CabinetScoreTests(unittest.TestCase):
    def test_computes_weighted_category_scores_and_penalties(self):
        result = compute_final_cabinet_scores(sample_input())

        self.assertEqual(result["alpha"], 3.0)
        self.assertEqual(
            result["raw_sums"],
            {
                "FINANCE": 1.0,
                "MILITARY": -0.7,
                "BANKING": 0.2,
                "SECURITY": -1.0,
                "GOVERNANCE": -3.5,
            },
        )
        self.assertEqual(result["final_scores"]["FINANCE"], round(math.tanh(1 / 3), 2))
        self.assertEqual(result["final_scores"]["GOVERNANCE"], round(math.tanh(-3.5 / 3), 2))

    def test_inherits_cabinet_information_from_input(self):
        source = sample_input()
        result = compute_final_cabinet_scores(source)

        for field in (
            "prime_minister_number",
            "name",
            "name_romaji",
            "tenure_start_date",
            "tenure_end_date",
            "tenure_days",
            "model",
        ):
            self.assertEqual(result[field], source[field])

    def test_carryover_expiry_is_excluded_from_governance_penalty(self):
        source = sample_input()
        source["task2_response"]["scored_bills"] = [
            {
                "category": "GOVERNANCE",
                "policy_score": 1,
                "normalized_status": "未了",
                "is_carryover": True,
            },
            {
                "category": "GOVERNANCE",
                "policy_score": -1,
                "normalized_status": "未了",
                "is_carryover": False,
            },
        ]
        source["task2_response"]["scored_resolutions"] = []
        source["task2_response"]["scored_events"] = []

        result = compute_final_cabinet_scores(source)

        self.assertEqual(result["raw_sums"]["GOVERNANCE"], -0.5)

    def test_requires_carryover_metadata_for_unresolved_bill(self):
        source = sample_input()
        source["task2_response"]["scored_bills"] = [
            {
                "category": "GOVERNANCE",
                "policy_score": 1,
                "normalized_status": "未了",
            }
        ]
        source["task2_response"]["scored_resolutions"] = []
        source["task2_response"]["scored_events"] = []

        with self.assertRaisesRegex(ValueError, "cabinet_llmを再実行"):
            compute_final_cabinet_scores(source)

    def test_rejects_non_binary_input(self):
        source = sample_input()
        source["task2_response"]["scored_bills"][0]["policy_score"] = 0

        with self.assertRaisesRegex(ValueError, "整数の-1または1"):
            compute_final_cabinet_scores(source)

    def test_writes_result_json_next_to_config(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            config_path = Path(temporary_directory) / "config.yaml"
            config_path.write_text("common: {}\n", encoding="utf-8")
            input_path = Path(temporary_directory) / "cabinet_llm.json"
            input_path.write_text(
                json.dumps(sample_input(), ensure_ascii=False),
                encoding="utf-8",
            )

            output_path = run(config_path)

            self.assertEqual(output_path.name, "cabinet_score.json")
            saved_result = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(saved_result["name"], "総理大臣")
            self.assertIn("final_scores", saved_result)

    def test_reports_empty_input_with_guidance(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            config_path = Path(temporary_directory) / "config.yaml"
            config_path.write_text("common: {}\n", encoding="utf-8")
            (Path(temporary_directory) / "cabinet_llm.json").write_text(
                " \n", encoding="utf-8"
            )

            with self.assertRaisesRegex(ValueError, "ファイルが空です.*cabinet_llmを実行"):
                run(config_path)

    def test_reports_invalid_json_location(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            config_path = Path(temporary_directory) / "config.yaml"
            config_path.write_text("common: {}\n", encoding="utf-8")
            (Path(temporary_directory) / "cabinet_llm.json").write_text(
                "not-json", encoding="utf-8"
            )

            with self.assertRaisesRegex(ValueError, "1行1列"):
                run(config_path)


if __name__ == "__main__":
    unittest.main()
