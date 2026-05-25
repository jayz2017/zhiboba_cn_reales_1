from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal


RelationSide = Literal["offense", "defense"]


@dataclass(frozen=True)
class RelationTypeDefinition:
    """Stable relation ontology used by validators and API presentation."""

    code: str
    label_zh: str
    default_side: RelationSide
    subject_role_zh: str
    object_role_zh: str
    verb_zh: str
    description_zh: str


RELATION_TYPE_DEFINITIONS: dict[str, RelationTypeDefinition] = {
    "passes_to": RelationTypeDefinition(
        code="passes_to",
        label_zh="传球",
        default_side="offense",
        subject_role_zh="传球人",
        object_role_zh="接球人",
        verb_zh="传球给",
        description_zh="进攻方球员将球传给队友。",
    ),
    "assist_to": RelationTypeDefinition(
        code="assist_to",
        label_zh="助攻",
        default_side="offense",
        subject_role_zh="助攻者",
        object_role_zh="得分者",
        verb_zh="助攻",
        description_zh="进攻方球员助攻队友完成得分。",
    ),
    "attacks_against": RelationTypeDefinition(
        code="attacks_against",
        label_zh="进攻对位",
        default_side="offense",
        subject_role_zh="进攻者",
        object_role_zh="防守者",
        verb_zh="进攻面对",
        description_zh="进攻方球员持球或终结时面对防守球员。",
    ),
    "scores_over": RelationTypeDefinition(
        code="scores_over",
        label_zh="面对防守得分",
        default_side="offense",
        subject_role_zh="得分者",
        object_role_zh="防守者",
        verb_zh="在防守下得分",
        description_zh="进攻方球员在指定防守球员防守下完成得分。",
    ),
    "screen_for": RelationTypeDefinition(
        code="screen_for",
        label_zh="掩护",
        default_side="offense",
        subject_role_zh="掩护者",
        object_role_zh="受益进攻者",
        verb_zh="为其掩护",
        description_zh="进攻方球员为队友做掩护或挡拆。",
    ),
    "steals_from": RelationTypeDefinition(
        code="steals_from",
        label_zh="抢断",
        default_side="defense",
        subject_role_zh="抢断者",
        object_role_zh="被抢断者",
        verb_zh="抢断",
        description_zh="防守方球员从进攻球员处完成抢断。",
    ),
    "blocks": RelationTypeDefinition(
        code="blocks",
        label_zh="封盖",
        default_side="defense",
        subject_role_zh="封盖者",
        object_role_zh="被封盖者",
        verb_zh="封盖",
        description_zh="防守方球员封盖进攻球员的出手。",
    ),
    "defends": RelationTypeDefinition(
        code="defends",
        label_zh="防守",
        default_side="defense",
        subject_role_zh="防守者",
        object_role_zh="进攻者",
        verb_zh="防守",
        description_zh="防守方球员对进攻球员形成防守或干扰。",
    ),
    "rebounds_over": RelationTypeDefinition(
        code="rebounds_over",
        label_zh="篮板争抢",
        default_side="defense",
        subject_role_zh="篮板获得者",
        object_role_zh="争抢对手",
        verb_zh="争抢篮板胜过",
        description_zh="球员在篮板争抢中相对另一名球员取得优势。",
    ),
    "fouls_on": RelationTypeDefinition(
        code="fouls_on",
        label_zh="犯规",
        default_side="defense",
        subject_role_zh="犯规者",
        object_role_zh="被犯规者",
        verb_zh="对其犯规",
        description_zh="防守方或对位球员对另一名球员犯规。",
    ),
    "forces_turnover": RelationTypeDefinition(
        code="forces_turnover",
        label_zh="造成失误",
        default_side="defense",
        subject_role_zh="施压者",
        object_role_zh="失误者",
        verb_zh="造成其失误",
        description_zh="防守方球员通过施压造成进攻球员失误。",
    ),
    "contests_shot": RelationTypeDefinition(
        code="contests_shot",
        label_zh="干扰投篮",
        default_side="defense",
        subject_role_zh="干扰者",
        object_role_zh="出手者",
        verb_zh="干扰其出手",
        description_zh="防守方球员干扰进攻球员投篮或终结。",
    ),
}


def valid_relation_types() -> list[str]:
    return list(RELATION_TYPE_DEFINITIONS)


def get_relation_definition(relation_type: str) -> RelationTypeDefinition | None:
    return RELATION_TYPE_DEFINITIONS.get((relation_type or "").strip())


def _score_suffix(score_points: int | None) -> str:
    if score_points is None or score_points <= 0:
        return ""
    return f"，得到{score_points}分"


