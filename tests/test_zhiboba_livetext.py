import unittest
from unittest.mock import Mock, patch

from app.modules.nba_live_text.nlp.tokenizer import TokenizeResult
from app.modules.nba_live_text.zhiboba_livetext import (
    CONTENT_REMOVE_RULE_TYPE,
    LINE_SKIP_RULE_TYPE,
    MATCH_MODE_CONTAINS,
    MATCH_MODE_EXACT,
    PlayerSegmentationConfig,
    TARGET_LIVE_TEXT,
    TARGET_PID_TEXT,
    LiveTextFilterRule,
    build_segmented_text,
    clean_live_text_for_tokenization,
    enrich_records_with_game_state,
    fetch_zhiboba_live_text_events,
    load_player_segmentation_config,
    normalize_player_tokens,
    parse_livetext_payload,
    sync_zhiboba_live_text,
)


class FakeTokenizer:
    instances: list["FakeTokenizer"] = []

    def __init__(self, *args, **kwargs) -> None:
        self.words: list[str] = []
        self.batch_calls: list[tuple[list[str], set[str] | None]] = []
        type(self).instances.append(self)

    def add_words(self, words: list[str]) -> None:
        self.words = list(words)

    def tokenize_batch(self, texts: list[str], *, stopwords: set[str] | None = None) -> list[TokenizeResult]:
        self.batch_calls.append((list(texts), stopwords))
        return [TokenizeResult(tokens=[f"token-{idx}", "命中"]) for idx, _ in enumerate(texts, start=1)]


class FakeHttpClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.urls: list[str] = []
        self.headers: list[dict[str, str] | None] = []

    def get_json_with_status(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        allow_status_codes: set[int] | None = None,
    ):
        self.urls.append(url)
        self.headers.append(headers)
        return self.responses.pop(0)


