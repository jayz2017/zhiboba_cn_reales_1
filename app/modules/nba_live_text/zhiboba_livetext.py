from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.modules.nba_live_text.nlp.tokenizer import Tokenizer
from app.core.http_resources import QIUMIBAO_LIVETEXT_BASE_URL, build_livetext_headers
from app.utils.db_helpers import to_int
from app.utils.http.client import HttpClient

LINE_SKIP_RULE_TYPE = "line_skip"
CONTENT_REMOVE_RULE_TYPE = "content_remove"
TARGET_PID_TEXT = "pid_text"
TARGET_LIVE_TEXT = "live_text"
MATCH_MODE_EXACT = "exact"
MATCH_MODE_CONTAINS = "contains"
MATCH_MODE_PREFIX = "prefix"

_DEFAULT_LINE_SKIP_RULES: tuple[tuple[str, str, str, str], ...] = (
    (LINE_SKIP_RULE_TYPE, TARGET_PID_TEXT, MATCH_MODE_EXACT, "未赛"),
    (LINE_SKIP_RULE_TYPE, TARGET_PID_TEXT, MATCH_MODE_EXACT, "中场休息"),
    (LINE_SKIP_RULE_TYPE, TARGET_LIVE_TEXT, MATCH_MODE_PREFIX, "@"),
)

_DEFAULT_CONTENT_REMOVE_RULES: tuple[str, ...] = (
    "啊",
    "呀",
    "吧",
    "呢",
    "吗",
    "啦",
    "哦",
    "诶",
    "哎",
    "哈",
    "呵",
    "唉",
    "嗯",
    "呃",
    "哇",
    "嘛",
    "呐",
    "噢",
    "！",
    "？",
    "，",
    "。",
    "、",
    "：",
    "；",
    "…",
    "（",
    "）",
    "(",
    ")",
    "[",
    "]",
    "【",
    "】",
)

_LEADING_COMMENT_PREFIX_PATTERN = re.compile(r"^@[^:：]{1,64}[:：]\s*")


@dataclass(frozen=True)
class ZhibobaLiveTextEventRecord:
    saishi_id: str
    live_sid: int
    live_pid: str | None
    pid_text: str | None
    live_text: str
    segmented_text: str | None
    home_score: int | None
    visit_score: int | None
    user_chn: str | None
    current_player_name: str | None = None
    home_score_change: int | None = None
    visit_score_change: int | None = None
    score_team_side: str | None = None
    score_points: int | None = None
    score_diff: int | None = None


@dataclass(frozen=True)
class LiveTextFilterRule:
    rule_type: str
    target_field: str
    match_mode: str
    filter_text: str


@dataclass(frozen=True)
class GameTeamContext:
    home_team_id: str
    guest_team_id: str
    home_team_name: str | None = None
    guest_team_name: str | None = None


@dataclass(frozen=True)
class PlayerSegmentationConfig:
    words: list[str]
    alias_to_full_name: dict[str, str]
    player_to_team_id: dict[str, str] = field(default_factory=dict)
    player_to_team_name: dict[str, str] = field(default_factory=dict)
    player_to_team_side: dict[str, str] = field(default_factory=dict)
    game_team_context: GameTeamContext | None = None


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


_DDL_CREATE_EVENT_TABLE = """
CREATE TABLE IF NOT EXISTS nba_zhiboba_live_text_event (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  saishi_id VARCHAR(32) NOT NULL,
  live_sid BIGINT UNSIGNED NOT NULL,
  live_pid VARCHAR(32) NULL,
  pid_text VARCHAR(64) NULL,
  live_text LONGTEXT NOT NULL,
  segmented_text LONGTEXT NULL,
  visit_score INT NULL,
  home_score INT NULL,
  user_chn VARCHAR(64) NULL,
  current_player_name VARCHAR(128) NULL,
  home_score_change INT NULL,
  visit_score_change INT NULL,
  score_team_side VARCHAR(16) NULL,
  score_points INT NULL,
  score_diff INT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uk_live_sid (live_sid),
  KEY idx_saishi_id (saishi_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
""".strip()

