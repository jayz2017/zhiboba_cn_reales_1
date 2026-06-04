from __future__ import annotations

from typing import Any

from app.modules.nba_live_text.zhiboba_livetext import (
    LIVE_TEXT_SOURCE_ZHIBOBA,
    normalize_player_name,
)
from app.modules.semantics.models import (
    EventRelationContext,
    PlayerRelationRecord,
    PlayerSegmentationConfig,
)
from app.modules.semantics.rule_config import (
    RelationRuleConfig,
    default_relation_rule_config,
)


def normalize_segmented_text_for_uie(segmented_text: str | None, live_text: str | None) -> str:
    base_text = (segmented_text or "").strip()
    if base_text:
        return base_text.replace("\\", "")
    return (live_text or "").strip()


def _relation_texts(
    relations: dict[str, Any],
    key: str,
    alias_to_full_name: dict[str, str] | None = None,
) -> list[str]:
    values = relations.get(key)
    if not isinstance(values, list):
        return []

    alias_map = alias_to_full_name or {}
    normalized: list[str] = []
    for item in values:
        if not isinstance(item, dict):
            continue
        text_value = item.get("text")
        if not isinstance(text_value, str) or not text_value.strip():
            continue
        value = text_value.strip()
        if alias_map:
            value = normalize_player_name(value, alias_map) or value
        normalized.append(value)
    return normalized


def _best_probability(entity: dict[str, Any], relations: dict[str, Any]) -> float:
    scores: list[float] = []
    probability = entity.get("probability")
    if isinstance(probability, (float, int)):
        scores.append(float(probability))
    for values in relations.values():
        if not isinstance(values, list):
            continue
        for item in values:
            if not isinstance(item, dict):
                continue
            value = item.get("probability")
            if isinstance(value, (float, int)):
                scores.append(float(value))
    if not scores:
        return 0.5
    return max(0.0, min(1.0, min(scores)))


def _detect_defensive_relation_type(
    actions: list[str],
    rule_config: RelationRuleConfig | None = None,
) -> str:
    config = rule_config or default_relation_rule_config()
    combined = " ".join(actions)
    if any(keyword in combined for keyword in config.keywords("block")):
        return "blocks"
    if any(keyword in combined for keyword in config.keywords("steal")):
        return "steals_from"
    if any(keyword in combined for keyword in config.keywords("foul")):
        return "fouls_on"
    if any(keyword in combined for keyword in config.keywords("turnover")):
        return "forces_turnover"
    if any(keyword in combined for keyword in config.keywords("contest")):
        return "contests_shot"
    return "defends"


def _looks_like_scoring(
    actions: list[str],
    results: list[str],
    score_points: int | None,
    rule_config: RelationRuleConfig | None = None,
) -> bool:
    if score_points is not None and score_points > 0:
        return True
    config = rule_config or default_relation_rule_config()
    combined = " ".join(actions + results)
    return any(keyword in combined for keyword in config.keywords("score"))


def _get_player_team_info(
    player_name: str,
    segmentation_config: PlayerSegmentationConfig,
    home_score: int | None = None,
    visit_score: int | None = None,
) -> tuple[str | None, str | None, str | None, int | None]:
    if not player_name or not segmentation_config.player_to_team_id:
        return None, None, None, None

    team_id = segmentation_config.player_to_team_id.get(player_name)
    team_name = segmentation_config.player_to_team_name.get(player_name)
    team_side = segmentation_config.player_to_team_side.get(player_name)

    team_score = None
    if team_side == "home":
        team_score = home_score
    elif team_side == "visit":
        team_score = visit_score

    return team_id, team_name, team_side, team_score