class TestZhibobaLiveText(unittest.TestCase):
    def setUp(self) -> None:
        FakeTokenizer.instances = []

    def test_build_segmented_text(self) -> None:
        self.assertEqual(build_segmented_text(["艾顿", "跳赢了"]), "艾顿\\跳赢了")
        self.assertIsNone(build_segmented_text([]))

    def test_normalize_player_tokens(self) -> None:
        self.assertEqual(
            normalize_player_tokens(["追梦", "助攻", "库明加"], {"追梦": "德雷蒙德-格林", "库明加": "乔纳森-库明加"}),
            ["德雷蒙德-格林", "助攻", "乔纳森-库明加"],
        )

    def test_load_player_segmentation_config_merges_player_names_and_aliases(self) -> None:
        db = Mock()
        player_id_exists_result = Mock()
        player_id_exists_result.fetchone.return_value = Mock()
        alias_table_exists_result = Mock()
        alias_table_exists_result.fetchone.return_value = Mock()
        player_rows_result = Mock()
        player_rows_result.fetchall.return_value = [
            Mock(
                nba_player_name="德雷蒙德-格林",
                player_id="100",
                zhiboba_player_id="200",
                zhiboba_player_name="格林",
                player_name_alias="追梦/嘴哥",
            ),
            Mock(
                nba_player_name=None,
                player_id="101",
                zhiboba_player_id="201",
                zhiboba_player_name="艾顿",
                player_name_alias="顿宝",
            ),
        ]
        alias_rows_result = Mock()
        alias_rows_result.fetchall.return_value = [
            Mock(player_id="200", alias_name="追梦"),
            Mock(player_id="101", alias_name="状元顿"),
        ]
        db.execute.side_effect = [player_id_exists_result, alias_table_exists_result, player_rows_result, alias_rows_result]

        with patch("app.modules.nba_live_text.zhiboba_livetext._get_team_ids_for_saishi", return_value=("1", "2")):
            config = load_player_segmentation_config(db=db, saishi_id="1976690")

        self.assertEqual(
            config.words,
            ["嘴哥", "德雷蒙德-格林", "格林", "状元顿", "艾顿", "追梦", "顿宝"],
        )
        self.assertEqual(config.alias_to_full_name["追梦"], "德雷蒙德-格林")
        self.assertEqual(config.alias_to_full_name["格林"], "德雷蒙德-格林")
        self.assertEqual(config.alias_to_full_name["顿宝"], "艾顿")
        self.assertEqual(config.alias_to_full_name["状元顿"], "艾顿")

    def test_clean_live_text_for_tokenization(self) -> None:
        rules = [
            LiveTextFilterRule(
                rule_type=CONTENT_REMOVE_RULE_TYPE,
                target_field=TARGET_LIVE_TEXT,
                match_mode=MATCH_MODE_CONTAINS,
                filter_text="！",
            ),
            LiveTextFilterRule(
                rule_type=CONTENT_REMOVE_RULE_TYPE,
                target_field=TARGET_LIVE_TEXT,
                match_mode=MATCH_MODE_CONTAINS,
                filter_text="啊",
            ),
        ]
        self.assertEqual(clean_live_text_for_tokenization("艾顿跳赢了！！啊", rules), "艾顿跳赢了")
        self.assertEqual(
            clean_live_text_for_tokenization("湖人先得了两分！！[勇士0-2湖人]啊", rules),
            "湖人先得了两分",
        )
        self.assertEqual(
            clean_live_text_for_tokenization("@玉鼎山人里斯夫：3分钟失误2次——", rules),
            "3分钟失误2次——",
        )
        self.assertEqual(
            clean_live_text_for_tokenization("@ 萌神哦麦噶：库明加这么打有前途", rules),
            "库明加这么打有前途",
        )

    def test_parse_livetext_payload_skips_invalid_live_pid(self) -> None:
        payload = [
            {
                "saishi_id": "1976690",
                "live_sid": "1",
                "live_pid": "1",
                "pid_text": "第1节",
                "live_text": "艾顿跳赢了！！",
            },
            {
                "saishi_id": "1976690",
                "live_sid": "2",
                "live_pid": "-1",
                "pid_text": "节间",
                "live_text": "比赛即将继续",
            },
            {
                "saishi_id": "1976690",
                "live_sid": "3",
                "live_pid": "0",
                "pid_text": "无效",
                "live_text": "这条不要",
            },
            {
                "saishi_id": "1976690",
                "live_sid": "4",
                "live_pid": "-9",
                "pid_text": "未赛",
                "live_text": "这条也不要",
            },
        ]

        records = parse_livetext_payload(payload)

        self.assertEqual([(record.live_sid, record.live_pid) for record in records], [(1, "1"), (2, "-1")])

    def test_filter_live_text_records_skips_comment_lines_starting_with_at(self) -> None:
        records = parse_livetext_payload(
            [
                {
                    "saishi_id": "1976690",
                    "live_sid": "1",
                    "live_pid": "1",
                    "pid_text": "第1节",
                    "live_text": "@程哥丨：切特疯了",
                },
                {
                    "saishi_id": "1976690",
                    "live_sid": "2",
                    "live_pid": "1",
                    "pid_text": "第1节",
                    "live_text": "切特疯了",
                },
            ]
        )

        rules = [
            LiveTextFilterRule(
                rule_type=LINE_SKIP_RULE_TYPE,
                target_field=TARGET_LIVE_TEXT,
                match_mode="prefix",
                filter_text="@",
            )
        ]

        from app.modules.nba_live_text.zhiboba_livetext import filter_live_text_records

        filtered = filter_live_text_records(records, rules)

        self.assertEqual([r.live_sid for r in filtered], [2])

    def test_filter_live_text_records_skips_lines_when_live_text_contains_keyword(self) -> None:
        records = parse_livetext_payload(
            [
                {
                    "saishi_id": "1976690",
                    "live_sid": "1",
                    "live_pid": "1",
                    "pid_text": "第1节",
                    "live_text": "裁判响哨了，给了防守犯规",
                },
                {
                    "saishi_id": "1976690",
                    "live_sid": "2",
                    "live_pid": "1",
                    "pid_text": "第1节",
                    "live_text": "申京篮下强打命中",
                },
            ]
        )

        rules = [
            LiveTextFilterRule(
                rule_type=LINE_SKIP_RULE_TYPE,
                target_field=TARGET_LIVE_TEXT,
                match_mode=MATCH_MODE_CONTAINS,
                filter_text="裁判",
            )
        ]

        from app.modules.nba_live_text.zhiboba_livetext import filter_live_text_records

        filtered = filter_live_text_records(records, rules)

        self.assertEqual([r.live_sid for r in filtered], [2])

    def test_enrich_records_with_game_state_calculates_score_changes(self) -> None:
        records = parse_livetext_payload(
            [
                {
                    "saishi_id": "1976690",
                    "live_sid": "10",
                    "live_pid": "1",
                    "pid_text": "第1节",
                    "live_text": "跳球",
                    "home_score": "0",
                    "visit_score": "0",
                    "user_chn": None,
                },
                {
                    "saishi_id": "1976690",
                    "live_sid": "11",
                    "live_pid": "1",
                    "pid_text": "第1节",
                    "live_text": "詹姆斯上篮命中",
                    "home_score": "2",
                    "visit_score": "0",
                    "user_chn": "詹姆斯",
                },
                {
                    "saishi_id": "1976690",
                    "live_sid": "12",
                    "live_pid": "1",
                    "pid_text": "第1节",
                    "live_text": "库里三分命中",
                    "home_score": "2",
                    "visit_score": "3",
                    "user_chn": "库里",
                },
            ]
        )

        enriched = enrich_records_with_game_state(db=object(), records=records)

        self.assertEqual(enriched[0].score_diff, 0)
        self.assertIsNone(enriched[0].score_points)
        self.assertEqual(enriched[1].home_score_change, 2)
        self.assertEqual(enriched[1].visit_score_change, 0)
        self.assertEqual(enriched[1].score_team_side, "home")
        self.assertEqual(enriched[1].score_points, 2)
        self.assertEqual(enriched[1].score_diff, 2)
        self.assertEqual(enriched[2].home_score_change, 0)
        self.assertEqual(enriched[2].visit_score_change, 3)
        self.assertEqual(enriched[2].score_team_side, "visit")
        self.assertEqual(enriched[2].score_points, 3)
        self.assertEqual(enriched[2].score_diff, -1)

    def test_fetch_only_syncs_raw_events_with_default_cursor_rule(self) -> None:
        payload = [
            {
                "saishi_id": "1976690",
                "live_sid": "1",
                "live_pid": "1",
                "pid_text": "第1节",
                "live_text": "比赛开始",
                "home_score": "0",
                "visit_score": "0",
                "user_chn": None,
            },
            {
                "saishi_id": "1976690",
                "live_sid": "2",
                "live_pid": "0",
                "pid_text": "第1节",
                "live_text": "这条不要",
                "home_score": "2",
                "visit_score": "0",
                "user_chn": None,
            },
            {
                "saishi_id": "1976690",
                "live_sid": "3",
                "live_pid": "2",
                "pid_text": "比赛结束",
                "live_text": "湖人先得了两分！！[勇士0-2湖人]",
                "home_score": "2",
                "visit_score": "0",
                "user_chn": None,
            },
        ]
        http_client = FakeHttpClient(responses=[(200, payload)])
        upserted_records = []

        with (
            patch("app.modules.nba_live_text.zhiboba_livetext.ensure_live_text_tables"),
            patch("app.modules.nba_live_text.zhiboba_livetext.load_live_text_filter_rules", return_value=[]),
            patch(
                "app.modules.nba_live_text.zhiboba_livetext.upsert_live_text_events",
                side_effect=lambda db, records: upserted_records.extend(records) or len(records),
            ),
        ):
            result = fetch_zhiboba_live_text_events(db=object(), http_client=http_client, saishi_id="1976690")

        self.assertEqual(result["pages"], 1)
        self.assertEqual(result["events"], 2)
        self.assertTrue(result["finished"])
        self.assertEqual(result["last_cursor"], 4)
        self.assertEqual([record.live_sid for record in upserted_records], [1, 3])
        self.assertIsNone(upserted_records[0].score_points)
        self.assertEqual(upserted_records[0].score_diff, 0)
        self.assertEqual(upserted_records[1].score_team_side, "home")
        self.assertEqual(upserted_records[1].score_points, 2)
        self.assertEqual(upserted_records[1].score_diff, 2)
        self.assertEqual(http_client.urls[0].endswith("/1.json"), True)

    def test_sync_batches_tokenization_and_stops_on_game_finished(self) -> None:
        payload = [
            {
                "saishi_id": "1976690",
                "live_sid": "1650",
                "live_pid": "4",
                "pid_text": "第四节",
                "live_text": "詹姆斯突破上篮命中",
                "home_score": "101",
                "visit_score": "99",
                "user_chn": "詹姆斯",
            },
            {
                "saishi_id": "1976690",
                "live_sid": "1651",
                "live_pid": "4",
                "pid_text": "比赛结束",
                "live_text": "库里三分命中",
                "home_score": "101",
                "visit_score": "102",
                "user_chn": "库里",
            },
        ]
        http_client = FakeHttpClient(responses=[(200, payload), (200, [])])

        with (
            patch("app.modules.nba_live_text.zhiboba_livetext.Tokenizer", FakeTokenizer),
            patch(
                "app.modules.nba_live_text.zhiboba_livetext.load_player_segmentation_config",
                return_value=PlayerSegmentationConfig(
                    words=["詹姆斯", "库里"],
                    alias_to_full_name={},
                ),
            ),
            patch("app.modules.nba_live_text.zhiboba_livetext.ensure_live_text_tables"),
            patch("app.modules.nba_live_text.zhiboba_livetext.load_live_text_filter_rules", return_value=[]),
            patch("app.modules.nba_live_text.zhiboba_livetext.upsert_live_text_events", side_effect=lambda db, records: len(records)),
        ):
            result = sync_zhiboba_live_text(db=object(), http_client=http_client, saishi_id="1976690")

        self.assertEqual(result["pages"], 1)
        self.assertEqual(result["events"], 2)
        self.assertTrue(result["finished"])
        self.assertEqual(result["last_cursor"], 3)
        self.assertEqual(FakeTokenizer.instances[0].words, ["詹姆斯", "库里"])
        self.assertEqual(
            FakeTokenizer.instances[0].batch_calls[0][0],
            ["詹姆斯突破上篮命中", "库里三分命中"],
        )
        self.assertEqual(http_client.headers[0]["referer"], "https://www.qiumibao.com/")

    def test_sync_filters_pending_records_and_returns_segmented_examples(self) -> None:
        payload = [
            {
                "saishi_id": "1976690",
                "live_sid": "-9",
                "live_pid": "-9",
                "pid_text": "未赛",
                "live_text": "湖人勇士赶紧跳球！！！",
                "home_score": "0",
                "visit_score": "0",
                "user_chn": None,
            },
            {
                "saishi_id": "1976690",
                "live_sid": "-8",
                "live_pid": "-8",
                "pid_text": "中场休息",
                "live_text": "两队回到更衣室调整。",
                "home_score": "55",
                "visit_score": "52",
                "user_chn": None,
            },
            {
                "saishi_id": "1976690",
                "live_sid": "1",
                "live_pid": "1",
                "pid_text": "第1节",
                "live_text": "艾顿跳赢了！！[湖人0-0太阳]",
                "home_score": "0",
                "visit_score": "0",
                "user_chn": "顿宝",
            },
            {
                "saishi_id": "1976690",
                "live_sid": "2",
                "live_pid": "0",
                "pid_text": "第1节",
                "live_text": "这条不要进入分词",
                "home_score": "0",
                "visit_score": "0",
                "user_chn": None,
            },
        ]
        http_client = FakeHttpClient(responses=[(200, payload), (200, [])])
        upserted_records = []

        class PendingFilterTokenizer(FakeTokenizer):
            def tokenize_batch(self, texts: list[str], *, stopwords: set[str] | None = None) -> list[TokenizeResult]:
                self.batch_calls.append((list(texts), stopwords))
                return [TokenizeResult(tokens=["顿宝", "跳赢了"])]

        with (
            patch("app.modules.nba_live_text.zhiboba_livetext.Tokenizer", PendingFilterTokenizer),
            patch(
                "app.modules.nba_live_text.zhiboba_livetext.load_player_segmentation_config",
                return_value=PlayerSegmentationConfig(
                    words=["艾顿", "顿宝"],
                    alias_to_full_name={"顿宝": "艾顿"},
                ),
            ),
            patch("app.modules.nba_live_text.zhiboba_livetext.ensure_live_text_tables"),
            patch(
                "app.modules.nba_live_text.zhiboba_livetext.load_live_text_filter_rules",
                return_value=[
                    LiveTextFilterRule(
                        rule_type=LINE_SKIP_RULE_TYPE,
                        target_field=TARGET_PID_TEXT,
                        match_mode=MATCH_MODE_EXACT,
                        filter_text="未赛",
                    ),
                    LiveTextFilterRule(
                        rule_type=LINE_SKIP_RULE_TYPE,
                        target_field=TARGET_PID_TEXT,
                        match_mode=MATCH_MODE_EXACT,
                        filter_text="中场休息",
                    ),
                    LiveTextFilterRule(
                        rule_type=CONTENT_REMOVE_RULE_TYPE,
                        target_field=TARGET_LIVE_TEXT,
                        match_mode=MATCH_MODE_CONTAINS,
                        filter_text="！",
                    ),
                ],
            ),
            patch(
                "app.modules.nba_live_text.zhiboba_livetext.upsert_live_text_events",
                side_effect=lambda db, records: upserted_records.extend(records) or len(records),
            ),
        ):
            result = sync_zhiboba_live_text(db=object(), http_client=http_client, saishi_id="1976690")

        self.assertEqual(result["filtered"], 2)
        self.assertEqual(result["events"], 1)
        self.assertEqual(PendingFilterTokenizer.instances[0].batch_calls[0][0], ["艾顿跳赢了"])
        self.assertEqual(len(upserted_records), 1)
        self.assertEqual(upserted_records[0].pid_text, "第1节")
        self.assertEqual(upserted_records[0].segmented_text, "艾顿\\跳赢了")
        self.assertEqual(upserted_records[0].current_player_name, "艾顿")
        self.assertEqual(upserted_records[0].score_diff, 0)
        self.assertEqual(
            result["segmented_examples"],
            [
                {
                    "live_sid": 1,
                    "pid_text": "第1节",
                    "live_text": "艾顿跳赢了！！[湖人0-0太阳]",
                    "cleaned_text": "艾顿跳赢了",
                    "segmented_text": "艾顿\\跳赢了",
                    "current_player_name": "艾顿",
                    "score_team_side": "",
                    "score_points": None,
                    "score_diff": 0,
                    "home_score_change": None,
                    "visit_score_change": None,
                    "home_score": 0,
                    "visit_score": 0,
                }
            ],
        )

    def test_sync_retries_with_incremented_cursor_after_404(self) -> None:
        payload = [
            {
                "saishi_id": "1976690",
                "live_sid": "1651",
                "live_pid": "4",
                "pid_text": "比赛结束",
                "live_text": "詹姆斯罚球命中",
                "home_score": "100",
                "visit_score": "98",
                "user_chn": "詹姆斯",
            }
        ]
        http_client = FakeHttpClient(responses=[(404, None), (200, payload)])

        with (
            patch("app.modules.nba_live_text.zhiboba_livetext.Tokenizer", FakeTokenizer),
            patch(
                "app.modules.nba_live_text.zhiboba_livetext.load_player_segmentation_config",
                return_value=PlayerSegmentationConfig(words=[], alias_to_full_name={}),
            ),
            patch("app.modules.nba_live_text.zhiboba_livetext.ensure_live_text_tables"),
            patch("app.modules.nba_live_text.zhiboba_livetext.load_live_text_filter_rules", return_value=[]),
            patch("app.modules.nba_live_text.zhiboba_livetext.upsert_live_text_events", return_value=1),
        ):
            result = sync_zhiboba_live_text(db=object(), http_client=http_client, saishi_id="1976690")

        self.assertEqual(len(http_client.urls), 2)
        self.assertTrue(http_client.urls[0].endswith("/1.json"))
        self.assertTrue(http_client.urls[1].endswith("/2.json"))
        self.assertEqual(http_client.headers[0]["origin"], "https://www.qiumibao.com")
        self.assertTrue(result["finished"])


if __name__ == "__main__":
    unittest.main()
