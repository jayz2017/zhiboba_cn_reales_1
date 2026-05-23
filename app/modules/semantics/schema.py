from sqlalchemy import text
from sqlalchemy.orm import Session

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
  ) AS new_val
ON DUPLICATE KEY UPDATE
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


def ensure_player_relation_table(db: Session) -> None:
    db.execute(text(_DDL_CREATE_PLAYER_RELATION_TABLE))
    db.commit()


def ensure_extraction_progress_table(db: Session) -> None:
    db.execute(text(_DDL_CREATE_EXTRACTION_PROGRESS_TABLE))
    db.commit()


__all__ = [
    "ensure_player_relation_table",
    "ensure_extraction_progress_table",
]
