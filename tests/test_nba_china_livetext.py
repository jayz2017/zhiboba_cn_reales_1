import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.modules.nba_live_text.nlp.tokenizer import TokenizeResult
from app.modules.nba_live_text.nba_china_livetext import (
    build_nba_china_structured_relations,
    build_nba_china_live_sid,
    build_nba_china_pbp_params,
    extract_nba_china_player_relations,
    parse_nba_china_pbp_payload,
    parse_periods,
    sync_nba_china_live_text,
)
from app.modules.nba_live_text.zhiboba_livetext import LiveTextFilterRule, PlayerSegmentationConfig


class FakeTokenizer:
    instances = []

    def __init__(self, *args, **kwargs):
        self.words = []
        self.batch_calls = []
        type(self).instances.append(self)

    def add_words(self, words):
        self.words = list(words)

    def tokenize_batch(self, texts, *, stopwords=None):
        self.batch_calls.append(list(texts))
        return [TokenizeResult(tokens=text.split()) for text in texts]


class FakeHttpClient:
    def __init__(self, payload):
        self.payloads = list(payload) if isinstance(payload, list) else [payload]
        self.calls = []

    def get_json(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.payloads.pop(0)


class FakeDb:
    def execute(self, *args, **kwargs):
        return SimpleNamespace(fetchone=lambda: None, fetchall=lambda: [])

    def commit(self):
        return None


class _MappingResult:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return self

    def all(self):
        return self._rows


class ExtractFakeDb:
    def __init__(self, rows):
        self.rows = rows
        self.sql = []
        self.commits = 0

    def execute(self, sql, *args, **kwargs):
        sql_text = str(sql)
        self.sql.append(sql_text)
        if "SELECT *" in sql_text:
            return _MappingResult(self.rows)
        return SimpleNamespace(fetchone=lambda: None, fetchall=lambda: [], mappings=lambda: _MappingResult([]))

    def commit(self):
        self.commits += 1


class TestNbaChinaLiveText(unittest.TestCase):
    def setUp(self):
        FakeTokenizer.instances = []

    def test_build_params_uses_dynamic_timestamp(self):
        params = build_nba_china_pbp_params(game_id="0042500316", period=2, timestamp=1780026334)

        self.assertEqual(params["gameId"], "0042500316")
        self.assertEqual(params["period"], "2")
        self.assertEqual(params["t"], "1780026334")
        self.assertEqual(params["network"], "N/A")

    def test_build_live_sid_is_stable_and_global(self):
        self.assertEqual(build_nba_china_live_sid("0042500316", 332, 2), 42500316000332)

    def test_parse_payload_converts_plays_to_live_text_records(self):
        payload = {
            "code": 0,
            "data": {
                "data": {
                    "g": {
                        "pla": [
                            {
                                "period": 2,
                                "periodName": "第二节",
                                "evt": 327,
                                "de": "[马刺 53-60] 文班亚马 点拨上篮：命中 (22分) 助攻：福克斯 (2次助攻)",
                                "tid": 1610612759,
                                "pid": 1641705,
                                "hs": 60,
                                "vs": 53,
                                "pts": 2,
                            },
                            {
                                "period": 2,
                                "periodName": "第二节",
                                "evt": 332,
                                "de": "本节比赛结束",
                                "tid": 0,
                                "pid": 0,
                            },
                        ]
                    }
                }
            },
        }

        records = parse_nba_china_pbp_payload(
            payload,
            game_id="0042500316",
            player_names_by_id={"1641705": "维克托-文班亚马"},
        )

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].saishi_id, "0042500316")
        self.assertEqual(records[0].live_sid, 42500316000327)
        self.assertEqual(records[0].pid_text, "第二节")
        self.assertEqual(records[0].live_text, "[马刺 53-60] 文班亚马 点拨上篮：命中 (22分) 助攻：福克斯 (2次助攻)")
        self.assertEqual(records[0].home_score, 60)
        self.assertEqual(records[0].visit_score, 53)
        self.assertEqual(records[0].user_chn, "维克托-文班亚马")
        self.assertEqual(records[0].score_points, 2)

    def test_build_structured_relations_extracts_assist_and_block(self):
        rows = [
            {
                "id": 1,
                "saishi_id": "0042500316",
                "live_sid": 42500316000007,
                "live_text": "[马刺 0-3] 尚帕涅 三分投篮：命中 (3分) 助攻：卡斯尔 (1次助攻)",
                "segmented_text": "尚帕涅\\三分\\投篮\\命中\\助攻\\卡斯尔",
                "current_player_name": "尚帕涅",
                "score_points": 3,
                "score_team_side": "home",
                "home_score": 3,
                "visit_score": 0,
            },
            {
                "id": 2,
                "saishi_id": "0042500316",
                "live_sid": 42500316000013,
                "live_text": "麦凯恩 上篮：不中 封盖：文班亚马",
                "segmented_text": "麦凯恩\\上篮\\不中\\封盖\\文班亚马",
                "current_player_name": "麦凯恩",
                "score_points": None,
                "score_team_side": None,
                "home_score": 3,
                "visit_score": 0,
            },
        ]

        relations = build_nba_china_structured_relations(
            rows,
            PlayerSegmentationConfig(
                words=["尚帕涅", "卡斯尔", "麦凯恩", "文班亚马"],
                alias_to_full_name={},
            ),
        )

        simplified = {
            (relation.subject_player_name, relation.relation_type, relation.object_player_name)
            for relation in relations
        }
        self.assertIn(("卡斯尔", "assist_to", "尚帕涅"), simplified)
        self.assertIn(("文班亚马", "blocks", "麦凯恩"), simplified)

    def test_extract_prefers_structured_nba_china_event_relations(self):
        rows = [
            {
                "id": 1,
                "saishi_id": "0042500316",
                "live_sid": 42500316000007,
                "live_text": "[马刺 0-3] 尚帕涅 三分投篮：命中 (3分) 助攻：卡斯尔 (1次助攻)",
                "segmented_text": "尚帕涅\\三分\\投篮\\命中\\助攻\\卡斯尔",
                "current_player_name": "尚帕涅",
                "score_points": 3,
                "score_team_side": "home",
                "home_score": 3,
                "visit_score": 0,
            }
        ]
        upserted_relations = []

        with (
            patch("app.modules.nba_live_text.nba_china_livetext.ensure_live_text_tables"),
            patch("app.modules.nba_live_text.nba_china_livetext.ensure_player_relation_table"),
            patch("app.modules.nba_live_text.nba_china_livetext.ensure_relation_rule_config_tables"),
            patch(
                "app.modules.nba_live_text.nba_china_livetext.load_player_segmentation_config",
                return_value=PlayerSegmentationConfig(
                    words=["尚帕涅", "卡斯尔"],
                    alias_to_full_name={},
                ),
            ),
            patch(
                "app.modules.nba_live_text.nba_china_livetext.PlayerRelationRepository.bulk_upsert",
                side_effect=lambda relations, batch_size=500: upserted_relations.extend(relations) or len(relations),
            ),
        ):
            result = extract_nba_china_player_relations(
                db=ExtractFakeDb(rows),
                game_id="0042500316",
                sample_limit=5,
            )

        simplified = {
            (relation.subject_player_name, relation.relation_type, relation.object_player_name)
            for relation in upserted_relations
        }
        self.assertEqual(result["relations"], 1)
        self.assertIn(("卡斯尔", "assist_to", "尚帕涅"), simplified)
        self.assertNotIn(("尚帕涅", "scores_over", "卡斯尔"), simplified)

    def test_parse_periods(self):
        self.assertIsNone(parse_periods(None))
        self.assertIsNone(parse_periods(""))
        self.assertEqual(parse_periods("2, 3"), [2, 3])

    def test_sync_tokenizes_and_upserts_records(self):
        payload = {
            "data": {
                "data": {
                    "g": {
                        "pla": [
                            {
                                "period": 2,
                                "periodName": "第二节",
                                "evt": 327,
                                "de": "[马刺 53-60] 文班亚马 点拨上篮：命中 (22分) 助攻：福克斯 (2次助攻)",
                                "tid": 1610612759,
                                "pid": 1641705,
                                "hs": 60,
                                "vs": 53,
                            }
                        ]
                    }
                }
            }
        }
        upserted = []

        with (
            patch("app.modules.nba_live_text.nba_china_livetext.Tokenizer", FakeTokenizer),
            patch("app.modules.nba_live_text.nba_china_livetext.ensure_live_text_tables"),
            patch("app.modules.nba_live_text.nba_china_livetext.load_nba_player_names_by_id", return_value={}),
            patch(
                "app.modules.nba_live_text.nba_china_livetext.load_player_segmentation_config",
                return_value=PlayerSegmentationConfig(words=["文班亚马", "福克斯"], alias_to_full_name={}),
            ),
            patch("app.modules.nba_live_text.nba_china_livetext.load_live_text_filter_rules", return_value=[]),
            patch(
                "app.modules.nba_live_text.nba_china_livetext.upsert_live_text_events",
                side_effect=lambda db, records: upserted.extend(records) or len(records),
            ),
        ):
            result = sync_nba_china_live_text(
                db=FakeDb(),
                http_client=FakeHttpClient(payload),
                game_id="0042500316",
                periods=[2],
            )

        self.assertEqual(result["events"], 1)
        self.assertEqual(result["upserted"], 1)
        self.assertEqual(FakeTokenizer.instances[0].words, ["文班亚马", "福克斯"])
        self.assertEqual(len(upserted), 1)
        self.assertIsNotNone(upserted[0].segmented_text)

    def test_sync_does_not_remove_filter_word_inside_player_name(self):
        payload = {
            "data": {
                "data": {
                    "g": {
                        "pla": [
                            {
                                "period": 1,
                                "periodName": "第一节",
                                "evt": 9,
                                "de": "[雷霆 2-3] 哈尔滕施泰因 漂移跳投：命中 (2分) 助攻：麦凯恩 (1次助攻)",
                                "tid": 1610612760,
                                "pid": 123,
                                "hs": 3,
                                "vs": 2,
                                "pts": 2,
                            }
                        ]
                    }
                }
            }
        }
        upserted = []

        with (
            patch("app.modules.nba_live_text.nba_china_livetext.Tokenizer", FakeTokenizer),
            patch("app.modules.nba_live_text.nba_china_livetext.ensure_live_text_tables"),
            patch("app.modules.nba_live_text.nba_china_livetext.load_nba_player_names_by_id", return_value={}),
            patch(
                "app.modules.nba_live_text.nba_china_livetext.load_player_segmentation_config",
                return_value=PlayerSegmentationConfig(
                    words=["麦凯恩"],
                    alias_to_full_name={"哈尔滕施泰因": "哈尔滕施泰因", "麦凯恩": "麦凯恩"},
                ),
            ),
            patch(
                "app.modules.nba_live_text.nba_china_livetext.load_live_text_filter_rules",
                return_value=[
                    LiveTextFilterRule(
                        rule_type="content_remove",
                        target_field="live_text",
                        match_mode="contains",
                        filter_text="哈",
                    )
                ],
            ),
            patch(
                "app.modules.nba_live_text.nba_china_livetext.upsert_live_text_events",
                side_effect=lambda db, records: upserted.extend(records) or len(records),
            ),
        ):
            result = sync_nba_china_live_text(
                db=FakeDb(),
                http_client=FakeHttpClient(payload),
                game_id="0042500316",
                periods=[1],
            )

        self.assertEqual(result["events"], 1)
        self.assertIn("哈尔滕施泰因", FakeTokenizer.instances[0].batch_calls[0][0])

    def test_sync_auto_increments_period_until_empty_pla(self):
        period_one_payload = {
            "data": {
                "data": {
                    "g": {
                        "pla": [
                            {
                                "period": 1,
                                "periodName": "第一节",
                                "evt": 1,
                                "de": "文班亚马 跳投：不中",
                                "tid": 1610612759,
                                "pid": 1641705,
                                "hs": 0,
                                "vs": 0,
                            }
                        ]
                    }
                }
            }
        }
        empty_payload = {"data": {"data": {"g": {"pla": []}}}}
        upserted = []

        with (
            patch("app.modules.nba_live_text.nba_china_livetext.Tokenizer", FakeTokenizer),
            patch("app.modules.nba_live_text.nba_china_livetext.ensure_live_text_tables"),
            patch("app.modules.nba_live_text.nba_china_livetext.load_nba_player_names_by_id", return_value={}),
            patch(
                "app.modules.nba_live_text.nba_china_livetext.load_player_segmentation_config",
                return_value=PlayerSegmentationConfig(words=["文班亚马"], alias_to_full_name={}),
            ),
            patch("app.modules.nba_live_text.nba_china_livetext.load_live_text_filter_rules", return_value=[]),
            patch(
                "app.modules.nba_live_text.nba_china_livetext.upsert_live_text_events",
                side_effect=lambda db, records: upserted.extend(records) or len(records),
            ),
        ):
            http_client = FakeHttpClient([period_one_payload, empty_payload])
            result = sync_nba_china_live_text(
                db=FakeDb(),
                http_client=http_client,
                game_id="0042500316",
                periods=None,
                max_auto_period=5,
            )

        self.assertEqual([call[1]["params"]["period"] for call in http_client.calls], ["1", "2"])
        self.assertEqual(result["periods"], [1])
        self.assertEqual(result["attempted_periods"], [1, 2])
        self.assertEqual(result["stop_period"], 2)
        self.assertEqual(result["stop_reason"], "empty_pla")
        self.assertEqual(result["events"], 1)
        self.assertEqual(len(upserted), 1)


if __name__ == "__main__":
    unittest.main()
