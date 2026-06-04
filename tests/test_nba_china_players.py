import unittest
from types import SimpleNamespace
from urllib.parse import urlencode
from unittest.mock import patch

from app.modules.nba_schedule.nba_china_players import (
    build_nba_china_players_params,
    diagnose_unmatched_nba_china_players,
    fetch_nba_china_player_records,
    find_unmatched_nba_china_player_records,
    normalize_player_code,
    parse_nba_china_players_payload,
    sync_nba_china_players,
    upsert_nba_china_player_records,
)


class _RowsResult:
    def __init__(self, rows=None, scalar_id=None):
        self._rows = rows or []
        self._scalar_id = scalar_id

    def fetchall(self):
        return self._rows

    def fetchone(self):
        if self._scalar_id is not None:
            return SimpleNamespace(id=self._scalar_id)
        return None


class FakeDb:
    def __init__(self, existing_rows=None, existing_team_jersey_rows=None):
        self.existing_rows = existing_rows or []
        self.existing_team_jersey_rows = existing_team_jersey_rows or []
        self.executed = []
        self.commits = 0
        self.next_id = 100

    def execute(self, sql, params=None):
        sql_text = str(sql)
        self.executed.append((sql_text, params))
        if "SELECT id, player_code" in sql_text:
            return _RowsResult(self.existing_rows)
        if "SELECT id, team_name, nba_jersey_number, zhiboba_jersey_number" in sql_text:
            return _RowsResult(self.existing_team_jersey_rows)
        if "SELECT LAST_INSERT_ID()" in sql_text:
            return _RowsResult(scalar_id=self.next_id)
        return _RowsResult()

    def commit(self):
        self.commits += 1


