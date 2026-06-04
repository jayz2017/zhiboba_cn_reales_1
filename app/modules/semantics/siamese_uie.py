from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
from typing import Any

from app.core.config import settings
from app.modules.nba_live_text.zhiboba_livetext import (
    LIVE_TEXT_SOURCE_ZHIBOBA,
    normalize_player_name,
)
from app.modules.semantics.models import (
    EventRelationContext,
    PlayerRelationRecord,
    PlayerSegmentationConfig,
    _FallbackContext,
    _PossessionTracker,
)
from app.modules.semantics.context_builder import (
    _canonical_text,
    _extract_player_mentions_from_segmented_text,
    _row_score_points,
)
from app.modules.semantics.rule_config import (
    RelationRuleConfig,
    default_relation_rule_config,
)
from app.modules.semantics.uie_result_parser import (
    _get_player_team_info,
    build_relation_records_from_uie_result,
    normalize_segmented_text_for_uie,
)

"""
SiameseUIE 球员关系抽取主入口模块。

编排 UIE 模型推理、规则回退、质量过滤等完整的关系抽取流程。
"""

logger = logging.getLogger(__name__)

_DEFAULT_RELATION_SCHEMA: list[dict[str, list[str]]] = [
    {"进攻球员": ["防守球员", "协作球员", "进攻动作", "结果", "得分值"]},
    {"防守球员": ["进攻球员", "防守动作", "结果"]},
]



class SiameseUIEExtractor:
    def __init__(
        self,
        *,
        model_name: str | None = None,
        batch_size: int | None = None,
        schema: list[dict[str, list[str]]] | None = None,
    ) -> None:
        self._model_name = (model_name or settings.SIAMESE_UIE_MODEL_NAME).strip()
        self._batch_size = max(1, int(batch_size or settings.SIAMESE_UIE_BATCH_SIZE))
        self._schema = schema or _DEFAULT_RELATION_SCHEMA
        self.last_backend = "uninitialized"

    def extract_batch(self, texts: list[str]) -> list[dict[str, Any]]:
        normalized = [(text or "").strip() for text in (texts or [])]
        if not normalized:
            self.last_backend = "empty"
            return []

        raw_results = self._run_taskflow_subprocess(normalized)
        if raw_results is None:
            self.last_backend = "unavailable"
            return [{} for _ in normalized]
        self.last_backend = "taskflow_subprocess"
        if not isinstance(raw_results, list):
            return [{} for _ in normalized]

        normalized_results: list[dict[str, Any]] = []
        for item in raw_results:
            normalized_results.append(item if isinstance(item, dict) else {})
        while len(normalized_results) < len(normalized):
            normalized_results.append({})
        return normalized_results[: len(normalized)]

    def _run_taskflow_subprocess(self, texts: list[str]) -> list[dict[str, Any]] | None:
        if not texts:
            return []

        with TemporaryDirectory(prefix="siamese_uie_runtime_") as temp_root:
            payload_path = os.path.join(temp_root, "payload.json")
            result_path = os.path.join(temp_root, "result.json")
            with open(payload_path, "w", encoding="utf-8") as fp:
                json.dump(
                    {
                        "texts": texts,
                        "schema": self._schema,
                        "model_name": self._model_name,
                    },
                    fp,
                    ensure_ascii=False,
                )

            runner_code = """
import json
import os
import sys
os.environ.setdefault("FLAGS_enable_pir_api", "0")
from paddlenlp import Taskflow

with open(sys.argv[1], "r", encoding="utf-8") as fp:
    payload = json.load(fp)

extractor = Taskflow(
    "information_extraction",
    schema=payload["schema"],
    model=payload["model_name"],
)
results = extractor(payload["texts"])
with open(sys.argv[2], "w", encoding="utf-8") as fp:
    json.dump(results, fp, ensure_ascii=False)
print("SIAMESE_UIE_OK", flush=True)
"""
            try:
                completed = subprocess.run(
                    [sys.executable, "-X", "faulthandler", "-c", runner_code, payload_path, result_path],
                    capture_output=True,
                    text=True,
                    timeout=240,
                    env=os.environ.copy(),
                )
            except Exception:
                return None

            if completed.returncode != 0 or "SIAMESE_UIE_OK" not in (completed.stdout or ""):
                return None
            if not os.path.exists(result_path):
                return None
            with open(result_path, "r", encoding="utf-8") as fp:
                loaded = json.load(fp)
            return loaded if isinstance(loaded, list) else None