_DDL_CREATE_FILTER_RULE_TABLE = """
CREATE TABLE IF NOT EXISTS nba_zhiboba_live_text_filter_rule (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  rule_type VARCHAR(32) NOT NULL,
  target_field VARCHAR(32) NOT NULL,
  match_mode VARCHAR(16) NOT NULL DEFAULT 'contains',
  filter_text VARCHAR(255) NOT NULL,
  is_enabled TINYINT(1) NOT NULL DEFAULT 1,
  sort_order INT NOT NULL DEFAULT 0,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uk_rule_unique (rule_type, target_field, match_mode, filter_text),
  KEY idx_rule_lookup (rule_type, target_field, is_enabled, sort_order)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
""".strip()

_SQL_INSERT_FILTER_RULE_IGNORE = """
INSERT IGNORE INTO nba_zhiboba_live_text_filter_rule
  (rule_type, target_field, match_mode, filter_text, is_enabled, sort_order)
VALUES
  (:rule_type, :target_field, :match_mode, :filter_text, 1, :sort_order)
""".strip()


def normalize_live_text_filter_rules(db: Session) -> None:
    # Migrate old live_text keyword rules to the modes the code actually expects:
    # - "@" should skip comment lines by prefix
    # - other live_text exact keyword rules should behave as contains
    db.execute(
        text(
            """
            DELETE src
            FROM nba_zhiboba_live_text_filter_rule AS src
            INNER JOIN nba_zhiboba_live_text_filter_rule AS dst
                ON dst.rule_type = src.rule_type
               AND dst.target_field = src.target_field
               AND dst.filter_text = src.filter_text
               AND dst.match_mode = :new_match_mode
            WHERE src.rule_type = :rule_type
              AND src.target_field = :target_field
              AND src.match_mode = :old_match_mode
              AND src.filter_text = :filter_text
            """
        ),
        {
            "new_match_mode": MATCH_MODE_PREFIX,
            "rule_type": LINE_SKIP_RULE_TYPE,
            "target_field": TARGET_LIVE_TEXT,
            "old_match_mode": MATCH_MODE_EXACT,
            "filter_text": "@",
        },
    )
    db.execute(
        text(
            """
            UPDATE nba_zhiboba_live_text_filter_rule
            SET match_mode = :match_mode
            WHERE rule_type = :rule_type
              AND target_field = :target_field
              AND match_mode = :old_match_mode
              AND filter_text = :filter_text
            """
        ),
        {
            "match_mode": MATCH_MODE_PREFIX,
            "rule_type": LINE_SKIP_RULE_TYPE,
            "target_field": TARGET_LIVE_TEXT,
            "old_match_mode": MATCH_MODE_EXACT,
            "filter_text": "@",
        },
    )
    db.execute(
        text(
            """
            DELETE src
            FROM nba_zhiboba_live_text_filter_rule AS src
            INNER JOIN nba_zhiboba_live_text_filter_rule AS dst
                ON dst.rule_type = src.rule_type
               AND dst.target_field = src.target_field
               AND dst.filter_text = src.filter_text
               AND dst.match_mode = :new_match_mode
            WHERE src.rule_type = :rule_type
              AND src.target_field = :target_field
              AND src.match_mode = :old_match_mode
              AND src.filter_text <> :filter_text
            """
        ),
        {
            "new_match_mode": MATCH_MODE_CONTAINS,
            "rule_type": LINE_SKIP_RULE_TYPE,
            "target_field": TARGET_LIVE_TEXT,
            "old_match_mode": MATCH_MODE_EXACT,
            "filter_text": "@",
        },
    )
    db.execute(
        text(
            """
            UPDATE nba_zhiboba_live_text_filter_rule
            SET match_mode = :match_mode
            WHERE rule_type = :rule_type
              AND target_field = :target_field
              AND match_mode = :old_match_mode
              AND filter_text <> :filter_text
            """
        ),
        {
            "match_mode": MATCH_MODE_CONTAINS,
            "rule_type": LINE_SKIP_RULE_TYPE,
            "target_field": TARGET_LIVE_TEXT,
            "old_match_mode": MATCH_MODE_EXACT,
            "filter_text": "@",
        },
    )


_tables_ensured = False


