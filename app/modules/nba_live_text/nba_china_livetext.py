from __future__ import annotations

import re
import time
from dataclasses import replace
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.http_resources import NBA_CHINA_PBP_DETAILS_URL, build_nba_china_pbp_headers
from app.modules.nba_live_text.nlp.tokenizer import Tokenizer
from app.modules.nba_live_text.zhiboba_livetext import (
    LIVE_TEXT_SOURCE_NBA_CHINA,
    PlayerSegmentationConfig,
    ZhibobaLiveTextEventRecord,
    build_segmented_text,
    clean_live_text_for_tokenization,
    enrich_records_with_game_state,
    ensure_live_text_tables,
    load_live_text_filter_rules,
    load_player_segmentation_config,
    normalize_player_name,
    normalize_player_tokens,
    split_filter_rules,
    upsert_live_text_events,
)
from app.modules.semantics.extractors.rule_extractor import RuleBasedExtractor
from app.modules.semantics.models import EventRelationContext, PlayerRelationRecord
from app.modules.semantics.repository import PlayerRelationRepository
from app.modules.semantics.rule_config import load_relation_rule_config
from app.modules.semantics.schema import ensure_player_relation_table, ensure_relation_rule_config_tables
from app.utils.db_helpers import to_int
from app.utils.http.client import HttpClient


NBA_CHINA_DEFAULT_APP_KEY = "tiKB2tNdncnZFPOi"
NBA_CHINA_DEFAULT_APP_VERSION = "1.1.0"
NBA_CHINA_DEFAULT_CHANNEL = "NBA"
NBA_CHINA_DEFAULT_DEVICE_ID = "8d3361df7e6300eb3a7381d2470f4c50"
NBA_CHINA_DEFAULT_INSTALL_ID = "3816250247"
NBA_CHINA_DEFAULT_SIGN2 = "ACF992E80EB6606C4CAEBDE8D211D443463F7FAE176A0429ED98925A02CD8516"

NBA_CHINA_LINE_SKIP_KEYWORDS = (
    "本节比赛开始",
    "本节比赛结束",
    "暂停",
    "换下",
    "换上",
    "即时录像回放",
    "中止比赛",
)

_LEADING_SCORE_PATTERN = re.compile(r"^\[[^\]]+]\s*")
_PRIMARY_PLAYER_PATTERN = re.compile(r"^([\u4e00-\u9fffA-Za-z.\-·路]+)(?:\s|：|:)")
_RELATED_PLAYER_PATTERNS = (
    re.compile(r"助攻[:：]([\u4e00-\u9fffA-Za-z.\-·路]+)"),
    re.compile(r"盖帽[:：]([\u4e00-\u9fffA-Za-z.\-·路]+)"),
    re.compile(r"抢断[:：]([\u4e00-\u9fffA-Za-z.\-·路]+)"),
)
_ASSIST_PLAYER_PATTERN = re.compile(r"助攻[:：]\s*([\u4e00-\u9fffA-Za-z.\-·路]+)")
_BLOCK_PLAYER_PATTERN = re.compile(r"(?:封盖|盖帽)[:：]\s*([\u4e00-\u9fffA-Za-z.\-·路]+)")
_STEAL_PLAYER_PATTERN = re.compile(r"抢断[:：]\s*([\u4e00-\u9fffA-Za-z.\-·路]+)")


def build_nba_china_pbp_params(
    *,
    game_id: str,
    period: int,
    timestamp: int | None = None,
    device_id: str = NBA_CHINA_DEFAULT_DEVICE_ID,
    install_id: str = NBA_CHINA_DEFAULT_INSTALL_ID,
    sign2: str = NBA_CHINA_DEFAULT_SIGN2,
) -> dict[str, str]:
    return {
        "app_key": NBA_CHINA_DEFAULT_APP_KEY,
        "app_version": NBA_CHINA_DEFAULT_APP_VERSION,
        "channel": NBA_CHINA_DEFAULT_CHANNEL,
        "device_id": device_id,
        "gameId": game_id,
        "install_id": install_id,
        "network": "N/A",
        "os_type": "3",
        "os_version": "1.0.0",
        "period": str(int(period)),
        "sign": "sign_v2",
        "sign2": sign2,
        "t": str(int(timestamp if timestamp is not None else time.time())),
    }


