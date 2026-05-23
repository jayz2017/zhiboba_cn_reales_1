from __future__ import annotations

from dataclasses import dataclass
from datetime import date, time, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.http_resources import QIUMIBAO_TEAM_RANKING_API_URL, build_team_ranking_headers
from app.utils.db_helpers import to_int, to_decimal
from app.utils.http.client import HttpClient


GAME_LIST_DEFAULT_TYPE = "NBA"


@dataclass(frozen=True)
class GameListRecord:
    id: str
    home_team: str
    visit_team: str
    home_id: str
    guest_id: str
    home_ls: int | None = None
    guest_ls: int | None = None
    guest_play_off_win: int | None = None
    guest_rank: int | None = None
    guest_win_diff: Decimal | None = None
    guest_win_or_filr: str | None = None
    guest_win_rate: Decimal | None = None
    guest_zone: int | None = None
    home_play_off_win: int | None = None
    home_rank: int | None = None
    home_win_diff: Decimal | None = None
    home_win_or_filr: str | None = None
    home_win_rate: Decimal | None = None
    home_zone: int | None = None
    period_cn: str | None = None
    create_date: object | None = None
    end_date: date | None = None
    season_type: str = ""
    sdate: date | None = None
    start: time | None = None
    current_time: str | None = None
    type: str = GAME_LIST_DEFAULT_TYPE


@dataclass(frozen=True)
class TeamRankingRecord:
    team_id: str
    team_name: str
    rank: int | None
    wins: int | None
    losses: int | None
    win_rate: Decimal | None
    recent_form: str | None
    wins_losses_text: str | None
    win_diff: Decimal | None
    zone: int | None


_DDL_CREATE_GAME_LIST_TABLE = """
CREATE TABLE IF NOT EXISTS game_list (
  id VARCHAR(32) NOT NULL,
  home_team VARCHAR(64) NULL,
  visit_team VARCHAR(64) NULL,
  home_id VARCHAR(32) NULL,
  guest_id VARCHAR(32) NULL,
  home_ls INT NULL,
  guest_ls INT NULL,
  guest_play_off_win INT NULL,
  guest_rank INT NULL,
  guest_win_diff DECIMAL(5,2) NULL,
  guest_win_or_filr VARCHAR(32) NULL,
  guest_win_rate DECIMAL(5,1) NULL,
  guest_zone INT NULL,
  home_play_off_win INT NULL,
  home_rank INT NULL,
  home_win_diff DECIMAL(5,2) NULL,
  home_win_or_filr VARCHAR(32) NULL,
  home_win_rate DECIMAL(5,1) NULL,
  home_zone INT NULL,
  period_cn VARCHAR(64) NULL,
  create_date TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP,
  end_date DATE NULL,
  season_type VARCHAR(128) NULL,
  sdate DATE NULL,
  `start` TIME NULL,
  `time` VARCHAR(32) NULL,
  type VARCHAR(32) NOT NULL DEFAULT 'NBA',
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_sdate (sdate)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
""".strip()


_ALTER_GAME_LIST_COLUMNS = {
    "home_id": "ALTER TABLE game_list ADD COLUMN home_id VARCHAR(32) NULL AFTER visit_team",
    "guest_id": "ALTER TABLE game_list ADD COLUMN guest_id VARCHAR(32) NULL AFTER home_id",
    "home_ls": "ALTER TABLE game_list ADD COLUMN home_ls INT NULL AFTER guest_id",
    "guest_ls": "ALTER TABLE game_list ADD COLUMN guest_ls INT NULL AFTER home_ls",
    "guest_play_off_win": "ALTER TABLE game_list ADD COLUMN guest_play_off_win INT NULL AFTER guest_ls",
    "guest_rank": "ALTER TABLE game_list ADD COLUMN guest_rank INT NULL AFTER guest_play_off_win",
    "guest_win_diff": "ALTER TABLE game_list ADD COLUMN guest_win_diff DECIMAL(5,2) NULL AFTER guest_rank",
    "guest_win_or_filr": "ALTER TABLE game_list ADD COLUMN guest_win_or_filr VARCHAR(32) NULL AFTER guest_win_diff",
    "guest_win_rate": "ALTER TABLE game_list ADD COLUMN guest_win_rate DECIMAL(5,1) NULL AFTER guest_win_or_filr",
    "guest_zone": "ALTER TABLE game_list ADD COLUMN guest_zone INT NULL AFTER guest_win_rate",
    "home_play_off_win": "ALTER TABLE game_list ADD COLUMN home_play_off_win INT NULL AFTER guest_zone",
    "home_rank": "ALTER TABLE game_list ADD COLUMN home_rank INT NULL AFTER home_play_off_win",
    "home_win_diff": "ALTER TABLE game_list ADD COLUMN home_win_diff DECIMAL(5,2) NULL AFTER home_rank",
    "home_win_or_filr": "ALTER TABLE game_list ADD COLUMN home_win_or_filr VARCHAR(32) NULL AFTER home_win_diff",
    "home_win_rate": "ALTER TABLE game_list ADD COLUMN home_win_rate DECIMAL(5,1) NULL AFTER home_win_or_filr",
    "home_zone": "ALTER TABLE game_list ADD COLUMN home_zone INT NULL AFTER home_win_rate",
    "period_cn": "ALTER TABLE game_list ADD COLUMN period_cn VARCHAR(64) NULL AFTER home_zone",
    "create_date": "ALTER TABLE game_list ADD COLUMN create_date TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP AFTER period_cn",
    "end_date": "ALTER TABLE game_list ADD COLUMN end_date DATE NULL AFTER create_date",
    "time": "ALTER TABLE game_list ADD COLUMN `time` VARCHAR(32) NULL AFTER `start`",
}


