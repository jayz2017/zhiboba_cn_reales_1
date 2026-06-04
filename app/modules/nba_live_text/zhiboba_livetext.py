from __future__ import annotations

import logging
import re
from dataclasses import replace
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.modules.nba_live_text.nlp.tokenizer import Tokenizer
from app.core.http_resources import QIUMIBAO_LIVETEXT_BASE_URL, build_livetext_headers
from app.utils.db_helpers import to_int
from app.utils.http.client import HttpClient

from .livetext_schema import (
    CONTENT_REMOVE_RULE_TYPE,
    GameTeamContext,
    LINE_SKIP_RULE_TYPE,
    LIVE_TEXT_SOURCE_NBA_CHINA,
    LIVE_TEXT_SOURCE_ZHIBOBA,
    LiveTextFilterRule,
    MATCH_MODE_CONTAINS,
    MATCH_MODE_EXACT,
    MATCH_MODE_PREFIX,
    PlayerSegmentationConfig,
    TARGET_LIVE_TEXT,
    TARGET_PID_TEXT,
    ZhibobaLiveTextEventRecord,
    ensure_live_text_tables,
)
from .livetext_filter import (
    clean_live_text_for_tokenization,
    count_line_skipped_payload_items,
    count_pending_payload_items,
    filter_live_text_records,
    load_live_text_filter_rules,
    split_filter_rules,
)

logger = logging.getLogger(__name__)

"""
直播吧(zhiboba)直播文本处理模块。

提供直播文本事件的抓取、解析、分词、过滤、存储等核心功能。
"""
__all__ = [
    "ZhibobaLiveTextEventRecord",
    "LiveTextFilterRule",
    "GameTeamContext",
    "PlayerSegmentationConfig",
    "fetch_zhiboba_live_text_events",
    "sync_zhiboba_live_text",
    "ensure_live_text_tables",
    "load_player_segmentation_config",
    "load_player_dictionary",
    "upsert_live_text_events",
    "parse_livetext_payload",
    "filter_live_text_records",
    "clean_live_text_for_tokenization",
    "build_segmented_text",
    "normalize_player_tokens",
    "normalize_player_name",
    "enrich_records_with_game_state",
    "count_pending_payload_items",
    "count_line_skipped_payload_items",
    "load_live_text_filter_rules",
    "split_filter_rules",
    "LIVE_TEXT_SOURCE_ZHIBOBA",
    "LINE_SKIP_RULE_TYPE",
    "CONTENT_REMOVE_RULE_TYPE",
]


def build_livetext_url(saishi_id: str, cursor: int, *, page_size: int = 10) -> str:
    return f"{QIUMIBAO_LIVETEXT_BASE_URL}/{saishi_id}/0/page_{page_size}/{cursor}.json"


def _normalize_live_pid(value: Any) -> str | None:
    if isinstance(value, int):
        if value == -1 or value > 0:
            return str(value)
        return None

    if not isinstance(value, str):
        return None

    stripped = value.strip()
    if not stripped:
        return None
    if stripped == "-1":
        return stripped
    if stripped.isdigit() and int(stripped) > 0:
        return str(int(stripped))
    return None


def parse_livetext_payload(payload: Any) -> list[ZhibobaLiveTextEventRecord]:
    if not isinstance(payload, list):
        return []

    records: list[ZhibobaLiveTextEventRecord] = []
    for item in payload:
        if not isinstance(item, dict):
            continue

        live_text = item.get("live_text")
        saishi_id = item.get("saishi_id")
        live_sid = item.get("live_sid")

        if not isinstance(live_text, str) or not live_text.strip():
            continue
        if not isinstance(saishi_id, str) or not saishi_id.strip():
            continue

        live_sid_value: int | None = None
        if isinstance(live_sid, str) and live_sid.isdigit():
            live_sid_value = int(live_sid)
        elif isinstance(live_sid, int):
            live_sid_value = live_sid
        if live_sid_value is None:
            continue

        live_pid = item.get("live_pid")
        live_pid_value = _normalize_live_pid(live_pid)
        if live_pid_value is None:
            continue
        pid_text = item.get("pid_text")
        pid_text_value = pid_text.strip() if isinstance(pid_text, str) and pid_text.strip() else None

        home_score = to_int(item.get("home_score"))
        visit_score = to_int(item.get("visit_score"))
        user_chn = item.get("user_chn")
        user_chn_value = user_chn.strip() if isinstance(user_chn, str) and user_chn.strip() else None

        records.append(
            ZhibobaLiveTextEventRecord(
                saishi_id=saishi_id.strip(),
                live_sid=live_sid_value,
                live_pid=live_pid_value,
                pid_text=pid_text_value,
                live_text=live_text.strip(),
                segmented_text=None,
                home_score=home_score,
                visit_score=visit_score,
                user_chn=user_chn_value,
            )
        )

    return records


