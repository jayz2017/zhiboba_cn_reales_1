from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from decimal import Decimal
from tempfile import TemporaryDirectory
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.modules.nba_live_text.zhiboba_livetext import (
    ensure_live_text_tables,
    load_player_segmentation_config,
    normalize_player_name,
)

_DDL_CREATE_PLAYER_RELATION_TABLE = """
CREATE TABLE IF NOT EXISTS nba_zhiboba_player_relation (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  saishi_id VARCHAR(32) NOT NULL,
  evidence_event_id BIGINT UNSIGNED NOT NULL,
  live_sid BIGINT UNSIGNED NOT NULL,
  relation_type VARCHAR(64) NOT NULL,
  relation_side VARCHAR(16) NOT NULL,
  subject_player_name VARCHAR(128) NOT NULL,
  subject_team_id VARCHAR(32) NULL,
  subject_team_name VARCHAR(64) NULL,
  subject_team_side VARCHAR(16) NULL,
  subject_team_score INT NULL,
  object_player_name VARCHAR(128) NOT NULL,
  object_team_id VARCHAR(32) NULL,
  object_team_name VARCHAR(64) NULL,
  object_team_side VARCHAR(16) NULL,
  object_team_score INT NULL,
  offense_team_id VARCHAR(32) NULL,
  offense_team_name VARCHAR(64) NULL,
  offense_team_side VARCHAR(16) NULL,
  offense_team_score INT NULL,
  offense_team_points INT NULL,
  possession_number INT NULL,
  home_score INT NULL,
  visit_score INT NULL,
  action_text VARCHAR(128) NULL,
  result_text VARCHAR(128) NULL,
  score_points INT NULL,
  evidence_text LONGTEXT NOT NULL,
  segmented_text LONGTEXT NULL,
  extractor_name VARCHAR(64) NOT NULL DEFAULT 'siamese_uie',
  confidence DECIMAL(5,4) NOT NULL DEFAULT 0.5000,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uk_relation_unique (saishi_id, evidence_event_id, relation_type, subject_player_name, object_player_name),
  KEY idx_relation_game (saishi_id),
  KEY idx_relation_live_sid (live_sid),
  KEY idx_relation_subject (subject_player_name),
  KEY idx_relation_object (object_player_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
""".strip()

_ALTER_PLAYER_RELATION_COLUMNS: dict[str, str] = {
    "subject_team_id": "ALTER TABLE nba_zhiboba_player_relation ADD COLUMN subject_team_id VARCHAR(32) NULL AFTER subject_player_name",
    "subject_team_name": "ALTER TABLE nba_zhiboba_player_relation ADD COLUMN subject_team_name VARCHAR(64) NULL AFTER subject_team_id",
    "subject_team_side": "ALTER TABLE nba_zhiboba_player_relation ADD COLUMN subject_team_side VARCHAR(16) NULL AFTER subject_team_name",
    "subject_team_score": "ALTER TABLE nba_zhiboba_player_relation ADD COLUMN subject_team_score INT NULL AFTER subject_team_side",
    "object_team_id": "ALTER TABLE nba_zhiboba_player_relation ADD COLUMN object_team_id VARCHAR(32) NULL AFTER object_player_name",
    "object_team_name": "ALTER TABLE nba_zhiboba_player_relation ADD COLUMN object_team_name VARCHAR(64) NULL AFTER object_team_id",
    "object_team_side": "ALTER TABLE nba_zhiboba_player_relation ADD COLUMN object_team_side VARCHAR(16) NULL AFTER object_team_name",
    "object_team_score": "ALTER TABLE nba_zhiboba_player_relation ADD COLUMN object_team_score INT NULL AFTER object_team_side",
    "offense_team_id": "ALTER TABLE nba_zhiboba_player_relation ADD COLUMN offense_team_id VARCHAR(32) NULL AFTER object_team_score",
    "offense_team_name": "ALTER TABLE nba_zhiboba_player_relation ADD COLUMN offense_team_name VARCHAR(64) NULL AFTER offense_team_id",
    "offense_team_side": "ALTER TABLE nba_zhiboba_player_relation ADD COLUMN offense_team_side VARCHAR(16) NULL AFTER offense_team_name",
    "offense_team_score": "ALTER TABLE nba_zhiboba_player_relation ADD COLUMN offense_team_score INT NULL AFTER offense_team_side",
    "offense_team_points": "ALTER TABLE nba_zhiboba_player_relation ADD COLUMN offense_team_points INT NULL AFTER offense_team_score",
    "possession_number": "ALTER TABLE nba_zhiboba_player_relation ADD COLUMN possession_number INT NULL AFTER offense_team_points",
    "home_score": "ALTER TABLE nba_zhiboba_player_relation ADD COLUMN home_score INT NULL AFTER possession_number",
    "visit_score": "ALTER TABLE nba_zhiboba_player_relation ADD COLUMN visit_score INT NULL AFTER home_score",
}

