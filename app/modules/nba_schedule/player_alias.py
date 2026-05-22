from __future__ import annotations

import json
import random
import re
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.http_resources import QIUMIBAO_PLAYER_ALIAS_BASE_URL, build_player_alias_headers
from app.utils.http.client import HttpClient

PLAYER_ALIAS_DEFAULT_TYPE = "NBA"


@dataclass(frozen=True)
class MatchAliasSource:
    saishi_id: str
    game_date: date


@dataclass(frozen=True)
class PlayerAliasRecord:
    player_id: str
    alias_name: str


def build_player_alias_url(game_date: date, saishi_id: str) -> str:
    return f"{QIUMIBAO_PLAYER_ALIAS_BASE_URL}/{game_date.isoformat()}/player_{saishi_id}.htm"


def build_player_alias_params() -> dict[str, str]:
    return {"get": str(random.random())}


def iter_candidate_game_dates(game_date: date) -> list[date]:
    # 别名源偶发存在比赛日期偏移，按原日期优先，再尝试前后一天补偿。
    candidates: list[date] = []
    for offset in (0, -1, 1):
        candidate = game_date + timedelta(days=offset)
        if candidate not in candidates:
            candidates.append(candidate)
    return candidates


def list_alias_match_sources(db: Session, saishi_id: str | None = None) -> list[MatchAliasSource]:
    sql = """
        SELECT saishi_id, game_date
        FROM nba_zhiboba_yj_gamelist
        WHERE saishi_id IS NOT NULL
          AND game_date IS NOT NULL
    """
    params: dict[str, Any] = {}
    if saishi_id is not None:
        sql += " AND saishi_id = :saishi_id"
        params["saishi_id"] = saishi_id
    sql += " ORDER BY game_date DESC, saishi_id DESC"

    rows = db.execute(text(sql), params).fetchall()
    matches: list[MatchAliasSource] = []
    for row in rows:
        match_saishi_id = getattr(row, "saishi_id", None)
        match_game_date = getattr(row, "game_date", None)
        if not isinstance(match_saishi_id, str) or not match_saishi_id.strip():
            continue
        if not isinstance(match_game_date, date):
            continue
        matches.append(MatchAliasSource(saishi_id=match_saishi_id.strip(), game_date=match_game_date))
    return matches


def _collect_alias_records(data: Any, seen: set[tuple[str, str]], records: list[PlayerAliasRecord]) -> None:
    if isinstance(data, dict):
        player_id = data.get("player_id")
        alias_name = data.get("player_name_cn")
        if isinstance(player_id, (str, int)) and isinstance(alias_name, str):
            normalized_player_id = str(player_id).strip()
            normalized_alias_name = alias_name.strip()
            if normalized_player_id and normalized_alias_name:
                key = (normalized_player_id, normalized_alias_name)
                if key not in seen:
                    seen.add(key)
                    records.append(PlayerAliasRecord(player_id=normalized_player_id, alias_name=normalized_alias_name))

        for value in data.values():
            _collect_alias_records(value, seen=seen, records=records)
        return

    if isinstance(data, list):
        for item in data:
            _collect_alias_records(item, seen=seen, records=records)


def parse_player_alias_payload(payload: Any) -> list[PlayerAliasRecord]:
    records: list[PlayerAliasRecord] = []
    _collect_alias_records(payload, seen=set(), records=records)
    return records


def parse_player_alias_response(content: str) -> list[PlayerAliasRecord]:
    stripped = content.strip()
    if not stripped:
        return []

    candidates = [stripped]
    match = re.search(r"(\{[\s\S]*\}|\[[\s\S]*\])", stripped)
    if match:
        candidates.append(match.group(1))

    for candidate in candidates:
        try:
            payload = json.loads(candidate)
            return parse_player_alias_payload(payload)
        except json.JSONDecodeError:
            continue

    return []


_DDL_CREATE_PLAYER_ALIAS_TABLE = """
CREATE TABLE IF NOT EXISTS player_alias_name_info (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  player_id VARCHAR(50) NOT NULL,
  alias_name VARCHAR(128) NOT NULL,
  type VARCHAR(20) NOT NULL DEFAULT 'NBA',
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uk_player_alias (player_id, alias_name),
  KEY idx_player_id (player_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
""".strip()


_DDL_ADD_PLAYER_ALIAS_TYPE_COLUMN = """
ALTER TABLE player_alias_name_info
ADD COLUMN type VARCHAR(20) NOT NULL DEFAULT 'NBA' AFTER alias_name
""".strip()

_DDL_ADD_PLAYER_ALIAS_CREATED_AT_COLUMN = """
ALTER TABLE player_alias_name_info
ADD COLUMN created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP AFTER type
""".strip()

_DDL_ADD_PLAYER_ALIAS_UPDATED_AT_COLUMN = """
ALTER TABLE player_alias_name_info
ADD COLUMN updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP AFTER created_at
""".strip()

_DDL_ADD_PLAYER_ALIAS_UNIQUE_KEY = """
ALTER TABLE player_alias_name_info
ADD UNIQUE KEY uk_player_alias (player_id, alias_name)
""".strip()