def ensure_live_text_tables(db: Session) -> None:
    global _tables_ensured
    if _tables_ensured:
        return
    db.execute(text(_DDL_CREATE_EVENT_TABLE))
    db.execute(text(_DDL_CREATE_FILTER_RULE_TABLE))
    required_event_columns: tuple[tuple[str, str], ...] = (
        ("segmented_text", "ALTER TABLE nba_zhiboba_live_text_event ADD COLUMN segmented_text LONGTEXT NULL AFTER live_text"),
        ("current_player_name", "ALTER TABLE nba_zhiboba_live_text_event ADD COLUMN current_player_name VARCHAR(128) NULL AFTER user_chn"),
        ("home_score_change", "ALTER TABLE nba_zhiboba_live_text_event ADD COLUMN home_score_change INT NULL AFTER current_player_name"),
        ("visit_score_change", "ALTER TABLE nba_zhiboba_live_text_event ADD COLUMN visit_score_change INT NULL AFTER home_score_change"),
        ("score_team_side", "ALTER TABLE nba_zhiboba_live_text_event ADD COLUMN score_team_side VARCHAR(16) NULL AFTER visit_score_change"),
        ("score_points", "ALTER TABLE nba_zhiboba_live_text_event ADD COLUMN score_points INT NULL AFTER score_team_side"),
        ("score_diff", "ALTER TABLE nba_zhiboba_live_text_event ADD COLUMN score_diff INT NULL AFTER score_points"),
    )
    for column_name, alter_sql in required_event_columns:
        column_exists = db.execute(
            text(
                """
                SELECT 1
                FROM information_schema.COLUMNS
                WHERE TABLE_SCHEMA = DATABASE()
                  AND TABLE_NAME = 'nba_zhiboba_live_text_event'
                  AND COLUMN_NAME = :column_name
                LIMIT 1
                """
            ),
            {"column_name": column_name},
        ).fetchone()
        if column_exists is None:
            db.execute(text(alter_sql))
    for sort_order, (rule_type, target_field, match_mode, filter_text) in enumerate(_DEFAULT_LINE_SKIP_RULES, start=1):
        db.execute(
            text(_SQL_INSERT_FILTER_RULE_IGNORE),
            {
                "rule_type": rule_type,
                "target_field": target_field,
                "match_mode": match_mode,
                "filter_text": filter_text,
                "sort_order": sort_order,
            },
        )
    for index, filter_text in enumerate(_DEFAULT_CONTENT_REMOVE_RULES, start=100):
        db.execute(
            text(_SQL_INSERT_FILTER_RULE_IGNORE),
            {
                "rule_type": CONTENT_REMOVE_RULE_TYPE,
                "target_field": TARGET_LIVE_TEXT,
                "match_mode": MATCH_MODE_CONTAINS,
                "filter_text": filter_text,
                "sort_order": index,
            },
        )
    normalize_live_text_filter_rules(db=db)
    db.commit()
    _tables_ensured = True