_SQL_UPSERT_PLAYER_RELATION = """
INSERT INTO nba_zhiboba_player_relation
  (
    saishi_id,
    evidence_event_id,
    live_sid,
    relation_type,
    relation_side,
    subject_player_name,
    subject_team_id,
    subject_team_name,
    subject_team_side,
    subject_team_score,
    object_player_name,
    object_team_id,
    object_team_name,
    object_team_side,
    object_team_score,
    offense_team_id,
    offense_team_name,
    offense_team_side,
    offense_team_score,
    offense_team_points,
    possession_number,
    home_score,
    visit_score,
    action_text,
    result_text,
    score_points,
    evidence_text,
    segmented_text,
    extractor_name,
    confidence
  )
VALUES
  (
    :saishi_id,
    :evidence_event_id,
    :live_sid,
    :relation_type,
    :relation_side,
    :subject_player_name,
    :subject_team_id,
    :subject_team_name,
    :subject_team_side,
    :subject_team_score,
    :object_player_name,
    :object_team_id,
    :object_team_name,
    :object_team_side,
    :object_team_score,
    :offense_team_id,
    :offense_team_name,
    :offense_team_side,
    :offense_team_score,
    :offense_team_points,
    :possession_number,
    :home_score,
    :visit_score,
    :action_text,
    :result_text,
    :score_points,
    :evidence_text,
    :segmented_text,
    :extractor_name,
    :confidence
  )
ON DUPLICATE KEY UPDATE
  relation_side = VALUES(relation_side),
  subject_team_id = VALUES(subject_team_id),
  subject_team_name = VALUES(subject_team_name),
  subject_team_side = VALUES(subject_team_side),
  subject_team_score = VALUES(subject_team_score),
  object_team_id = VALUES(object_team_id),
  object_team_name = VALUES(object_team_name),
  object_team_side = VALUES(object_team_side),
  object_team_score = VALUES(object_team_score),
  offense_team_id = VALUES(offense_team_id),
  offense_team_name = VALUES(offense_team_name),
  offense_team_side = VALUES(offense_team_side),
  offense_team_score = VALUES(offense_team_score),
  offense_team_points = VALUES(offense_team_points),
  possession_number = VALUES(possession_number),
  home_score = VALUES(home_score),
  visit_score = VALUES(visit_score),
  action_text = VALUES(action_text),
  result_text = VALUES(result_text),
  score_points = VALUES(score_points),
  evidence_text = VALUES(evidence_text),
  segmented_text = VALUES(segmented_text),
  extractor_name = VALUES(extractor_name),
  confidence = VALUES(confidence),
  updated_at = CURRENT_TIMESTAMP
""".strip()

_DEFAULT_RELATION_SCHEMA: list[dict[str, list[str]]] = [
    {"进攻球员": ["防守球员", "协作球员", "进攻动作", "结果", "得分值"]},
    {"防守球员": ["进攻球员", "防守动作", "结果"]},
]

