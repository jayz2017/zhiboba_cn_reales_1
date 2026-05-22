import re
import unittest
from unittest.mock import patch
from datetime import date

from app.modules.nba_schedule.zhiboba_schedule import build_zhiboba_schedule_params, parse_zhiboba_schedule


class TestZhibobaSchedule(unittest.TestCase):
    def test_build_params_dynamic_fields(self) -> None:
        params = build_zhiboba_schedule_params(year=2025)
        self.assertEqual(params["year"], "2025")
        
        # Test dynamic year calculation
        with patch('app.modules.nba_schedule.zhiboba_schedule.datetime') as mock_datetime:
            mock_datetime.now.return_value = date(2026, 5, 16) # Month < 9
            mock_datetime.side_effect = lambda *args, **kw: date(*args, **kw)
            
            params_auto = build_zhiboba_schedule_params()
            expected_year = str(date.today().year - 1) if date.today().month < 9 else str(date.today().year)
            self.assertEqual(params_auto["year"], expected_year)

        self.assertEqual(params["league_id"], "924")
        self.assertEqual(params["league"], "NBA")
        self.assertTrue(re.fullmatch(r"\d{13}", params["_t"]))

    def test_parse_payload_extracts_key_fields(self) -> None:
        payload = {
            "name": "nba",
            "type": "match",
            "data": [
                {
                    "title": "2025-06-26 周四",
                    "list": [
                        {
                            "saishi_id": "1628363",
                            "日期": "2025-06-26",
                            "时间": "08:00",
                            "homeId": "50001806",
                            "guestId": "50001687",
                            "is_finish": 1,
                            "赛事": "选秀大会",
                        }
                    ],
                }
            ],
        }

        records = parse_zhiboba_schedule(payload)
        self.assertEqual(len(records), 1)

        r = records[0]
        self.assertEqual(r.saishi_id, "1628363")
        self.assertEqual(r.game_date, date(2025, 6, 26))
        self.assertEqual(r.start_time, "08:00:00")
        self.assertEqual(r.home_id, "50001806")
        self.assertEqual(r.guest_id, "50001687")
        self.assertEqual(r.is_finish, 1)
        self.assertEqual(r.event_name, "选秀大会")


if __name__ == "__main__":
    unittest.main()