def build_nba_china_live_sid(game_id: str, event_no: int, period: int) -> int:
    numeric_game_id = int(re.sub(r"\D", "", game_id).lstrip("0") or "0")
    normalized_event_no = int(event_no) if event_no > 0 else int(period) * 1000
    return numeric_game_id * 1_000_000 + normalized_event_no


def _find_play_items(payload: Any) -> list[dict[str, Any]]:
    try:
        plays = payload["data"]["data"]["g"]["pla"]
    except (KeyError, TypeError):
        return []
    if not isinstance(plays, list):
        return []
    return [item for item in plays if isinstance(item, dict)]


def _clean_description(description: Any) -> str | None:
    if not isinstance(description, str):
        return None
    cleaned = description.strip()
    return cleaned or None


def _is_action_description(description: str, team_id: int | None) -> bool:
    if team_id is None or team_id == 0:
        return False
    return not any(keyword in description for keyword in NBA_CHINA_LINE_SKIP_KEYWORDS)


def _extract_primary_player_name(description: str) -> str | None:
    without_score = _LEADING_SCORE_PATTERN.sub("", description).strip()
    match = _PRIMARY_PLAYER_PATTERN.search(without_score)
    if not match:
        return None
    player_name = match.group(1).strip()
    if player_name in {"球队", "马刺", "雷霆", "湖人", "勇士", "凯尔特人", "尼克斯"}:
        return None
    return player_name or None


def _extract_related_player_names(description: str) -> list[str]:
    names: list[str] = []
    for pattern in _RELATED_PLAYER_PATTERNS:
        for match in pattern.finditer(description):
            player_name = match.group(1).strip()
            if player_name and player_name not in names:
                names.append(player_name)
    return names


def _normalize_player_id(value: Any) -> str | None:
    player_id = str(value).strip() if value is not None else ""
    if not player_id or player_id == "0":
        return None
    return player_id


def parse_nba_china_pbp_payload(
    payload: Any,
    *,
    game_id: str,
    player_names_by_id: dict[str, str] | None = None,
) -> list[ZhibobaLiveTextEventRecord]:
    player_names_by_id = player_names_by_id or {}
    records: list[ZhibobaLiveTextEventRecord] = []
    for item in _find_play_items(payload):
        description = _clean_description(item.get("de"))
        if not description:
            continue

        period = to_int(item.get("period"), default=None)
        event_no = to_int(item.get("evt"), default=None)
        team_id = to_int(item.get("tid"), default=None)
        if period is None or event_no is None or not _is_action_description(description, team_id):
            continue

        player_id = _normalize_player_id(item.get("pid"))
        current_player_name = player_names_by_id.get(player_id or "") or _extract_primary_player_name(description)

        records.append(
            ZhibobaLiveTextEventRecord(
                saishi_id=game_id,
                live_sid=build_nba_china_live_sid(game_id, event_no, period),
                live_pid=str(period),
                pid_text=str(item.get("periodName") or f"第{period}节"),
                live_text=description,
                segmented_text=None,
                home_score=to_int(item.get("hs"), default=None),
                visit_score=to_int(item.get("vs"), default=None),
                user_chn=current_player_name,
                score_points=to_int(item.get("pts"), default=None),
                source=LIVE_TEXT_SOURCE_NBA_CHINA,
            )
        )

    return sorted(records, key=lambda record: record.live_sid)