_BLOCK_KEYWORDS = ("盖帽", "封盖", "帽", "大帽")
_STEAL_KEYWORDS = ("抢断", "断下", "断球")
_FOUL_KEYWORDS = ("犯规",)
_TURNOVER_KEYWORDS = ("造成失误", "逼出失误", "逼失误")
_CONTEST_KEYWORDS = ("干扰", "封到", "扑防")
_SCORE_KEYWORDS = ("命中", "打进", "上进", "抛进", "投进", "罚进", "扣进", "绝杀", "补进")
_SCREEN_KEYWORDS = ("挡拆", "掩护")
_PASS_KEYWORDS = ("递给", "分", "回球", "给", "找", "击地")
_ATTACK_KEYWORDS = ("对", "对位", "打", "面对", "单打")
_REBOUND_KEYWORDS = ("篮板", "前场板", "后场板")


@dataclass(frozen=True)
class PlayerRelationRecord:
    saishi_id: str
    evidence_event_id: int
    live_sid: int
    relation_type: str
    relation_side: str
    subject_player_name: str
    subject_team_id: str | None
    subject_team_name: str | None
    subject_team_side: str | None
    subject_team_score: int | None
    object_player_name: str
    object_team_id: str | None
    object_team_name: str | None
    object_team_side: str | None
    object_team_score: int | None
    offense_team_id: str | None
    offense_team_name: str | None
    offense_team_side: str | None
    offense_team_score: int | None
    offense_team_points: int | None
    possession_number: int | None
    home_score: int | None
    visit_score: int | None
    action_text: str | None
    result_text: str | None
    score_points: int | None
    evidence_text: str
    segmented_text: str | None
    extractor_name: str
    confidence: float


@dataclass(frozen=True)
class EventRelationContext:
    offense_team_id: str | None = None
    offense_team_name: str | None = None
    offense_team_side: str | None = None
    offense_team_score: int | None = None
    offense_team_points: int | None = None
    possession_number: int | None = None
    home_score: int | None = None
    visit_score: int | None = None


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


@dataclass(frozen=True)
class _FallbackContext:
    passer: str | None = None
    receiver: str | None = None
    attacker: str | None = None
    defender: str | None = None


def ensure_player_relation_table(db: Session) -> None:
    db.execute(text(_DDL_CREATE_PLAYER_RELATION_TABLE))
    db.commit()


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


def _detect_defensive_relation_type(actions: list[str]) -> str:
    combined = " ".join(actions)
    if any(keyword in combined for keyword in _BLOCK_KEYWORDS):
        return "blocks"
    if any(keyword in combined for keyword in _STEAL_KEYWORDS):
        return "steals_from"
    if any(keyword in combined for keyword in _FOUL_KEYWORDS):
        return "fouls_on"
    if any(keyword in combined for keyword in _TURNOVER_KEYWORDS):
        return "forces_turnover"
    if any(keyword in combined for keyword in _CONTEST_KEYWORDS):
        return "contests_shot"
    return "defends"


def _looks_like_scoring(actions: list[str], results: list[str], score_points: int | None) -> bool:
    if score_points is not None and score_points > 0:
        return True
    combined = " ".join(actions + results)
    return any(keyword in combined for keyword in _SCORE_KEYWORDS)


@dataclass(frozen=True)
class _PossessionTracker:
    possession_number: int = 1
    offense_team_side: str | None = None

    def detect_possession_change(self, new_offense_side: str | None, is_turnover: bool = False, is_steal: bool = False, is_rebound: bool = False) -> _PossessionTracker:
        if new_offense_side and self.offense_team_side and new_offense_side != self.offense_team_side:
            return _PossessionTracker(
                possession_number=self.possession_number + 1,
                offense_team_side=new_offense_side,
            )
        if is_turnover or is_steal or is_rebound:
            if self.offense_team_side:
                opposite_side = "visit" if self.offense_team_side == "home" else "home"
                return _PossessionTracker(
                    possession_number=self.possession_number + 1,
                    offense_team_side=opposite_side,
                )
        if new_offense_side and not self.offense_team_side:
            return _PossessionTracker(
                possession_number=self.possession_number,
                offense_team_side=new_offense_side,
            )
        return _PossessionTracker(
            possession_number=self.possession_number,
            offense_team_side=new_offense_side or self.offense_team_side,
        )


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


