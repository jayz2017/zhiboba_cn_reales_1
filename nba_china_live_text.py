#!/usr/bin/env python
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from app.core.database import SessionLocal
from app.modules.nba_live_text.nba_china_livetext import (
    NBA_CHINA_DEFAULT_SIGN2,
    parse_periods,
    sync_and_extract_nba_china_live_text,
    sync_nba_china_live_text,
)
from app.utils.http.client import HttpClient


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Sync NBA China play-by-play text and optionally extract semantics.")
    parser.add_argument("--game-id", required=True, help="NBA official game id, for example 0042500316.")
    parser.add_argument(
        "--periods",
        default=None,
        help="Comma-separated periods, for example 1,2. Omit to auto-fetch from period=1 until pla is empty.",
    )
    parser.add_argument("--max-auto-period", type=int, default=20, help="Safety cap for auto period fetching.")
    parser.add_argument("--sign2", default=NBA_CHINA_DEFAULT_SIGN2, help="NBA China sign2 token.")
    parser.add_argument("--extract", action="store_true", help="Extract semantic player relations after tokenization.")
    parser.add_argument("--max-rows", type=int, default=5000, help="Maximum segmented rows for semantic extraction.")
    parser.add_argument("--sample-limit", type=int, default=20, help="Number of relation samples to print.")
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    periods = parse_periods(args.periods)

    db = SessionLocal()
    http_client = HttpClient()
    try:
        if args.extract:
            result = sync_and_extract_nba_china_live_text(
                db=db,
                http_client=http_client,
                game_id=args.game_id,
                periods=periods,
                sign2=args.sign2,
                max_auto_period=args.max_auto_period,
                max_rows=args.max_rows,
                sample_limit=args.sample_limit,
            )
        else:
            result = sync_nba_china_live_text(
                db=db,
                http_client=http_client,
                game_id=args.game_id,
                periods=periods,
                sign2=args.sign2,
                max_auto_period=args.max_auto_period,
            )
    finally:
        http_client.close()
        db.close()

    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
