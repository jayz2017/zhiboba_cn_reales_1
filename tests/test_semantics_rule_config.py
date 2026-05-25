from __future__ import annotations

from unittest.mock import Mock

from app.modules.semantics.models import EventRelationContext, PlayerSegmentationConfig
from app.modules.semantics.rule_config import (
    RelationRuleConfig,
    load_relation_rule_config,
)
from app.modules.semantics.siamese_uie import build_relation_records_from_uie_result


class _MappingsResult:
    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows

    def mappings(self) -> "_MappingsResult":
        return self

    def all(self) -> list[dict]:
        return self._rows


def test_load_relation_rule_config_overrides_defaults_from_db() -> None:
    db = Mock()
    db.execute.side_effect = [
        _MappingsResult(
            [
                {"category": "pass", "keyword": "塞给", "is_enabled": 1},
                {"category": "pass", "keyword": "传球", "is_enabled": 0},
                {"category": "screen", "keyword": "挂掩护", "is_enabled": 1},
            ]
        ),
        _MappingsResult(
            [
                {"config_key": "CONFIDENCE_PASS", "confidence": 0.91},
                {"config_key": "CONFIDENCE_STEAL", "confidence": 1.2},
            ]
        ),
    ]

    config = load_relation_rule_config(db)

    assert config.keywords("pass") == ("塞给",)
    assert config.keywords("screen") == ("挂掩护",)
    assert config.confidence("CONFIDENCE_PASS") == 0.91
    assert config.confidence("CONFIDENCE_STEAL") == 1.0


def test_load_relation_rule_config_uses_defaults_when_db_fails() -> None:
    db = Mock()
    db.execute.side_effect = RuntimeError("table missing")

    config = load_relation_rule_config(db)

    assert "传球" in config.keywords("pass")
    assert config.confidence("CONFIDENCE_PASS") == 0.68


def test_build_relations_uses_dynamic_score_and_screen_keywords() -> None:
    config = RelationRuleConfig(
        keyword_groups={
            "score": ("终结",),
            "screen": ("挂掩护",),
        },
        confidence_values={},
    )

    relations = build_relation_records_from_uie_result(
        saishi_id="1780736",
        evidence_event_id=1,
        live_sid=10,
        live_text="库里挂掩护，格林终结",
        segmented_text="库里\\挂掩护\\格林\\终结",
        current_player_name="格林",
        score_points=None,
        uie_result={
            "进攻球员": [
                {
                    "text": "格林",
                    "probability": 0.9,
                    "relations": {
                        "协作球员": [{"text": "库里", "probability": 0.9}],
                        "防守球员": [{"text": "霍福德", "probability": 0.9}],
                        "进攻动作": [{"text": "挂掩护", "probability": 0.9}],
                        "结果": [{"text": "终结", "probability": 0.9}],
                    },
                }
            ]
        },
        segmentation_config=PlayerSegmentationConfig(
            words=["库里", "格林", "霍福德"],
            alias_to_full_name={
                "库里": "斯蒂芬-库里",
                "格林": "德雷蒙德-格林",
                "霍福德": "艾尔-霍福德",
            },
        ),
        event_context=EventRelationContext(),
        rule_config=config,
    )

    simplified = {(item.subject_player_name, item.relation_type, item.object_player_name) for item in relations}

    assert ("斯蒂芬-库里", "screen_for", "德雷蒙德-格林") in simplified
    assert ("德雷蒙德-格林", "scores_over", "艾尔-霍福德") in simplified