_SQL_UPSERT_EVENT = """
INSERT INTO nba_zhiboba_live_text_event
  (
    saishi_id,
    live_sid,
    source,
    live_pid,
    pid_text,
    live_text,
    segmented_text,
    visit_score,
    home_score,
    user_chn,
    current_player_name,
    home_score_change,
    visit_score_change,
    score_team_side,
    score_points,
    score_diff
  )
VALUES
  (
    :saishi_id,
    :live_sid,
    :source,
    :live_pid,
    :pid_text,
    :live_text,
    :segmented_text,
    :visit_score,
    :home_score,
    :user_chn,
    :current_player_name,
    :home_score_change,
    :visit_score_change,
    :score_team_side,
    :score_points,
    :score_diff
  )
ON DUPLICATE KEY UPDATE
  saishi_id = VALUES(saishi_id),
  source = VALUES(source),
  live_pid = VALUES(live_pid),
  pid_text = VALUES(pid_text),
  live_text = VALUES(live_text),
  segmented_text = VALUES(segmented_text),
  visit_score = VALUES(visit_score),
  home_score = VALUES(home_score),
  user_chn = VALUES(user_chn),
  current_player_name = VALUES(current_player_name),
  home_score_change = VALUES(home_score_change),
  visit_score_change = VALUES(visit_score_change),
  score_team_side = VALUES(score_team_side),
  score_points = VALUES(score_points),
  score_diff = VALUES(score_diff),
  updated_at = CURRENT_TIMESTAMP;
""".strip()


def upsert_live_text_events(db: Session, records: list[ZhibobaLiveTextEventRecord]) -> int:
    if not records:
        return 0

    params_list = [
        {
            "saishi_id": r.saishi_id,
            "live_sid": r.live_sid,
            "source": r.source,
            "live_pid": r.live_pid,
            "pid_text": r.pid_text,
            "live_text": r.live_text,
            "segmented_text": r.segmented_text,
            "visit_score": r.visit_score,
            "home_score": r.home_score,
            "user_chn": r.user_chn,
            "current_player_name": r.current_player_name,
            "home_score_change": r.home_score_change,
            "visit_score_change": r.visit_score_change,
            "score_team_side": r.score_team_side,
            "score_points": r.score_points,
            "score_diff": r.score_diff,
        }
        for r in records
    ]
    db.execute(text(_SQL_UPSERT_EVENT), params_list)
    db.commit()
    return len(params_list)


def _get_game_team_context_for_saishi(db: Session, saishi_id: str) -> GameTeamContext | None:
    try:
        row = db.execute(
            text(
                """
                SELECT
                  schedule.home_id,
                  schedule.guest_id,
                  home_team.team_name AS home_team_name,
                  guest_team.team_name AS guest_team_name
                FROM nba_zhiboba_yj_gamelist AS schedule
                LEFT JOIN nba_teams_name_data AS home_team
                  ON schedule.home_id = home_team.zhiboba_team_id
                LEFT JOIN nba_teams_name_data AS guest_team
                  ON schedule.guest_id = guest_team.zhiboba_team_id
                WHERE saishi_id = :saishi_id
                LIMIT 1
                """
            ),
            {"saishi_id": saishi_id},
        ).fetchone()
    except Exception:
        logger.warning("get_game_team_context_failed", extra={"saishi_id": saishi_id}, exc_info=True)
        row = None

    if not row:
        try:
            row = db.execute(
                text(
                    """
                    SELECT
                      home_team_id AS home_id,
                      visit_team_id AS guest_id,
                      home_name AS home_team_name,
                      visit_name AS guest_team_name
                    FROM nba_store_game_list
                    WHERE game_id = :saishi_id
                    LIMIT 1
                    """
                ),
                {"saishi_id": saishi_id},
            ).fetchone()
        except Exception:
            logger.warning("get_game_team_context_fallback_failed", extra={"saishi_id": saishi_id}, exc_info=True)
            return None

    if not row:
        return None

    home_id = getattr(row, "home_id", None)
    guest_id = getattr(row, "guest_id", None)
    if not isinstance(home_id, str) or not home_id.strip():
        return None
    if not isinstance(guest_id, str) or not guest_id.strip():
        return None
    home_team_name = getattr(row, "home_team_name", None)
    guest_team_name = getattr(row, "guest_team_name", None)
    return GameTeamContext(
        home_team_id=home_id.strip(),
        guest_team_id=guest_id.strip(),
        home_team_name=home_team_name.strip() if isinstance(home_team_name, str) and home_team_name.strip() else None,
        guest_team_name=guest_team_name.strip() if isinstance(guest_team_name, str) and guest_team_name.strip() else None,
    )


