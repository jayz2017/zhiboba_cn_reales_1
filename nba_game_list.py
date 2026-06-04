#!/usr/bin/env python
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path


project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from app.core.database import SessionLocal
from app.modules.nba_schedule.nba_game_list import sync_nba_store_game_list
from app.utils.http.client import HttpClient


def _parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("date must use YYYY-MM-DD format") from exc


def _iter_dates(start_date: date, end_date: date):
    if end_date < start_date:
        raise argparse.ArgumentTypeError("end date must be greater than or equal to start date")
    current = start_date
    while current <= end_date:
        yield current
        current += timedelta(days=1)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Sync NBA.com official game list into nba_store_game_list.")
    parser.add_argument("--date", type=_parse_date, default=None, help="Single game date, format YYYY-MM-DD.")
    parser.add_argument("--start-date", type=_parse_date, default=None, help="Range start date, format YYYY-MM-DD.")
    parser.add_argument("--end-date", type=_parse_date, default=None, help="Range end date, format YYYY-MM-DD.")
    return parser


def main() -> int:
    args = _build_parser().parse_args()

    if args.start_date or args.end_date:
        start_date = args.start_date or args.end_date
        end_date = args.end_date or args.start_date
        target_dates = list(_iter_dates(start_date, end_date))
    else:
        target_dates = [args.date or date.today()]

    db = SessionLocal()
    http_client = HttpClient()
    try:
        results = [
            sync_nba_store_game_list(db=db, http_client=http_client, game_date=target_date)
            for target_date in target_dates
        ]
    finally:
        http_client.close()
        db.close()

    output = {
        "days": len(results),
        "games": sum(int(item["games"]) for item in results),
        "upserted": sum(int(item["upserted"]) for item in results),
        "results": results,
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