def fetch_nba_china_pbp_payload(
    http_client: HttpClient,
    *,
    game_id: str,
    period: int,
    sign2: str = NBA_CHINA_DEFAULT_SIGN2,
) -> Any:
    return http_client.get_json(
        NBA_CHINA_PBP_DETAILS_URL,
        params=build_nba_china_pbp_params(game_id=game_id, period=period, sign2=sign2),
        headers=build_nba_china_pbp_headers(),
    )


def _column_exists(db: Session, *, table_name: str, column_name: str) -> bool:
    row = db.execute(
        text(
            """
            SELECT 1
            FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE()
              AND TABLE_NAME = :table_name
              AND COLUMN_NAME = :column_name
            LIMIT 1
            """
        ),
        {"table_name": table_name, "column_name": column_name},
    ).fetchone()
    return row is not None


def load_nba_player_names_by_id(db: Session, *, game_id: str) -> dict[str, str]:
    if not _column_exists(db, table_name="nba_players_name_data", column_name="player_id"):
        return {}

    try:
        context_row = db.execute(
            text(
                """
                SELECT home_team_id, visit_team_id
                FROM nba_store_game_list
                WHERE game_id = :game_id
                LIMIT 1
                """
            ),
            {"game_id": game_id},
        ).fetchone()
    except Exception:
        context_row = None

    team_ids: list[str] = []
    if context_row is not None:
        for value in (getattr(context_row, "home_team_id", None), getattr(context_row, "visit_team_id", None)):
            if isinstance(value, str) and value.strip():
                team_ids.append(value.strip())

    where_sql = ""
    params: dict[str, Any] = {}
    if team_ids:
        where_sql = "WHERE team_id IN (:home_team_id, :visit_team_id)"
        params = {
            "home_team_id": team_ids[0],
            "visit_team_id": team_ids[1] if len(team_ids) > 1 else team_ids[0],
        }

    rows = db.execute(
        text(
            f"""
            SELECT player_id, nba_player_name, zhiboba_player_name
            FROM nba_players_name_data
            {where_sql}
            """
        ),
        params,
    ).fetchall()

    result: dict[str, str] = {}
    for row in rows:
        player_id = getattr(row, "player_id", None)
        player_name = getattr(row, "nba_player_name", None) or getattr(row, "zhiboba_player_name", None)
        if isinstance(player_id, str) and player_id.strip() and isinstance(player_name, str) and player_name.strip():
            result[player_id.strip()] = player_name.strip()
    return result


def _extend_player_segmentation_config(
    base_config: PlayerSegmentationConfig,
    records: list[ZhibobaLiveTextEventRecord],
) -> PlayerSegmentationConfig:
    words = set(base_config.words)
    alias_to_full_name = dict(base_config.alias_to_full_name)
    for record in records:
        candidates = []
        primary_player = _extract_primary_player_name(record.live_text)
        if primary_player:
            candidates.append(primary_player)
        if record.current_player_name:
            candidates.append(record.current_player_name)
        candidates.extend(_extract_related_player_names(record.live_text))
        for candidate in candidates:
            cleaned = candidate.strip()
            if not cleaned:
                continue
            words.add(cleaned)
            alias_to_full_name.setdefault(cleaned, cleaned)

    return replace(
        base_config,
        words=sorted(words),
        alias_to_full_name=alias_to_full_name,
    )