def _get_team_ids_for_saishi(db: Session, saishi_id: str) -> tuple[str, str] | None:
    context = _get_game_team_context_for_saishi(db=db, saishi_id=saishi_id)
    if context is None:
        return None
    return context.home_team_id, context.guest_team_id


def _split_aliases(raw: str) -> list[str]:
    content = (raw or "").strip()
    if not content:
        return []
    parts = re.split(r"[/,，、;；|\s]+", content)
    return [p.strip() for p in parts if p.strip()]


def _first_non_empty(*values: object) -> str | None:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _resolve_full_player_name(row: Any) -> str | None:
    return _first_non_empty(
        getattr(row, "nba_player_name", None),
        getattr(row, "zhiboba_player_name", None),
    )


def _collect_player_variants(row: Any) -> list[str]:
    variants: set[str] = set()
    for value in (
        _resolve_full_player_name(row),
        getattr(row, "zhiboba_player_name", None),
        getattr(row, "alias_name", None),
    ):
        if isinstance(value, str) and value.strip():
            variants.add(value.strip())

    alias = getattr(row, "player_name_alias", None)
    if isinstance(alias, str) and alias.strip():
        for part in _split_aliases(alias):
            variants.add(part)
    return sorted(variants)


def load_player_segmentation_config(db: Session, saishi_id: str) -> PlayerSegmentationConfig:
    team_ids = _get_team_ids_for_saishi(db=db, saishi_id=saishi_id)
    if team_ids is None:
        return PlayerSegmentationConfig(words=[], alias_to_full_name={})
    game_team_context = GameTeamContext(
        home_team_id=team_ids[0],
        guest_team_id=team_ids[1],
    )

    home_id = game_team_context.home_team_id
    guest_id = game_team_context.guest_team_id
    player_id_column_exists = (
        db.execute(
            text(
                """
                SELECT 1
                FROM information_schema.COLUMNS
                WHERE TABLE_SCHEMA = DATABASE()
                  AND TABLE_NAME = 'nba_players_name_data'
                  AND COLUMN_NAME = 'player_id'
                LIMIT 1
                """
            )
        ).fetchone()
        is not None
    )
    alias_table_exists = (
        db.execute(
            text(
                """
                SELECT 1
                FROM information_schema.TABLES
                WHERE TABLE_SCHEMA = DATABASE()
                  AND TABLE_NAME = 'player_alias_name_info'
                LIMIT 1
                """
            )
        ).fetchone()
        is not None
    )

    _VALID_PLAYER_ID_SELECTS = {"np.player_id", "NULL"}
    select_player_id = "np.player_id" if player_id_column_exists else "NULL"
    if select_player_id not in _VALID_PLAYER_ID_SELECTS:
        select_player_id = "NULL"

    rows = db.execute(
        text(
            f"""
            SELECT
              {select_player_id} AS player_id,
              np.team_id,
              np.team_name,
              np.zhiboba_player_id,
              np.nba_player_name,
              np.zhiboba_player_name,
              np.player_name_alias
            FROM nba_players_name_data AS np
            WHERE np.team_id IN (:home_id, :guest_id)
            """
        ),
        {"home_id": home_id, "guest_id": guest_id},
    ).fetchall()

    alias_name_map: dict[str, list[str]] = {}
    if alias_table_exists and rows:
        player_ids: list[str] = []
        for row in rows:
            for player_id in (
                getattr(row, "zhiboba_player_id", None),
                getattr(row, "player_id", None) if player_id_column_exists else None,
            ):
                if isinstance(player_id, str) and player_id.strip():
                    player_ids.append(player_id.strip())

        unique_player_ids = sorted(set(player_ids))
        if unique_player_ids:
            player_id_placeholders = []
            alias_params: dict[str, str] = {}
            for index, player_id in enumerate(unique_player_ids):
                param_name = f"player_id_{index}"
                player_id_placeholders.append(f":{param_name}")
                alias_params[param_name] = player_id

            alias_rows = db.execute(
                text(
                    f"""
                    SELECT player_id, alias_name
                    FROM player_alias_name_info
                    WHERE player_id IN ({", ".join(player_id_placeholders)})
                    """
                ),
                alias_params,
            ).fetchall()
            for alias_row in alias_rows:
                player_id = getattr(alias_row, "player_id", None)
                alias_name = getattr(alias_row, "alias_name", None)
                if not isinstance(player_id, str) or not player_id.strip():
                    continue
                if not isinstance(alias_name, str) or not alias_name.strip():
                    continue
                alias_name_map.setdefault(player_id.strip(), []).append(alias_name.strip())

    words: set[str] = set()
    alias_to_full_name: dict[str, str] = {}
    player_to_team_id: dict[str, str] = {}
    player_to_team_name: dict[str, str] = {}
    player_to_team_side: dict[str, str] = {}

    for row in rows:
        full_name = _resolve_full_player_name(row)
        variants = _collect_player_variants(row)
        row_team_id = getattr(row, "team_id", None)
        row_team_name = getattr(row, "team_name", None)
        normalized_team_id = row_team_id.strip() if isinstance(row_team_id, str) and row_team_id.strip() else None
        normalized_team_name = row_team_name.strip() if isinstance(row_team_name, str) and row_team_name.strip() else None
        team_side: str | None = None
        if normalized_team_id == home_id:
            team_side = "home"
        elif normalized_team_id == guest_id:
            team_side = "visit"

        for player_id in (
            getattr(row, "zhiboba_player_id", None),
            getattr(row, "player_id", None) if player_id_column_exists else None,
        ):
            if not isinstance(player_id, str) or not player_id.strip():
                continue
            variants.extend(alias_name_map.get(player_id.strip(), []))
        if not variants:
            continue
        for variant in variants:
            words.add(variant)
            if full_name:
                alias_to_full_name[variant] = full_name
            if normalized_team_id:
                player_to_team_id[variant] = normalized_team_id
            if normalized_team_name:
                player_to_team_name[variant] = normalized_team_name
            if team_side:
                player_to_team_side[variant] = team_side

    return PlayerSegmentationConfig(
        words=sorted(words),
        alias_to_full_name=alias_to_full_name,
        player_to_team_id=player_to_team_id,
        player_to_team_name=player_to_team_name,
        player_to_team_side=player_to_team_side,
        game_team_context=game_team_context,
    )