_SQL_UPSERT_EVENT = """
INSERT INTO nba_zhiboba_live_text_event
  (
    saishi_id,
    live_sid,
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
    game_team_context = _get_game_team_context_for_saishi(db=db, saishi_id=saishi_id)
    if game_team_context is None:
        return PlayerSegmentationConfig(words=[], alias_to_full_name={})

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

    select_player_id = "np.player_id" if player_id_column_exists else "NULL"

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


def load_live_text_filter_rules(db: Session) -> list[LiveTextFilterRule]:
    rows = db.execute(
        text(
            """
            SELECT rule_type, target_field, match_mode, filter_text
            FROM nba_zhiboba_live_text_filter_rule
            WHERE is_enabled = 1
            ORDER BY sort_order ASC, id ASC
            """
        )
    ).fetchall()
    rules: list[LiveTextFilterRule] = []
    for row in rows:
        rule_type = getattr(row, "rule_type", None)
        target_field = getattr(row, "target_field", None)
        match_mode = getattr(row, "match_mode", None)
        filter_text = getattr(row, "filter_text", None)
        if not all(isinstance(value, str) and value.strip() for value in (rule_type, target_field, match_mode, filter_text)):
            continue
        rules.append(
            LiveTextFilterRule(
                rule_type=rule_type.strip(),
                target_field=target_field.strip(),
                match_mode=match_mode.strip(),
                filter_text=filter_text.strip(),
            )
        )
    return rules


def split_filter_rules(
    rules: list[LiveTextFilterRule],
) -> tuple[list[LiveTextFilterRule], list[LiveTextFilterRule]]:
    line_skip_rules = [rule for rule in rules if rule.rule_type == LINE_SKIP_RULE_TYPE]
    content_remove_rules = [rule for rule in rules if rule.rule_type == CONTENT_REMOVE_RULE_TYPE]
    return line_skip_rules, content_remove_rules


def _get_rule_target_value(*, pid_text: str | None, live_text: str, target_field: str) -> str:
    if target_field == TARGET_PID_TEXT:
        return (pid_text or "").strip()
    return (live_text or "").strip()


def _matches_filter_rule(value: str, rule: LiveTextFilterRule) -> bool:
    if not value or not rule.filter_text:
        return False
    if rule.match_mode == MATCH_MODE_EXACT:
        return value == rule.filter_text
    if rule.match_mode == MATCH_MODE_PREFIX:
        return value.startswith(rule.filter_text)
    return rule.filter_text in value


def count_pending_payload_items(payload: Any) -> int:
    if not isinstance(payload, list):
        return 0
    count = 0
    for item in payload:
        if not isinstance(item, dict):
            continue
        pid_text = item.get("pid_text")
        if isinstance(pid_text, str) and pid_text.strip() == "未赛":
            count += 1
    return count


def count_line_skipped_payload_items(payload: Any, rules: list[LiveTextFilterRule]) -> int:
    if not isinstance(payload, list):
        return 0
    count = 0
    for item in payload:
        if not isinstance(item, dict):
            continue
        pid_text = item.get("pid_text")
        live_text = item.get("live_text")
        pid_text_value = pid_text.strip() if isinstance(pid_text, str) else None
        live_text_value = live_text.strip() if isinstance(live_text, str) else ""
        for rule in rules:
            target_value = _get_rule_target_value(
                pid_text=pid_text_value,
                live_text=live_text_value,
                target_field=rule.target_field,
            )
            if _matches_filter_rule(target_value, rule):
                count += 1
                break
    return count


def _should_skip_record(record: ZhibobaLiveTextEventRecord, rules: list[LiveTextFilterRule]) -> bool:
    for rule in rules:
        target_value = _get_rule_target_value(
            pid_text=record.pid_text,
            live_text=record.live_text,
            target_field=rule.target_field,
        )
        if _matches_filter_rule(target_value, rule):
            return True
    return False


def filter_live_text_records(
    records: list[ZhibobaLiveTextEventRecord], rules: list[LiveTextFilterRule]
) -> list[ZhibobaLiveTextEventRecord]:
    return [record for record in records if not _should_skip_record(record, rules)]


def clean_live_text_for_tokenization(content: str, rules: list[LiveTextFilterRule]) -> str:
    cleaned = (content or "").strip()
    if not cleaned:
        return ""
    cleaned = re.sub(r"\[[^\[\]]*]", "", cleaned)
    cleaned = _LEADING_COMMENT_PREFIX_PATTERN.sub("", cleaned)
    cleaned = re.sub(r"^@\s*", "", cleaned)
    for rule in rules:
        if rule.target_field != TARGET_LIVE_TEXT or not rule.filter_text:
            continue
        if rule.match_mode == MATCH_MODE_EXACT:
            if cleaned == rule.filter_text:
                cleaned = ""
        else:
            cleaned = cleaned.replace(rule.filter_text, "")
    return re.sub(r"\s+", " ", cleaned).strip()


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
) -> tuple[int | None, int | None]:
    try:
        row = db.execute(
            text(
                """
                SELECT home_score, visit_score
                FROM nba_zhiboba_live_text_event
                WHERE saishi_id = :saishi_id
                  AND live_sid < :min_live_sid
                ORDER BY live_sid DESC
                LIMIT 1
                """
            ),
            {"saishi_id": saishi_id, "min_live_sid": min_live_sid},
        ).fetchone()
    except Exception:
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
