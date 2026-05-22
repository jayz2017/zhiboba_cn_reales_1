from __future__ import annotations

import re
import time
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.http_resources import QIUMIBAO_STATS_API_URL, build_playoffs_headers
from app.utils.http.client import HttpClient
from app.modules.nba_schedule.zhiboba_schedule import ZhibobaScheduleRecord, ensure_zhiboba_schedule_table, upsert_zhiboba_schedule_records

def build_playoffs_params(year: int | None = None) -> dict[str, str]:
    if year is None:
        now = datetime.now()
        year = now.year - 1 if now.month < 9 else now.year

    ts_ms = int(time.time() * 1000)
    return {
        "_url": "/data/index",
        "league": "NBA",
        "tab": "对阵",
        "type": "对阵",
        "year": str(year),
        "_t": str(ts_ms),
        "appname": "zhibo8"
    }

def _parse_schedule_list(schedule_list: list[dict], current_year: str) -> list[ZhibobaScheduleRecord]:
    records = []
    for item in schedule_list:
        if not isinstance(item, dict):
            continue
        
        date_str = item.get("date_str", "")
        item_time = item.get("time", "")
        item_date = item.get("date", "")
        
        if "待定" in date_str or "待定" in item_time or "待定" in item_date:
            continue
        if not item_date or not item_time:
            continue

        left_team = item.get("left_team", "")
        right_team = item.get("right_team", "")
        if "待定" in left_team or "待定" in right_team:
            continue

        saishi_id = item.get("id")
        if not saishi_id:
            continue
            
        item_url = item.get("url", "")
        match = re.search(r'/nba/(\d{4})/', item_url)
        year_str = match.group(1) if match else current_year
        
        month_day = item_date.strip()
        if "/" in month_day:
            m, d = month_day.split("/", 1)
            game_date_str = f"{year_str}-{m.zfill(2)}-{d.zfill(2)}"
        elif "-" in month_day:
            m, d = month_day.split("-", 1)
            game_date_str = f"{year_str}-{m.zfill(2)}-{d.zfill(2)}"
        else:
            continue
            
        start_time = f"{item_time.strip()}:00" if len(item_time.strip()) == 5 else item_time.strip()
        
        home_id = item.get("right_team_id")
        guest_id = item.get("left_team_id")
        
        if not home_id or not guest_id:
            continue
            
        state = str(item.get("state", "0"))
        is_finish = 1 if state == "3" else 0
        event_name = item.get("rounds", "NBA季后赛")
        
        records.append(
            ZhibobaScheduleRecord(
                saishi_id=saishi_id,
                game_date=game_date_str,
                start_time=start_time,
                home_id=home_id,
                guest_id=guest_id,
                is_finish=is_finish,
                event_name=event_name,
                raw_json=None
            )
        )
    return records

def parse_playoffs_data(payload: dict, current_year: str) -> list[ZhibobaScheduleRecord]:
    data = payload.get("data", {})
    if not isinstance(data, dict):
        return []
        
    all_records = []
    
    for key in ['top', 'bottom']:
        section = data.get(key, [])
        if isinstance(section, list):
            for col in section:
                if isinstance(col, list):
                    for match_up in col:
                        if isinstance(match_up, dict) and match_up.get("schedule"):
                            sched_list = match_up["schedule"].get("list", [])
                            all_records.extend(_parse_schedule_list(sched_list, current_year))

    finals = data.get("finals", {})
    if isinstance(finals, dict) and finals.get("schedule"):
        sched_list = finals["schedule"].get("list", [])
        all_records.extend(_parse_schedule_list(sched_list, current_year))
    elif isinstance(finals, list):
        for match_up in finals:
            if isinstance(match_up, dict) and match_up.get("schedule"):
                sched_list = match_up["schedule"].get("list", [])
                all_records.extend(_parse_schedule_list(sched_list, current_year))
                
    return all_records

def sync_zhiboba_playoffs(db: Session, http_client: HttpClient, year: int | None = None) -> dict[str, int]:
    params = build_playoffs_params(year=year)
    headers = build_playoffs_headers()
    
    payload = http_client.get_json(QIUMIBAO_STATS_API_URL, params=params, headers=headers)
    
    # Extract the actual year used for fallback parsing
    current_year = params["year"]
    
    records = parse_playoffs_data(payload, current_year)
    
    ensure_zhiboba_schedule_table(db=db)
    upserted = upsert_zhiboba_schedule_records(db=db, records=records)
    
    return {
        "games": len(records),
        "upserted": upserted
    }