def _tokenize_nba_china_records(
    db: Session,
    records: list[ZhibobaLiveTextEventRecord],
    *,
    player_segmentation: PlayerSegmentationConfig,
) -> tuple[list[ZhibobaLiveTextEventRecord], list[dict[str, Any]]]:
    tokenizer = Tokenizer()
    tokenizer.add_words(player_segmentation.words)
    filter_rules = load_live_text_filter_rules(db=db)
    _, content_remove_rules = split_filter_rules(filter_rules)
    player_terms = set(player_segmentation.words) | set(player_segmentation.alias_to_full_name)
    content_remove_rules = [
        rule
        for rule in content_remove_rules
        if not (
            len(rule.filter_text) <= 1
            and any(rule.filter_text in player_term for player_term in player_terms)
        )
    ]

    texts_for_tokenization = [
        clean_live_text_for_tokenization(record.live_text, content_remove_rules)
        for record in records
    ]
    token_results = tokenizer.tokenize_batch(texts_for_tokenization)
    segmented_records: list[ZhibobaLiveTextEventRecord] = []
    segmented_examples: list[dict[str, Any]] = []

    for record, cleaned_text, token_result in zip(records, texts_for_tokenization, token_results, strict=False):
        normalized_tokens = normalize_player_tokens(
            token_result.tokens,
            player_segmentation.alias_to_full_name,
        )
        segmented_text = build_segmented_text(normalized_tokens)
        segmented_records.append(replace(record, segmented_text=segmented_text))
        if segmented_text and len(segmented_examples) < 10:
            segmented_examples.append(
                {
                    "live_sid": record.live_sid,
                    "period": record.live_pid,
                    "live_text": record.live_text,
                    "cleaned_text": cleaned_text,
                    "segmented_text": segmented_text,
                    "current_player_name": normalize_player_name(record.user_chn, player_segmentation.alias_to_full_name) or "",
                    "home_score": record.home_score,
                    "visit_score": record.visit_score,
                }
            )

    return enrich_records_with_game_state(
        db=db,
        records=segmented_records,
        alias_to_full_name=player_segmentation.alias_to_full_name,
    ), segmented_examples


def _normalize_nba_china_relation_player(
    player_name: str | None,
    alias_to_full_name: dict[str, str],
) -> str | None:
    return normalize_player_name(player_name, alias_to_full_name)


def _get_relation_player_team_info(
    player_name: str,
    segmentation_config: PlayerSegmentationConfig,
    home_score: int | None = None,
    visit_score: int | None = None,
) -> tuple[str | None, str | None, str | None, int | None]:
    if not player_name:
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


def _build_nba_china_event_context(
    row: dict[str, Any],
    segmentation_config: PlayerSegmentationConfig,
) -> EventRelationContext:
    home_score = to_int(row.get("home_score"), default=None)
    visit_score = to_int(row.get("visit_score"), default=None)
    score_points = to_int(row.get("score_points"), default=None)
    score_team_side = row.get("score_team_side")
    offense_side = score_team_side if isinstance(score_team_side, str) and score_team_side in {"home", "visit"} else None

    offense_team_id = None
    offense_team_name = None
    offense_team_score = None
    if segmentation_config.game_team_context:
        if offense_side == "home":
            offense_team_id = segmentation_config.game_team_context.home_team_id
            offense_team_name = segmentation_config.game_team_context.home_team_name
            offense_team_score = home_score
        elif offense_side == "visit":
            offense_team_id = segmentation_config.game_team_context.guest_team_id
            offense_team_name = segmentation_config.game_team_context.guest_team_name
            offense_team_score = visit_score

    return EventRelationContext(
        offense_team_id=offense_team_id,
        offense_team_name=offense_team_name,
        offense_team_side=offense_side,
        offense_team_score=offense_team_score,
        offense_team_points=score_points,
        home_score=home_score,
        visit_score=visit_score,
    )


def _infer_nba_china_score_points(row: dict[str, Any], live_text: str) -> int | None:
    score_points = to_int(row.get("score_points"), default=None)
    if score_points is not None:
        return score_points
    if "命中" not in live_text and "罚中" not in live_text:
        return None
    if "三分" in live_text:
        return 3
    if "罚球" in live_text or "罚中" in live_text:
        return 1
    return 2