def _build_event_context_from_row(
    row: dict[str, Any],
    segmentation_config: PlayerSegmentationConfig,
    possession_tracker: _PossessionTracker,
) -> tuple[EventRelationContext, _PossessionTracker]:
    home_score = row.get("home_score")
    visit_score = row.get("visit_score")
    score_points = row.get("score_points")
    score_team_side = row.get("score_team_side")

    home_score_val = int(home_score) if isinstance(home_score, (int, float)) and home_score is not None else None
    visit_score_val = int(visit_score) if isinstance(visit_score, (int, float)) and visit_score is not None else None
    score_points_val = int(score_points) if isinstance(score_points, (int, float)) and score_points is not None else None

    offense_side = score_team_side if isinstance(score_team_side, str) and score_team_side.strip() else None
    if offense_side == "both":
        offense_side = None

    updated_tracker = possession_tracker.detect_possession_change(offense_side)

    offense_team_id = None
    offense_team_name = None
    offense_team_score = None

    if segmentation_config.game_team_context:
        if offense_side == "home":
            offense_team_id = segmentation_config.game_team_context.home_team_id
            offense_team_name = segmentation_config.game_team_context.home_team_name
            offense_team_score = home_score_val
        elif offense_side == "visit":
            offense_team_id = segmentation_config.game_team_context.guest_team_id
            offense_team_name = segmentation_config.game_team_context.guest_team_name
            offense_team_score = visit_score_val

    context = EventRelationContext(
        offense_team_id=offense_team_id,
        offense_team_name=offense_team_name,
        offense_team_side=updated_tracker.offense_team_side,
        offense_team_score=offense_team_score,
        offense_team_points=score_points_val,
        possession_number=updated_tracker.possession_number,
        home_score=home_score_val,
        visit_score=visit_score_val,
    )

    return context, updated_tracker


def _append_relation(
    relations: list[PlayerRelationRecord],
    *,
    saishi_id: str,
    evidence_event_id: int,
    live_sid: int,
    relation_type: str,
    relation_side: str,
    subject_player_name: str,
    object_player_name: str,
    action_text: str | None,
    result_text: str | None,
    score_points: int | None,
    evidence_text: str,
    segmented_text: str | None,
    confidence: float,
    event_context: EventRelationContext | None = None,
    subject_team_id: str | None = None,
    subject_team_name: str | None = None,
    subject_team_side: str | None = None,
    subject_team_score: int | None = None,
    object_team_id: str | None = None,
    object_team_name: str | None = None,
    object_team_side: str | None = None,
    object_team_score: int | None = None,
    source: str = LIVE_TEXT_SOURCE_ZHIBOBA,
) -> None:
    subject = (subject_player_name or "").strip()
    obj = (object_player_name or "").strip()
    if not subject or not obj or subject == obj:
        return

    ctx = event_context or EventRelationContext()
    relations.append(
        PlayerRelationRecord(
            saishi_id=saishi_id,
            evidence_event_id=evidence_event_id,
            live_sid=live_sid,
            source=source,
            relation_type=relation_type,
            relation_side=relation_side,
            subject_player_name=subject,
            subject_team_id=subject_team_id,
            subject_team_name=subject_team_name,
            subject_team_side=subject_team_side,
            subject_team_score=subject_team_score,
            object_player_name=obj,
            object_team_id=object_team_id,
            object_team_name=object_team_name,
            object_team_side=object_team_side,
            object_team_score=object_team_score,
            offense_team_id=ctx.offense_team_id,
            offense_team_name=ctx.offense_team_name,
            offense_team_side=ctx.offense_team_side,
            offense_team_score=ctx.offense_team_score,
            offense_team_points=ctx.offense_team_points,
            possession_number=ctx.possession_number,
            home_score=ctx.home_score,
            visit_score=ctx.visit_score,
            action_text=(action_text or "").strip() or None,
            result_text=(result_text or "").strip() or None,
            score_points=score_points,
            evidence_text=evidence_text,
            segmented_text=segmented_text,
            extractor_name="siamese_uie",
            confidence=confidence,
        )
    )