_SQL_SELECT_GAME_LIST_SOURCE = """
SELECT
  schedule.saishi_id,
  schedule.game_date,
  schedule.start_time,
  schedule.home_id,
  schedule.guest_id,
  schedule.event_name,
  schedule.created_at,
  home_team.team_name AS home_team_name,
  guest_team.team_name AS guest_team_name
FROM nba_zhiboba_yj_gamelist AS schedule
LEFT JOIN nba_teams_name_data AS home_team
  ON schedule.home_id = home_team.zhiboba_team_id
LEFT JOIN nba_teams_name_data AS guest_team
  ON schedule.guest_id = guest_team.zhiboba_team_id
WHERE schedule.game_date = :game_date
ORDER BY schedule.start_time ASC, schedule.saishi_id ASC
""".strip()


_SQL_UPSERT_GAME_LIST = """
INSERT INTO game_list (
  id, home_team, visit_team, home_id, guest_id,
  home_ls, guest_ls, guest_play_off_win, guest_rank, guest_win_diff, guest_win_or_filr, guest_win_rate, guest_zone,
  home_play_off_win, home_rank, home_win_diff, home_win_or_filr, home_win_rate, home_zone,
  period_cn, create_date, end_date, season_type, sdate, `start`, `time`, type
)
VALUES (
  :id, :home_team, :visit_team, :home_id, :guest_id,
  :home_ls, :guest_ls, :guest_play_off_win, :guest_rank, :guest_win_diff, :guest_win_or_filr, :guest_win_rate, :guest_zone,
  :home_play_off_win, :home_rank, :home_win_diff, :home_win_or_filr, :home_win_rate, :home_zone,
  :period_cn, :create_date, :end_date, :season_type, :sdate, :start, :current_time, :type
)
ON DUPLICATE KEY UPDATE
  home_team = VALUES(home_team),
  visit_team = VALUES(visit_team),
  home_id = VALUES(home_id),
  guest_id = VALUES(guest_id),
  home_ls = VALUES(home_ls),
  guest_ls = VALUES(guest_ls),
  guest_play_off_win = VALUES(guest_play_off_win),
  guest_rank = VALUES(guest_rank),
  guest_win_diff = VALUES(guest_win_diff),
  guest_win_or_filr = VALUES(guest_win_or_filr),
  guest_win_rate = VALUES(guest_win_rate),
  guest_zone = VALUES(guest_zone),
  home_play_off_win = VALUES(home_play_off_win),
  home_rank = VALUES(home_rank),
  home_win_diff = VALUES(home_win_diff),
  home_win_or_filr = VALUES(home_win_or_filr),
  home_win_rate = VALUES(home_win_rate),
  home_zone = VALUES(home_zone),
  period_cn = VALUES(period_cn),
  create_date = VALUES(create_date),
  end_date = VALUES(end_date),
  season_type = VALUES(season_type),
  sdate = VALUES(sdate),
  `start` = VALUES(`start`),
  `time` = VALUES(`time`),
  type = VALUES(type),
  updated_at = CURRENT_TIMESTAMP
""".strip()


_game_list_table_ensured = False