def _append_nba_china_relation_if_new(
    relations: list[PlayerRelationRecord],
    seen_keys: set[tuple[str, str, str, int]],
    *,
    row: dict[str, Any],
    segmentation_config: PlayerSegmentationConfig,
    event_context: EventRelationContext,
    relation_type: str,
    relation_side: str,
    subject_player_name: str,
    object_player_name: str,
    action_text: str,
    result_text: str | None = None,
    score_points: int | None = None,
    confidence: float = 0.8,
) -> None:
    subject = subject_player_name.strip()
    obj = object_player_name.strip()
    if not subject or not obj or subject == obj:
        return

    live_sid = int(row["live_sid"])
    key = (subject, relation_type, obj, live_sid)
    if key in seen_keys:
        return
    seen_keys.add(key)

    subject_team = _get_relation_player_team_info(
        subject,
        segmentation_config,
        event_context.home_score,
        event_context.visit_score,
    )
    object_team = _get_relation_player_team_info(
        obj,
        segmentation_config,
        event_context.home_score,
        event_context.visit_score,
    )

    relations.append(
        PlayerRelationRecord(
            saishi_id=str(row["saishi_id"]),
            evidence_event_id=int(row["id"]),
            live_sid=live_sid,
            source=LIVE_TEXT_SOURCE_NBA_CHINA,
            relation_type=relation_type,
            relation_side=relation_side,
            subject_player_name=subject,
            subject_team_id=subject_team[0],
            subject_team_name=subject_team[1],
            subject_team_side=subject_team[2],
            subject_team_score=subject_team[3],
            object_player_name=obj,
            object_team_id=object_team[0],
            object_team_name=object_team[1],
            object_team_side=object_team[2],
            object_team_score=object_team[3],
            offense_team_id=event_context.offense_team_id,
            offense_team_name=event_context.offense_team_name,
            offense_team_side=event_context.offense_team_side,
            offense_team_score=event_context.offense_team_score,
            offense_team_points=event_context.offense_team_points,
            possession_number=event_context.possession_number,
            home_score=event_context.home_score,
            visit_score=event_context.visit_score,
            action_text=action_text,
            result_text=result_text,
            score_points=score_points,
            evidence_text=str(row.get("live_text") or ""),
            segmented_text=str(row.get("segmented_text") or "") or None,
            extractor_name="nba_china_rule",
            confidence=confidence,
        )
    )


def build_nba_china_structured_relations(
    rows: list[dict[str, Any]],
    segmentation_config: PlayerSegmentationConfig,
) -> list[PlayerRelationRecord]:
    relations: list[PlayerRelationRecord] = []
    seen_keys: set[tuple[str, str, str, int]] = set()

    for row in rows:
        live_text = str(row.get("live_text") or "")
        scorer = _normalize_nba_china_relation_player(
            row.get("current_player_name") if isinstance(row.get("current_player_name"), str) else None,
            segmentation_config.alias_to_full_name,
        )
        if scorer is None:
            scorer = _normalize_nba_china_relation_player(
                _extract_primary_player_name(live_text),
                segmentation_config.alias_to_full_name,
            )

        score_points = _infer_nba_china_score_points(row, live_text)

        event_context = _build_nba_china_event_context(row, segmentation_config)

        assist_match = _ASSIST_PLAYER_PATTERN.search(live_text)
        if scorer and assist_match and ("命中" in live_text or (score_points is not None and score_points > 0)):
            assister = _normalize_nba_china_relation_player(
                assist_match.group(1),
                segmentation_config.alias_to_full_name,
            )
            if assister:
                _append_nba_china_relation_if_new(
                    relations,
                    seen_keys,
                    row=row,
                    segmentation_config=segmentation_config,
                    event_context=event_context,
                    relation_type="assist_to",
                    relation_side="offense",
                    subject_player_name=assister,
                    object_player_name=scorer,
                    action_text="助攻",
                    result_text="命中",
                    score_points=score_points,
                    confidence=0.86,
                )

        block_match = _BLOCK_PLAYER_PATTERN.search(live_text)
        if scorer and block_match:
            blocker = _normalize_nba_china_relation_player(
                block_match.group(1),
                segmentation_config.alias_to_full_name,
            )
            if blocker:
                _append_nba_china_relation_if_new(
                    relations,
                    seen_keys,
                    row=row,
                    segmentation_config=segmentation_config,
                    event_context=event_context,
                    relation_type="blocks",
                    relation_side="defense",
                    subject_player_name=blocker,
                    object_player_name=scorer,
                    action_text="封盖",
                    confidence=0.9,
                )

        steal_match = _STEAL_PLAYER_PATTERN.search(live_text)
        if scorer and steal_match:
            stealer = _normalize_nba_china_relation_player(
                steal_match.group(1),
                segmentation_config.alias_to_full_name,
            )
            if stealer:
                _append_nba_china_relation_if_new(
                    relations,
                    seen_keys,
                    row=row,
                    segmentation_config=segmentation_config,
                    event_context=event_context,
                    relation_type="steals_from",
                    relation_side="defense",
                    subject_player_name=stealer,
                    object_player_name=scorer,
                    action_text="抢断",
                    confidence=0.88,
                )

    return relations