def _get_player_team_info(
    player_name: str,
    segmentation_config: PlayerSegmentationConfig,
) -> tuple[str | None, str | None, str | None, int | None]:
    if not player_name or not segmentation_config.player_to_team_id:
        return None, None, None, None

    team_id = segmentation_config.player_to_team_id.get(player_name)
    team_name = segmentation_config.player_to_team_name.get(player_name)
    team_side = segmentation_config.player_to_team_side.get(player_name)

    team_score = None
    if team_side == "home":
        pass
    elif team_side == "visit":
        pass

    return team_id, team_name, team_side, team_score


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


def _canonical_text(value: str | None) -> str:
    return (value or "").replace("\\", "").replace(" ", "").strip()


def _extract_player_mentions_from_segmented_text(
    text_value: str,
    alias_to_full_name: dict[str, str],
) -> list[str]:
    content = _canonical_text(text_value)
    if not content:
        return []

    matches: list[tuple[int, int, str]] = []
    candidates = sorted(set(alias_to_full_name.values()) | set(alias_to_full_name.keys()), key=len, reverse=True)
    for candidate in candidates:
        normalized_candidate = _canonical_text(candidate)
        if not normalized_candidate:
            continue
        start_index = 0
        while True:
            found_at = content.find(normalized_candidate, start_index)
            if found_at < 0:
                break
            canonical_name = alias_to_full_name.get(candidate, candidate)
            matches.append((found_at, len(normalized_candidate), canonical_name))
            start_index = found_at + len(normalized_candidate)

    matches.sort(key=lambda item: (item[0], -item[1]))
    deduped: list[str] = []
    occupied_ranges: list[tuple[int, int]] = []
    for start, length, player_name in matches:
        end = start + length
        if any(not (end <= occ_start or start >= occ_end) for occ_start, occ_end in occupied_ranges):
            continue
        occupied_ranges.append((start, end))
        if player_name not in deduped:
            deduped.append(player_name)
    return deduped


