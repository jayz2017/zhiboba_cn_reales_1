from sqlalchemy import text
from sqlalchemy.orm import Session

from app.modules.semantics.constants import (
    CONFIDENCE_DESCRIPTIONS,
    DEFAULT_CONFIDENCE_VALUES,
    DEFAULT_KEYWORD_GROUPS,
    KEYWORD_CATEGORY_DESCRIPTIONS,
)

_DDL_CREATE_PLAYER_RELATION_TABLE = """
CREATE TABLE IF NOT EXISTS nba_zhiboba_player_relation (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  saishi_id VARCHAR(32) NOT NULL,
  evidence_event_id BIGINT UNSIGNED NOT NULL,
  live_sid BIGINT UNSIGNED NOT NULL,
  source VARCHAR(32) NOT NULL DEFAULT 'zhiboba',
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
  UNIQUE KEY uk_relation_source_unique (source, saishi_id, evidence_event_id, relation_type, subject_player_name, object_player_name),
  KEY idx_relation_game (saishi_id),
  KEY idx_relation_source (source),
  KEY idx_relation_live_sid (live_sid),
  KEY idx_relation_subject (subject_player_name),
  KEY idx_relation_object (object_player_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
""".strip()

_SQL_UPSERT_PLAYER_RELATION = """
INSERT INTO nba_zhiboba_player_relation
  (
    saishi_id,
    evidence_event_id,
    live_sid,
    source,
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
    :source,
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
  ) AS new_val
ON DUPLICATE KEY UPDATE
  source = new_val.source,
  relation_side = new_val.relation_side,
  subject_team_id = new_val.subject_team_id,
  subject_team_name = new_val.subject_team_name,
  subject_team_side = new_val.subject_team_side,
  subject_team_score = new_val.subject_team_score,
  object_team_id = new_val.object_team_id,
  object_team_name = new_val.object_team_name,
  object_team_side = new_val.object_team_side,
  object_team_score = new_val.object_team_score,
  offense_team_id = new_val.offense_team_id,
  offense_team_name = new_val.offense_team_name,
  offense_team_side = new_val.offense_team_side,
  offense_team_score = new_val.offense_team_score,
  offense_team_points = new_val.offense_team_points,
  possession_number = new_val.possession_number,
  home_score = new_val.home_score,
  visit_score = new_val.visit_score,
  action_text = new_val.action_text,
  result_text = new_val.result_text,
  score_points = new_val.score_points,
  evidence_text = new_val.evidence_text,
  segmented_text = new_val.segmented_text,
  extractor_name = new_val.extractor_name,
  confidence = new_val.confidence
""".strip()


_DDL_CREATE_EXTRACTION_PROGRESS_TABLE = """
CREATE TABLE IF NOT EXISTS nba_zhiboba_extraction_progress (
    saishi_id VARCHAR(32) NOT NULL PRIMARY KEY COMMENT '比赛ID',
    last_processed_live_sid BIGINT DEFAULT NULL COMMENT '最后处理的live_sid',
    last_extracted_at TIMESTAMP NULL COMMENT '最后抽取时间',
    total_relations INT DEFAULT 0 COMMENT '累计关系总数',
    total_events_processed INT DEFAULT 0 COMMENT '累计处理事件数',
    backend_used VARCHAR(32) NULL COMMENT '使用的后端类型',
    extraction_status ENUM('idle', 'running', 'completed', 'failed') DEFAULT 'idle' COMMENT '抽取状态',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_last_extracted_at (last_extracted_at),
    INDEX idx_extraction_status (extraction_status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='关系抽取进度追踪表'
""".strip()

_DDL_CREATE_RELATION_RULE_KEYWORD_TABLE = """
CREATE TABLE IF NOT EXISTS nba_zhiboba_relation_rule_keyword (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键ID',
  category VARCHAR(64) NOT NULL COMMENT '关键词分类，如 pass/block/score',
  keyword VARCHAR(64) NOT NULL COMMENT '中文触发关键词',
  is_enabled TINYINT(1) NOT NULL DEFAULT 1 COMMENT '是否启用：1启用，0禁用',
  description VARCHAR(255) NULL COMMENT '配置说明',
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (id),
  UNIQUE KEY uk_relation_rule_keyword (category, keyword),
  KEY idx_relation_rule_keyword_category_enabled (category, is_enabled)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='球员关系规则关键词配置表';
""".strip()

