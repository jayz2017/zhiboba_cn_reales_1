import re
import json
import random
from typing import Any
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.http_resources import ZHIBO8_TEAM_DATA_API_URL, build_team_player_headers
from app.utils.http.client import HttpClient

@dataclass
class ZhibobaTeamPlayerRecord:
    team_id: str
    team_name: str
    zhiboba_player_id: str
    zhiboba_player_name: str
    zhiboba_jersey_number: str
    player_code: str | None
    player_salary: float | None
    position_name: str


@dataclass(frozen=True)
class TeamIdMapping:
    team_id: str
    zhiboba_team_id: str
    team_name: str | None = None


def get_nba_team_type_column(db: Session) -> str:
    row = db.execute(
        text(
            """
            SELECT COLUMN_NAME AS column_name
            FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE()
              AND TABLE_NAME = 'nba_teams_name_data'
              AND COLUMN_NAME IN ( 'team_type')
            ORDER BY CASE WHEN COLUMN_NAME = 'type' THEN 0 ELSE 1 END
            LIMIT 1
            """
        )
    ).fetchone()

    column_name = getattr(row, "column_name", None)
    if isinstance(column_name, str) and column_name.strip():
        return column_name.strip()
    return "team_type"


def build_nba_team_filter_sql(db: Session) -> str:
    team_type_column = get_nba_team_type_column(db=db)
    return f"UPPER(TRIM(`{team_type_column}`)) = 'NBA'"

def build_team_player_params(team_id: str) -> dict[str, str]:
    return {
        "_url": "/nba_v2/team",
        "random": str(random.random()),
        "teamId": team_id
    }


def build_player_detail_params(player_id: str) -> dict[str, str]:
    return {
        "_url": "/nba_v2_player/player",
        "playerId": player_id,
    }

def _find_first_str_value(data: Any, target_key: str) -> str | None:
    if isinstance(data, dict):
        for key, value in data.items():
            if key == target_key and isinstance(value, str) and value.strip():
                return value.strip()
            nested_value = _find_first_str_value(value, target_key)
            if nested_value:
                return nested_value
    elif isinstance(data, list):
        for item in data:
            nested_value = _find_first_str_value(item, target_key)
            if nested_value:
                return nested_value
    return None

def _parse_salary(salary_str: str) -> float | None:
    if not salary_str or salary_str == "-":
        return None
    # 移除 $ 和 , 提取数字
    cleaned = salary_str.replace("$", "").replace(",", "").strip()
    try:
        return float(cleaned)
    except ValueError:
        return None


def _normalize_player_name(player_name: Any) -> str:
    if not isinstance(player_name, str):
        return ""
    normalized = re.sub(r"\s+", "", player_name.strip())
    return normalized.replace(".", "").replace("·", "")



def parse_team_players(payload: dict) -> list[ZhibobaTeamPlayerRecord]:
    data = payload.get("data", {})
    if not data:
        return []

    team_info = data.get("team", {})
    team_id = team_info.get("teamId", "")
    team_name = team_info.get("teamName", "")
    
    player_data = data.get("player", {})
    player_info = player_data.get("info", {})
    player_list = player_info.get("list", [])
    
    records = []
    for item in player_list:
        if not isinstance(item, dict):
            continue
            
        zhiboba_player_id = item.get("playerId")
        if not zhiboba_player_id:
            continue
            
        zhiboba_player_name = _normalize_player_name(item.get("球员", item.get("姓名", "")))
        zhiboba_jersey_number = item.get("球号", "")
        position_name = item.get("位置", "")
        
        salary_str = item.get("当赛季薪资", "")
        player_salary = _parse_salary(salary_str)
        
        records.append(
            ZhibobaTeamPlayerRecord(
                team_id=str(team_id),
                team_name=str(team_name),
                zhiboba_player_id=str(zhiboba_player_id),
                zhiboba_player_name=str(zhiboba_player_name),
                zhiboba_jersey_number=str(zhiboba_jersey_number),
                player_code=None,
                player_salary=player_salary,
                position_name=str(position_name)
            )
        )
        
    return records


def fetch_player_code(http_client: HttpClient, player_id: str) -> str | None:
    payload = http_client.get_json(
        ZHIBO8_TEAM_DATA_API_URL,
        params=build_player_detail_params(player_id=player_id),
        headers=build_team_player_headers(),
    )
    return _find_first_str_value(payload, "playerCode")


def enrich_players_with_player_code(
    records: list[ZhibobaTeamPlayerRecord], http_client: HttpClient
) -> list[ZhibobaTeamPlayerRecord]:
    for record in records:
        try:
            record.player_code = fetch_player_code(http_client=http_client, player_id=record.zhiboba_player_id)
        except Exception:
            record.player_code = None
    return records

