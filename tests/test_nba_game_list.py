import unittest
from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import patch

from app.modules.nba_schedule.nba_game_list import (
    NbaStoreGameRecord,
    build_nba_store_game_params,
    format_nba_store_game_date,
    parse_nba_store_game_list,
    sync_nba_store_game_list,
    upsert_nba_store_game_records,
)


class FakeDb:
    def __init__(self):
        self.executed = []
        self.commits = 0

    def execute(self, *args, **kwargs):
        self.executed.append((args, kwargs))
        return SimpleNamespace(fetchone=lambda: None, fetchall=lambda: [])

    def commit(self):
        self.commits += 1


class TestNbaGameList(unittest.TestCase):
    def test_build_params_uses_java_date_format(self) -> None:
        target_date = date(2026, 5, 29)

        self.assertEqual(format_nba_store_game_date(target_date), "05/29/2026")
        self.assertEqual(
            build_nba_store_game_params(target_date),
            {"gamedate": "05/29/2026", "platform": "web"},
        )

    def test_parse_payload_extracts_game_cards(self) -> None:
        payload = {
            "modules": [
                {
                    "cards": [
                        {
                            "cardData": {
                                "gameId": "0022400061",
                                "seasonYear": "2024-25",
                                "seasonType": "Regular Season",
                                "gameStatus": 3,
                                "gameStatusText": "Final",
                                "gameTimeUtc": "2024-10-22T23:30:00Z",
                                "gameTimeEastern": "2024-10-22T19:30:00Z",
                                "homeTeam": {
                                    "teamId": 1610612738,
                                    "teamName": "Celtics",
                                    "teamTricode": "BOS",
                                },
                                "awayTeam": {
                                    "teamId": 1610612752,
                                    "teamName": "Knicks",
                                    "teamTricode": "NYK",
                                },
                            }
                        }
                    ]
                }
            ]
        }

        records = parse_nba_store_game_list(
            payload,
            game_date=date(2024, 10, 22),
            team_names_by_code={"BOS": "Boston local", "NYK": "New York local"},
        )

        self.assertEqual(len(records), 1)
        record = records[0]
        self.assertEqual(record.game_id, "0022400061")
        self.assertEqual(record.home_name, "Boston local")
        self.assertEqual(record.visit_name, "New York local")
        self.assertEqual(record.home_team_name_abbr, "bos")
        self.assertEqual(record.visit_team_name_abbr, "nyk")
        self.assertEqual(record.home_team_id, "1610612738")
        self.assertEqual(record.visit_team_id, "1610612752")
        self.assertEqual(record.game_status, 3)
        self.assertEqual(record.game_time_utc, datetime(2024, 10, 22, 23, 30, 0))
        self.assertIn('"gameId": "0022400061"', record.raw_json or "")

    def test_upsert_records_writes_expected_table(self) -> None:
        db = FakeDb()
        affected = upsert_nba_store_game_records(
            db=db,
            records=[
                NbaStoreGameRecord(
                    game_id="0022400061",
                    game_date=date(2024, 10, 22),
                    home_name="Boston local",
                    visit_name="New York local",
                    home_team_name_abbr="bos",
                    visit_team_name_abbr="nyk",
                    raw_json='{"gameId":"0022400061"}',
                )
            ],
        )

        self.assertEqual(affected, 1)
        sql_args, sql_kwargs = db.executed[0]
        self.assertIn("INSERT INTO nba_store_game_list", str(sql_args[0]))
        params = sql_args[1][0]
        self.assertEqual(params["game_id"], "0022400061")
        self.assertEqual(params["home_team_name_abbr"], "bos")
        self.assertEqual(params["type"], "NBA")
        self.assertTrue(params["id"])
        self.assertEqual(sql_kwargs, {})
        self.assertEqual(db.commits, 1)

    def test_sync_fetches_parses_and_upserts(self) -> None:
        payload = {
            "modules": [
                {
                    "cards": [
                        {
                            "cardData": {
                                "gameId": "0022400061",
                                "homeTeam": {"teamName": "Celtics", "teamTricode": "BOS"},
                                "awayTeam": {"teamName": "Knicks", "teamTricode": "NYK"},
                            }
                        }
                    ]
                }
            ]
        }

        with patch(
            "app.modules.nba_schedule.nba_game_list.fetch_nba_store_game_payload",
            return_value=payload,
        ), patch(
            "app.modules.nba_schedule.nba_game_list.load_team_names_by_code",
            return_value={},
        ), patch(
            "app.modules.nba_schedule.nba_game_list.ensure_nba_store_game_list_table",
        ), patch(
            "app.modules.nba_schedule.nba_game_list.upsert_nba_store_game_records",
            return_value=1,
        ):
            result = sync_nba_store_game_list(db=object(), http_client=object(), game_date=date(2024, 10, 22))

        self.assertEqual(result, {"game_date": "2024-10-22", "games": 1, "upserted": 1})


if __name__ == "__main__":
    unittest.main()
