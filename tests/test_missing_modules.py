"""
缺失模块补充测试 —— 覆盖 zhiboba_playoffs、nba_china_livetext 辅助函数、db_helpers
"""

import unittest
from unittest.mock import MagicMock, Mock, patch

from app.modules.nba_schedule import zhiboba_playoffs
from app.modules.nba_live_text import nba_china_livetext
from app.utils import db_helpers


# ==========================================================================
# db_helpers
# ==========================================================================

class TestDbHelpers(unittest.TestCase):
    def test_to_int_normal(self):
        self.assertEqual(db_helpers.to_int("42"), 42)
        self.assertEqual(db_helpers.to_int(42), 42)

    def test_to_int_none(self):
        self.assertEqual(db_helpers.to_int(None), 0)
        self.assertEqual(db_helpers.to_int(None, default=-1), -1)

    def test_to_int_invalid(self):
        self.assertEqual(db_helpers.to_int("abc"), 0)
        self.assertEqual(db_helpers.to_int("abc", default=99), 99)
        self.assertEqual(db_helpers.to_int([1, 2, 3]), 0)

    def test_to_decimal_normal(self):
        from decimal import Decimal
        result = db_helpers.to_decimal("3.14")
        self.assertEqual(result, Decimal("3.14"))

    def test_to_decimal_none(self):
        from decimal import Decimal
        self.assertEqual(db_helpers.to_decimal(None), Decimal("0"))
        self.assertEqual(db_helpers.to_decimal(None, default=Decimal("1")), Decimal("1"))

    def test_to_decimal_invalid(self):
        from decimal import Decimal
        self.assertEqual(db_helpers.to_decimal("xyz"), Decimal("0"))


# ==========================================================================
# zhiboba_playoffs
# ==========================================================================

class TestZhibobaPlayoffs(unittest.TestCase):
    def test_build_playoffs_params_default(self):
        params = zhiboba_playoffs.build_playoffs_params()
        self.assertIn("year", params)
        self.assertEqual(params["league"], "NBA")
        self.assertEqual(params["tab"], "对阵")
        self.assertEqual(params["appname"], "zhibo8")
        self.assertIn("_t", params)

    def test_build_playoffs_params_explicit_year(self):
        params = zhiboba_playoffs.build_playoffs_params(year=2025)
        self.assertEqual(params["year"], "2025")

    def test_parse_schedule_list_basic(self):
        schedule_list = [
            {
                "date_str": "06-15",
                "time": "08:00",
                "date": "06-15",
                "left_team": "湖人",
                "right_team": "勇士",
                "id": "1780736",
                "url": "/nba/2025/",
                "left_team_id": "6916",
                "right_team_id": "6917",
                "state": "3",
                "rounds": "总决赛",
            }
        ]
        records = zhiboba_playoffs._parse_schedule_list(schedule_list, "2025")
        self.assertEqual(len(records), 1)
        r = records[0]
        self.assertEqual(r.saishi_id, "1780736")
        self.assertEqual(r.game_date, "2025-06-15")
        self.assertEqual(r.start_time, "08:00:00")
        self.assertEqual(r.home_id, "6917")
        self.assertEqual(r.guest_id, "6916")
        self.assertEqual(r.is_finish, 1)
        self.assertEqual(r.event_name, "总决赛")

    def test_parse_schedule_list_skips_pending(self):
        """待定比赛应被跳过"""
        schedule_list = [
            {"date_str": "待定", "time": "待定", "date": "待定", "left_team": "待定", "right_team": "待定", "id": "1", "url": "/nba/2025/"},
            {"date_str": "06-15", "time": "待定", "date": "06-15", "left_team": "湖人", "right_team": "勇士", "id": "2", "url": "/nba/2025/"},
        ]
        records = zhiboba_playoffs._parse_schedule_list(schedule_list, "2025")
        self.assertEqual(len(records), 0)

    def test_parse_schedule_list_skips_missing_ids(self):
        """缺少 team_id 的应跳过"""
        schedule_list = [
            {"date_str": "06-15", "time": "08:00", "date": "06-15", "left_team": "湖人", "right_team": "勇士", "id": "1", "url": "/nba/2025/", "left_team_id": None, "right_team_id": "6917"},
        ]
        records = zhiboba_playoffs._parse_schedule_list(schedule_list, "2025")
        self.assertEqual(len(records), 0)

    def test_parse_schedule_list_date_with_slash(self):
        """日期包含 / 分隔符"""
        schedule_list = [
            {"date_str": "06/15", "time": "08:00", "date": "06/15", "left_team": "湖人", "right_team": "勇士", "id": "1", "url": "/nba/2025/", "left_team_id": "6916", "right_team_id": "6917", "state": "0"},
        ]
        records = zhiboba_playoffs._parse_schedule_list(schedule_list, "2025")
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].game_date, "2025-06-15")

    def test_parse_schedule_list_non_dict_skipped(self):
        records = zhiboba_playoffs._parse_schedule_list(["not a dict"], "2025")
        self.assertEqual(len(records), 0)

    def test_parse_playoffs_data_top_bottom(self):
        payload = {
            "data": {
                "top": [
                    [
                        {"schedule": {"list": [
                            {"date_str": "06-15", "time": "08:00", "date": "06-15", "left_team": "A", "right_team": "B", "id": "1", "url": "/nba/2025/", "left_team_id": "1", "right_team_id": "2", "state": "0"},
                        ]}}
                    ]
                ],
                "bottom": [
                    [
                        {"schedule": {"list": [
                            {"date_str": "06-16", "time": "09:00", "date": "06-16", "left_team": "C", "right_team": "D", "id": "2", "url": "/nba/2025/", "left_team_id": "3", "right_team_id": "4", "state": "3"},
                        ]}}
                    ]
                ],
            }
        }
        records = zhiboba_playoffs.parse_playoffs_data(payload, "2025")
        self.assertEqual(len(records), 2)

    def test_parse_playoffs_data_finals_dict(self):
        payload = {
            "data": {
                "finals": {"schedule": {"list": [
                    {"date_str": "06-15", "time": "08:00", "date": "06-15", "left_team": "A", "right_team": "B", "id": "1", "url": "/nba/2025/", "left_team_id": "1", "right_team_id": "2", "state": "0"},
                ]}}
            }
        }
        records = zhiboba_playoffs.parse_playoffs_data(payload, "2025")
        self.assertEqual(len(records), 1)

    def test_parse_playoffs_data_finals_list(self):
        payload = {
            "data": {
                "finals": [
                    {"schedule": {"list": [
                        {"date_str": "06-15", "time": "08:00", "date": "06-15", "left_team": "A", "right_team": "B", "id": "1", "url": "/nba/2025/", "left_team_id": "1", "right_team_id": "2", "state": "0"},
                    ]}}
                ]
            }
        }
        records = zhiboba_playoffs.parse_playoffs_data(payload, "2025")
        self.assertEqual(len(records), 1)

    def test_parse_playoffs_data_empty(self):
        self.assertEqual(len(zhiboba_playoffs.parse_playoffs_data({}, "2025")), 0)
        self.assertEqual(len(zhiboba_playoffs.parse_playoffs_data({"data": 123}, "2025")), 0)

    def test_sync_zhiboba_playoffs(self):
        db = MagicMock()
        http_client = MagicMock()
        http_client.get_json.return_value = {
            "data": {
                "top": [[{"schedule": {"list": [
                    {"date_str": "06-15", "time": "08:00", "date": "06-15", "left_team": "A", "right_team": "B", "id": "1", "url": "/nba/2025/", "left_team_id": "1", "right_team_id": "2", "state": "0"},
                ]}}]]
            }
        }

        with patch("app.modules.nba_schedule.zhiboba_playoffs.ensure_zhiboba_schedule_table"), \
             patch("app.modules.nba_schedule.zhiboba_playoffs.upsert_zhiboba_schedule_records", return_value=1):
            result = zhiboba_playoffs.sync_zhiboba_playoffs(db=db, http_client=http_client, year=2025)

        self.assertEqual(result["games"], 1)
        self.assertEqual(result["upserted"], 1)