def _append_relation_if_new(
    relation_records: list[PlayerRelationRecord],
    seen_keys: set[tuple[str, str, str, int]],
    *,
    saishi_id: str,
    evidence_event_id: int,
    live_sid: int,
    relation_type: str,
    relation_side: str,
    subject_player_name: str,
    object_player_name: str,
    action_text: str | None,
    result_text: str | None,
    score_points: int | None,
    evidence_text: str,
    segmented_text: str | None,
    extractor_name: str,
    confidence: float,
    event_context: EventRelationContext | None = None,
    subject_team_id: str | None = None,
    subject_team_name: str | None = None,
    subject_team_side: str | None = None,
    subject_team_score: int | None = None,
    object_team_id: str | None = None,
    object_team_name: str | None = None,
    object_team_side: str | None = None,
    object_team_score: int | None = None,
    source: str = LIVE_TEXT_SOURCE_ZHIBOBA,
) -> None:
    key = (subject_player_name.strip(), relation_type.strip(), object_player_name.strip(), live_sid)
    if key in seen_keys:
        return
    seen_keys.add(key)
    _append_relation(
        relation_records,
        saishi_id=saishi_id,
        evidence_event_id=evidence_event_id,
        live_sid=live_sid,
        source=source,
        relation_type=relation_type,
        relation_side=relation_side,
        subject_player_name=subject_player_name,
        object_player_name=object_player_name,
        action_text=action_text,
        result_text=result_text,
        score_points=score_points,
        evidence_text=evidence_text,
        segmented_text=segmented_text,
        confidence=confidence,
        event_context=event_context,
        subject_team_id=subject_team_id,
        subject_team_name=subject_team_name,
        subject_team_side=subject_team_side,
        subject_team_score=subject_team_score,
        object_team_id=object_team_id,
        object_team_name=object_team_name,
        object_team_side=object_team_side,
        object_team_score=object_team_score,
    )
    relation_records[-1] = PlayerRelationRecord(
        saishi_id=relation_records[-1].saishi_id,
        evidence_event_id=relation_records[-1].evidence_event_id,
        live_sid=relation_records[-1].live_sid,
        source=relation_records[-1].source,
        relation_type=relation_records[-1].relation_type,
        relation_side=relation_records[-1].relation_side,
        subject_player_name=relation_records[-1].subject_player_name,
        subject_team_id=relation_records[-1].subject_team_id,
        subject_team_name=relation_records[-1].subject_team_name,
        subject_team_side=relation_records[-1].subject_team_side,
        subject_team_score=relation_records[-1].subject_team_score,
        object_player_name=relation_records[-1].object_player_name,
        object_team_id=relation_records[-1].object_team_id,
        object_team_name=relation_records[-1].object_team_name,
        object_team_side=relation_records[-1].object_team_side,
        object_team_score=relation_records[-1].object_team_score,
        offense_team_id=relation_records[-1].offense_team_id,
        offense_team_name=relation_records[-1].offense_team_name,
        offense_team_side=relation_records[-1].offense_team_side,
        offense_team_score=relation_records[-1].offense_team_score,
        offense_team_points=relation_records[-1].offense_team_points,
        possession_number=relation_records[-1].possession_number,
        home_score=relation_records[-1].home_score,
        visit_score=relation_records[-1].visit_score,
        action_text=relation_records[-1].action_text,
        result_text=relation_records[-1].result_text,
        score_points=relation_records[-1].score_points,
        evidence_text=relation_records[-1].evidence_text,
        segmented_text=relation_records[-1].segmented_text,
        extractor_name=extractor_name,
        confidence=confidence,
    )


