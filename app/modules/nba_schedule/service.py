from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.modules.nba_schedule.parser import ParsedGame, parse_schedule


def save_schedule_raw(db: Session, source: str, season: str, payload: Any) -> int:
    raw_json = json.dumps(payload, ensure_ascii=False)
    result = db.execute(
        text(
            """
            INSERT INTO nba_schedule_raw (source, season, fetched_at, raw_json)
            VALUES (:source, :season, :fetched_at, CAST(:raw_json AS JSON))
            """
        ),
        {"source": source, "season": season, "fetched_at": datetime.now(timezone.utc), "raw_json": raw_json},
    )
    db.commit()
    return int(getattr(result, "lastrowid", 0) or 0)


def upsert_game_by_abbr(db: Session, game: ParsedGame) -> None:
    team_ids = db.execute(
        text(
            """
            SELECT id, abbreviation
            FROM nba_team
            WHERE abbreviation IN (:home, :away)
            """
        ),
        {"home": game.home_abbr, "away": game.away_abbr},
    ).fetchall()

    abbr_to_id = {row.abbreviation: row.id for row in team_ids}
    home_id = abbr_to_id.get(game.home_abbr)
    away_id = abbr_to_id.get(game.away_abbr)
    if not home_id or not away_id:
        return

    db.execute(
        text(
            """
            INSERT INTO nba_game (season, game_date, home_team_id, away_team_id, status)
            VALUES (:season, :game_date, :home_team_id, :away_team_id, :status)
            ON DUPLICATE KEY UPDATE
              status = VALUES(status),
              updated_at = CURRENT_TIMESTAMP
            """
        ),
        {
            "season": game.season,
            "game_date": game.game_date,
            "home_team_id": home_id,
            "away_team_id": away_id,
            "status": "scheduled",
        },
    )
    db.commit()


def ingest_schedule(db: Session, source: str, season: str, payload: Any) -> list[ParsedGame]:
    save_schedule_raw(db=db, source=source, season=season, payload=payload)
    parsed = parse_schedule(payload=payload, season=season)
    for game in parsed:
        upsert_game_by_abbr(db=db, game=game)
    return parsed