def load_player_dictionary(db: Session, saishi_id: str) -> list[str]:
    return load_player_segmentation_config(db=db, saishi_id=saishi_id).words


def _has_game_finished(records: list[ZhibobaLiveTextEventRecord]) -> bool:
    for r in records:
        if (r.pid_text or "").strip() == "比赛结束":
            return True
    return False


def build_segmented_text(tokens: list[str]) -> str | None:
    cleaned = [token.strip() for token in (tokens or []) if isinstance(token, str) and token.strip()]
    if not cleaned:
        return None
    return "\\".join(cleaned)


def normalize_player_tokens(tokens: list[str], alias_to_full_name: dict[str, str]) -> list[str]:
    normalized: list[str] = []
    for token in tokens or []:
        if not isinstance(token, str):
            continue
        cleaned = token.strip()
        if not cleaned:
            continue
        normalized.append(alias_to_full_name.get(cleaned, cleaned))
    return normalized


def normalize_player_name(name: str | None, alias_to_full_name: dict[str, str]) -> str | None:
    if not isinstance(name, str):
        return None
    cleaned = name.strip()
    if not cleaned:
        return None
    return alias_to_full_name.get(cleaned, cleaned)


def _load_previous_score_state(
    db: Session,
    *,
    saishi_id: str,
    min_live_sid: int,
    source: str = LIVE_TEXT_SOURCE_ZHIBOBA,
) -> tuple[int | None, int | None]:
    try:
        row = db.execute(
            text(
                """
                SELECT home_score, visit_score
                FROM nba_zhiboba_live_text_event
                WHERE saishi_id = :saishi_id
                  AND source = :source
                  AND live_sid < :min_live_sid
                ORDER BY live_sid DESC
                LIMIT 1
                """
            ),
            {"saishi_id": saishi_id, "source": source, "min_live_sid": min_live_sid},
        ).fetchone()
    except Exception:
        logger.warning("load_previous_score_state_failed", extra={"saishi_id": saishi_id, "source": source}, exc_info=True)
        return None, None
    if row is None:
        return None, None
    return getattr(row, "home_score", None), getattr(row, "visit_score", None)


