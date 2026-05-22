from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any


@dataclass(frozen=True)
class ParsedGame:
    season: str
    game_date: date
    home_abbr: str
    away_abbr: str


def parse_schedule(payload: Any, season: str) -> list[ParsedGame]:
    games: list[ParsedGame] = []

    if not isinstance(payload, dict):
        return games

    raw_games = payload.get("games")
    if not isinstance(raw_games, list):
        return games

    for item in raw_games:
        if not isinstance(item, dict):
            continue

        raw_date = item.get("date")
        home = item.get("home_abbr")
        away = item.get("away_abbr")
        if not (isinstance(raw_date, str) and isinstance(home, str) and isinstance(away, str)):
            continue

        try:
            game_date = date.fromisoformat(raw_date)
        except ValueError:
            continue

        games.append(
            ParsedGame(
                season=season,
                game_date=game_date,
                home_abbr=home.strip().upper(),
                away_abbr=away.strip().upper(),
            )
        )

    return games