def sync_nba_china_live_text(
    db: Session,
    http_client: HttpClient,
    *,
    game_id: str,
    periods: list[int] | None = None,
    sign2: str = NBA_CHINA_DEFAULT_SIGN2,
    max_auto_period: int = 20,
) -> dict[str, Any]:
    ensure_live_text_tables(db=db)
    player_names_by_id = load_nba_player_names_by_id(db=db, game_id=game_id)
    all_records: list[ZhibobaLiveTextEventRecord] = []
    fetched_periods = 0
    attempted_periods: list[int] = []
    synced_periods: list[int] = []
    stop_period: int | None = None
    auto_mode = periods is None
    period_iterable = periods if periods is not None else range(1, max(1, int(max_auto_period)) + 1)
    stop_reason = "manual_periods_completed"

    for period in period_iterable:
        attempted_periods.append(period)
        payload = fetch_nba_china_pbp_payload(
            http_client=http_client,
            game_id=game_id,
            period=period,
            sign2=sign2,
        )
        raw_play_items = _find_play_items(payload)
        if auto_mode and not raw_play_items:
            stop_period = period
            stop_reason = "empty_pla"
            break

        period_records = parse_nba_china_pbp_payload(
            payload,
            game_id=game_id,
            player_names_by_id=player_names_by_id,
        )
        fetched_periods += 1
        synced_periods.append(period)
        all_records.extend(period_records)
    else:
        if auto_mode:
            stop_reason = "max_auto_period_reached"

    all_records = sorted({record.live_sid: record for record in all_records}.values(), key=lambda record: record.live_sid)
    base_segmentation = load_player_segmentation_config(db=db, saishi_id=game_id)
    player_segmentation = _extend_player_segmentation_config(base_segmentation, all_records)
    enriched_records, segmented_examples = _tokenize_nba_china_records(
        db=db,
        records=all_records,
        player_segmentation=player_segmentation,
    )
    upserted = upsert_live_text_events(db=db, records=enriched_records)

    return {
        "game_id": game_id,
        "periods": synced_periods,
        "attempted_periods": attempted_periods,
        "fetched_periods": fetched_periods,
        "stop_period": stop_period,
        "stop_reason": stop_reason,
        "events": len(enriched_records),
        "upserted": upserted,
        "segmented_examples": segmented_examples,
    }


