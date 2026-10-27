import math
import random
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from main import (
    FILTERS,
    INSTRUCTION_IMAGE_DPI,
    INSTRUCTION_IMAGE_SIZE,
    INSTRUCTION_LINE_COLOR,
    INSTRUCTION_SHAPE_HEADINGS,
    NormalizedStatus,
    PolicyCategory,
    ScoredBillItem,
    ScoredEventItem,
    ScoredResolutionItem,
    Task1FilterOutput,
    Task2ScoreOutput,
    compute_scores,
    decoration_category,
    filter_percentile_ranges,
    governance_percent,
    instruction_header_character,
    metric_values,
    run_pipeline,
    score_percentile,
    select_character_path,
    tag_from_name_romaji,
    task1_input,
)


def make_candidate(path_id, *, area, centroid_y, curve_ratio, total_length):
    return {
        "id": path_id,
        "category": "latin",
        "name": f"s-{path_id}",
        "strokes": [[{"x": -1, "y": 0}, {"x": 1, "y": 0}]],
        "metrics": {
            "boundingBox": {"width": area, "height": 1},
            "centroid": {"x": 0, "y": centroid_y},
            "curveRatio": curve_ratio,
            "totalLength": total_length,
        },
    }


class TagPipelineTests(unittest.TestCase):
    def test_instruction_shape_headings_are_in_metric_order(self):
        self.assertEqual(
            INSTRUCTION_SHAPE_HEADINGS,
            ("linearity", "length", "area", "centroid", "addon"),
        )

    def test_instruction_header_capitalizes_only_capital_category(self):
        self.assertEqual(instruction_header_character("a", "capital"), "A")
        self.assertEqual(instruction_header_character("a", "lowercase"), "a")

    def test_tag_is_derived_from_configured_romaji(self):
        self.assertEqual(tag_from_name_romaji("Ryutaro Hashimoto"), "rytr")
        self.assertEqual(tag_from_name_romaji("Shinzo Abe"), "shnz")
        with self.assertRaises(ValueError):
            tag_from_name_romaji("Aeiou Abe")

    def test_task1_input_omits_deliberation_status(self):
        self.assertEqual(
            task1_input(
                [
                    {
                        "id": 1,
                        "category": "閣法",
                        "bill_number": "1",
                        "bill_title": "test bill",
                        "deliberation_status": "成立",
                    }
                ]
            ),
            [
                {
                    "row_id": 1,
                    "category": "閣法",
                    "bill_number": "1",
                    "bill_title": "test bill",
                }
            ],
        )

    def test_filter_order_matches_configuration(self):
        self.assertEqual(
            FILTERS,
            (
                ("MILITARY", "inverse_curve_ratio"),
                ("SECURITY", "total_length"),
                ("FINANCE", "bbox_area"),
                ("BANKING", "centroid_y"),
            ),
        )

    def test_scores_map_to_percentiles_and_governance_decoration_categories(self):
        self.assertEqual([score_percentile(value) for value in (-1, 0, 1)], [25, 50, 75])
        self.assertEqual([governance_percent(value) for value in (-1, 0, 1)], [0, 50, 100])
        self.assertEqual(
            [
                decoration_category(value)
                for value in (-1, -0.6, -0.2, 0.2, 0.6, 1)
            ],
            ["arrow", "double quotes", "null", "underline", "halo", "halo"],
        )

    def test_filter_percentile_ranges_are_grouped_by_category(self):
        ranges = filter_percentile_ranges(
            {
                "MILITARY": 0.27,
                "SECURITY": 0.27,
                "FINANCE": 0.85,
                "BANKING": 0.5,
                "GOVERNANCE": -0.39,
            }
        )
        self.assertEqual(
            ranges["MILITARY"],
            {
                "metric": "inverse_curve_ratio",
                "threshold_percentile": 56.75,
                "percentile_range": [31.75, 81.75],
            },
        )
        self.assertEqual(
            ranges["FINANCE"]["percentile_range"],
            [46.25, 96.25],
        )

    def test_metrics_use_requested_fields(self):
        values = metric_values(
            {
                "boundingBox": {"width": 4, "height": 3},
                "centroid": {"x": 0, "y": -2},
                "curveRatio": 0.25,
                "totalLength": 11,
            }
        )
        self.assertEqual(values, {
            "bbox_area": 12,
            "centroid_y": -2,
            "inverse_curve_ratio": 0.75,
            "total_length": 11,
        })

    def test_positive_military_score_selects_within_plus_minus_25_percentiles(self):
        candidates = [
            make_candidate(i, area=1, centroid_y=0, curve_ratio=i / 5, total_length=1)
            for i in range(1, 5)
        ]
        scores = {category: 0.0 for category in (
            "FINANCE", "MILITARY", "BANKING", "SECURITY", "GOVERNANCE"
        )}
        scores["MILITARY"] = 0.5

        selected = select_character_path("s", candidates, scores, random.Random(1))

        self.assertEqual(selected["selection"]["filter_steps"][0]["candidate_count_after"], 2)
        self.assertIn(selected["id"], {2, 3})

    def test_negative_military_score_uses_same_centered_window(self):
        candidates = [
            make_candidate(i, area=1, centroid_y=0, curve_ratio=i / 5, total_length=1)
            for i in range(1, 5)
        ]
        scores = {
            category: 0.0
            for category in ("FINANCE", "MILITARY", "BANKING", "SECURITY", "GOVERNANCE")
        }
        scores["MILITARY"] = -0.5

        selected = select_character_path("s", candidates, scores, random.Random(1))

        military_step = selected["selection"]["filter_steps"][0]
        self.assertEqual(military_step["candidate_count_after"], 2)
        self.assertIn(selected["id"], {3, 4})

    def test_empty_higher_priority_filter_is_skipped_before_lower_filters(self):
        candidates = [
            make_candidate(
                i,
                area=1,
                centroid_y=0,
                curve_ratio=0.5,
                total_length=i,
            )
            for i in range(1, 5)
        ]
        scores = {
            "FINANCE": 1.0,
            "MILITARY": 0.0,
            "BANKING": 1.0,
            "SECURITY": 0.5,
            "GOVERNANCE": 0.0,
        }

        selected = select_character_path("s", candidates, scores, random.Random(1))

        steps = selected["selection"]["filter_steps"]
        self.assertEqual(len(steps), 4)
        self.assertEqual(steps[0]["filter"], "MILITARY")
        self.assertEqual(steps[0]["candidate_count_after"], 0)
        self.assertEqual(steps[1]["filter"], "SECURITY")
        self.assertEqual(steps[1]["candidate_count_before"], 4)
        self.assertEqual(steps[1]["candidate_count_after"], 2)
        self.assertEqual(selected["selection"]["skipped_filters"], ["MILITARY"])
        self.assertIn(selected["id"], {2, 3})

    def test_binary_scores_are_strict_and_weighted(self):
        bill = ScoredBillItem(
            row_id=1,
            bill_title="test",
            is_carryover=False,
            category=PolicyCategory.FINANCE,
            policy_score=1,
            normalized_status=NormalizedStatus.PASSED,
            score_reason="test",
        )
        event = ScoredEventItem(
            event_title="test",
            category=PolicyCategory.MILITARY,
            event_score=-1,
            score_reason="test",
        )
        scored = Task2ScoreOutput(scored_bills=[bill], scored_events=[event])
        cabinet = {"tenure_days": 365}
        result = compute_scores(cabinet, scored)
        self.assertEqual(result["alpha"], 3.0)
        self.assertEqual(result["raw_sums"]["FINANCE"], 1.0)
        self.assertEqual(result["raw_sums"]["MILITARY"], -1.0)
        self.assertEqual(result["raw_sums"]["GOVERNANCE"], 0.0)
        self.assertEqual(result["final_scores"]["FINANCE"], round(math.tanh(1 / 3), 2))
        with self.assertRaises(ValueError):
            ScoredEventItem(
                event_title="bad",
                category=PolicyCategory.MILITARY,
                event_score=0,
                score_reason="bad",
            )

    def test_governance_resolution_penalties_without_success_bonus(self):
        bills = [
            ScoredBillItem(
                row_id=index,
                bill_title=f"bill-{index}",
                is_carryover=False,
                category=PolicyCategory.FINANCE,
                policy_score=1,
                normalized_status=status,
                score_reason="test",
            )
            for index, status in enumerate(
                (NormalizedStatus.PASSED, NormalizedStatus.AMENDED_PASSED), start=1
            )
        ]
        resolutions = [
            ScoredResolutionItem(
                row_id=index,
                bill_title=f"resolution-{index}",
                normalized_status=status,
            )
            for index, status in enumerate(
                (
                    NormalizedStatus.REJECTED,
                    NormalizedStatus.EXPIRED,
                    NormalizedStatus.CONTINUOUS,
                    NormalizedStatus.WITHDRAWN,
                    NormalizedStatus.PASSED,
                ),
                start=10,
            )
        ]

        result = compute_scores(
            {"tenure_days": 365},
            Task2ScoreOutput(
                scored_bills=bills,
                scored_resolutions=resolutions,
            ),
        )

        self.assertEqual(
            result["raw_sums"]["GOVERNANCE"],
            -0.25 - 0.5 - 1.0,
        )
        self.assertEqual(result["raw_sums"]["FINANCE"], 1.75)

    def test_bill_governance_penalties_skip_carryover_expiry(self):
        bills = [
            ScoredBillItem(
                row_id=index,
                bill_title=f"bill-{index}",
                is_carryover=is_carryover,
                category=PolicyCategory.FINANCE,
                policy_score=1,
                normalized_status=status,
                score_reason="test",
            )
            for index, (status, is_carryover) in enumerate(
                (
                    (NormalizedStatus.WITHDRAWN, False),
                    (NormalizedStatus.EXPIRED, False),
                    (NormalizedStatus.REJECTED, False),
                    (NormalizedStatus.EXPIRED, True),
                ),
                start=1,
            )
        ]
        result = compute_scores(
            {"tenure_days": 365},
            Task2ScoreOutput(scored_bills=bills),
        )
        self.assertEqual(result["raw_sums"]["GOVERNANCE"], -0.25 - 0.5)

    def test_pipeline_writes_tag_json_and_instruction_png(self):
        cabinet = {
            "prime_minister_number": 42,
            "name": "総理大臣",
            "name_romaji": "Prime Minister",
            "tenure_start_date": "2020-01-01",
            "tenure_end_date": "2020-12-31",
            "tenure_days": 365,
            "wiki_body": "<p>history</p>",
            "diet": [],
        }
        candidate = make_candidate(
            1, area=1, centroid_y=0, curve_ratio=0, total_length=1
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            config_path = Path(temporary_directory) / "config.yaml"
            config_path.write_text(
                "common:\n"
                "  cabinet_number: 42\n"
                "  name_romaji: Ryutaro Abe\n"
                "  random_seed: 9\n",
                encoding="utf-8",
            )
            (Path(temporary_directory) / "cabinet_llm.json").write_text(
                "stale", encoding="utf-8"
            )
            (Path(temporary_directory) / "cabinet_score.json").write_text(
                "stale", encoding="utf-8"
            )
            with (
                patch("main.connect_database"),
                patch("main.ensure_mart_schema"),
                patch("main.fetch_cabinet", return_value=cabinet),
                patch(
                    "main.fetch_character_paths",
                    side_effect=lambda _connection, initial: [
                        {**candidate, "name": f"{initial}-{candidate['id']}"}
                    ],
                ),
                patch(
                    "main.generate_cached",
                    side_effect=[Task1FilterOutput(), Task2ScoreOutput()],
                ),
            ):
                output_path = run_pipeline(config_path)

            result = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(output_path.name, "tag.json")
            self.assertEqual(result["prime_minister_number"], 42)
            self.assertEqual(result["name_romaji"], "Ryutaro Abe")
            self.assertEqual(result["tag"], "rytr")
            self.assertEqual(result["random_seed"], 9)
            self.assertIn("task1_response", result)
            self.assertIn("task2_response", result)
            self.assertIn("raw_sums", result)
            self.assertIn("final_scores", result)
            self.assertEqual(result["governance_percent"], 50)
            self.assertEqual(result["decoration_category"], "null")
            self.assertNotIn("decoration_count", result)
            self.assertNotIn("generation", result)
            self.assertEqual(
                result["selection"]["filter_ranges"]["MILITARY"]["percentile_range"],
                [25.0, 75.0],
            )
            self.assertNotIn(
                "percentile_range",
                result["selection"]["paths"][0]["selection"]["filter_steps"][0],
            )
            self.assertEqual(
                [path["role"] for path in result["selection"]["paths"]],
                ["tag_character", "tag_character", "tag_character", "tag_character"],
            )
            self.assertFalse((Path(temporary_directory) / "cabinet_llm.json").exists())
            self.assertFalse((Path(temporary_directory) / "cabinet_score.json").exists())
            self.assertTrue(
                (Path(temporary_directory) / "debug" / "selected-string.png").is_file()
            )
            instruction_path = Path(temporary_directory) / "instruction.png"
            self.assertTrue(instruction_path.is_file())
            with Image.open(instruction_path) as instruction:
                self.assertEqual(instruction.size, INSTRUCTION_IMAGE_SIZE)
                self.assertAlmostEqual(
                    instruction.info["dpi"][0],
                    INSTRUCTION_IMAGE_DPI,
                    delta=0.5,
                )
                self.assertEqual(instruction.format, "PNG")
                x = round(80 * INSTRUCTION_IMAGE_SIZE[0] / 1200)
                self.assertEqual(
                    instruction.getpixel(
                        (x, round(722 * INSTRUCTION_IMAGE_SIZE[1] / 1698))
                    ),
                    (255, 255, 255),
                )
                self.assertEqual(
                    instruction.getpixel(
                        (x, round(780 * INSTRUCTION_IMAGE_SIZE[1] / 1698))
                    ),
                    INSTRUCTION_LINE_COLOR,
                )
                self.assertEqual(
                    instruction.getpixel(
                        (x, round(782 * INSTRUCTION_IMAGE_SIZE[1] / 1698))
                    ),
                    (255, 255, 255),
                )
                self.assertEqual(
                    instruction.getpixel(
                        (x, round(838 * INSTRUCTION_IMAGE_SIZE[1] / 1698))
                    ),
                    (255, 255, 255),
                )
                self.assertEqual(
                    instruction.getpixel(
                        (x, round(896 * INSTRUCTION_IMAGE_SIZE[1] / 1698))
                    ),
                    INSTRUCTION_LINE_COLOR,
                )
                self.assertEqual(
                    instruction.getpixel(
                        (
                            round(600 * INSTRUCTION_IMAGE_SIZE[0] / 1200),
                            round(1401 * INSTRUCTION_IMAGE_SIZE[1] / 1698),
                        )
                    ),
                    (255, 255, 255),
                )


if __name__ == "__main__":
    unittest.main()
