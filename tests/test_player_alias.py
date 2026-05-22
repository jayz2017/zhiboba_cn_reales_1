import unittest
from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

from app.modules.nba_schedule.player_alias import (
    MatchAliasSource,
    PlayerAliasRecord,
    PLAYER_ALIAS_DEFAULT_TYPE,
    build_player_alias_url,
    fetch_player_alias_records,
    has_player_alias_type_column,
    iter_candidate_game_dates,
    parse_player_alias_response,
    sync_player_aliases,
    upsert_player_alias_records,
)


class FakeDb:
    def __init__(self, rows):
        self._rows = rows
        self.executed = []

    def execute(self, *args, **kwargs):
        self.executed.append((args, kwargs))
        if "SELECT saishi_id, game_date" in str(args[0]):
            return SimpleNamespace(fetchall=lambda: self._rows)
        return SimpleNamespace(fetchone=lambda: None)

    def commit(self):
        return None


class TestPlayerAlias(unittest.TestCase):
    def test_build_player_alias_url(self) -> None:
        url = build_player_alias_url(date(2026, 5, 16), "1977335")
        self.assertEqual(
            url,
            "https://dc4pc.qiumibao.com/dc/matchs/data/2026-05-16/player_1977335.htm",
        )

    def test_parse_player_alias_response(self) -> None:
        content = """
        {
          "home": [{"player_id": "1001", "player_name_cn": "小詹"}],
          "guest": [{"player_id": "1002", "player_name_cn": "阿库"}],
          "dup": [{"player_id": "1001", "player_name_cn": "小詹"}]
        }
        """
        records = parse_player_alias_response(content)

        self.assertEqual(
            records,
            [
                PlayerAliasRecord(player_id="1001", alias_name="小詹"),
                PlayerAliasRecord(player_id="1002", alias_name="阿库"),
            ],
        )

    def test_iter_candidate_game_dates(self) -> None:
        self.assertEqual(
            iter_candidate_game_dates(date(2026, 5, 16)),
            [date(2026, 5, 16), date(2026, 5, 15), date(2026, 5, 17)],
        )

    def test_fetch_player_alias_records_skips_404_and_uses_nearby_date(self) -> None:
        class FakeHttpClient:
            def __init__(self) -> None:
                self.urls: list[str] = []

            def get_text_with_status(self, url: str, **kwargs):
                self.urls.append(url)
                if "2026-05-16" in url:
                    return 404, "not found"
                return 200, '{"list": [{"player_id": "1001", "player_name_cn": "小詹"}]}'

        http_client = FakeHttpClient()
        records = fetch_player_alias_records(
            http_client=http_client,
            source=MatchAliasSource(saishi_id="1977335", game_date=date(2026, 5, 16)),
        )

        self.assertEqual(records, [PlayerAliasRecord(player_id="1001", alias_name="小詹")])
        self.assertEqual(len(http_client.urls), 2)
        self.assertIn("2026-05-15", http_client.urls[1])

    def test_has_player_alias_type_column(self) -> None:
        db = FakeDb([])
        db.execute = lambda *args, **kwargs: SimpleNamespace(fetchone=lambda: SimpleNamespace())
        self.assertTrue(has_player_alias_type_column(db=db))

    def test_upsert_player_alias_records_uses_default_nba_type(self) -> None:
        db = FakeDb([])
        records = [PlayerAliasRecord(player_id="1001", alias_name="小詹")]

        inserted = upsert_player_alias_records(db=db, records=records)

        self.assertEqual(inserted, 1)
        sql_args, sql_kwargs = db.executed[0]
        self.assertIn("INSERT INTO player_alias_name_info (player_id, alias_name, type)", str(sql_args[0]))
        self.assertEqual(
            sql_args[1],
            {
                "player_id": "1001",
                "alias_name": "小詹",
                "type": PLAYER_ALIAS_DEFAULT_TYPE,
            },
        )
        self.assertEqual(sql_kwargs, {})

    def test_sync_player_aliases(self) -> None:
        db = FakeDb([SimpleNamespace(saishi_id="1977335", game_date=date(2026, 5, 16))])
        http_client = object()

        with patch(
            "app.modules.nba_schedule.player_alias.ensure_player_alias_table"
        ), patch(
            "app.modules.nba_schedule.player_alias.fetch_player_alias_records",
            return_value=[
                PlayerAliasRecord(player_id="1001", alias_name="小詹"),
                PlayerAliasRecord(player_id="1002", alias_name="阿库"),
            ],
        ), patch(
            "app.modules.nba_schedule.player_alias.upsert_player_alias_records",
            return_value=2,
        ):
            result = sync_player_aliases(db=db, http_client=http_client, saishi_id=None)

        self.assertEqual(result["matches"], 1)
        self.assertEqual(result["success_matches"], 1)
        self.assertEqual(result["failed_matches"], 0)
        self.assertEqual(result["aliases"], 2)
        self.assertEqual(result["upserted"], 2)
        self.assertEqual(result["failures"], [])


if __name__ == "__main__":
    unittest.main()