def enrich_records_with_game_state(
    db: Session,
    records: list[ZhibobaLiveTextEventRecord],
    *,
    alias_to_full_name: dict[str, str] | None = None,
) -> list[ZhibobaLiveTextEventRecord]:
    if not records:
        return []

    normalized_alias_map = alias_to_full_name or {}
    ordered_records = sorted(records, key=lambda item: item.live_sid)
    prev_home_score, prev_visit_score = _load_previous_score_state(
        db,
        saishi_id=ordered_records[0].saishi_id,
        min_live_sid=ordered_records[0].live_sid,
        source=ordered_records[0].source,
    )
    enriched_records: list[ZhibobaLiveTextEventRecord] = []

    for record in ordered_records:
        home_score_change: int | None = None
        visit_score_change: int | None = None
        score_team_side: str | None = None
        score_points: int | None = None
        score_diff: int | None = None

        if record.home_score is not None and record.visit_score is not None:
            score_diff = record.home_score - record.visit_score

        if record.home_score is not None and prev_home_score is not None:
            home_score_change = record.home_score - prev_home_score
        if record.visit_score is not None and prev_visit_score is not None:
            visit_score_change = record.visit_score - prev_visit_score

        home_positive = home_score_change is not None and home_score_change > 0
        visit_positive = visit_score_change is not None and visit_score_change > 0
        if home_positive and not visit_positive:
            score_team_side = "home"
            score_points = home_score_change
        elif visit_positive and not home_positive:
            score_team_side = "visit"
            score_points = visit_score_change
        elif home_positive and visit_positive:
            score_team_side = "both"
            score_points = home_score_change + visit_score_change
        if record.score_points is not None:
            score_points = record.score_points

        enriched_records.append(
            replace(
                record,
                current_player_name=normalize_player_name(record.user_chn, normalized_alias_map),
                home_score_change=home_score_change,
                visit_score_change=visit_score_change,
                score_team_side=score_team_side,
                score_points=score_points,
                score_diff=score_diff,
            )
        )
        if record.home_score is not None:
            prev_home_score = record.home_score
        if record.visit_score is not None:
            prev_visit_score = record.visit_score

    return enriched_records


def fetch_zhiboba_live_text_events(
    db: Session,
    http_client: HttpClient,
    *,
    saishi_id: str,
    start_cursor: int = 1,
    page_size: int = 10,
    max_consecutive_404: int = 5000,
) -> dict[str, int | bool]:
    ensure_live_text_tables(db=db)
    filter_rules = load_live_text_filter_rules(db=db)
    line_skip_rules, _ = split_filter_rules(filter_rules)

    cursor = max(1, int(start_cursor))
    pages = 0
    events = 0
    filtered = 0
    consecutive_404 = 0
    finished = False

    while True:
        url = build_livetext_url(saishi_id=saishi_id, cursor=cursor, page_size=page_size)
        status, payload = http_client.get_json_with_status(
            url,
            headers=build_livetext_headers(),
            allow_status_codes={404},
        )

        if status == 404:
            consecutive_404 += 1
            if consecutive_404 >= max_consecutive_404:
                break
            cursor += 1
            continue

        consecutive_404 = 0
        if not isinstance(payload, list) or not payload:
            break

        raw_count = len(payload)
        filtered += count_line_skipped_payload_items(payload, line_skip_rules)
        raw_records = parse_livetext_payload(payload)
        records = filter_live_text_records(raw_records, line_skip_rules)
        if not records:
            cursor += raw_count
            if any((item.get("pid_text") or "").strip() == "比赛结束" for item in payload if isinstance(item, dict)):
                finished = True
                break
            continue

        pages += 1
        enriched_records = enrich_records_with_game_state(db=db, records=records)
        events += upsert_live_text_events(db=db, records=enriched_records)

        cursor += raw_count
        if _has_game_finished(enriched_records):
            finished = True
            break

    return {
        "pages": pages,
        "events": events,
        "filtered": filtered,
        "finished": finished,
        "last_cursor": cursor,
    }


