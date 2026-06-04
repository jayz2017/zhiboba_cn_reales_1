#!/usr/bin/env python
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path


project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from app.core.database import SessionLocal
from app.modules.nba_live_text.nba_china_livetext import NBA_CHINA_DEFAULT_SIGN2
from app.modules.nba_schedule.nba_china_players import (
    NBA_CHINA_PLAYERS_DEFAULT_PAGE_SIZE,
    diagnose_unmatched_nba_china_players,
    sync_nba_china_players,
)
from app.utils.http.client import HttpClient


LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s - %(message)s"


def _configure_console_output() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(errors="backslashreplace")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Sync NBA China players into nba_players_name_data.")
    parser.add_argument("--page-size", type=int, default=NBA_CHINA_PLAYERS_DEFAULT_PAGE_SIZE)
    parser.add_argument("--max-pages", type=int, default=200)
    parser.add_argument("--sign2", default=NBA_CHINA_DEFAULT_SIGN2)
    parser.add_argument("--log-level", default="INFO", help="Python logging level, for example INFO or WARNING.")
    parser.add_argument("--diagnose-unmatched", action="store_true", help="Print unmatched players without writing DB.")
    parser.add_argument("--sample-limit", type=int, default=20, help="Number of unmatched players to include in JSON.")
    return parser


def main() -> int:
    _configure_console_output()
    args = _build_parser().parse_args()
    logging.basicConfig(level=getattr(logging, str(args.log_level).upper(), logging.INFO), format=LOG_FORMAT)
    db = SessionLocal()
    http_client = HttpClient()
    try:
        if args.diagnose_unmatched:
            result = diagnose_unmatched_nba_china_players(
                db=db,
                http_client=http_client,
                page_size=args.page_size,
                max_pages=args.max_pages,
                sign2=args.sign2,
                sample_limit=args.sample_limit,
            )
        else:
            result = sync_nba_china_players(
                db=db,
                http_client=http_client,
                page_size=args.page_size,
                max_pages=args.max_pages,
                sign2=args.sign2,
            )
    finally:
        http_client.close()
        db.close()

    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