def extract_nba_china_player_relations(
    db: Session,
    *,
    game_id: str,
    max_rows: int = 5000,
    sample_limit: int = 20,
) -> dict[str, Any]:
    ensure_live_text_tables(db=db)
    ensure_player_relation_table(db=db)
    ensure_relation_rule_config_tables(db=db)

    rows = (
        db.execute(
            text(
                """
                SELECT *
                FROM nba_zhiboba_live_text_event
                WHERE saishi_id = :game_id
                  AND source = :source
                  AND segmented_text IS NOT NULL
                ORDER BY live_sid ASC
                LIMIT :max_rows
                """
            ),
            {
                "game_id": game_id,
                "source": LIVE_TEXT_SOURCE_NBA_CHINA,
                "max_rows": max(1, int(max_rows)),
            },
        )
        .mappings()
        .all()
    )
    event_rows = [dict(row) for row in rows]
    if not event_rows:
        return {
            "processed": False,
            "game_id": game_id,
            "events": 0,
            "relations": 0,
            "samples": [],
        }

    base_segmentation = load_player_segmentation_config(db=db, saishi_id=game_id)
    pseudo_records = [
        ZhibobaLiveTextEventRecord(
            saishi_id=game_id,
            live_sid=int(row["live_sid"]),
            live_pid=None,
            pid_text=None,
            live_text=str(row["live_text"] or ""),
            segmented_text=str(row["segmented_text"] or ""),
            home_score=row.get("home_score"),
            visit_score=row.get("visit_score"),
            user_chn=row.get("current_player_name"),
            source=LIVE_TEXT_SOURCE_NBA_CHINA,
        )
        for row in event_rows
    ]
    segmentation_config = _extend_player_segmentation_config(base_segmentation, pseudo_records)
    rule_config = load_relation_rule_config(db=db)
    extractor = RuleBasedExtractor(rule_config=rule_config)
    structured_relations = build_nba_china_structured_relations(
        rows=event_rows,
        segmentation_config=segmentation_config,
    )
    fallback_relations = extractor.extract_from_rows(rows=event_rows, segmentation_config=segmentation_config)
    structured_live_sids = {relation.live_sid for relation in structured_relations}
    filtered_fallback_relations = [
        relation
        for relation in fallback_relations
        if relation.live_sid not in structured_live_sids
    ]
    relations: list[PlayerRelationRecord] = []
    relation_keys: set[tuple[str, str, str, int]] = set()
    for relation in [*structured_relations, *filtered_fallback_relations]:
        key = (
            relation.subject_player_name,
            relation.relation_type,
            relation.object_player_name,
            relation.live_sid,
        )
        if key in relation_keys:
            continue
        relation_keys.add(key)
        relations.append(relation)

    inserted = 0
    if relations:
        db.execute(
            text(
                """
                DELETE FROM nba_zhiboba_player_relation
                WHERE saishi_id = :game_id
                  AND source = :source
                  AND extractor_name IN ('nba_china_rule', 'rule_fallback')
                """
            ),
            {"game_id": game_id, "source": LIVE_TEXT_SOURCE_NBA_CHINA},
        )
        db.commit()
        inserted = PlayerRelationRepository(db).bulk_upsert(relations, batch_size=1)

    samples = []
    for relation in relations[: max(0, int(sample_limit))]:
        samples.append(relation.__dict__)

    return {
        "processed": True,
        "game_id": game_id,
        "events": len(event_rows),
        "relations": inserted,
        "backend": "nba_china_rule+rule_based",
        "samples": samples,
    }


def sync_and_extract_nba_china_live_text(
    db: Session,
    http_client: HttpClient,
    *,
    game_id: str,
    periods: list[int] | None = None,
    sign2: str = NBA_CHINA_DEFAULT_SIGN2,
    max_auto_period: int = 20,
    max_rows: int = 5000,
    sample_limit: int = 20,
) -> dict[str, Any]:
    sync_result = sync_nba_china_live_text(
        db=db,
        http_client=http_client,
        game_id=game_id,
        periods=periods,
        sign2=sign2,
        max_auto_period=max_auto_period,
    )
    relation_result = extract_nba_china_player_relations(
        db=db,
        game_id=game_id,
        max_rows=max_rows,
        sample_limit=sample_limit,
    )
    return {
        "game_id": game_id,
        "sync": sync_result,
        "relations": relation_result,
    }


def parse_periods(value: str | None) -> list[int] | None:
    if not value or not value.strip():
        return None
    periods: list[int] = []
    for item in value.split(","):
        stripped = item.strip()
        if not stripped:
            continue
        period = int(stripped)
        if period <= 0:
            raise ValueError("period must be positive")
        periods.append(period)
    return periods or None