def sync_zhiboba_live_text(
    db: Session,
    http_client: HttpClient,
    *,
    saishi_id: str,
    start_cursor: int = 1,
    page_size: int = 10,
    max_consecutive_404: int = 5000,
) -> dict[str, int | bool]:
    tokenizer = Tokenizer()
    player_segmentation = load_player_segmentation_config(db=db, saishi_id=saishi_id)
    tokenizer.add_words(player_segmentation.words)
    ensure_live_text_tables(db=db)
    filter_rules = load_live_text_filter_rules(db=db)
    line_skip_rules, content_remove_rules = split_filter_rules(filter_rules)

    cursor = max(1, int(start_cursor))
    pages = 0
    events = 0
    filtered = 0
    consecutive_404 = 0
    finished = False
    segmented_examples: list[dict[str, str | int]] = []

    while True:
        url = build_livetext_url(saishi_id=saishi_id, cursor=cursor, page_size=page_size)
        status, payload = http_client.get_json_with_status(
            url,
            headers=build_livetext_headers(),
            allow_status_codes={404},
        )

        if status == 404:
            consecutive_404 += 1
            if consecutive_404 >= max_consecutive_404:
                break
            cursor += 1
            continue

        consecutive_404 = 0
        if not isinstance(payload, list) or not payload:
            break

        raw_count = len(payload)
        filtered += count_line_skipped_payload_items(payload, line_skip_rules)
        raw_records = parse_livetext_payload(payload)
        records = filter_live_text_records(raw_records, line_skip_rules)
        if not records:
            cursor += raw_count
            if any((item.get("pid_text") or "").strip() == "比赛结束" for item in payload if isinstance(item, dict)):
                finished = True
                break
            continue

        pages += 1
        texts_for_tokenization = [clean_live_text_for_tokenization(record.live_text, content_remove_rules) for record in records]
        token_results = tokenizer.tokenize_batch(texts_for_tokenization)
        segmented_records: list[ZhibobaLiveTextEventRecord] = []

        for r, cleaned_text, token_result in zip(records, texts_for_tokenization, token_results, strict=False):
            normalized_tokens = normalize_player_tokens(
                token_result.tokens,
                player_segmentation.alias_to_full_name,
            )
            segmented_text = build_segmented_text(normalized_tokens)
            segmented_records.append(
                ZhibobaLiveTextEventRecord(
                    saishi_id=r.saishi_id,
                    live_sid=r.live_sid,
                    live_pid=r.live_pid,
                    pid_text=r.pid_text,
                    live_text=r.live_text,
                    segmented_text=segmented_text,
                    home_score=r.home_score,
                    visit_score=r.visit_score,
                    user_chn=r.user_chn,
                )
            )
            if segmented_text and len(segmented_examples) < 10:
                segmented_examples.append(
                    {
                        "live_sid": r.live_sid,
                        "pid_text": r.pid_text or "",
                        "live_text": r.live_text,
                        "cleaned_text": cleaned_text,
                        "segmented_text": segmented_text,
                        "current_player_name": normalize_player_name(r.user_chn, player_segmentation.alias_to_full_name) or "",
                        "score_diff": (r.home_score - r.visit_score) if r.home_score is not None and r.visit_score is not None else None,
                    }
                )

        enriched_records = enrich_records_with_game_state(
            db=db,
            records=segmented_records,
            alias_to_full_name=player_segmentation.alias_to_full_name,
        )
        if segmented_examples:
            example_by_sid = {item["live_sid"]: item for item in segmented_examples}
            for record in enriched_records:
                example = example_by_sid.get(record.live_sid)
                if example is None:
                    continue
                example["current_player_name"] = record.current_player_name or ""
                example["score_team_side"] = record.score_team_side or ""
                example["score_points"] = record.score_points
                example["score_diff"] = record.score_diff
                example["home_score_change"] = record.home_score_change
                example["visit_score_change"] = record.visit_score_change
                example["home_score"] = record.home_score
                example["visit_score"] = record.visit_score

        events += upsert_live_text_events(db=db, records=enriched_records)

        cursor += raw_count
        if _has_game_finished(enriched_records):
            finished = True
            break

    return {
        "pages": pages,
        "events": events,
        "filtered": filtered,
        "finished": finished,
        "last_cursor": cursor,
        "segmented_examples": segmented_examples,
    }