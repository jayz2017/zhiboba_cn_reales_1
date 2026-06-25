import unittest
from unittest.mock import Mock, patch

from app.modules.semantics.siamese_uie import (
    build_relation_records_from_uie_result,
    build_relation_records_with_rule_fallback,
    extract_postgame_player_relations,
    normalize_segmented_text_for_uie,
)
from app.modules.semantics.models import EventRelationContext, PlayerSegmentationConfig
from app.modules.semantics.ontology import format_relation_sample
from app.modules.semantics.validators import RelationType


class TestSiameseUIE(unittest.TestCase):
    def test_normalize_segmented_text_for_uie(self) -> None:
        self.assertEqual(
            normalize_segmented_text_for_uie("斯蒂芬·库里\\助攻\\德雷蒙德·格林\\上篮\\命中", "ignored"),
            "斯蒂芬·库里助攻德雷蒙德·格林上篮命中",
        )
        self.assertEqual(normalize_segmented_text_for_uie(None, "库里助攻格林上篮命中"), "库里助攻格林上篮命中")

    def test_build_relation_records_from_uie_result_creates_offense_and_defense_relations(self) -> None:
        result = build_relation_records_from_uie_result(
            saishi_id="1780736",
            evidence_event_id=12,
            live_sid=640,
            live_text="库里助攻格林上篮命中，霍姆格伦补防被打成2+1",
            segmented_text="斯蒂芬·库里\\助攻\\德雷蒙德·格林\\上篮\\命中",
            current_player_name="格林",
            score_points=2,
            uie_result={
                "进攻球员": [
                    {
                        "text": "格林",
                        "probability": 0.95,
                        "relations": {
                            "协作球员": [{"text": "库里", "probability": 0.97}],
                            "防守球员": [{"text": "霍姆格伦", "probability": 0.8}],
                            "进攻动作": [{"text": "上篮", "probability": 0.92}],
                            "结果": [{"text": "命中", "probability": 0.99}],
                        },
                    }
                ],
                "防守球员": [
                    {
                        "text": "霍姆格伦",
                        "probability": 0.93,
                        "relations": {
                            "进攻球员": [{"text": "格林", "probability": 0.91}],
                            "防守动作": [{"text": "补防", "probability": 0.88}],
                        },
                    }
                ],
            },
            segmentation_config=PlayerSegmentationConfig(
                words=["库里", "格林", "霍姆格伦"],
                alias_to_full_name={
                    "库里": "斯蒂芬·库里",
                    "格林": "德雷蒙德·格林",
                    "霍姆格伦": "切特·霍姆格伦",
                },
            ),
            event_context=EventRelationContext(),
        )

        simplified = {(item.subject_player_name, item.relation_type, item.object_player_name) for item in result}
        self.assertIn(("斯蒂芬·库里", "assist_to", "德雷蒙德·格林"), simplified)
        self.assertIn(("德雷蒙德·格林", "scores_over", "切特·霍姆格伦"), simplified)
        self.assertIn(("切特·霍姆格伦", "defends", "德雷蒙德·格林"), simplified)

    def test_relation_ontology_covers_defensive_uie_types(self) -> None:
        valid_types = set(RelationType.valid_values())
        self.assertIn("fouls_on", valid_types)
        self.assertIn("forces_turnover", valid_types)
        self.assertIn("contests_shot", valid_types)

        result = build_relation_records_from_uie_result(
            saishi_id="1780736",
            evidence_event_id=13,
            live_sid=641,
            live_text="多特逼出格林失误",
            segmented_text="多特\\逼出\\格林\\失误",
            current_player_name="多特",
            score_points=None,
            uie_result={
                "防守球员": [
                    {
                        "text": "多特",
                        "probability": 0.9,
                        "relations": {
                            "进攻球员": [{"text": "格林", "probability": 0.89}],
                            "防守动作": [{"text": "逼出失误", "probability": 0.88}],
                            "结果": [{"text": "失误", "probability": 0.86}],
                        },
                    }
                ]
            },
            segmentation_config=PlayerSegmentationConfig(
                words=["多特", "格林"],
                alias_to_full_name={"多特": "吕冈茨·多特", "格林": "德雷蒙德·格林"},
            ),
            event_context=EventRelationContext(),
        )

        self.assertEqual(result[0].relation_type, "forces_turnover")
        sample = format_relation_sample(result[0])
        self.assertEqual(sample["relation_label_zh"], "造成失误")
        self.assertIn("造成", sample["display_text"])

    def test_extract_postgame_player_relations_returns_samples(self) -> None:
        db = Mock()
        execute_result = Mock()
        execute_result.mappings.return_value.all.return_value = [
            {
                "id": 99,
                "saishi_id": "1780736",
                "live_sid": 640,
                "live_text": "库里助攻格林上篮命中",
                "segmented_text": "库里\\助攻\\格林\\上篮\\命中",
                "current_player_name": "格林",
                "score_points": 2,
            }
        ]
        db.execute.return_value = execute_result

        fake_extractor = Mock()
        fake_extractor.last_backend = "taskflow_subprocess"
        fake_extractor.extract_batch.return_value = [
            {
                "进攻球员": [
                    {
                        "text": "格林",
                        "probability": 0.95,
                        "relations": {
                            "协作球员": [{"text": "库里", "probability": 0.97}],
                            "进攻动作": [{"text": "上篮"}],
                            "结果": [{"text": "命中"}],
                        },
                    }
                ]
            }
        ]

        with (
            patch("app.modules.semantics.orchestrator.ensure_live_text_tables"),
            patch("app.modules.semantics.orchestrator.ensure_player_relation_table"),
            patch(
                "app.modules.semantics.orchestrator.load_player_segmentation_config",
                return_value=PlayerSegmentationConfig(
                    words=["库里", "格林"],
                    alias_to_full_name={"库里": "斯蒂芬·库里", "格林": "德雷蒙德·格林"},
                ),
            ),
            patch("app.modules.semantics.orchestrator.SiameseUIEExtractor", return_value=fake_extractor),
            patch("app.modules.semantics.orchestrator.upsert_player_relations", side_effect=lambda db, relations: len(relations)),
        ):
            result = extract_postgame_player_relations(db=db, saishi_id="1780736", max_rows=10, sample_limit=5)

        self.assertTrue(result["processed"])
        self.assertEqual(result["saishi_id"], "1780736")
        self.assertEqual(result["events"], 1)
        self.assertEqual(result["relations"], 1)
        self.assertEqual(result["backend"], "taskflow_subprocess")
        self.assertEqual(result["samples"][0]["relation_type"], "assist_to")
        self.assertEqual(result["samples"][0]["relation_label_zh"], "助攻")
        self.assertIn("助攻", result["samples"][0]["display_text"])
        self.assertEqual(result["samples"][0]["evidence"]["live_sid"], 640)

    def test_build_relation_records_with_rule_fallback_creates_relations(self) -> None:
        rows = [
            {
                "id": 1,
                "saishi_id": "1780736",
                "live_sid": 48,
                "live_text": "亚历山大控球过半场！！",
                "segmented_text": "谢伊·吉尔杰斯-亚历山大\\控球\\过\\半场",
                "current_player_name": "亚历山大",
                "score_points": None,
            },
            {
                "id": 2,
                "saishi_id": "1780736",
                "live_sid": 49,
                "live_text": "分右侧外线！多特！",
                "segmented_text": "分\\右侧\\外线\\多特",
                "current_player_name": "亚历山大",
                "score_points": None,
            },
            {
                "id": 3,
                "saishi_id": "1780736",
                "live_sid": 50,
                "live_text": "击地底线！切特！",
                "segmented_text": "击地\\底线\\切特·霍姆格伦",
                "current_player_name": "亚历山大",
                "score_points": None,
            },
            {
                "id": 4,
                "saishi_id": "1780736",
                "live_sid": 51,
                "live_text": "切入上篮打进！AND ONE！！！",
                "segmented_text": "切入\\上篮\\打进\\AND\\ONE",
                "current_player_name": "切特·霍姆格伦",
                "score_points": 2,
            },
            {
                "id": 5,
                "saishi_id": "1780736",
                "live_sid": 52,
                "live_text": "贾巴里协防晚了！",
                "segmented_text": "贾巴里·史密斯\\协防\\晚\\了",
                "current_player_name": "贾巴里",
                "score_points": None,
            },
        ]

        relations = build_relation_records_with_rule_fallback(
            rows=rows,
            segmentation_config=PlayerSegmentationConfig(
                words=["亚历山大", "多特", "切特", "贾巴里"],
                alias_to_full_name={
                    "亚历山大": "谢伊·吉尔杰斯-亚历山大",
                    "多特": "吕冈茨·多特",
                    "切特": "切特·霍姆格伦",
                    "切特·霍姆格伦": "切特·霍姆格伦",
                    "贾巴里": "贾巴里·史密斯",
                    "贾巴里·史密斯": "贾巴里·史密斯",
                },
            ),
        )

        simplified = {(item.subject_player_name, item.relation_type, item.object_player_name) for item in relations}
        self.assertIn(("谢伊·吉尔杰斯-亚历山大", "passes_to", "吕冈茨·多特"), simplified)
        self.assertIn(("吕冈茨·多特", "passes_to", "切特·霍姆格伦"), simplified)
        self.assertIn(("吕冈茨·多特", "assist_to", "切特·霍姆格伦"), simplified)
        self.assertIn(("切特·霍姆格伦", "scores_over", "贾巴里·史密斯"), simplified)

    def test_extract_postgame_player_relations_uses_rule_fallback_when_uie_unavailable(self) -> None:
        db = Mock()
        execute_result = Mock()
        execute_result.mappings.return_value.all.return_value = [
            {
                "id": 99,
                "saishi_id": "1780736",
                "live_sid": 49,
                "live_text": "分右侧外线！多特！",
                "segmented_text": "分\\右侧\\外线\\多特",
                "current_player_name": "亚历山大",
                "score_points": None,
            },
            {
                "id": 100,
                "saishi_id": "1780736",
                "live_sid": 50,
                "live_text": "击地底线！切特！",
                "segmented_text": "击地\\底线\\切特·霍姆格伦",
                "current_player_name": "亚历山大",
                "score_points": None,
            },
            {
                "id": 101,
                "saishi_id": "1780736",
                "live_sid": 51,
                "live_text": "切入上篮打进！AND ONE！！！",
                "segmented_text": "切入\\上篮\\打进\\AND\\ONE",
                "current_player_name": "切特·霍姆格伦",
                "score_points": 2,
            },
        ]
        db.execute.return_value = execute_result

        fake_extractor = Mock()
        fake_extractor.last_backend = "unavailable"
        fake_extractor.extract_batch.return_value = [{}, {}, {}]

        with (
            patch("app.modules.semantics.orchestrator.ensure_live_text_tables"),
            patch("app.modules.semantics.orchestrator.ensure_player_relation_table"),
            patch(
                "app.modules.semantics.orchestrator.load_player_segmentation_config",
                return_value=PlayerSegmentationConfig(
                    words=["亚历山大", "多特", "切特"],
                    alias_to_full_name={
                        "亚历山大": "谢伊·吉尔杰斯-亚历山大",
                        "多特": "吕冈茨·多特",
                        "切特": "切特·霍姆格伦",
                        "切特·霍姆格伦": "切特·霍姆格伦",
                    },
                ),
            ),
            patch("app.modules.semantics.orchestrator.SiameseUIEExtractor", return_value=fake_extractor),
            patch("app.modules.semantics.orchestrator.upsert_player_relations", side_effect=lambda db, relations: len(relations)),
        ):
            result = extract_postgame_player_relations(db=db, saishi_id="1780736", max_rows=10, sample_limit=5)

        self.assertTrue(result["processed"])
        self.assertEqual(result["backend"], "rule_fallback")
        self.assertGreaterEqual(result["relations"], 1)
        self.assertTrue(any(item["relation_type"] == "assist_to" for item in result["samples"]))


if __name__ == "__main__":
    unittest.main()
