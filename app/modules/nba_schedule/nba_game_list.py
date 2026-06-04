from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.http_resources import NBA_STORE_GAMECARD_FEED_URL, build_nba_store_game_headers
from app.utils.http.client import HttpClient


NBA_STORE_DEFAULT_TYPE = "NBA"

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class NbaStoreGameRecord:
    game_id: str
    game_date: date
    home_name: str | None
    visit_name: str | None
    home_team_name_abbr: str
    visit_team_name_abbr: str
    home_team_id: str | None = None
    visit_team_id: str | None = None
    source_home_team_name: str | None = None
    source_visit_team_name: str | None = None
    season_year: str | None = None
    season_type: str | None = None
    game_status: int | None = None
    game_status_text: str | None = None
    game_time_utc: datetime | None = None
    game_time_eastern: datetime | None = None
    type: str = NBA_STORE_DEFAULT_TYPE
    raw_json: str | None = None


def format_nba_store_game_date(game_date: date) -> str:
    return game_date.strftime("%m/%d/%Y")


def build_nba_store_game_params(game_date: date) -> dict[str, str]:
    return {"gamedate": format_nba_store_game_date(game_date), "platform": "web"}


def _clean_str(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _to_str(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _to_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def _parse_iso_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    raw_value = value.strip()
    try:
        parsed = datetime.fromisoformat(raw_value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def _get_team_field(team: dict[str, Any], field_name: str) -> str | None:
    value = team.get(field_name)
    return _to_str(value)


def parse_nba_store_game_list(
    payload: Any,
    *,
    game_date: date,
    team_names_by_code: dict[str, str] | None = None,
) -> list[NbaStoreGameRecord]:
    if not isinstance(payload, dict):
        return []

    modules = payload.get("modules")
    if not isinstance(modules, list):
        return []

    team_names_by_code = {k.upper(): v for k, v in (team_names_by_code or {}).items() if k and v}
    records: list[NbaStoreGameRecord] = []
    seen_game_ids: set[str] = set()

    for module in modules:
        if not isinstance(module, dict):
            continue
        cards = module.get("cards")
        if not isinstance(cards, list):
            continue
        for card in cards:
            if not isinstance(card, dict):
                continue
            card_data = card.get("cardData")
            if not isinstance(card_data, dict):
                continue

            game_id = _to_str(card_data.get("gameId"))
            home_team = card_data.get("homeTeam")
            away_team = card_data.get("awayTeam")
            if not game_id or not isinstance(home_team, dict) or not isinstance(away_team, dict):
                continue

            home_code = _get_team_field(home_team, "teamTricode")
            away_code = _get_team_field(away_team, "teamTricode")
            if not home_code or not away_code:
                continue
            if game_id in seen_game_ids:
                continue

            normalized_home_code = home_code.upper()
            normalized_away_code = away_code.upper()
            source_home_name = _get_team_field(home_team, "teamName")
            source_away_name = _get_team_field(away_team, "teamName")

            records.append(
                NbaStoreGameRecord(
                    game_id=game_id,
                    game_date=game_date,
                    home_name=team_names_by_code.get(normalized_home_code) or source_home_name or normalized_home_code,
                    visit_name=team_names_by_code.get(normalized_away_code) or source_away_name or normalized_away_code,
                    home_team_name_abbr=normalized_home_code.lower(),
                    visit_team_name_abbr=normalized_away_code.lower(),
                    home_team_id=_to_str(home_team.get("teamId")),
                    visit_team_id=_to_str(away_team.get("teamId")),
                    source_home_team_name=source_home_name,
                    source_visit_team_name=source_away_name,
                    season_year=_to_str(card_data.get("seasonYear")),
                    season_type=_to_str(card_data.get("seasonType")),
                    game_status=_to_int(card_data.get("gameStatus")),
                    game_status_text=_to_str(card_data.get("gameStatusText")),
                    game_time_utc=_parse_iso_datetime(card_data.get("gameTimeUtc")),
                    game_time_eastern=_parse_iso_datetime(card_data.get("gameTimeEastern")),
                    raw_json=json.dumps(card_data, ensure_ascii=False),
                )
            )
            seen_game_ids.add(game_id)

    return records


_DDL_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS nba_store_game_list (
  id VARCHAR(36) NOT NULL COMMENT 'Primary key generated by the sync script',
  game_id VARCHAR(32) NOT NULL COMMENT 'NBA official game id',
  game_date DATE NOT NULL COMMENT 'Game date requested from NBA.com',
  home_name VARCHAR(64) NULL COMMENT 'Home team display name from local team mapping when available',
  visit_name VARCHAR(64) NULL COMMENT 'Away team display name from local team mapping when available',
  create_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT 'Compatibility timestamp used by the old Java table',
  home_team_name_abbr VARCHAR(8) NOT NULL COMMENT 'Lowercase home team tricode',
  visit_team_name_abbr VARCHAR(8) NOT NULL COMMENT 'Lowercase away team tricode',
  `type` VARCHAR(32) NOT NULL DEFAULT 'NBA' COMMENT 'League type',
  home_team_id VARCHAR(32) NULL COMMENT 'NBA official home team id',
  visit_team_id VARCHAR(32) NULL COMMENT 'NBA official away team id',
  source_home_team_name VARCHAR(64) NULL COMMENT 'Home team name returned by NBA.com',
  source_visit_team_name VARCHAR(64) NULL COMMENT 'Away team name returned by NBA.com',
  season_year VARCHAR(16) NULL COMMENT 'NBA season year text',
  season_type VARCHAR(64) NULL COMMENT 'NBA season type text',
  game_status TINYINT NULL COMMENT 'NBA official game status code',
  game_status_text VARCHAR(64) NULL COMMENT 'NBA official game status text',
  game_time_utc DATETIME NULL COMMENT 'Scheduled game time in UTC as returned by NBA.com',
  game_time_eastern DATETIME NULL COMMENT 'Scheduled game time field named Eastern by NBA.com',
  raw_json JSON NULL COMMENT 'Original cardData payload',
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT 'Row create time',
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT 'Row update time',
  PRIMARY KEY (id),
  UNIQUE KEY uk_nba_store_game_list_game_id (game_id),
  KEY idx_nba_store_game_list_game_date (game_date),
  KEY idx_nba_store_game_list_type_date (`type`, game_date),
  KEY idx_nba_store_game_list_home_visit (home_team_name_abbr, visit_team_name_abbr)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='NBA.com official schedule game list';
""".strip()

_ALTER_NBA_STORE_GAME_LIST_COLUMNS = {
    "home_team_id": "ALTER TABLE nba_store_game_list ADD COLUMN home_team_id VARCHAR(32) NULL COMMENT 'NBA official home team id' AFTER `type`",
    "visit_team_id": "ALTER TABLE nba_store_game_list ADD COLUMN visit_team_id VARCHAR(32) NULL COMMENT 'NBA official away team id' AFTER home_team_id",
    "source_home_team_name": "ALTER TABLE nba_store_game_list ADD COLUMN source_home_team_name VARCHAR(64) NULL COMMENT 'Home team name returned by NBA.com' AFTER visit_team_id",
    "source_visit_team_name": "ALTER TABLE nba_store_game_list ADD COLUMN source_visit_team_name VARCHAR(64) NULL COMMENT 'Away team name returned by NBA.com' AFTER source_home_team_name",
    "season_year": "ALTER TABLE nba_store_game_list ADD COLUMN season_year VARCHAR(16) NULL COMMENT 'NBA season year text' AFTER source_visit_team_name",
    "season_type": "ALTER TABLE nba_store_game_list ADD COLUMN season_type VARCHAR(64) NULL COMMENT 'NBA season type text' AFTER season_year",
    "game_status": "ALTER TABLE nba_store_game_list ADD COLUMN game_status TINYINT NULL COMMENT 'NBA official game status code' AFTER season_type",
    "game_status_text": "ALTER TABLE nba_store_game_list ADD COLUMN game_status_text VARCHAR(64) NULL COMMENT 'NBA official game status text' AFTER game_status",
    "game_time_utc": "ALTER TABLE nba_store_game_list ADD COLUMN game_time_utc DATETIME NULL COMMENT 'Scheduled game time in UTC as returned by NBA.com' AFTER game_status_text",
    "game_time_eastern": "ALTER TABLE nba_store_game_list ADD COLUMN game_time_eastern DATETIME NULL COMMENT 'Scheduled game time field named Eastern by NBA.com' AFTER game_time_utc",
    "raw_json": "ALTER TABLE nba_store_game_list ADD COLUMN raw_json JSON NULL COMMENT 'Original cardData payload' AFTER game_time_eastern",
    "created_at": "ALTER TABLE nba_store_game_list ADD COLUMN created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT 'Row create time' AFTER raw_json",
    "updated_at": "ALTER TABLE nba_store_game_list ADD COLUMN updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT 'Row update time' AFTER created_at",
}

_nba_store_game_list_table_ensured = False


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


def _index_exists(db: Session, *, table_name: str, index_name: str) -> bool:
    row = db.execute(
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
    return row is not None


def ensure_nba_store_game_list_table(db: Session) -> None:
    global _nba_store_game_list_table_ensured
    if _nba_store_game_list_table_ensured:
        return

    db.execute(text(_DDL_CREATE_TABLE))
    for column_name, alter_sql in _ALTER_NBA_STORE_GAME_LIST_COLUMNS.items():
        if not _column_exists(db, table_name="nba_store_game_list", column_name=column_name):
            db.execute(text(alter_sql))

    if not _index_exists(db, table_name="nba_store_game_list", index_name="uk_nba_store_game_list_game_id"):
        db.execute(
            text(
                "ALTER TABLE nba_store_game_list "
                "ADD UNIQUE KEY uk_nba_store_game_list_game_id (game_id)"
            )
        )
    db.commit()
    _nba_store_game_list_table_ensured = True


def _get_table_columns(db: Session, table_name: str) -> set[str]:
    rows = db.execute(
        text(
            """
            SELECT COLUMN_NAME AS column_name
            FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE()
              AND TABLE_NAME = :table_name
            """
        ),
        {"table_name": table_name},
    ).fetchall()
    return {
        column_name
        for row in rows
        if isinstance((column_name := getattr(row, "column_name", None)), str) and column_name.strip()
    }


def _first_existing_column(columns: set[str], candidates: tuple[str, ...]) -> str | None:
    for candidate in candidates:
        if candidate in columns:
            return candidate
    return None


def load_team_names_by_code(db: Session) -> dict[str, str]:
    try:
        columns = _get_table_columns(db=db, table_name="nba_teams_name_data")
    except SQLAlchemyError as exc:
        logger.warning("Failed to inspect nba_teams_name_data columns: %s", exc)
        return {}

    team_code_column = _first_existing_column(columns, ("team_code", "teamCode"))
    team_name_column = _first_existing_column(columns, ("team_name", "teamName"))
    team_type_column = _first_existing_column(columns, ("team_type", "type", "teamType"))
    if not team_code_column or not team_name_column:
        return {}

    where_sql = ""
    if team_type_column:
        where_sql = f"WHERE UPPER(TRIM(`{team_type_column}`)) = 'NBA'"

    try:
        rows = db.execute(
            text(
                f"""
                SELECT `{team_code_column}` AS team_code, `{team_name_column}` AS team_name
                FROM nba_teams_name_data
                {where_sql}
                """
            )
        ).fetchall()
    except SQLAlchemyError as exc:
        logger.warning("Failed to load NBA team names by code: %s", exc)
        return {}

    result: dict[str, str] = {}
    for row in rows:
        team_code = getattr(row, "team_code", None)
        team_name = getattr(row, "team_name", None)
        if isinstance(team_code, str) and team_code.strip() and isinstance(team_name, str) and team_name.strip():
            result[team_code.strip().upper()] = team_name.strip()
    return result


_SQL_UPSERT = """
INSERT INTO nba_store_game_list (
  id, game_id, game_date, home_name, visit_name, create_date,
  home_team_name_abbr, visit_team_name_abbr, `type`,
  home_team_id, visit_team_id, source_home_team_name, source_visit_team_name,
  season_year, season_type, game_status, game_status_text, game_time_utc,
  game_time_eastern, raw_json
)
VALUES (
  :id, :game_id, :game_date, :home_name, :visit_name, CURRENT_TIMESTAMP,
  :home_team_name_abbr, :visit_team_name_abbr, :type,
  :home_team_id, :visit_team_id, :source_home_team_name, :source_visit_team_name,
  :season_year, :season_type, :game_status, :game_status_text, :game_time_utc,
  :game_time_eastern, CAST(:raw_json AS JSON)
)
ON DUPLICATE KEY UPDATE
  game_date = VALUES(game_date),
  home_name = VALUES(home_name),
  visit_name = VALUES(visit_name),
  home_team_name_abbr = VALUES(home_team_name_abbr),
  visit_team_name_abbr = VALUES(visit_team_name_abbr),
  `type` = VALUES(`type`),
  home_team_id = VALUES(home_team_id),
  visit_team_id = VALUES(visit_team_id),
  source_home_team_name = VALUES(source_home_team_name),
  source_visit_team_name = VALUES(source_visit_team_name),
  season_year = VALUES(season_year),
  season_type = VALUES(season_type),
  game_status = VALUES(game_status),
  game_status_text = VALUES(game_status_text),
  game_time_utc = VALUES(game_time_utc),
  game_time_eastern = VALUES(game_time_eastern),
  raw_json = VALUES(raw_json),
  updated_at = CURRENT_TIMESTAMP
""".strip()


def upsert_nba_store_game_records(db: Session, records: list[NbaStoreGameRecord]) -> int:
    if not records:
        return 0

    params_list = [
        {
            "id": uuid.uuid4().hex,
            "game_id": record.game_id,
            "game_date": record.game_date,
            "home_name": record.home_name,
            "visit_name": record.visit_name,
            "home_team_name_abbr": record.home_team_name_abbr,
            "visit_team_name_abbr": record.visit_team_name_abbr,
            "type": record.type,
            "home_team_id": record.home_team_id,
            "visit_team_id": record.visit_team_id,
            "source_home_team_name": record.source_home_team_name,
            "source_visit_team_name": record.source_visit_team_name,
            "season_year": record.season_year,
            "season_type": record.season_type,
            "game_status": record.game_status,
            "game_status_text": record.game_status_text,
            "game_time_utc": record.game_time_utc,
            "game_time_eastern": record.game_time_eastern,
            "raw_json": record.raw_json,
        }
        for record in records
    ]
    db.execute(text(_SQL_UPSERT), params_list)
    db.commit()
    return len(params_list)


def fetch_nba_store_game_payload(http_client: HttpClient, *, game_date: date) -> Any:
    return http_client.get_json(
        NBA_STORE_GAMECARD_FEED_URL,
        params=build_nba_store_game_params(game_date=game_date),
        headers=build_nba_store_game_headers(),
    )


def sync_nba_store_game_list(db: Session, http_client: HttpClient, *, game_date: date) -> dict[str, int | str]:
    payload = fetch_nba_store_game_payload(http_client=http_client, game_date=game_date)
    team_names_by_code = load_team_names_by_code(db=db)
    records = parse_nba_store_game_list(
        payload,
        game_date=game_date,
        team_names_by_code=team_names_by_code,
    )
    ensure_nba_store_game_list_table(db=db)
    upserted = upsert_nba_store_game_records(db=db, records=records)
    return {
        "game_date": game_date.isoformat(),
        "games": len(records),
        "upserted": upserted,
    }