def _row_score_points(row: dict[str, Any]) -> int | None:
    score_points = row.get("score_points")
    return int(score_points) if score_points is not None else None


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
) -> list[PlayerRelationRecord]:
    relation_records: list[PlayerRelationRecord] = []
    seen_keys: set[tuple[str, str, str, int]] = set()
    context = _FallbackContext()
    possession_tracker = _PossessionTracker()

    for row in rows:
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

        passer = player_mentions[0] if player_mentions else context.passer
        receiver = player_mentions[1] if len(player_mentions) > 1 else None
        primary_player = player_mentions[0] if player_mentions else normalized_current

        def _get_subject_team(player):
            return _get_player_team_info(player or "", segmentation_config)

        def _get_object_team(player):
            return _get_player_team_info(player or "", segmentation_config)

        if any(keyword in canonical_live_text for keyword in _PASS_KEYWORDS):
            is_steal_event = any(keyword in canonical_live_text for keyword in _STEAL_KEYWORDS)
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
                    confidence=0.68,
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
                    confidence=0.62,
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
            any(keyword in canonical_live_text for keyword in _ATTACK_KEYWORDS) and len(player_mentions) >= 2
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
                    confidence=0.72,
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

        if any(keyword in canonical_live_text for keyword in _STEAL_KEYWORDS):
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
                    confidence=0.85,
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

        if any(keyword in canonical_live_text for keyword in _BLOCK_KEYWORDS):
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
                    confidence=0.88,
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

        if any(keyword in canonical_live_text for keyword in ("协防", "补防", "扑防", "干扰")):
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
                    confidence=0.66,
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
                    confidence=0.7,
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
                    confidence=0.74,
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
                    confidence=0.79,
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
                        confidence=0.68,
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

        if any(keyword in canonical_live_text for keyword in _REBOUND_KEYWORDS) and primary_player and context.attacker and primary_player != context.attacker:
            possession_tracker = possession_tracker.detect_possession_change(None, is_rebound=True)

            rebr_team = _get_subject_team(primary_player)
            att_team = _get_object_team(context.attacker)
            _append_relation_if_new(
                relation_records,
                seen_keys,
                saishi_id=row["saishi_id"],
                evidence_event_id=int(row["id"]),
                live_sid=int(row["live_sid"]),
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
                confidence=0.61,
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
) -> list[PlayerRelationRecord]:
    if not isinstance(uie_result, dict):
        return []

    relation_records: list[PlayerRelationRecord] = []
    seen_keys: set[tuple[str, str, str]] = set()

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
        scored = _looks_like_scoring(offense_actions, result_texts, score_points)

        off_team_info = _get_player_team_info(normalized_offense, segmentation_config)

        for helper in helpers:
            key = (helper, "assist_to", normalized_offense)
            if key not in seen_keys:
                seen_keys.add(key)
                helper_team_info = _get_player_team_info(helper, segmentation_config)
                _append_relation(
                    relation_records,
                    saishi_id=saishi_id,
                    evidence_event_id=evidence_event_id,
                    live_sid=live_sid,
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
            if any(keyword in " ".join(offense_actions) for keyword in _SCREEN_KEYWORDS):
                key = (helper, "screen_for", normalized_offense)
                if key not in seen_keys:
                    seen_keys.add(key)
                    helper_team_info = _get_player_team_info(helper, segmentation_config)
                    _append_relation(
                        relation_records,
                        saishi_id=saishi_id,
                        evidence_event_id=evidence_event_id,
                        live_sid=live_sid,
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
            def_team_info = _get_player_team_info(defender, segmentation_config)
            _append_relation(
                relation_records,
                saishi_id=saishi_id,
                evidence_event_id=evidence_event_id,
                live_sid=live_sid,
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
        relation_type = _detect_defensive_relation_type(defense_actions)
        primary_action = defense_actions[0] if defense_actions else None
        primary_result = result_texts[0] if result_texts else None

        def_team_info = _get_player_team_info(normalized_defender, segmentation_config)

        for offense_player in offense_players:
            key = (normalized_defender, relation_type, offense_player)
            if key in seen_keys:
                continue
            seen_keys.add(key)
            off_team_info = _get_player_team_info(offense_player, segmentation_config)
            _append_relation(
                relation_records,
                saishi_id=saishi_id,
                evidence_event_id=evidence_event_id,
                live_sid=live_sid,
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
        cur_team_info = _get_player_team_info(current_name, segmentation_config)
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
            def_team_info = _get_player_team_info(normalized_defender, segmentation_config)
            _append_relation(
                relation_records,
                saishi_id=saishi_id,
                evidence_event_id=evidence_event_id,
                live_sid=live_sid,
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


def upsert_player_relations(db: Session, relations: list[PlayerRelationRecord]) -> int:
    if not relations:
        return 0

    affected = 0
    for relation in relations:
        db.execute(
            text(_SQL_UPSERT_PLAYER_RELATION),
            {
                "saishi_id": relation.saishi_id,
                "evidence_event_id": relation.evidence_event_id,
                "live_sid": relation.live_sid,
                "relation_type": relation.relation_type,
                "relation_side": relation.relation_side,
                "subject_player_name": relation.subject_player_name,
                "subject_team_id": relation.subject_team_id,
                "subject_team_name": relation.subject_team_name,
                "subject_team_side": relation.subject_team_side,
                "subject_team_score": relation.subject_team_score,
                "object_player_name": relation.object_player_name,
                "object_team_id": relation.object_team_id,
                "object_team_name": relation.object_team_name,
                "object_team_side": relation.object_team_side,
                "object_team_score": relation.object_team_score,
                "offense_team_id": relation.offense_team_id,
                "offense_team_name": relation.offense_team_name,
                "offense_team_side": relation.offense_team_side,
                "offense_team_score": relation.offense_team_score,
                "offense_team_points": relation.offense_team_points,
                "possession_number": relation.possession_number,
                "home_score": relation.home_score,
                "visit_score": relation.visit_score,
                "action_text": relation.action_text,
                "result_text": relation.result_text,
                "score_points": relation.score_points,
                "evidence_text": relation.evidence_text,
                "segmented_text": relation.segmented_text,
                "extractor_name": relation.extractor_name,
                "confidence": Decimal(f"{relation.confidence:.4f}"),
            },
        )
        affected += 1
    db.commit()
    return affected


def extract_postgame_player_relations(
    db: Session,
    *,
    saishi_id: str,
    max_rows: int = 5000,
    sample_limit: int = 20,
) -> dict[str, Any]:
    ensure_live_text_tables(db=db)
    ensure_player_relation_table(db=db)
    segmentation_config = load_player_segmentation_config(db=db, saishi_id=saishi_id)
    rows = db.execute(
        text(
            """
            SELECT
              id,
              saishi_id,
              live_sid,
              live_text,
              segmented_text,
              current_player_name,
              score_points,
              home_score,
              visit_score,
              score_team_side
            FROM nba_zhiboba_live_text_event
            WHERE saishi_id = :saishi_id
              AND segmented_text IS NOT NULL
              AND TRIM(segmented_text) <> ''
            ORDER BY live_sid ASC
            LIMIT :limit_rows
            """
        ),
        {"saishi_id": saishi_id, "limit_rows": max(1, int(max_rows))},
    ).mappings().all()
    if not rows:
        return {
            "processed": False,
            "saishi_id": saishi_id,
            "message": "未找到已完成分词的直播文本记录",
            "events": 0,
            "relations": 0,
            "backend": "empty",
            "samples": [],
        }

    extractor = SiameseUIEExtractor()
    model_inputs = [normalize_segmented_text_for_uie(row["segmented_text"], row["live_text"]) for row in rows]
    raw_results = extractor.extract_batch(model_inputs)

    relation_records: list[PlayerRelationRecord] = []
    samples: list[dict[str, Any]] = []
    possession_tracker = _PossessionTracker()

    for row, raw_result in zip(rows, raw_results, strict=False):
        current_player_name = row["current_player_name"] if isinstance(row["current_player_name"], str) else None

        event_context, possession_tracker = _build_event_context_from_row(
            row=dict(row),
            segmentation_config=segmentation_config,
            possession_tracker=possession_tracker,
        )

        built_relations = build_relation_records_from_uie_result(
            saishi_id=row["saishi_id"],
            evidence_event_id=int(row["id"]),
            live_sid=int(row["live_sid"]),
            live_text=row["live_text"],
            segmented_text=row["segmented_text"],
            current_player_name=current_player_name,
            score_points=int(row["score_points"]) if row["score_points"] is not None else None,
            uie_result=raw_result,
            segmentation_config=segmentation_config,
            event_context=event_context,
        )
        relation_records.extend(built_relations)
        if built_relations and len(samples) < max(1, int(sample_limit)):
            for relation in built_relations:
                if len(samples) >= max(1, int(sample_limit)):
                    break
                samples.append(
                    {
                        "live_sid": relation.live_sid,
                        "relation_type": relation.relation_type,
                        "relation_side": relation.relation_side,
                        "subject_player_name": relation.subject_player_name,
                        "subject_team_id": relation.subject_team_id,
                        "subject_team_name": relation.subject_team_name,
                        "subject_team_side": relation.subject_team_side,
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
                        "evidence_text": relation.evidence_text,
                        "segmented_text": relation.segmented_text or "",
                        "confidence": relation.confidence,
                    }
                )

    if not relation_records and extractor.last_backend == "unavailable":
        possession_tracker_fallback = _PossessionTracker()
        relation_records = build_relation_records_with_rule_fallback(
            rows=[dict(row) for row in rows],
            segmentation_config=segmentation_config,
        )
        for relation in relation_records[: max(1, int(sample_limit))]:
            samples.append(
                {
                    "live_sid": relation.live_sid,
                    "relation_type": relation.relation_type,
                    "relation_side": relation.relation_side,
                    "subject_player_name": relation.subject_player_name,
                    "subject_team_id": relation.subject_team_id,
                    "subject_team_name": relation.subject_team_name,
                    "subject_team_side": relation.subject_team_side,
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
                    "evidence_text": relation.evidence_text,
                    "segmented_text": relation.segmented_text or "",
                    "confidence": relation.confidence,
                }
            )
        if relation_records:
            extractor.last_backend = "rule_fallback"

    inserted = upsert_player_relations(db=db, relations=relation_records)
    return {
        "processed": True,
        "saishi_id": saishi_id,
        "events": len(rows),
        "relations": inserted,
        "backend": extractor.last_backend,
        "model_name": settings.SIAMESE_UIE_MODEL_NAME,
        "samples": samples,
    }
