from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

LINE_SKIP_RULE_TYPE = "line_skip"
CONTENT_REMOVE_RULE_TYPE = "content_remove"
TARGET_PID_TEXT = "pid_text"
TARGET_LIVE_TEXT = "live_text"
MATCH_MODE_EXACT = "exact"
MATCH_MODE_CONTAINS = "contains"
MATCH_MODE_PREFIX = "prefix"
LIVE_TEXT_SOURCE_ZHIBOBA = "zhiboba"
LIVE_TEXT_SOURCE_NBA_CHINA = "nba_china"

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
    source: str = LIVE_TEXT_SOURCE_ZHIBOBA


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


_DDL_CREATE_EVENT_TABLE = """
CREATE TABLE IF NOT EXISTS nba_zhiboba_live_text_event (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  saishi_id VARCHAR(32) NOT NULL,
  live_sid BIGINT UNSIGNED NOT NULL,
  source VARCHAR(32) NOT NULL DEFAULT 'zhiboba',
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
  UNIQUE KEY uk_live_source_sid (source, live_sid),
  KEY idx_saishi_id (saishi_id),
  KEY idx_live_text_source (source)
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
        ("source", "ALTER TABLE nba_zhiboba_live_text_event ADD COLUMN source VARCHAR(32) NOT NULL DEFAULT 'zhiboba' AFTER live_sid"),
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
    _drop_index_if_exists(
        db=db,
        table_name="nba_zhiboba_live_text_event",
        index_name="uk_live_sid",
    )
    _ensure_index(
        db=db,
        table_name="nba_zhiboba_live_text_event",
        index_name="uk_live_source_sid",
        create_sql="ALTER TABLE nba_zhiboba_live_text_event ADD UNIQUE KEY uk_live_source_sid (source, live_sid)",
    )
    _ensure_index(
        db=db,
        table_name="nba_zhiboba_live_text_event",
        index_name="idx_live_text_source",
        create_sql="ALTER TABLE nba_zhiboba_live_text_event ADD KEY idx_live_text_source (source)",
    )
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


def _drop_index_if_exists(db: Session, *, table_name: str, index_name: str) -> None:
    index_exists = db.execute(
        text(
            """
            SELECT 1
            FROM information_schema.STATISTICS
            WHERE TABLE_SCHEMA = DATABASE()
              AND TABLE_NAME = :table_name
              AND INDEX_NAME = :index_name
            LIMIT 1
            """
        ),
        {"table_name": table_name, "index_name": index_name},
    ).fetchone()
    if index_exists is not None:
        db.execute(text(f"ALTER TABLE {table_name} DROP INDEX {index_name}"))


def _ensure_index(db: Session, *, table_name: str, index_name: str, create_sql: str) -> None:
    index_exists = db.execute(
        text(
            """
            SELECT 1
            FROM information_schema.STATISTICS
            WHERE TABLE_SCHEMA = DATABASE()
              AND TABLE_NAME = :table_name
              AND INDEX_NAME = :index_name
            LIMIT 1
            """
        ),
        {"table_name": table_name, "index_name": index_name},
    ).fetchone()
    if index_exists is None:
        db.execute(text(create_sql))