class FakeHttpClient:
    def __init__(self, payloads):
        self.payloads = list(payloads)
        self.calls = []

    def get_json(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.payloads.pop(0)


def _player(
    player_id,
    player_code,
    first_name="First",
    last_name="Last",
    jersey_no="1",
    team_name="Team",
    first_name_en=None,
    last_name_en=None,
):
    resolved_first_name_en = first_name if first_name_en is None else first_name_en
    resolved_last_name_en = last_name if last_name_en is None else last_name_en
    return {
        "playerId": player_id,
        "playerCode": player_code,
        "firstName": first_name,
        "lastName": last_name,
        "firstNameEn": resolved_first_name_en,
        "lastNameEn": resolved_last_name_en,
        "jerseyNo": jersey_no,
        "teamName": team_name,
    }


def _payload(players, *, total=None, page_no=None, page_size=None):
    payload = {"data": players}
    pagination = {}
    if total is not None:
        pagination["total"] = total
    if page_no is not None:
        pagination["page_no"] = page_no
    if page_size is not None:
        pagination["page_size"] = page_size
    if pagination:
        payload["pagination"] = pagination
    return payload


class TestNbaChinaPlayers(unittest.TestCase):
    def test_normalize_player_code_removes_special_chars(self):
        self.assertEqual(normalize_player_code("LeBron_James."), "lebronjames")
        self.assertEqual(normalize_player_code(" lebron-james "), "lebronjames")

    def test_build_params(self):
        params = build_nba_china_players_params(page_no=2, page_size=50, timestamp=1780038163)

        self.assertEqual(params["page_no"], "2")
        self.assertEqual(params["page_size"], "50")
        self.assertEqual(params["retireStat"], "A")
        self.assertEqual(params["startYearRange"], ["", ""])
        self.assertEqual(params["t"], "1780038163")
        self.assertIn("startYearRange=&startYearRange=", urlencode(params, doseq=True))

    def test_parse_payload_extracts_players_and_total(self):
        payload = _payload(
            [_player("2544", "lebron_james", "LeBron", "James", "23", "Lakers")],
            total=1,
            page_no=1,
            page_size=50,
        )

        records, total = parse_nba_china_players_payload(payload)

        self.assertEqual(total, 1)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].player_id, "2544")
        self.assertEqual(records[0].player_code, "lebron_james")
        self.assertEqual(records[0].nba_player_name, "LeBronJames")
        self.assertEqual(records[0].en_player_name, "James LeBron")
        self.assertEqual(records[0].nba_jersey_number, "23")
        self.assertEqual(records[0].team_name, "Lakers")

    def test_parse_payload_skips_rows_without_player_code(self):
        payload = _payload(
            [
                _player("2544", "lebron_james", "LeBron", "James", "23", "Lakers"),
                {"playerId": "9999", "firstName": "No", "lastName": "Code"},
            ],
            total=2,
            page_no=1,
            page_size=50,
        )

        records, total = parse_nba_china_players_payload(payload)

        self.assertEqual(total, 2)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].player_code, "lebron_james")

    def test_upsert_updates_existing_by_normalized_player_code(self):
        records, _ = parse_nba_china_players_payload(
            _payload([_player("2544", "lebron_james", "LeBron", "James", "23", "Lakers")])
        )
        db = FakeDb(existing_rows=[SimpleNamespace(id=7, player_code="LeBron.James")])

        result = upsert_nba_china_player_records(db=db, records=records)

        self.assertEqual(
            result,
            {
                "upserted": 1,
                "updated": 1,
                "inserted": 0,
                "matched_by_player_code": 1,
                "matched_by_team_jersey": 0,
            },
        )
        self.assertTrue(any("UPDATE nba_players_name_data" in sql for sql, _ in db.executed))
        update_params = next(params for sql, params in db.executed if "UPDATE nba_players_name_data" in sql)
        self.assertEqual(update_params["id"], 7)
        self.assertEqual(update_params["player_id"], "2544")
        self.assertEqual(update_params["nba_player_name"], "LeBronJames")
        self.assertEqual(update_params["en_player_name"], "James LeBron")

    def test_upsert_updates_existing_by_team_name_and_jersey_when_code_misses(self):
        records, _ = parse_nba_china_players_payload(
            _payload([_player("2544", "lebron_james", "LeBron", "James", "23", "Lakers")])
        )
        db = FakeDb(
            existing_rows=[],
            existing_team_jersey_rows=[
                SimpleNamespace(
                    id=9,
                    team_name="Lakers",
                    nba_jersey_number=None,
                    zhiboba_jersey_number="23",
                )
            ],
        )

        result = upsert_nba_china_player_records(db=db, records=records)

        self.assertEqual(
            result,
            {
                "upserted": 1,
                "updated": 1,
                "inserted": 0,
                "matched_by_player_code": 0,
                "matched_by_team_jersey": 1,
            },
        )
        update_params = next(params for sql, params in db.executed if "UPDATE nba_players_name_data" in sql)
        self.assertEqual(update_params["id"], 9)
        self.assertEqual(update_params["team_name"], "Lakers")
        self.assertEqual(update_params["nba_jersey_number"], "23")

    def test_upsert_inserts_when_no_player_code_match(self):
        records, _ = parse_nba_china_players_payload(
            _payload([_player("201939", "stephen_curry", "Stephen", "Curry", "30", "Warriors")])
        )
        db = FakeDb()

        with self.assertLogs("app.modules.nba_schedule.nba_china_players", level="WARNING") as log:
            result = upsert_nba_china_player_records(db=db, records=records)

        self.assertEqual(
            result,
            {
                "upserted": 1,
                "updated": 0,
                "inserted": 1,
                "matched_by_player_code": 0,
                "matched_by_team_jersey": 0,
            },
        )
        self.assertIn("nba_china_player_unmatched", log.output[0])
        self.assertIn("player_code=stephen_curry", log.output[0])
        self.assertIn("normalized_code=stephencurry", log.output[0])
        insert_params = next(params for sql, params in db.executed if "INSERT INTO nba_players_name_data" in sql)
        self.assertEqual(insert_params["zhiboba_player_id"], "nba_cn_201939")
        self.assertEqual(insert_params["team_name"], "Warriors")
        self.assertEqual(insert_params["en_player_name"], "Curry Stephen")

    def test_sync_pages_until_total_count(self):
        http_client = FakeHttpClient(
            [
                _payload([_player("1", "player_one", "Player", "One", "1")], total=2, page_no=1, page_size=1),
                _payload([_player("2", "player_two", "Player", "Two", "2")], total=2, page_no=2, page_size=1),
            ]
        )

        with patch("app.modules.nba_schedule.nba_china_players.ensure_nba_china_player_columns"):
            result = sync_nba_china_players(
                db=FakeDb(),
                http_client=http_client,
                page_size=1,
                max_pages=5,
            )

        self.assertEqual(result["pages"], 2)
        self.assertEqual(result["players"], 2)
        self.assertEqual(result["source_rows"], 2)
        self.assertEqual(result["skipped_without_player_code"], 0)
        self.assertEqual(result["upserted"], 2)
        self.assertEqual(result["matched_by_player_code"], 0)
        self.assertEqual(result["matched_by_team_jersey"], 0)
        self.assertEqual(http_client.calls[0][1]["params"]["page_no"], "1")
        self.assertEqual(http_client.calls[1][1]["params"]["page_no"], "2")
        self.assertEqual(http_client.calls[1][1]["params"]["page_size"], "1")

    def test_fetch_player_records_uses_response_pagination_for_next_page(self):
        http_client = FakeHttpClient(
            [
                _payload([_player("1", "player_one", "A", "One")], total=3, page_no=1, page_size=1),
                _payload([_player("2", "player_one", "B", "Two")], total=3, page_no=2, page_size=1),
                _payload([{"playerId": "3", "firstName": "No", "lastName": "Code"}], total=3, page_no=3, page_size=1),
            ]
        )

        result = fetch_nba_china_player_records(
            http_client=http_client,
            page_size=1,
            max_pages=5,
        )

        self.assertEqual(result.pages, 3)
        self.assertEqual(result.total_count, 3)
        self.assertEqual(result.source_rows, 3)
        self.assertEqual(result.skipped_without_player_code, 1)
        self.assertEqual(len(result.records), 2)
        self.assertEqual(http_client.calls[0][1]["params"]["page_no"], "1")
        self.assertEqual(http_client.calls[1][1]["params"]["page_no"], "2")
        self.assertEqual(http_client.calls[2][1]["params"]["page_no"], "3")

    def test_find_unmatched_returns_records_without_db_match(self):
        records, _ = parse_nba_china_players_payload(
            _payload(
                [
                    _player("1", "player_one", "A", "", "1"),
                    _player("2", "player_two", "B", "", "2"),
                ]
            )
        )
        db = FakeDb(
            existing_rows=[SimpleNamespace(id=11, player_code="Player.One")],
            existing_team_jersey_rows=[
                SimpleNamespace(id=12, team_name="Team", nba_jersey_number="2", zhiboba_jersey_number=None)
            ],
        )

        matched, unmatched = find_unmatched_nba_china_player_records(db=db, records=records)

        self.assertEqual(matched, 2)
        self.assertEqual(unmatched, [])

    def test_diagnose_unmatched_does_not_write_db(self):
        payload = _payload([_player("1", "player_one", "A", "")], total=1, page_no=1, page_size=50)
        db = FakeDb()

        with patch("app.modules.nba_schedule.nba_china_players.ensure_nba_china_player_columns"):
            with self.assertLogs("app.modules.nba_schedule.nba_china_players", level="WARNING") as log:
                result = diagnose_unmatched_nba_china_players(
                    db=db,
                    http_client=FakeHttpClient([payload]),
                    page_size=50,
                    max_pages=1,
                    sample_limit=1,
                )

        self.assertEqual(result["matched"], 0)
        self.assertEqual(result["unmatched"], 1)
        self.assertEqual(result["unmatched_sample"][0]["player_code"], "player_one")
        self.assertIn("nba_china_player_unmatched", log.output[0])
        self.assertFalse(any("INSERT INTO nba_players_name_data" in sql for sql, _ in db.executed))


if __name__ == "__main__":
    unittest.main()
