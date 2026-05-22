import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException

from app.api.v1.endpoints.schedule import (
    bind_players_team_id_by_zhiboba_team_id_api,
    zhiboba_team_players_sync_by_master_team_id,
)
from app.modules.nba_schedule.zhiboba_team_players import (
    TeamIdMapping,
    ZhibobaTeamPlayerRecord,
    build_nba_team_filter_sql,
    enrich_players_with_player_code,
    fetch_player_code,
    get_nba_team_type_column,
    get_zhiboba_team_id_by_team_id,
    list_all_teams_with_zhiboba_team_id,
    parse_team_players,
    sync_all_zhiboba_team_players,
)


class FakeDb:
    def __init__(self, row):
        self._row = row

    def execute(self, *args, **kwargs):
        return SimpleNamespace(fetchone=lambda: self._row)


class FakeDbRows:
    def __init__(self, rows):
        self._rows = rows

    def execute(self, *args, **kwargs):
        return SimpleNamespace(fetchall=lambda: self._rows)


class TestZhibobaTeamPlayers(unittest.TestCase):
    def test_get_nba_team_type_column_prefers_type(self) -> None:
        db = FakeDb(SimpleNamespace(column_name="type"))
        self.assertEqual(get_nba_team_type_column(db=db), "type")

    def test_build_nba_team_filter_sql(self) -> None:
        db = FakeDb(SimpleNamespace(column_name="type"))
        self.assertEqual(build_nba_team_filter_sql(db=db), "UPPER(TRIM(`type`)) = 'NBA'")

    def test_fetch_player_code(self) -> None:
        http_client = SimpleNamespace(
            get_json=lambda *args, **kwargs: {"data": {"player": {"playerCode": "lebron-james"}}}
        )

        player_code = fetch_player_code(http_client=http_client, player_id="215757")

        self.assertEqual(player_code, "lebron-james")

    def test_enrich_players_with_player_code(self) -> None:
        record = ZhibobaTeamPlayerRecord(
            team_id="6916",
            team_name="老鹰",
            zhiboba_player_id="215757",
            zhiboba_player_name="某球员",
            zhiboba_jersey_number="23",
            player_code=None,
            player_salary=100.0,
            position_name="前锋",
        )

        with patch(
            "app.modules.nba_schedule.zhiboba_team_players.fetch_player_code",
            return_value="player-code-001",
        ):
            records = enrich_players_with_player_code(records=[record], http_client=object())

        self.assertEqual(records[0].player_code, "player-code-001")

    def test_parse_team_players_normalizes_player_name_before_upsert(self) -> None:
        payload = {
            "data": {
                "team": {"teamId": "6916", "teamName": "老鹰"},
                "player": {
                    "info": {
                        "list": [
                            {
                                "playerId": "215757",
                                "姓名": "A .J · 格林",
                                "位置": "后卫",
                                "球号": "20",
                                "当赛季薪资": "$1,234,567",
                            }
                        ]
                    }
                },
            }
        }

        records = parse_team_players(payload)

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].zhiboba_player_name, "AJ格林")

    def test_get_zhiboba_team_id_by_team_id(self) -> None:
        db = FakeDb(SimpleNamespace(team_id="1610612747", zhiboba_team_id="6916", team_name="湖人"))
        with patch("app.modules.nba_schedule.zhiboba_team_players.build_nba_team_filter_sql", return_value="UPPER(TRIM(`type`)) = 'NBA'"):
            mapping = get_zhiboba_team_id_by_team_id(db=db, team_id="1610612747")

        assert mapping is not None
        self.assertEqual(mapping.team_id, "1610612747")
        self.assertEqual(mapping.zhiboba_team_id, "6916")
        self.assertEqual(mapping.team_name, "湖人")

    def test_api_returns_404_when_team_id_not_found(self) -> None:
        with patch(
            "app.api.v1.endpoints.schedule.sync_zhiboba_team_players_by_master_team_id",
            side_effect=ValueError("not found"),
        ):
            with self.assertRaises(HTTPException) as ctx:
                zhiboba_team_players_sync_by_master_team_id(team_id="unknown", db=object())

        self.assertEqual(ctx.exception.status_code, 404)

    def test_bind_team_id_api_returns_404_when_zhiboba_team_id_not_found(self) -> None:
        with patch(
            "app.api.v1.endpoints.schedule.bind_players_team_id_by_zhiboba_team_id",
            side_effect=ValueError("not found"),
        ):
            with self.assertRaises(HTTPException) as ctx:
                bind_players_team_id_by_zhiboba_team_id_api(zhiboba_team_id="999999", db=object())

        self.assertEqual(ctx.exception.status_code, 404)

    def test_list_all_teams_with_zhiboba_team_id(self) -> None:
        db = FakeDbRows(
            [
                SimpleNamespace(team_id="1610612747", zhiboba_team_id="6916", team_name="湖人"),
                SimpleNamespace(team_id="1610612744", zhiboba_team_id="6898", team_name="勇士"),
            ]
        )

        with patch("app.modules.nba_schedule.zhiboba_team_players.build_nba_team_filter_sql", return_value="UPPER(TRIM(`type`)) = 'NBA'"):
            teams = list_all_teams_with_zhiboba_team_id(db=db)

        self.assertEqual(len(teams), 2)
        self.assertEqual(teams[0].team_id, "1610612747")
        self.assertEqual(teams[1].zhiboba_team_id, "6898")

    def test_sync_all_zhiboba_team_players(self) -> None:
        teams = [
            TeamIdMapping(team_id="1610612747", zhiboba_team_id="6916", team_name="湖人"),
            TeamIdMapping(team_id="1610612744", zhiboba_team_id="6898", team_name="勇士"),
        ]

        with patch(
            "app.modules.nba_schedule.zhiboba_team_players.list_all_teams_with_zhiboba_team_id",
            return_value=teams,
        ), patch(
            "app.modules.nba_schedule.zhiboba_team_players.ensure_players_table"
        ), patch(
            "app.modules.nba_schedule.zhiboba_team_players.sync_zhiboba_team_players",
            side_effect=[{"players": 15, "upserted": 15}, {"players": 14, "upserted": 14}],
        ):
            result = sync_all_zhiboba_team_players(db=object(), http_client=object())

        self.assertEqual(result["teams"], 2)
        self.assertEqual(result["success_teams"], 2)
        self.assertEqual(result["failed_teams"], 0)
        self.assertEqual(result["players"], 29)
        self.assertEqual(result["upserted"], 29)
        self.assertEqual(result["failures"], [])


if __name__ == "__main__":
    unittest.main()