def ensure_game_list_table(db: Session) -> None:
    global _game_list_table_ensured
    if _game_list_table_ensured:
        return
    db.execute(text(_DDL_CREATE_GAME_LIST_TABLE))
    for column_name, alter_sql in _ALTER_GAME_LIST_COLUMNS.items():
        row = db.execute(
            text(
                """
                SELECT 1
                FROM information_schema.COLUMNS
                WHERE TABLE_SCHEMA = DATABASE()
                  AND TABLE_NAME = 'game_list'
                  AND COLUMN_NAME = :column_name
                LIMIT 1
                """
            ),
            {"column_name": column_name},
        ).fetchone()
        if row is None:
            db.execute(text(alter_sql))
    db.execute(text("ALTER TABLE game_list MODIFY COLUMN guest_win_rate DECIMAL(5,1) NULL"))
    db.execute(text("ALTER TABLE game_list MODIFY COLUMN home_win_rate DECIMAL(5,1) NULL"))
    db.commit()
    _game_list_table_ensured = True


def normalize_start_time(value: object) -> time | None:
    if isinstance(value, time):
        return value
    if isinstance(value, timedelta):
        total_seconds = int(value.total_seconds())
        if total_seconds < 0:
            return None
        hours = (total_seconds // 3600) % 24
        minutes = (total_seconds % 3600) // 60
        seconds = total_seconds % 60
        return time(hour=hours, minute=minutes, second=seconds)
    return None


def _to_win_rate_decimal(value: Any) -> Decimal | None:
    decimal_value = to_decimal(value)
    if decimal_value is None:
        return None
    return decimal_value.quantize(Decimal("0.1"))


def _normalize_team_name(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return value.replace("*", "").strip()


def _parse_zone_code(section_title: Any) -> int | None:
    if not isinstance(section_title, str):
        return None
    normalized = section_title.strip()
    if "东" in normalized:
        return 1
    if "西" in normalized:
        return 2
    return None


def derive_ranking_year(game_date: date) -> int:
    return game_date.year - 1 if game_date.month < 9 else game_date.year


def build_team_ranking_params(*, game_date: date) -> dict[str, str]:
    return {
        "_url": "/data/index",
        "year": str(derive_ranking_year(game_date)),
        "type": "排行",
        "tab": "排行",
        "league_id": "924",
        "league": "NBA",
        "_platform": "web",
        "_env": "pc",
    }


def parse_team_ranking_payload(payload: Any) -> dict[str, TeamRankingRecord]:
    if not isinstance(payload, dict):
        return {}
    data = payload.get("data")
    if not isinstance(data, list):
        return {}

    result: dict[str, TeamRankingRecord] = {}
    for section in data:
        if not isinstance(section, dict):
            continue
        zone_code = _parse_zone_code(section.get("title"))
        rows = section.get("list")
        if not isinstance(rows, list):
            continue
        for item in rows:
            if not isinstance(item, dict):
                continue
            team_id = item.get("teamId")
            if not isinstance(team_id, str) or not team_id.strip():
                continue
            normalized_team_id = team_id.strip()
            result[normalized_team_id] = TeamRankingRecord(
                team_id=normalized_team_id,
                team_name=_normalize_team_name(item.get("球队名称") or item.get("球队")),
                rank=to_int(item.get("排名")),
                wins=to_int(item.get("胜")),
                losses=to_int(item.get("负")),
                win_rate=_to_win_rate_decimal(item.get("胜率")),
                recent_form=item.get("近况").strip() if isinstance(item.get("近况"), str) and item.get("近况").strip() else None,
                wins_losses_text=item.get("胜/负").strip() if isinstance(item.get("胜/负"), str) and item.get("胜/负").strip() else None,
                win_diff=to_decimal(item.get("胜差")),
                zone=zone_code,
            )
    return result


def fetch_team_rankings(http_client: HttpClient, *, game_date: date) -> dict[str, TeamRankingRecord]:
    payload = http_client.get_json(
        QIUMIBAO_TEAM_RANKING_API_URL,
        params=build_team_ranking_params(game_date=game_date),
        headers=build_team_ranking_headers(),
    )
    return parse_team_ranking_payload(payload)


def list_game_list_source_records(
    db: Session,
    *,
    game_date: date,
    rankings: dict[str, TeamRankingRecord] | None = None,
) -> list[GameListRecord]:
    rankings = rankings or {}
    rows = db.execute(text(_SQL_SELECT_GAME_LIST_SOURCE), {"game_date": game_date}).fetchall()
    records: list[GameListRecord] = []
    for row in rows:
        saishi_id = getattr(row, "saishi_id", None)
        home_team_name = getattr(row, "home_team_name", None)
        guest_team_name = getattr(row, "guest_team_name", None)
        home_id = getattr(row, "home_id", None)
        guest_id = getattr(row, "guest_id", None)
        event_name = getattr(row, "event_name", None)
        row_game_date = getattr(row, "game_date", None)
        row_start_time = getattr(row, "start_time", None)
        row_created_at = getattr(row, "created_at", None)

        if not isinstance(saishi_id, str) or not saishi_id.strip():
            continue
        if not isinstance(row_game_date, date):
            continue

        normalized_home_id = home_id.strip() if isinstance(home_id, str) else ""
        normalized_guest_id = guest_id.strip() if isinstance(guest_id, str) else ""
        home_ranking = rankings.get(normalized_home_id)
        guest_ranking = rankings.get(normalized_guest_id)

        records.append(
            GameListRecord(
                id=saishi_id.strip(),
                home_team=home_ranking.team_name if home_ranking and home_ranking.team_name else (home_team_name.strip() if isinstance(home_team_name, str) else ""),
                visit_team=guest_ranking.team_name if guest_ranking and guest_ranking.team_name else (guest_team_name.strip() if isinstance(guest_team_name, str) else ""),
                home_id=normalized_home_id,
                guest_id=normalized_guest_id,
                home_ls=home_ranking.rank if home_ranking else None,
                guest_ls=guest_ranking.rank if guest_ranking else None,
                guest_play_off_win=None,
                guest_rank=guest_ranking.rank if guest_ranking else None,
                guest_win_diff=guest_ranking.win_diff if guest_ranking else None,
                guest_win_or_filr=guest_ranking.recent_form if guest_ranking else None,
                guest_win_rate=guest_ranking.win_rate if guest_ranking else None,
                guest_zone=guest_ranking.zone if guest_ranking else None,
                home_play_off_win=None,
                home_rank=home_ranking.rank if home_ranking else None,
                home_win_diff=home_ranking.win_diff if home_ranking else None,
                home_win_or_filr=home_ranking.recent_form if home_ranking else None,
                home_win_rate=home_ranking.win_rate if home_ranking else None,
                home_zone=home_ranking.zone if home_ranking else None,
                season_type=event_name.strip() if isinstance(event_name, str) else "",
                sdate=row_game_date,
                start=normalize_start_time(row_start_time),
                create_date=row_created_at,
                current_time=None,
            )
        )
    return records


def upsert_game_list_records(db: Session, records: list[GameListRecord]) -> int:
    if not records:
        return 0

    params_list = [
        {
            "id": record.id,
            "home_team": record.home_team,
            "visit_team": record.visit_team,
            "home_id": record.home_id,
            "guest_id": record.guest_id,
            "home_ls": record.home_ls,
            "guest_ls": record.guest_ls,
            "guest_play_off_win": record.guest_play_off_win,
            "guest_rank": record.guest_rank,
            "guest_win_diff": record.guest_win_diff,
            "guest_win_or_filr": record.guest_win_or_filr,
            "guest_win_rate": record.guest_win_rate,
            "guest_zone": record.guest_zone,
            "home_play_off_win": record.home_play_off_win,
            "home_rank": record.home_rank,
            "home_win_diff": record.home_win_diff,
            "home_win_or_filr": record.home_win_or_filr,
            "home_win_rate": record.home_win_rate,
            "home_zone": record.home_zone,
            "period_cn": record.period_cn,
            "create_date": record.create_date,
            "end_date": record.end_date,
            "season_type": record.season_type,
            "sdate": record.sdate,
            "start": record.start,
            "current_time": record.current_time,
            "type": record.type,
        }
        for record in records
    ]
    db.execute(text(_SQL_UPSERT_GAME_LIST), params_list)
    db.commit()
    return len(params_list)


def sync_game_list_by_date(db: Session, http_client: HttpClient, *, game_date: date) -> dict[str, int | str]:
    ensure_game_list_table(db=db)
    rankings = fetch_team_rankings(http_client=http_client, game_date=game_date)
    records = list_game_list_source_records(db=db, game_date=game_date, rankings=rankings)
    upserted = upsert_game_list_records(db=db, records=records)
    return {
        "game_date": game_date.isoformat(),
        "games": len(records),
        "upserted": upserted,
    }
