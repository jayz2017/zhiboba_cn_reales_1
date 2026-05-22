import unittest
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from types import SimpleNamespace

from app.modules.nba_schedule.game_list_by_date import (
    GAME_LIST_DEFAULT_TYPE,
    GameListRecord,
    TeamRankingRecord,
    build_team_ranking_params,
    derive_ranking_year,
    fetch_team_rankings,
    list_game_list_source_records,
    normalize_start_time,
    parse_team_ranking_payload,
    sync_game_list_by_date,
    upsert_game_list_records,
)


class FakeDb:
    def __init__(self, rows):
        self._rows = rows
        self.executed = []

    def execute(self, *args, **kwargs):
        self.executed.append((args, kwargs))
        sql = str(args[0])
        if "FROM nba_zhiboba_yj_gamelist AS schedule" in sql:
            return SimpleNamespace(fetchall=lambda: self._rows)
        return SimpleNamespace(fetchone=lambda: None)

    def commit(self):
        return None


class TestGameListByDate(unittest.TestCase):
    def test_normalize_start_time_from_timedelta(self) -> None:
        self.assertEqual(normalize_start_time(timedelta(hours=9)), time(9, 0, 0))

    def test_derive_ranking_year(self) -> None:
        self.assertEqual(derive_ranking_year(date(2026, 4, 20)), 2025)
        self.assertEqual(derive_ranking_year(date(2026, 10, 20)), 2026)

    def test_build_team_ranking_params(self) -> None:
        params = build_team_ranking_params(game_date=date(2026, 4, 20))
        self.assertEqual(params["year"], "2025")
        self.assertEqual(params["type"], "排行")
        self.assertEqual(params["tab"], "排行")

    def test_parse_team_ranking_payload(self) -> None:
        payload = {
            "data": [
                {
                    "title": "西部",
                    "list": [
                        {
                            "teamId": "6894",
                            "球队名称": "马刺 *",
                            "排名": "2",
                            "胜": "62",
                            "负": "20",
                            "胜率": "75.6%",
                            "近况": "1连败",
                            "胜/负": "62/20",
                            "胜差": "2",
                        }
                    ],
                }
            ]
        }
        result = parse_team_ranking_payload(payload)
        self.assertEqual(
            result["6894"],
            TeamRankingRecord(
                team_id="6894",
                team_name="马刺",
                rank=2,
                wins=62,
                losses=20,
                win_rate=Decimal("75.6"),
                recent_form="1连败",
                wins_losses_text="62/20",
                win_diff=Decimal("2"),
                zone=2,
            ),
        )

    def test_fetch_team_rankings(self) -> None:
        class FakeHttpClient:
            def get_json(self, url, **kwargs):
                return {
                    "data": [
                        {
                            "title": "西部",
                            "list": [{"teamId": "6894", "球队名称": "马刺 *", "排名": "2"}],
                        }
                    ]
                }

        result = fetch_team_rankings(FakeHttpClient(), game_date=date(2026, 4, 20))
        self.assertEqual(result["6894"].team_name, "马刺")
        self.assertEqual(result["6894"].zone, 2)

    def test_list_game_list_source_records(self) -> None:
        db = FakeDb(
            [
                SimpleNamespace(
                    saishi_id="1966673",
                    game_date=date(2026, 4, 20),
                    start_time=timedelta(hours=9),
                    home_id="6888",
                    guest_id="6914",
                    event_name="NBA季后赛西部首轮G1",
                    home_team_name="湖人",
                    guest_team_name="勇士",
                    created_at=datetime(2026, 4, 20, 8, 0, 0),
                )
            ]
        )
        rankings = {
            "6888": TeamRankingRecord(
                team_id="6888",
                team_name="活塞",
                rank=6,
                wins=45,
                losses=37,
                win_rate=Decimal("54.9"),
                recent_form="2连胜",
                wins_losses_text="45/37",
                win_diff=Decimal("7"),
                zone=1,
            ),
            "6914": TeamRankingRecord(
                team_id="6914",
                team_name="勇士",
                rank=7,
                wins=44,
                losses=38,
                win_rate=Decimal("53.7"),
                recent_form="1连败",
                wins_losses_text="44/38",
                win_diff=Decimal("8"),
                zone=2,
            ),
        }

        records = list_game_list_source_records(db=db, game_date=date(2026, 4, 20), rankings=rankings)

        self.assertEqual(
            records,
            [
                GameListRecord(
                    id="1966673",
                    home_team="活塞",
                    visit_team="勇士",
                    home_id="6888",
                    guest_id="6914",
                    home_ls=6,
                    guest_ls=7,
                    guest_play_off_win=None,
                    guest_rank=7,
                    guest_win_diff=Decimal("8"),
                    guest_win_or_filr="1连败",
                    guest_win_rate=Decimal("53.7"),
                    guest_zone=2,
                    home_play_off_win=None,
                    home_rank=6,
                    home_win_diff=Decimal("7"),
                    home_win_or_filr="2连胜",
                    home_win_rate=Decimal("54.9"),
                    home_zone=1,
                    season_type="NBA季后赛西部首轮G1",
                    sdate=date(2026, 4, 20),
                    start=time(9, 0, 0),
                    create_date=datetime(2026, 4, 20, 8, 0, 0),
                    current_time=None,
                )
            ],
        )

    def test_upsert_game_list_records(self) -> None:
        db = FakeDb([])
        affected = upsert_game_list_records(
            db=db,
            records=[
                GameListRecord(
                    id="1966673",
                    home_team="湖人",
                    visit_team="勇士",
                    home_id="6888",
                    guest_id="6914",
                    season_type="NBA季后赛西部首轮G1",
                    sdate=date(2026, 4, 20),
                    start=time(9, 0, 0),
                )
            ],
        )

        self.assertEqual(affected, 1)
        sql_args, sql_kwargs = db.executed[0]
        self.assertIn("INSERT INTO game_list", str(sql_args[0]))
        self.assertEqual(sql_args[1]["type"], GAME_LIST_DEFAULT_TYPE)
        self.assertEqual(sql_args[1]["home_id"], "6888")
        self.assertEqual(sql_args[1]["guest_id"], "6914")
        self.assertEqual(sql_kwargs, {})

    def test_sync_game_list_by_date(self) -> None:
        db = FakeDb(
            [
                SimpleNamespace(
                    saishi_id="1966673",
                    game_date=date(2026, 4, 20),
                    start_time=time(9, 0, 0),
                    home_id="6888",
                    guest_id="6914",
                    event_name="NBA季后赛西部首轮G1",
                    home_team_name="湖人",
                    guest_team_name="勇士",
                    created_at=datetime(2026, 4, 20, 8, 0, 0),
                )
            ]
        )
        http_client = object()

        from unittest.mock import patch

        with patch(
            "app.modules.nba_schedule.game_list_by_date.fetch_team_rankings",
            return_value={},
        ):
            result = sync_game_list_by_date(db=db, http_client=http_client, game_date=date(2026, 4, 20))

        self.assertEqual(result["game_date"], "2026-04-20")
        self.assertEqual(result["games"], 1)
        self.assertEqual(result["upserted"], 1)


if __name__ == "__main__":
    unittest.main()