_DDL_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS nba_players_name_data (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  team_id VARCHAR(32) NULL,
  team_name VARCHAR(50) NULL,
  player_id VARCHAR(50) NULL,
  zhiboba_player_id VARCHAR(50) NOT NULL,
  hu_pu_player_id VARCHAR(50) NULL,
  en_player_name VARCHAR(128) NULL,
  nba_player_name VARCHAR(128) NULL,
  zhiboba_player_name VARCHAR(128) NULL,
  player_name_alias VARCHAR(128) NULL,
  nba_jersey_number VARCHAR(16) NULL,
  zhiboba_jersey_number VARCHAR(16) NULL,
  player_code VARCHAR(50) NULL,
  player_salary DECIMAL(15,2) NULL,
  position_name VARCHAR(64) NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uk_zhiboba_player_id (zhiboba_player_id),
  UNIQUE KEY uk_player_id (player_id),
  KEY idx_team_id (team_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
""".strip()

def ensure_players_table(db: Session) -> None:
    db.execute(text(_DDL_CREATE_TABLE))
    db.commit()

_SQL_UPSERT = """
INSERT INTO nba_players_name_data
  (team_id, team_name, zhiboba_player_id, zhiboba_player_name, zhiboba_jersey_number, player_code, player_salary, position_name)
VALUES
  (:team_id, :team_name, :zhiboba_player_id, :zhiboba_player_name, :zhiboba_jersey_number, :player_code, :player_salary, :position_name)
ON DUPLICATE KEY UPDATE
  team_id = VALUES(team_id),
  team_name = VALUES(team_name),
  zhiboba_player_name = VALUES(zhiboba_player_name),
  zhiboba_jersey_number = VALUES(zhiboba_jersey_number),
  player_code = VALUES(player_code),
  player_salary = VALUES(player_salary),
  position_name = VALUES(position_name),
  updated_at = CURRENT_TIMESTAMP;
""".strip()

def upsert_team_players(db: Session, records: list[ZhibobaTeamPlayerRecord]) -> int:
    if not records:
        return 0

    inserted = 0
    for r in records:
        db.execute(
            text(_SQL_UPSERT),
            {
                "team_id": r.team_id,
                "team_name": r.team_name,
                "zhiboba_player_id": r.zhiboba_player_id,
                "zhiboba_player_name": r.zhiboba_player_name,
                "zhiboba_jersey_number": r.zhiboba_jersey_number,
                "player_code": r.player_code,
                "player_salary": r.player_salary,
                "position_name": r.position_name,
            },
        )
        inserted += 1

    db.commit()
    return inserted


def get_zhiboba_team_id_by_team_id(db: Session, team_id: str) -> TeamIdMapping | None:
    team_filter_sql = build_nba_team_filter_sql(db=db)
    row = db.execute(
        text(
            f"""
            SELECT team_id, zhiboba_team_id, team_name
            FROM nba_teams_name_data
            WHERE {team_filter_sql} AND team_id = :team_id
            LIMIT 1
            """
        ),
        {"team_id": team_id},
    ).fetchone()

    if not row:
        return None

    mapped_team_id = getattr(row, "team_id", None)
    zhiboba_team_id = getattr(row, "zhiboba_team_id", None)
    team_name = getattr(row, "team_name", None)
    if not isinstance(mapped_team_id, str) or not mapped_team_id.strip():
        return None
    if not isinstance(zhiboba_team_id, str) or not zhiboba_team_id.strip():
        return None

    return TeamIdMapping(
        team_id=mapped_team_id.strip(),
        zhiboba_team_id=zhiboba_team_id.strip(),
        team_name=team_name.strip() if isinstance(team_name, str) and team_name.strip() else None,
    )


def get_team_by_zhiboba_team_id(db: Session, zhiboba_team_id: str) -> TeamIdMapping | None:
    team_filter_sql = build_nba_team_filter_sql(db=db)
    row = db.execute(
        text(
            f"""
            SELECT team_id, zhiboba_team_id, team_name
            FROM nba_teams_name_data
            WHERE {team_filter_sql} AND zhiboba_team_id = :zhiboba_team_id
            LIMIT 1
            """
        ),
        {"zhiboba_team_id": zhiboba_team_id},
    ).fetchone()

    if not row:
        return None

    team_id = getattr(row, "team_id", None)
    mapped_zhiboba_team_id = getattr(row, "zhiboba_team_id", None)
    team_name = getattr(row, "team_name", None)
    if not isinstance(team_id, str) or not team_id.strip():
        return None
    if not isinstance(mapped_zhiboba_team_id, str) or not mapped_zhiboba_team_id.strip():
        return None

    return TeamIdMapping(
        team_id=team_id.strip(),
        zhiboba_team_id=mapped_zhiboba_team_id.strip(),
        team_name=team_name.strip() if isinstance(team_name, str) and team_name.strip() else None,
    )


def list_all_teams_with_zhiboba_team_id(db: Session) -> list[TeamIdMapping]:
    team_filter_sql = build_nba_team_filter_sql(db=db)
    rows = db.execute(
        text(
            f"""
            SELECT team_id, zhiboba_team_id, team_name
            FROM nba_teams_name_data
            WHERE {team_filter_sql} AND zhiboba_team_id IS NOT NULL
              AND TRIM(zhiboba_team_id) <> ''
            ORDER BY id ASC
            """
        )
    ).fetchall()

    teams: list[TeamIdMapping] = []
    for row in rows:
        team_id = getattr(row, "team_id", None)
        zhiboba_team_id = getattr(row, "zhiboba_team_id", None)
        team_name = getattr(row, "team_name", None)
        if not isinstance(team_id, str) or not team_id.strip():
            continue
        if not isinstance(zhiboba_team_id, str) or not zhiboba_team_id.strip():
            continue
        teams.append(
            TeamIdMapping(
                team_id=team_id.strip(),
                zhiboba_team_id=zhiboba_team_id.strip(),
                team_name=team_name.strip() if isinstance(team_name, str) and team_name.strip() else None,
            )
        )
    return teams


def bind_players_team_id_by_team_name(db: Session, *, team_name: str, team_id: str) -> int:
    if not team_name.strip() or not team_id.strip():
        return 0

    result = db.execute(
        text(
            """
            UPDATE nba_players_name_data
            SET team_id = :team_id, updated_at = CURRENT_TIMESTAMP
            WHERE team_name = :team_name
            """
        ),
        {"team_id": team_id, "team_name": team_name},
    )
    db.commit()
    return int(getattr(result, "rowcount", 0) or 0)


def bind_players_team_id_by_zhiboba_team_id(db: Session, *, zhiboba_team_id: str) -> dict[str, int | str]:
    mapping = get_team_by_zhiboba_team_id(db=db, zhiboba_team_id=zhiboba_team_id)
    if mapping is None or not (mapping.team_name or "").strip():
        raise ValueError(f"未在 nba_teams_name_data 中找到 zhiboba_team_id={zhiboba_team_id} 对应的球队信息")

    updated = bind_players_team_id_by_team_name(db=db, team_name=mapping.team_name or "", team_id=mapping.team_id)
    return {
        "team_id": mapping.team_id,
        "zhiboba_team_id": mapping.zhiboba_team_id,
        "team_name": mapping.team_name or "",
        "updated_players": updated,
    }

def sync_zhiboba_team_players(db: Session, http_client: HttpClient, team_id: str) -> dict[str, int]:
    params = build_team_player_params(team_id=team_id)
    headers = build_team_player_headers()
    
    payload = http_client.get_json(ZHIBO8_TEAM_DATA_API_URL, params=params, headers=headers)
    records = parse_team_players(payload)
    records = enrich_players_with_player_code(records=records, http_client=http_client)
    
    ensure_players_table(db=db)
    upserted = upsert_team_players(db=db, records=records)
    
    return {
        "players": len(records),
        "upserted": upserted
    }


def sync_zhiboba_team_players_by_master_team_id(
    db: Session, http_client: HttpClient, team_id: str
) -> dict[str, int | str]:
    mapping = get_zhiboba_team_id_by_team_id(db=db, team_id=team_id)
    if mapping is None:
        raise ValueError(f"未在 nba_teams_name_data 中找到 team_id={team_id} 对应的直播吧球队ID")

    result = sync_zhiboba_team_players(db=db, http_client=http_client, team_id=mapping.zhiboba_team_id)
    return {
        "team_id": mapping.team_id,
        "zhiboba_team_id": mapping.zhiboba_team_id,
        "team_name": mapping.team_name or "",
        "players": int(result["players"]),
        "upserted": int(result["upserted"]),
    }


def sync_all_zhiboba_team_players(db: Session, http_client: HttpClient) -> dict[str, Any]:
    teams = list_all_teams_with_zhiboba_team_id(db=db)
    ensure_players_table(db=db)

    success_teams = 0
    failed_teams = 0
    total_players = 0
    total_upserted = 0
    failures: list[dict[str, str]] = []

    for team in teams:
        try:
            result = sync_zhiboba_team_players(db=db, http_client=http_client, team_id=team.zhiboba_team_id)
            success_teams += 1
            total_players += int(result["players"])
            total_upserted += int(result["upserted"])
        except Exception as exc:
            failed_teams += 1
            failures.append(
                {
                    "team_id": team.team_id,
                    "zhiboba_team_id": team.zhiboba_team_id,
                    "team_name": team.team_name or "",
                    "error": str(exc),
                }
            )

    return {
        "teams": len(teams),
        "success_teams": success_teams,
        "failed_teams": failed_teams,
        "players": total_players,
        "upserted": total_upserted,
        "failures": failures,
    }
