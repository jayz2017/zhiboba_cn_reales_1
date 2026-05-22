from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.http_resources import QIUMIBAO_STATS_API_URL, build_schedule_headers
from app.utils.http.client import HttpClient

@dataclass(frozen=True)
class ZhibobaScheduleRecord:
    saishi_id: str
    game_date: date
    start_time: str | None
    home_id: str
    guest_id: str
    is_finish: int
    event_name: str
    raw_json: str | None


def build_zhiboba_schedule_params(year: int | None = None) -> dict[str, str]:
    if year is None:
        now = datetime.now()
        # 默认取当前年份，如果月份 < 9，则 year = 当前年份 - 1
        year = now.year - 1 if now.month < 9 else now.year

    ts_ms = int(time.time() * 1000)
    return {
        "_url": "/data/index",
        "year": str(year),
        "type": "赛程",
        "tab": "赛程",
        "league_id": "924",
        "league": "NBA",
        "_t": str(ts_ms),
        "_platform": "web",
        "_env": "pc",
    }


def _parse_day_title_to_date(title: str) -> date | None:
    if not isinstance(title, str) or len(title) < 10:
        return None
    part = title[:10]
    try:
        return date.fromisoformat(part)
    except ValueError:
        return None


def _normalize_start_time(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    content = value.strip()
    if not content:
        return None
    if len(content) == 5 and content[2] == ":":
        h, m = content.split(":", 1)
        if h.isdigit() and m.isdigit():
            return f"{content}:00"
        return None

    if len(content) == 8 and content[2] == ":" and content[5] == ":":
        h, m, s = content.split(":", 2)
        if h.isdigit() and m.isdigit() and s.isdigit():
            return content

    return None


def parse_zhiboba_schedule(payload: Any) -> list[ZhibobaScheduleRecord]:
    if not isinstance(payload, dict):
        return []

    data = payload.get("data")
    if not isinstance(data, list):
        return []

    records: list[ZhibobaScheduleRecord] = []
    for day_block in data:
        if not isinstance(day_block, dict):
            continue

        day = _parse_day_title_to_date(day_block.get("title", ""))
        if day is None:
            continue

        items = day_block.get("list")
        if not isinstance(items, list):
            continue

        for item in items:
            if not isinstance(item, dict):
                continue

            saishi_id = item.get("saishi_id")
            home_id = item.get("homeId")
            guest_id = item.get("guestId")
            is_finish = item.get("is_finish")
            event_name = item.get("赛事")
            start_time = _normalize_start_time(item.get("时间"))

            if not all(isinstance(v, str) and v.strip() for v in (saishi_id, home_id, guest_id, event_name)):
                continue

            is_finish_value = int(is_finish) if isinstance(is_finish, int) else 0
            raw_json = json.dumps(item, ensure_ascii=False)

            records.append(
                ZhibobaScheduleRecord(
                    saishi_id=saishi_id.strip(),
                    game_date=day,
                    start_time=start_time,
                    home_id=home_id.strip(),
                    guest_id=guest_id.strip(),
                    is_finish=is_finish_value,
                    event_name=event_name.strip(),
                    raw_json=raw_json,
                )
            )

    return records


_DDL_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS nba_zhiboba_yj_gamelist (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  -- 赛事id
  saishi_id VARCHAR(32) NOT NULL,
  -- 比赛日期
  game_date DATE NOT NULL,
  -- 比赛时间
  start_time TIME NULL,
  -- 主队id
  home_id VARCHAR(32) NOT NULL,
  -- 客队Id
  guest_id VARCHAR(32) NOT NULL,
  -- 是否完赛
  is_finish TINYINT NOT NULL DEFAULT 0,
  event_name VARCHAR(128) NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uk_saishi_id (saishi_id),
  KEY idx_game_date (game_date),
  KEY idx_home_guest (home_id, guest_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
""".strip()


def ensure_zhiboba_schedule_table(db: Session) -> None:
    db.execute(text(_DDL_CREATE_TABLE))
    db.commit()


_SQL_UPSERT = """
INSERT INTO nba_zhiboba_yj_gamelist
  (saishi_id, game_date, start_time, home_id, guest_id, is_finish, event_name)
VALUES
  (:saishi_id, :game_date, :start_time, :home_id, :guest_id, :is_finish, :event_name)
ON DUPLICATE KEY UPDATE
  game_date = VALUES(game_date),
  start_time = VALUES(start_time),
  home_id = VALUES(home_id),
  guest_id = VALUES(guest_id),
  is_finish = VALUES(is_finish),
  event_name = VALUES(event_name),
  updated_at = CURRENT_TIMESTAMP;
""".strip()


def upsert_zhiboba_schedule_records(db: Session, records: list[ZhibobaScheduleRecord]) -> int:
    if not records:
        return 0

    inserted = 0
    for r in records:
        db.execute(
            text(_SQL_UPSERT),
            {
                "saishi_id": r.saishi_id,
                "game_date": r.game_date,
                "start_time": r.start_time,
                "home_id": r.home_id,
                "guest_id": r.guest_id,
                "is_finish": r.is_finish,
                "event_name": r.event_name,
            },
        )
        inserted += 1

    db.commit()
    return inserted


def sync_zhiboba_schedule(db: Session, http_client: HttpClient, year: int | None = None) -> dict[str, int]:
    params = build_zhiboba_schedule_params(year=year)
    headers = build_schedule_headers()
    payload = http_client.get_json(QIUMIBAO_STATS_API_URL, params=params, headers=headers)
    records = parse_zhiboba_schedule(payload)
    ensure_zhiboba_schedule_table(db=db)
    upserted = upsert_zhiboba_schedule_records(db=db, records=records)
    return {"days": len({r.game_date for r in records}), "games": len(records), "upserted": upserted}