# ==========================================================================
# nba_china_livetext helpers
# ==========================================================================

class TestNbaChinaLivetextHelpers(unittest.TestCase):
    def test_build_nba_china_pbp_params_defaults(self):
        params = nba_china_livetext.build_nba_china_pbp_params(game_id="0042500316", period=1)
        self.assertEqual(params["gameId"], "0042500316")
        self.assertEqual(params["period"], "1")
        self.assertEqual(params["app_key"], nba_china_livetext.NBA_CHINA_DEFAULT_APP_KEY)
        self.assertEqual(params["app_version"], nba_china_livetext.NBA_CHINA_DEFAULT_APP_VERSION)

    def test_parse_periods_single(self):
        result = nba_china_livetext.parse_periods("1,3,5")
        self.assertEqual(result, [1, 3, 5])

    def test_parse_periods_empty(self):
        self.assertIsNone(nba_china_livetext.parse_periods(None))
        self.assertIsNone(nba_china_livetext.parse_periods(""))

    def test_leading_score_pattern(self):
        self.assertIsNotNone(nba_china_livetext._LEADING_SCORE_PATTERN.match("[湖人 10-8] 詹姆斯跳投命中"))
        self.assertIsNone(nba_china_livetext._LEADING_SCORE_PATTERN.match("詹姆斯跳投命中"))

    def test_primary_player_pattern(self):
        m = nba_china_livetext._PRIMARY_PLAYER_PATTERN.match("詹姆斯 跳投命中")
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1), "詹姆斯")

    def test_assist_player_pattern(self):
        m = nba_china_livetext._ASSIST_PLAYER_PATTERN.search("助攻:戴维斯")
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1), "戴维斯")

    def test_block_player_pattern(self):
        m = nba_china_livetext._BLOCK_PLAYER_PATTERN.search("封盖:格林")
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1), "格林")

        m2 = nba_china_livetext._BLOCK_PLAYER_PATTERN.search("盖帽:格林")
        self.assertIsNotNone(m2)
        self.assertEqual(m2.group(1), "格林")

    def test_steal_player_pattern(self):
        m = nba_china_livetext._STEAL_PLAYER_PATTERN.search("抢断:库里")
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1), "库里")

    def test_line_skip_keywords_present(self):
        self.assertIn("本节比赛开始", nba_china_livetext.NBA_CHINA_LINE_SKIP_KEYWORDS)
        self.assertIn("暂停", nba_china_livetext.NBA_CHINA_LINE_SKIP_KEYWORDS)

    def test_default_sign2_is_constant(self):
        self.assertEqual(len(nba_china_livetext.NBA_CHINA_DEFAULT_SIGN2), 64)
        self.assertEqual(len(nba_china_livetext.NBA_CHINA_DEFAULT_DEVICE_ID), 32)


if __name__ == "__main__":
    unittest.main()