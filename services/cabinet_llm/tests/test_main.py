import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock

from main import (
    FilteredBillItem,
    NormalizedStatus,
    PolicyCategory,
    ScoredBillItem,
    ScoredEventItem,
    TASK1_PROMPT,
    Task1FilterOutput,
    Task2ScoreOutput,
    _task1_input,
    _task2_input,
    export_result,
    fetch_cabinet,
    generate_cached,
    load_cabinet_number,
    load_model_name,
    validate_task2_ids,
)


class CabinetLlmTests(unittest.TestCase):
    def test_task1_limits_resolutions_to_cabinet_or_minister_no_confidence(self):
        self.assertIn(
            "「内閣不信任決議案」および「閣僚不信任決議案」のみ",
            TASK1_PROMPT,
        )
        self.assertIn("問責決議、解任決議", TASK1_PROMPT)

    def test_policy_and_event_scores_accept_only_binary_values(self):
        for value in (-1, 1):
            with self.subTest(value=value):
                ScoredBillItem(
                    row_id=1,
                    bill_title="法案",
                    is_carryover=False,
                    category=PolicyCategory.FINANCE,
                    policy_score=value,
                    normalized_status=NormalizedStatus.PASSED,
                    score_reason="財政政策の方向",
                )
                ScoredEventItem(
                    event_title="歴史イベント",
                    category=PolicyCategory.GOVERNANCE,
                    event_score=value,
                    score_reason="統治制度の方向",
                )

        for value in (0, 0.5, -0.5):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    ScoredBillItem(
                        row_id=1,
                        bill_title="法案",
                        is_carryover=False,
                        category=PolicyCategory.FINANCE,
                        policy_score=value,
                        normalized_status=NormalizedStatus.PASSED,
                        score_reason="財政政策の方向",
                    )
                with self.assertRaises(ValueError):
                    ScoredEventItem(
                        event_title="歴史イベント",
                        category=PolicyCategory.GOVERNANCE,
                        event_score=value,
                        score_reason="統治制度の方向",
                    )

    def test_reads_cabinet_number_from_common(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            config_path = Path(temporary_directory) / "config.yaml"
            config_path.write_text(
                "common:\n  cabinet_number: 42\n",
                encoding="utf-8",
            )

            self.assertEqual(load_cabinet_number(config_path), 42)

    def test_accepts_database_column_name_for_cabinet_number(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            config_path = Path(temporary_directory) / "config.yaml"
            config_path.write_text(
                "common:\n  prime_minister_number: 12\n",
                encoding="utf-8",
            )

            self.assertEqual(load_cabinet_number(config_path), 12)

    def test_rejects_non_integer_cabinet_number(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            config_path = Path(temporary_directory) / "config.yaml"
            config_path.write_text(
                "common:\n  cabinet_number: '12'\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "整数"):
                load_cabinet_number(config_path)

    def test_reads_gemini_model_from_common(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            config_path = Path(temporary_directory) / "config.yaml"
            config_path.write_text(
                "common:\n  cabinet_number: 42\n  gemini_model: gemini-2.5-pro\n",
                encoding="utf-8",
            )

            self.assertEqual(load_model_name(config_path), "gemini-2.5-pro")

    def test_defaults_gemini_model_when_not_configured(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            config_path = Path(temporary_directory) / "config.yaml"
            config_path.write_text(
                "common:\n  cabinet_number: 42\n",
                encoding="utf-8",
            )

            self.assertEqual(load_model_name(config_path), "gemini-2.5-flash")

    def test_rejects_empty_gemini_model(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            config_path = Path(temporary_directory) / "config.yaml"
            config_path.write_text(
                "common:\n  cabinet_number: 42\n  gemini_model: '  '\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "gemini_model"):
                load_model_name(config_path)

    def test_fetches_selected_mart_row_and_decodes_diet(self):
        connection = MagicMock()
        cursor = connection.cursor.return_value
        cursor.fetchone.return_value = (
            42,
            "総理大臣",
            "Prime Minister",
            date(2020, 1, 1),
            date(2021, 1, 1),
            366,
            "<p>本文</p>",
            '[{"id": 7}]',
        )

        cabinet = fetch_cabinet(connection, 42)

        self.assertEqual(cabinet["prime_minister_number"], 42)
        self.assertEqual(cabinet["name_romaji"], "Prime Minister")
        self.assertEqual(cabinet["tenure_start_date"], "2020-01-01")
        self.assertEqual(cabinet["tenure_end_date"], "2021-01-01")
        self.assertEqual(cabinet["tenure_days"], 366)
        self.assertEqual(cabinet["diet"], [{"id": 7}])
        cursor.execute.assert_called_once()
        self.assertEqual(cursor.execute.call_args.args[1], (42,))
        cursor.close.assert_called_once()

    def test_task1_input_only_contains_target_categories(self):
        bills = [
            {"id": 1, "category": "閣法", "bill_title": "対象"},
            {"id": 2, "category": "衆法", "bill_title": "除外"},
        ]

        self.assertEqual(
            _task1_input(bills),
            [
                {
                    "row_id": 1,
                    "category": "閣法",
                    "bill_number": "",
                    "bill_title": "対象",
                    "deliberation_status": "",
                }
            ],
        )

    def test_task2_input_uses_selected_bills_and_wiki_context(self):
        cabinet = {"wiki_body": "<p>内閣の出来事</p>"}
        diet = {
            7: {
                "diet_number": 211,
                "submission_session": 210,
                "category": "閣法",
                "bill_title": "重要法案",
                "deliberation_status": "成立",
                "bill_body": "本文",
            }
        }
        task1_result = Task1FilterOutput(
            significant_bills=[
                FilteredBillItem(
                    row_id=7,
                    bill_title="重要法案",
                    expected_category="FINANCE",
                    filter_reason="財政政策に関する重要法案",
                )
            ]
        )

        payload = _task2_input(cabinet, task1_result, diet)

        self.assertEqual(payload["significant_bills_to_score"][0]["row_id"], 7)
        self.assertTrue(payload["significant_bills_to_score"][0]["is_carryover"])
        self.assertEqual(payload["historical_context"], "内閣の出来事")

    def test_rejects_carryover_flag_that_disagrees_with_source_data(self):
        task1_result = Task1FilterOutput(
            significant_bills=[
                FilteredBillItem(
                    row_id=7,
                    bill_title="法案",
                    expected_category=PolicyCategory.FINANCE,
                    filter_reason="財政政策",
                )
            ]
        )
        task2_result = Task2ScoreOutput(
            scored_bills=[
                ScoredBillItem(
                    row_id=7,
                    bill_title="法案",
                    is_carryover=True,
                    category=PolicyCategory.FINANCE,
                    policy_score=1,
                    normalized_status=NormalizedStatus.PASSED,
                    score_reason="財政政策の方向",
                )
            ]
        )
        records = {7: {"diet_number": 210, "submission_session": 210}}

        with self.assertRaisesRegex(ValueError, "持ち越し判定"):
            validate_task2_ids(task2_result, task1_result, records)

    def test_reuses_valid_cached_response_without_calling_llm(self):
        result = Task1FilterOutput(
            significant_bills=[
                FilteredBillItem(
                    row_id=7,
                    bill_title="法案",
                    expected_category="FINANCE",
                    filter_reason="財政政策の転換",
                )
            ]
        )
        client = MagicMock()
        client.models.generate_content.return_value.text = result.model_dump_json()
        client_factory = MagicMock(return_value=client)

        with tempfile.TemporaryDirectory() as temporary_directory:
            cache_dir = Path(temporary_directory)
            first_result = generate_cached(
                stage="task1-filter",
                model_name="test-model",
                system_instruction="instruction",
                payload={"bills": []},
                response_schema=Task1FilterOutput,
                cache_dir=cache_dir,
                client_factory=client_factory,
            )
            client_factory.reset_mock()

            cached = generate_cached(
                stage="task1-filter",
                model_name="test-model",
                system_instruction="instruction",
                payload={"bills": []},
                response_schema=Task1FilterOutput,
                cache_dir=cache_dir,
                client_factory=client_factory,
            )

        self.assertEqual(first_result, result)
        self.assertEqual(cached, result)
        client_factory.assert_not_called()

    def test_calls_llm_and_caches_structured_response(self):
        client = MagicMock()
        client.models.generate_content.return_value.text = json.dumps(
            {"significant_bills": [], "conflict_resolutions": []}
        )
        client_factory = MagicMock(return_value=client)

        with tempfile.TemporaryDirectory() as temporary_directory:
            cache_dir = Path(temporary_directory)
            result = generate_cached(
                stage="task1-filter",
                model_name="test-model",
                system_instruction="instruction",
                payload={"bills": []},
                response_schema=Task1FilterOutput,
                cache_dir=cache_dir,
                client_factory=client_factory,
            )

            self.assertIsInstance(result, Task1FilterOutput)
            self.assertEqual(len(list(cache_dir.glob("task1-filter-*.json"))), 1)

        client.models.generate_content.assert_called_once()

    def test_exports_raw_responses_to_work_json(self):
        cabinet = {
            "prime_minister_number": 42,
            "name": "総理大臣",
            "name_romaji": "Prime Minister",
            "tenure_start_date": "2020-01-01",
            "tenure_end_date": "2021-01-01",
            "tenure_days": 366,
        }
        task1_result = Task1FilterOutput()
        task2_result = Task2ScoreOutput()

        with tempfile.TemporaryDirectory() as temporary_directory:
            output_path = Path(temporary_directory) / "cabinet_llm.json"
            export_result(cabinet, "test-model", task1_result, task2_result, output_path)

            with output_path.open(encoding="utf-8") as json_file:
                result = json.load(json_file)

        self.assertEqual(result["prime_minister_number"], 42)
        self.assertEqual(result["name"], "総理大臣")
        self.assertEqual(result["name_romaji"], "Prime Minister")
        self.assertEqual(result["tenure_start_date"], "2020-01-01")
        self.assertEqual(result["tenure_end_date"], "2021-01-01")
        self.assertEqual(result["tenure_days"], 366)
        self.assertEqual(result["model"], "test-model")
        self.assertEqual(result["task1_response"], task1_result.model_dump(mode="json"))
        self.assertEqual(result["task2_response"], task2_result.model_dump(mode="json"))


if __name__ == "__main__":
    unittest.main()