_DDL_ADD_PLAYER_ALIAS_PLAYER_ID_INDEX = """
ALTER TABLE player_alias_name_info
ADD KEY idx_player_id (player_id)
""".strip()


_SQL_BACKFILL_PLAYER_ALIAS_TYPE = """
UPDATE player_alias_name_info
SET type = :type
WHERE type IS NULL OR TRIM(type) = ''
""".strip()


def has_player_alias_type_column(db: Session) -> bool:
    return has_player_alias_column(db=db, column_name="type")


def has_player_alias_column(db: Session, column_name: str) -> bool:
    row = db.execute(
        text(
            """
            SELECT 1
            FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE()
              AND TABLE_NAME = 'player_alias_name_info'
              AND COLUMN_NAME = :column_name
            LIMIT 1
            """
        ),
        {"column_name": column_name},
    ).fetchone()
    return row is not None


def has_player_alias_index(db: Session, index_name: str) -> bool:
    row = db.execute(
        text(
            """
            SELECT 1
            FROM information_schema.STATISTICS
            WHERE TABLE_SCHEMA = DATABASE()
              AND TABLE_NAME = 'player_alias_name_info'
              AND INDEX_NAME = :index_name
            LIMIT 1
            """
        ),
        {"index_name": index_name},
    ).fetchone()
    return row is not None


def ensure_player_alias_table(db: Session) -> None:
    db.execute(text(_DDL_CREATE_PLAYER_ALIAS_TABLE))
    if not has_player_alias_column(db=db, column_name="type"):
        db.execute(text(_DDL_ADD_PLAYER_ALIAS_TYPE_COLUMN))
    if not has_player_alias_column(db=db, column_name="created_at"):
        db.execute(text(_DDL_ADD_PLAYER_ALIAS_CREATED_AT_COLUMN))
    if not has_player_alias_column(db=db, column_name="updated_at"):
        db.execute(text(_DDL_ADD_PLAYER_ALIAS_UPDATED_AT_COLUMN))
    if not has_player_alias_index(db=db, index_name="uk_player_alias"):
        db.execute(text(_DDL_ADD_PLAYER_ALIAS_UNIQUE_KEY))
    if not has_player_alias_index(db=db, index_name="idx_player_id"):
        db.execute(text(_DDL_ADD_PLAYER_ALIAS_PLAYER_ID_INDEX))
    db.execute(text(_SQL_BACKFILL_PLAYER_ALIAS_TYPE), {"type": PLAYER_ALIAS_DEFAULT_TYPE})
    db.commit()


_SQL_INSERT_PLAYER_ALIAS = """
INSERT INTO player_alias_name_info (player_id, alias_name, type)
VALUES (:player_id, :alias_name, :type)
ON DUPLICATE KEY UPDATE
  type = VALUES(type),
  updated_at = CURRENT_TIMESTAMP
""".strip()


def upsert_player_alias_records(db: Session, records: list[PlayerAliasRecord]) -> int:
    if not records:
        return 0

    inserted = 0
    for record in records:
        db.execute(
            text(_SQL_INSERT_PLAYER_ALIAS),
            {
                "player_id": record.player_id,
                "alias_name": record.alias_name,
                "type": PLAYER_ALIAS_DEFAULT_TYPE,
            },
        )
        inserted += 1
    db.commit()
    return inserted


def fetch_player_alias_records(http_client: HttpClient, source: MatchAliasSource) -> list[PlayerAliasRecord]:
    last_status: int | None = None
    for candidate_game_date in iter_candidate_game_dates(source.game_date):
        status, content = http_client.get_text_with_status(
            build_player_alias_url(game_date=candidate_game_date, saishi_id=source.saishi_id),
            params=build_player_alias_params(),
            headers=build_player_alias_headers(),
            allow_status_codes={404},
        )
        last_status = status
        if status == 404:
            continue

        records = parse_player_alias_response(content)
        if records:
            return records

    if last_status == 404:
        return []
    return []


def sync_player_aliases(
    db: Session, http_client: HttpClient, saishi_id: str | None = None
) -> dict[str, int | list[dict[str, str]] | str | None]:
    sources = list_alias_match_sources(db=db, saishi_id=saishi_id)
    ensure_player_alias_table(db=db)

    success_matches = 0
    failed_matches = 0
    total_aliases = 0
    total_upserted = 0
    failures: list[dict[str, str]] = []

    for source in sources:
        try:
            records = fetch_player_alias_records(http_client=http_client, source=source)
            upserted = upsert_player_alias_records(db=db, records=records)
            success_matches += 1
            total_aliases += len(records)
            total_upserted += upserted
        except Exception as exc:
            failed_matches += 1
            failures.append(
                {
                    "saishi_id": source.saishi_id,
                    "game_date": source.game_date.isoformat(),
                    "error": str(exc),
                }
            )

    return {
        "saishi_id": saishi_id,
        "matches": len(sources),
        "success_matches": success_matches,
        "failed_matches": failed_matches,
        "aliases": total_aliases,
        "upserted": total_upserted,
        "failures": failures,
    }