def build_relation_records_from_uie_result(
    *,
    saishi_id: str,
    evidence_event_id: int,
    live_sid: int,
    live_text: str,
    segmented_text: str | None,
    current_player_name: str | None,
    score_points: int | None,
    uie_result: dict[str, Any],
    segmentation_config: PlayerSegmentationConfig,
    event_context: EventRelationContext,
    rule_config: RelationRuleConfig | None = None,
    source: str = LIVE_TEXT_SOURCE_ZHIBOBA,
) -> list[PlayerRelationRecord]:
    if not isinstance(uie_result, dict):
        return []

    # Lazy import to avoid circular dependency with siamese_uie
    from app.modules.semantics.siamese_uie import _append_relation

    config = rule_config or default_relation_rule_config()
    relation_records: list[PlayerRelationRecord] = []
    seen_keys: set[tuple[str, str, str]] = set()
    ctx = event_context

    for offense_entity in uie_result.get("进攻球员", []):
        if not isinstance(offense_entity, dict):
            continue
        offense_player = offense_entity.get("text")
        if not isinstance(offense_player, str) or not offense_player.strip():
            continue
        normalized_offense = normalize_player_name(offense_player, segmentation_config.alias_to_full_name) or offense_player.strip()
        relations = offense_entity.get("relations")
        if not isinstance(relations, dict):
            relations = {}

        helpers = _relation_texts(relations, "协作球员", segmentation_config.alias_to_full_name)
        defenders = _relation_texts(relations, "防守球员", segmentation_config.alias_to_full_name)
        offense_actions = _relation_texts(relations, "进攻动作")
        result_texts = _relation_texts(relations, "结果")
        confidence = _best_probability(offense_entity, relations)
        primary_action = offense_actions[0] if offense_actions else None
        primary_result = result_texts[0] if result_texts else None
        scored = _looks_like_scoring(offense_actions, result_texts, score_points, config)

        off_team_info = _get_player_team_info(normalized_offense, segmentation_config, ctx.home_score, ctx.visit_score)

        for helper in helpers:
            key = (helper, "assist_to", normalized_offense)
            if key not in seen_keys:
                seen_keys.add(key)
                helper_team_info = _get_player_team_info(helper, segmentation_config, ctx.home_score, ctx.visit_score)
                _append_relation(
                    relation_records,
                    saishi_id=saishi_id,
                    evidence_event_id=evidence_event_id,
                    live_sid=live_sid,
                    source=source,
                    relation_type="assist_to",
                    relation_side="offense",
                    subject_player_name=helper,
                    object_player_name=normalized_offense,
                    action_text=primary_action,
                    result_text=primary_result,
                    score_points=score_points,
                    evidence_text=live_text,
                    segmented_text=segmented_text,
                    confidence=confidence,
                    event_context=event_context,
                    subject_team_id=helper_team_info[0],
                    subject_team_name=helper_team_info[1],
                    subject_team_side=helper_team_info[2],
                    subject_team_score=helper_team_info[3],
                    object_team_id=off_team_info[0],
                    object_team_name=off_team_info[1],
                    object_team_side=off_team_info[2],
                    object_team_score=off_team_info[3],
                )
            if any(keyword in " ".join(offense_actions) for keyword in config.keywords("screen")):
                key = (helper, "screen_for", normalized_offense)
                if key not in seen_keys:
                    seen_keys.add(key)
                    helper_team_info = _get_player_team_info(helper, segmentation_config, ctx.home_score, ctx.visit_score)
                    _append_relation(
                        relation_records,
                        saishi_id=saishi_id,
                        evidence_event_id=evidence_event_id,
                        live_sid=live_sid,
                        source=source,
                        relation_type="screen_for",
                        relation_side="offense",
                        subject_player_name=helper,
                        object_player_name=normalized_offense,
                        action_text=primary_action,
                        result_text=primary_result,
                        score_points=score_points,
                        evidence_text=live_text,
                        segmented_text=segmented_text,
                        confidence=confidence,
                        event_context=event_context,
                        subject_team_id=helper_team_info[0],
                        subject_team_name=helper_team_info[1],
                        subject_team_side=helper_team_info[2],
                        subject_team_score=helper_team_info[3],
                        object_team_id=off_team_info[0],
                        object_team_name=off_team_info[1],
                        object_team_side=off_team_info[2],
                        object_team_score=off_team_info[3],
                    )

        for defender in defenders:
            relation_type = "scores_over" if scored else "attacks_against"
            key = (normalized_offense, relation_type, defender)
            if key in seen_keys:
                continue
            seen_keys.add(key)
            def_team_info = _get_player_team_info(defender, segmentation_config, ctx.home_score, ctx.visit_score)
            _append_relation(
                relation_records,
                saishi_id=saishi_id,
                evidence_event_id=evidence_event_id,
                live_sid=live_sid,
                source=source,
                relation_type=relation_type,
                relation_side="offense",
                subject_player_name=normalized_offense,
                object_player_name=defender,
                action_text=primary_action,
                result_text=primary_result,
                score_points=score_points,
                evidence_text=live_text,
                segmented_text=segmented_text,
                confidence=confidence,
                event_context=event_context,
                subject_team_id=off_team_info[0],
                subject_team_name=off_team_info[1],
                subject_team_side=off_team_info[2],
                subject_team_score=off_team_info[3],
                object_team_id=def_team_info[0],
                object_team_name=def_team_info[1],
                object_team_side=def_team_info[2],
                object_team_score=def_team_info[3],
            )

    for defense_entity in uie_result.get("防守球员", []):
        if not isinstance(defense_entity, dict):
            continue
        defense_player = defense_entity.get("text")
        if not isinstance(defense_player, str) or not defense_player.strip():
            continue
        normalized_defender = normalize_player_name(defense_player, segmentation_config.alias_to_full_name) or defense_player.strip()
        relations = defense_entity.get("relations")
        if not isinstance(relations, dict):
            relations = {}
        offense_players = _relation_texts(relations, "进攻球员", segmentation_config.alias_to_full_name)
        defense_actions = _relation_texts(relations, "防守动作")
        result_texts = _relation_texts(relations, "结果")
        confidence = _best_probability(defense_entity, relations)
        relation_type = _detect_defensive_relation_type(defense_actions, config)
        primary_action = defense_actions[0] if defense_actions else None
        primary_result = result_texts[0] if result_texts else None

        def_team_info = _get_player_team_info(normalized_defender, segmentation_config, ctx.home_score, ctx.visit_score)

        for offense_player in offense_players:
            key = (normalized_defender, relation_type, offense_player)
            if key in seen_keys:
                continue
            seen_keys.add(key)
            off_team_info = _get_player_team_info(offense_player, segmentation_config, ctx.home_score, ctx.visit_score)
            _append_relation(
                relation_records,
                saishi_id=saishi_id,
                evidence_event_id=evidence_event_id,
                live_sid=live_sid,
                source=source,
                relation_type=relation_type,
                relation_side="defense",
                subject_player_name=normalized_defender,
                object_player_name=offense_player,
                action_text=primary_action,
                result_text=primary_result,
                score_points=score_points,
                evidence_text=live_text,
                segmented_text=segmented_text,
                confidence=confidence,
                event_context=event_context,
                subject_team_id=def_team_info[0],
                subject_team_name=def_team_info[1],
                subject_team_side=def_team_info[2],
                subject_team_score=def_team_info[3],
                object_team_id=off_team_info[0],
                object_team_name=off_team_info[1],
                object_team_side=off_team_info[2],
                object_team_score=off_team_info[3],
            )

    if not relation_records and current_player_name:
        current_name = normalize_player_name(current_player_name, segmentation_config.alias_to_full_name) or current_player_name.strip()
        cur_team_info = _get_player_team_info(current_name, segmentation_config, ctx.home_score, ctx.visit_score)
        for defense_entity in uie_result.get("防守球员", []):
            if not isinstance(defense_entity, dict):
                continue
            defender = defense_entity.get("text")
            if not isinstance(defender, str) or not defender.strip():
                continue
            normalized_defender = normalize_player_name(defender, segmentation_config.alias_to_full_name) or defender.strip()
            key = (current_name, "attacks_against", normalized_defender)
            if key in seen_keys:
                continue
            seen_keys.add(key)
            def_team_info = _get_player_team_info(normalized_defender, segmentation_config, ctx.home_score, ctx.visit_score)
            _append_relation(
                relation_records,
                saishi_id=saishi_id,
                evidence_event_id=evidence_event_id,
                live_sid=live_sid,
                source=source,
                relation_type="attacks_against",
                relation_side="offense",
                subject_player_name=current_name,
                object_player_name=normalized_defender,
                action_text=None,
                result_text=None,
                score_points=score_points,
                evidence_text=live_text,
                segmented_text=segmented_text,
                confidence=0.5,
                event_context=event_context,
                subject_team_id=cur_team_info[0],
                subject_team_name=cur_team_info[1],
                subject_team_side=cur_team_info[2],
                subject_team_score=cur_team_info[3],
                object_team_id=def_team_info[0],
                object_team_name=def_team_info[1],
                object_team_side=def_team_info[2],
                object_team_score=def_team_info[3],
            )
    return relation_records


__all__ = [
    "normalize_segmented_text_for_uie",
    "_relation_texts",
    "_best_probability",
    "_detect_defensive_relation_type",
    "_looks_like_scoring",
    "_get_player_team_info",
    "build_relation_records_from_uie_result",
]