_DDL_CREATE_RELATION_CONFIDENCE_TABLE = """
CREATE TABLE IF NOT EXISTS nba_zhiboba_relation_confidence (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键ID',
  config_key VARCHAR(64) NOT NULL COMMENT '置信度配置键，如 CONFIDENCE_PASS',
  confidence DECIMAL(5,4) NOT NULL COMMENT '置信度，范围0.0000到1.0000',
  is_enabled TINYINT(1) NOT NULL DEFAULT 1 COMMENT '是否启用：1启用，0禁用',
  description VARCHAR(255) NULL COMMENT '配置说明',
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (id),
  UNIQUE KEY uk_relation_confidence_key (config_key),
  KEY idx_relation_confidence_enabled (is_enabled)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='球员关系抽取置信度配置表';
""".strip()

_SQL_SEED_RELATION_RULE_KEYWORD = """
INSERT INTO nba_zhiboba_relation_rule_keyword
  (category, keyword, is_enabled, description)
VALUES
  (:category, :keyword, 1, :description)
ON DUPLICATE KEY UPDATE
  id = id
""".strip()

_SQL_SEED_RELATION_CONFIDENCE = """
INSERT INTO nba_zhiboba_relation_confidence
  (config_key, confidence, is_enabled, description)
VALUES
  (:config_key, :confidence, 1, :description)
ON DUPLICATE KEY UPDATE
  id = id
""".strip()


def ensure_player_relation_table(db: Session) -> None:
    db.execute(text(_DDL_CREATE_PLAYER_RELATION_TABLE))
    _ensure_column(
        db=db,
        table_name="nba_zhiboba_player_relation",
        column_name="source",
        alter_sql="ALTER TABLE nba_zhiboba_player_relation ADD COLUMN source VARCHAR(32) NOT NULL DEFAULT 'zhiboba' AFTER live_sid",
    )
    _drop_index_if_exists(
        db=db,
        table_name="nba_zhiboba_player_relation",
        index_name="uk_relation_unique",
    )
    _ensure_index(
        db=db,
        table_name="nba_zhiboba_player_relation",
        index_name="uk_relation_source_unique",
        create_sql=(
            "ALTER TABLE nba_zhiboba_player_relation "
            "ADD UNIQUE KEY uk_relation_source_unique "
            "(source, saishi_id, evidence_event_id, relation_type, subject_player_name, object_player_name)"
        ),
    )
    _ensure_index(
        db=db,
        table_name="nba_zhiboba_player_relation",
        index_name="idx_relation_source",
        create_sql="ALTER TABLE nba_zhiboba_player_relation ADD KEY idx_relation_source (source)",
    )
    db.commit()


def _ensure_column(db: Session, *, table_name: str, column_name: str, alter_sql: str) -> None:
    exists = db.execute(
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
    if exists is None:
        db.execute(text(alter_sql))


_VALID_TABLE_NAMES = {"nba_zhiboba_player_relation"}
_VALID_INDEX_NAMES = {"uk_relation_unique"}


def _drop_index_if_exists(db: Session, *, table_name: str, index_name: str) -> None:
    exists = db.execute(
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
    if exists is not None:
        if table_name not in _VALID_TABLE_NAMES:
            raise ValueError(f"Invalid table name: {table_name}")
        if index_name not in _VALID_INDEX_NAMES:
            raise ValueError(f"Invalid index name: {index_name}")
        db.execute(text(f"ALTER TABLE {table_name} DROP INDEX {index_name}"))


def _ensure_index(db: Session, *, table_name: str, index_name: str, create_sql: str) -> None:
    exists = db.execute(
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
    if exists is None:
        db.execute(text(create_sql))


def ensure_extraction_progress_table(db: Session) -> None:
    db.execute(text(_DDL_CREATE_EXTRACTION_PROGRESS_TABLE))
    db.commit()


def ensure_relation_rule_config_tables(db: Session) -> None:
    db.execute(text(_DDL_CREATE_RELATION_RULE_KEYWORD_TABLE))
    db.execute(text(_DDL_CREATE_RELATION_CONFIDENCE_TABLE))

    keyword_params = [
        {
            "category": category,
            "keyword": keyword,
            "description": KEYWORD_CATEGORY_DESCRIPTIONS.get(category),
        }
        for category, keywords in DEFAULT_KEYWORD_GROUPS.items()
        for keyword in keywords
    ]
    if keyword_params:
        db.execute(text(_SQL_SEED_RELATION_RULE_KEYWORD), keyword_params)

    confidence_params = [
        {
            "config_key": config_key,
            "confidence": confidence,
            "description": CONFIDENCE_DESCRIPTIONS.get(config_key),
        }
        for config_key, confidence in DEFAULT_CONFIDENCE_VALUES.items()
    ]
    if confidence_params:
        db.execute(text(_SQL_SEED_RELATION_CONFIDENCE), confidence_params)

    db.commit()


__all__ = [
    "ensure_player_relation_table",
    "ensure_extraction_progress_table",
    "ensure_relation_rule_config_tables",
]
