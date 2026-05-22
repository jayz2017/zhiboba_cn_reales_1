CREATE TABLE IF NOT EXISTS nba_team (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  name VARCHAR(64) NOT NULL,
  abbreviation VARCHAR(8) NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uk_nba_team_abbr (abbreviation)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS nba_game (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  season VARCHAR(16) NOT NULL,
  game_date DATE NOT NULL,
  home_team_id BIGINT UNSIGNED NOT NULL,
  away_team_id BIGINT UNSIGNED NOT NULL,
  status VARCHAR(32) NOT NULL DEFAULT 'scheduled',
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uk_nba_game_unique (season, game_date, home_team_id, away_team_id),
  KEY idx_nba_game_date (game_date),
  KEY idx_nba_game_home (home_team_id),
  KEY idx_nba_game_away (away_team_id),
  CONSTRAINT fk_nba_game_home_team FOREIGN KEY (home_team_id) REFERENCES nba_team (id),
  CONSTRAINT fk_nba_game_away_team FOREIGN KEY (away_team_id) REFERENCES nba_team (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS nba_schedule_raw (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  source VARCHAR(64) NOT NULL,
  season VARCHAR(16) NOT NULL,
  fetched_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  raw_json JSON NOT NULL,
  PRIMARY KEY (id),
  KEY idx_nba_schedule_raw_season (season),
  KEY idx_nba_schedule_raw_source (source)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS nba_live_text_event (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  game_id BIGINT UNSIGNED NOT NULL,
  source VARCHAR(64) NOT NULL,
  event_time TIMESTAMP NULL,
  quarter TINYINT NULL,
  clock VARCHAR(16) NULL,
  text LONGTEXT NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_live_text_game (game_id),
  KEY idx_live_text_source (source),
  FULLTEXT KEY ftx_live_text (text),
  CONSTRAINT fk_live_text_game FOREIGN KEY (game_id) REFERENCES nba_game (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS nba_live_text_token (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  live_event_id BIGINT UNSIGNED NOT NULL,
  token VARCHAR(128) NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_live_token_event (live_event_id),
  KEY idx_live_token_token (token),
  CONSTRAINT fk_live_token_event FOREIGN KEY (live_event_id) REFERENCES nba_live_text_event (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS nba_semantic_relation (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  game_id BIGINT UNSIGNED NOT NULL,
  subject VARCHAR(256) NOT NULL,
  predicate VARCHAR(128) NOT NULL,
  object VARCHAR(256) NOT NULL,
  evidence_live_event_id BIGINT UNSIGNED NULL,
  confidence DECIMAL(5,4) NOT NULL DEFAULT 0.5000,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_semantic_game (game_id),
  KEY idx_semantic_spo (subject, predicate, object),
  KEY idx_semantic_evidence (evidence_live_event_id),
  CONSTRAINT fk_semantic_game FOREIGN KEY (game_id) REFERENCES nba_game (id),
  CONSTRAINT fk_semantic_evidence FOREIGN KEY (evidence_live_event_id) REFERENCES nba_live_text_event (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