def build_relation_records_with_rule_fallback(
    *,
    rows: list[dict[str, Any]],
    segmentation_config: PlayerSegmentationConfig,
    rule_config: RelationRuleConfig | None = None,
) -> list[PlayerRelationRecord]:
    config = rule_config or default_relation_rule_config()
    relation_records: list[PlayerRelationRecord] = []
    seen_keys: set[tuple[str, str, str, int]] = set()
    context = _FallbackContext()
    possession_tracker = _PossessionTracker()

    for row in rows:
        source = str(row.get("source") or LIVE_TEXT_SOURCE_ZHIBOBA)
        evidence_text = row["live_text"]
        segmented_text = row["segmented_text"]
        canonical_live_text = _canonical_text(row["live_text"])
        canonical_segmented = _canonical_text(row["segmented_text"])
        player_mentions = _extract_player_mentions_from_segmented_text(
            segmented_text or row["live_text"],
            segmentation_config.alias_to_full_name,
        )
        score_points = _row_score_points(row)
        current_player_name = row["current_player_name"] if isinstance(row["current_player_name"], str) else None
        normalized_current = normalize_player_name(current_player_name, segmentation_config.alias_to_full_name) if current_player_name else None

        event_context, possession_tracker = _build_event_context_from_row(
            row=row,
            segmentation_config=segmentation_config,
            possession_tracker=possession_tracker,
        )
        ctx = event_context

        passer = player_mentions[0] if player_mentions else context.passer
        receiver = player_mentions[1] if len(player_mentions) > 1 else None
        primary_player = player_mentions[0] if player_mentions else normalized_current

        def _get_subject_team(player):
            return _get_player_team_info(player or "", segmentation_config, ctx.home_score, ctx.visit_score)

        def _get_object_team(player):
            return _get_player_team_info(player or "", segmentation_config, ctx.home_score, ctx.visit_score)

        if any(keyword in canonical_live_text for keyword in config.keywords("pass")):
            is_steal_event = any(keyword in canonical_live_text for keyword in config.keywords("steal"))
            if is_steal_event:
                possession_tracker = possession_tracker.detect_possession_change(None, is_steal=True)

            if len(player_mentions) >= 2:
                passer = player_mentions[0]
                receiver = player_mentions[-1]
                sub_team = _get_subject_team(passer)
                obj_team = _get_object_team(receiver)
                _append_relation_if_new(
                    relation_records,
                    seen_keys,
                    saishi_id=row["saishi_id"],
                    evidence_event_id=int(row["id"]),
                    live_sid=int(row["live_sid"]),
                    source=source,
                    relation_type="passes_to",
                    relation_side="offense",
                    subject_player_name=passer,
                    object_player_name=receiver,
                    action_text="传球",
                    result_text=None,
                    score_points=None,
                    evidence_text=evidence_text,
                    segmented_text=segmented_text,
                    extractor_name="rule_fallback",
                    confidence=config.confidence("CONFIDENCE_PASS"),
                    event_context=event_context,
                    subject_team_id=sub_team[0],
                    subject_team_name=sub_team[1],
                    subject_team_side=sub_team[2],
                    subject_team_score=sub_team[3],
                    object_team_id=obj_team[0],
                    object_team_name=obj_team[1],
                    object_team_side=obj_team[2],
                    object_team_score=obj_team[3],
                )
                context = _FallbackContext(passer=passer, receiver=receiver, attacker=receiver, defender=context.defender)
                continue
            if len(player_mentions) == 1 and context.attacker and player_mentions[0] != context.attacker:
                sub_team = _get_subject_team(context.attacker)
                obj_team = _get_object_team(player_mentions[0])
                _append_relation_if_new(
                    relation_records,
                    seen_keys,
                    saishi_id=row["saishi_id"],
                    evidence_event_id=int(row["id"]),
                    live_sid=int(row["live_sid"]),
                    source=source,
                    relation_type="passes_to",
                    relation_side="offense",
                    subject_player_name=context.attacker,
                    object_player_name=player_mentions[0],
                    action_text="传球",
                    result_text=None,
                    score_points=None,
                    evidence_text=evidence_text,
                    segmented_text=segmented_text,
                    extractor_name="rule_fallback",
                    confidence=config.confidence("CONFIDENCE_PASS_LOW"),
                    event_context=event_context,
                    subject_team_id=sub_team[0],
                    subject_team_name=sub_team[1],
                    subject_team_side=sub_team[2],
                    subject_team_score=sub_team[3],
                    object_team_id=obj_team[0],
                    object_team_name=obj_team[1],
                    object_team_side=obj_team[2],
                    object_team_score=obj_team[3],
                )
                context = _FallbackContext(passer=context.attacker, receiver=player_mentions[0], attacker=player_mentions[0], defender=context.defender)
                continue

        if "对位" in canonical_live_text or (
            any(keyword in canonical_live_text for keyword in config.keywords("attack")) and len(player_mentions) >= 2
        ):
            if len(player_mentions) >= 2:
                attacker = player_mentions[0]
                defender = player_mentions[-1]
            else:
                attacker = primary_player
                defender = player_mentions[0] if player_mentions else None
            if attacker and defender and attacker != defender:
                sub_team = _get_subject_team(attacker)
                obj_team = _get_object_team(defender)
                _append_relation_if_new(
                    relation_records,
                    seen_keys,
                    saishi_id=row["saishi_id"],
                    evidence_event_id=int(row["id"]),
                    live_sid=int(row["live_sid"]),
                    source=source,
                    relation_type="attacks_against",
                    relation_side="offense",
                    subject_player_name=attacker,
                    object_player_name=defender,
                    action_text="单打对位",
                    result_text=None,
                    score_points=None,
                    evidence_text=evidence_text,
                    segmented_text=segmented_text,
                    extractor_name="rule_fallback",
                    confidence=config.confidence("CONFIDENCE_ATTACK"),
                    event_context=event_context,
                    subject_team_id=sub_team[0],
                    subject_team_name=sub_team[1],
                    subject_team_side=sub_team[2],
                    subject_team_score=sub_team[3],
                    object_team_id=obj_team[0],
                    object_team_name=obj_team[1],
                    object_team_side=obj_team[2],
                    object_team_score=obj_team[3],
                )
                context = _FallbackContext(passer=context.passer, receiver=context.receiver, attacker=attacker, defender=defender)
                continue

        if any(keyword in canonical_live_text for keyword in config.keywords("steal")):
            possession_tracker = possession_tracker.detect_possession_change(None, is_steal=True)

            if len(player_mentions) >= 2:
                stealer, victim = player_mentions[0], player_mentions[-1]
            elif primary_player and context.attacker and primary_player != context.attacker:
                stealer, victim = primary_player, context.attacker
            else:
                stealer, victim = None, None
            if stealer and victim:
                sub_team = _get_subject_team(stealer)
                obj_team = _get_object_team(victim)
                _append_relation_if_new(
                    relation_records,
                    seen_keys,
                    saishi_id=row["saishi_id"],
                    evidence_event_id=int(row["id"]),
                    live_sid=int(row["live_sid"]),
                    source=source,
                    relation_type="steals_from",
                    relation_side="defense",
                    subject_player_name=stealer,
                    object_player_name=victim,
                    action_text="抢断",
                    result_text=None,
                    score_points=None,
                    evidence_text=evidence_text,
                    segmented_text=segmented_text,
                    extractor_name="rule_fallback",
                    confidence=config.confidence("CONFIDENCE_STEAL"),
                    event_context=event_context,
                    subject_team_id=sub_team[0],
                    subject_team_name=sub_team[1],
                    subject_team_side=sub_team[2],
                    subject_team_score=sub_team[3],
                    object_team_id=obj_team[0],
                    object_team_name=obj_team[1],
                    object_team_side=obj_team[2],
                    object_team_score=obj_team[3],
                )
                context = _FallbackContext(attacker=stealer, defender=victim)
                continue

        if any(keyword in canonical_live_text for keyword in config.keywords("block")):
            if len(player_mentions) >= 2:
                blocker, victim = player_mentions[0], player_mentions[-1]
            elif primary_player and context.attacker and primary_player != context.attacker:
                blocker, victim = primary_player, context.attacker
            else:
                blocker, victim = None, None
            if blocker and victim:
                sub_team = _get_subject_team(blocker)
                obj_team = _get_object_team(victim)
                _append_relation_if_new(
                    relation_records,
                    seen_keys,
                    saishi_id=row["saishi_id"],
                    evidence_event_id=int(row["id"]),
                    live_sid=int(row["live_sid"]),
                    source=source,
                    relation_type="blocks",
                    relation_side="defense",
                    subject_player_name=blocker,
                    object_player_name=victim,
                    action_text="封盖",
                    result_text=None,
                    score_points=None,
                    evidence_text=evidence_text,
                    segmented_text=segmented_text,
                    extractor_name="rule_fallback",
                    confidence=config.confidence("CONFIDENCE_BLOCK"),
                    event_context=event_context,
                    subject_team_id=sub_team[0],
                    subject_team_name=sub_team[1],
                    subject_team_side=sub_team[2],
                    subject_team_score=sub_team[3],
                    object_team_id=obj_team[0],
                    object_team_name=obj_team[1],
                    object_team_side=obj_team[2],
                    object_team_score=obj_team[3],
                )
                context = _FallbackContext(attacker=victim, defender=blocker)
                continue

        if any(keyword in canonical_live_text for keyword in config.keywords("help_defense")):
            defender = primary_player
            attacker = context.attacker or context.receiver
            if defender and attacker and defender != attacker:
                att_team = _get_subject_team(attacker)
                def_team = _get_object_team(defender)
                _append_relation_if_new(
                    relation_records,
                    seen_keys,
                    saishi_id=row["saishi_id"],
                    evidence_event_id=int(row["id"]),
                    live_sid=int(row["live_sid"]),
                    source=source,
                    relation_type="scores_over",
                    relation_side="offense",
                    subject_player_name=attacker,
                    object_player_name=defender,
                    action_text="得分",
                    result_text="命中",
                    score_points=score_points,
                    evidence_text=evidence_text,
                    segmented_text=segmented_text,
                    extractor_name="rule_fallback",
                    confidence=config.confidence("CONFIDENCE_SCORE_OVER_CONTEST"),
                    event_context=event_context,
                    subject_team_id=att_team[0],
                    subject_team_name=att_team[1],
                    subject_team_side=att_team[2],
                    subject_team_score=att_team[3],
                    object_team_id=def_team[0],
                    object_team_name=def_team[1],
                    object_team_side=def_team[2],
                    object_team_score=def_team[3],
                )
                _append_relation_if_new(
                    relation_records,
                    seen_keys,
                    saishi_id=row["saishi_id"],
                    evidence_event_id=int(row["id"]),
                    live_sid=int(row["live_sid"]),
                    source=source,
                    relation_type="defends",
                    relation_side="defense",
                    subject_player_name=defender,
                    object_player_name=attacker,
                    action_text="协防干扰",
                    result_text=None,
                    score_points=None,
                    evidence_text=evidence_text,
                    segmented_text=segmented_text,
                    extractor_name="rule_fallback",
                    confidence=config.confidence("CONFIDENCE_DEFENDS_CONTEST"),
                    event_context=event_context,
                    subject_team_id=def_team[0],
                    subject_team_name=def_team[1],
                    subject_team_side=def_team[2],
                    subject_team_score=def_team[3],
                    object_team_id=att_team[0],
                    object_team_name=att_team[1],
                    object_team_side=att_team[2],
                    object_team_score=att_team[3],
                )
                context = _FallbackContext(attacker=attacker, defender=defender)
                continue

        if score_points is not None and score_points > 0:
            scorer = primary_player or context.receiver or context.attacker
            if scorer and context.passer and context.passer != scorer:
                pass_team = _get_subject_team(context.passer)
                scorer_team = _get_object_team(scorer)
                _append_relation_if_new(
                    relation_records,
                    seen_keys,
                    saishi_id=row["saishi_id"],
                    evidence_event_id=int(row["id"]),
                    live_sid=int(row["live_sid"]),
                    source=source,
                    relation_type="assist_to",
                    relation_side="offense",
                    subject_player_name=context.passer,
                    object_player_name=scorer,
                    action_text="助攻",
                    result_text="得分",
                    score_points=score_points,
                    evidence_text=evidence_text,
                    segmented_text=segmented_text,
                    extractor_name="rule_fallback",
                    confidence=config.confidence("CONFIDENCE_ASSIST"),
                    event_context=event_context,
                    subject_team_id=pass_team[0],
                    subject_team_name=pass_team[1],
                    subject_team_side=pass_team[2],
                    subject_team_score=pass_team[3],
                    object_team_id=scorer_team[0],
                    object_team_name=scorer_team[1],
                    object_team_side=scorer_team[2],
                    object_team_score=scorer_team[3],
                )
            if scorer and context.defender and context.defender != scorer:
                scorer_team = _get_subject_team(scorer)
                def_team = _get_object_team(context.defender)
                _append_relation_if_new(
                    relation_records,
                    seen_keys,
                    saishi_id=row["saishi_id"],
                    evidence_event_id=int(row["id"]),
                    live_sid=int(row["live_sid"]),
                    source=source,
                    relation_type="scores_over",
                    relation_side="offense",
                    subject_player_name=scorer,
                    object_player_name=context.defender,
                    action_text="得分",
                    result_text="命中",
                    score_points=score_points,
                    evidence_text=evidence_text,
                    segmented_text=segmented_text,
                    extractor_name="rule_fallback",
                    confidence=config.confidence("CONFIDENCE_SCORE_OVER"),
                    event_context=event_context,
                    subject_team_id=scorer_team[0],
                    subject_team_name=scorer_team[1],
                    subject_team_side=scorer_team[2],
                    subject_team_score=scorer_team[3],
                    object_team_id=def_team[0],
                    object_team_name=def_team[1],
                    object_team_side=def_team[2],
                    object_team_score=def_team[3],
                )
            if scorer and not context.defender and len(player_mentions) >= 2:
                defender = player_mentions[-1]
                if defender != scorer:
                    scorer_team = _get_subject_team(scorer)
                    def_team = _get_object_team(defender)
                    _append_relation_if_new(
                        relation_records,
                        seen_keys,
                        saishi_id=row["saishi_id"],
                        evidence_event_id=int(row["id"]),
                        live_sid=int(row["live_sid"]),
                        source=source,
                        relation_type="scores_over",
                        relation_side="offense",
                        subject_player_name=scorer,
                        object_player_name=defender,
                        action_text="得分",
                        result_text="命中",
                        score_points=score_points,
                        evidence_text=evidence_text,
                        segmented_text=segmented_text,
                        extractor_name="rule_fallback",
                        confidence=config.confidence("CONFIDENCE_SCORE_OVER_IMPLICIT"),
                        event_context=event_context,
                        subject_team_id=scorer_team[0],
                        subject_team_name=scorer_team[1],
                        subject_team_side=scorer_team[2],
                        subject_team_score=scorer_team[3],
                        object_team_id=def_team[0],
                        object_team_name=def_team[1],
                        object_team_side=def_team[2],
                        object_team_score=def_team[3],
                    )
            context = _FallbackContext(attacker=scorer, defender=context.defender)
            continue

        if any(keyword in canonical_live_text for keyword in config.keywords("rebound")) and primary_player and context.attacker and primary_player != context.attacker:
            possession_tracker = possession_tracker.detect_possession_change(None, is_rebound=True)

            rebr_team = _get_subject_team(primary_player)
            att_team = _get_object_team(context.attacker)
            _append_relation_if_new(
                relation_records,
                seen_keys,
                saishi_id=row["saishi_id"],
                evidence_event_id=int(row["id"]),
                live_sid=int(row["live_sid"]),
                source=source,
                relation_type="rebounds_over",
                relation_side="defense",
                subject_player_name=primary_player,
                object_player_name=context.attacker,
                action_text="篮板",
                result_text=None,
                score_points=None,
                evidence_text=evidence_text,
                segmented_text=segmented_text,
                extractor_name="rule_fallback",
                confidence=config.confidence("CONFIDENCE_REBOUND"),
                event_context=event_context,
                subject_team_id=rebr_team[0],
                subject_team_name=rebr_team[1],
                subject_team_side=rebr_team[2],
                subject_team_score=rebr_team[3],
                object_team_id=att_team[0],
                object_team_name=att_team[1],
                object_team_side=att_team[2],
                object_team_score=att_team[3],
            )
            context = _FallbackContext(attacker=primary_player)
            continue

        if primary_player:
            context = _FallbackContext(
                passer=context.passer,
                receiver=context.receiver,
                attacker=primary_player,
                defender=context.defender,
            )

    return relation_records


# ---------------------------------------------------------------------------
# Backward-compatible re-exports from extracted modules
# ---------------------------------------------------------------------------

from app.modules.semantics.orchestrator import (  # noqa: E402
    extract_postgame_player_relations,
    upsert_player_relations,
)

__all__ = [
    "SiameseUIEExtractor",
    "extract_postgame_player_relations",
    "build_relation_records_from_uie_result",
    "build_relation_records_with_rule_fallback",
    "upsert_player_relations",
    "normalize_segmented_text_for_uie",
]