def build_relation_display_text(relation: Any) -> str:
    subject = (getattr(relation, "subject_player_name", "") or "").strip()
    obj = (getattr(relation, "object_player_name", "") or "").strip()
    relation_type = (getattr(relation, "relation_type", "") or "").strip()
    action_text = (getattr(relation, "action_text", None) or "").strip()
    result_text = (getattr(relation, "result_text", None) or "").strip()
    score_points = getattr(relation, "score_points", None)
    definition = get_relation_definition(relation_type)

    if not subject or not obj:
        return ""

    details = "，".join(part for part in (action_text, result_text) if part)
    detail_suffix = f"（{details}）" if details else ""

    if relation_type == "assist_to":
        return f"{subject}助攻{obj}{_score_suffix(score_points)}{detail_suffix}"
    if relation_type == "passes_to":
        return f"{subject}传球给{obj}{detail_suffix}"
    if relation_type == "scores_over":
        return f"{subject}在{obj}防守下得分{_score_suffix(score_points)}{detail_suffix}"
    if relation_type == "screen_for":
        return f"{subject}为{obj}做掩护{detail_suffix}"
    if relation_type == "attacks_against":
        return f"{subject}进攻面对{obj}{detail_suffix}"
    if relation_type == "steals_from":
        return f"{subject}抢断{obj}{detail_suffix}"
    if relation_type == "blocks":
        return f"{subject}封盖{obj}{detail_suffix}"
    if relation_type == "defends":
        return f"{subject}防守{obj}{detail_suffix}"
    if relation_type == "rebounds_over":
        return f"{subject}与{obj}争抢篮板并占优{detail_suffix}"
    if relation_type == "fouls_on":
        return f"{subject}对{obj}犯规{detail_suffix}"
    if relation_type == "forces_turnover":
        return f"{subject}造成{obj}失误{detail_suffix}"
    if relation_type == "contests_shot":
        return f"{subject}干扰{obj}出手{detail_suffix}"

    verb = definition.verb_zh if definition else relation_type
    return f"{subject}{verb}{obj}{detail_suffix}"


def build_evidence_summary(relation: Any) -> str:
    parts = [
        f"event_id={getattr(relation, 'evidence_event_id', '')}",
        f"live_sid={getattr(relation, 'live_sid', '')}",
    ]
    action_text = getattr(relation, "action_text", None)
    result_text = getattr(relation, "result_text", None)
    score_points = getattr(relation, "score_points", None)
    if action_text:
        parts.append(f"动作={action_text}")
    if result_text:
        parts.append(f"结果={result_text}")
    if score_points is not None:
        parts.append(f"得分={score_points}")
    return "；".join(str(part) for part in parts if part)


def format_relation_sample(relation: Any) -> dict[str, Any]:
    definition = get_relation_definition(getattr(relation, "relation_type", ""))
    evidence_text = getattr(relation, "evidence_text", "")
    segmented_text = getattr(relation, "segmented_text", None) or ""

    return {
        "live_sid": relation.live_sid,
        "relation_type": relation.relation_type,
        "relation_label_zh": definition.label_zh if definition else relation.relation_type,
        "relation_side": relation.relation_side,
        "subject_role_zh": definition.subject_role_zh if definition else "主体",
        "subject_player_name": relation.subject_player_name,
        "subject_team_id": relation.subject_team_id,
        "subject_team_name": relation.subject_team_name,
        "subject_team_side": relation.subject_team_side,
        "object_role_zh": definition.object_role_zh if definition else "客体",
        "object_player_name": relation.object_player_name,
        "object_team_id": relation.object_team_id,
        "object_team_name": relation.object_team_name,
        "object_team_side": relation.object_team_side,
        "offense_team_id": relation.offense_team_id,
        "offense_team_name": relation.offense_team_name,
        "offense_team_side": relation.offense_team_side,
        "offense_team_points": relation.offense_team_points,
        "possession_number": relation.possession_number,
        "home_score": relation.home_score,
        "visit_score": relation.visit_score,
        "action_text": relation.action_text,
        "result_text": relation.result_text,
        "score_points": relation.score_points,
        "display_text": build_relation_display_text(relation),
        "evidence_summary": build_evidence_summary(relation),
        "evidence": {
            "event_id": relation.evidence_event_id,
            "live_sid": relation.live_sid,
            "text": evidence_text,
            "segmented_text": segmented_text,
        },
        "evidence_text": evidence_text,
        "segmented_text": segmented_text,
        "confidence": relation.confidence,
    }
