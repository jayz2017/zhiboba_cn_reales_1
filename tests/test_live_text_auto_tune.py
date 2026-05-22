import unittest
from datetime import date, time
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app.modules.nba_live_text.auto_tune import (
    GameListAutoTuneTarget,
    apply_auto_tune_filter_rules,
    auto_tune_next_game_live_text,
    select_next_game_list_target,
    validate_live_text_segmentation_spec,
)
from app.modules.nba_live_text.zhiboba_livetext import (
    CONTENT_REMOVE_RULE_TYPE,
    MATCH_MODE_CONTAINS,
    TARGET_LIVE_TEXT,
    LiveTextFilterRule,
)


class TestLiveTextAutoTune(unittest.TestCase):
    def test_select_next_game_list_target(self) -> None:
        db = Mock()
        db.execute.return_value.fetchone.return_value = SimpleNamespace(
            saishi_id="1780738",
            home_team="湖人",
            visit_team="勇士",
            sdate=date(2025, 10, 22),
            start_time=time(10, 0, 0),
        )

        target = select_next_game_list_target(db=db)

        self.assertEqual(
            target,
            GameListAutoTuneTarget(
                saishi_id="1780738",
                home_team="湖人",
                visit_team="勇士",
                sdate=date(2025, 10, 22),
                start_time=time(10, 0, 0),
            ),
        )

    def test_apply_auto_tune_filter_rules_only_inserts_empty_cleaned_lines(self) -> None:
        db = Mock()
        db.execute.return_value.fetchall.return_value = [
            SimpleNamespace(live_text="！！！", hit_count=3),
            SimpleNamespace(live_text="正常文本", hit_count=1),
        ]

        with patch(
            "app.modules.nba_live_text.auto_tune.load_live_text_filter_rules",
            return_value=[
                LiveTextFilterRule(
                    rule_type=CONTENT_REMOVE_RULE_TYPE,
                    target_field=TARGET_LIVE_TEXT,
                    match_mode=MATCH_MODE_CONTAINS,
                    filter_text="！",
                )
            ],
        ):
            result = apply_auto_tune_filter_rules(db=db, saishi_id="1780738")

        self.assertEqual(result["applied_rule_count"], 1)
        self.assertEqual(result["applied_rules"], ["！！！"])
        self.assertTrue(db.commit.called)

    def test_validate_live_text_segmentation_spec_returns_violations(self) -> None:
        db = Mock()
        db.execute.side_effect = [
            Mock(fetchall=Mock(return_value=[SimpleNamespace(id=1, target_field="live_text", match_mode="contains", filter_text="裁判")])),
            Mock(scalar=Mock(return_value=2)),
            Mock(
                fetchall=Mock(
                    return_value=[
                        SimpleNamespace(
                            saishi_id="1780738",
                            live_sid=11,
                            pid_text="第1节",
                            live_text="裁判响哨了",
                            segmented_text="裁判\\响哨\\了",
                        )
                    ]
                )
            ),
        ]

        result = validate_live_text_segmentation_spec(db=db, saishi_id="1780738", sample_limit=5)

        self.assertFalse(result["passed"])
        self.assertTrue(result["needs_update_fetch_skill"])
        self.assertEqual(result["violation_rule_count"], 1)
        self.assertEqual(result["violation_summaries"][0]["filter_text"], "裁判")
        self.assertEqual(result["violation_examples"][0]["live_sid"], 11)

    def test_auto_tune_next_game_live_text_reruns_when_rules_applied(self) -> None:
        db = Mock()
        http_client = Mock()

        with (
            patch(
                "app.modules.nba_live_text.auto_tune.select_next_game_list_target",
                return_value=GameListAutoTuneTarget(
                    saishi_id="1780738",
                    home_team="湖人",
                    visit_team="勇士",
                    sdate=date(2025, 10, 22),
                    start_time=time(10, 0, 0),
                ),
            ),
            patch(
                "app.modules.nba_live_text.auto_tune.fetch_zhiboba_live_text_events",
                return_value={"pages": 3, "events": 100, "filtered": 2, "finished": True, "last_cursor": 101},
            ) as fetch_mock,
            patch(
                "app.modules.nba_live_text.auto_tune.sync_zhiboba_live_text",
                side_effect=[
                    {"pages": 3, "events": 100, "filtered": 2, "finished": True, "last_cursor": 101},
                    {"pages": 3, "events": 98, "filtered": 4, "finished": True, "last_cursor": 101},
                ],
            ) as sync_mock,
            patch(
                "app.modules.nba_live_text.auto_tune.apply_auto_tune_filter_rules",
                side_effect=[
                    {"applied_rule_count": 1, "applied_rules": ["！！！"]},
                    {"applied_rule_count": 0, "applied_rules": []},
                ],
            ),
            patch(
                "app.modules.nba_live_text.auto_tune.validate_live_text_segmentation_spec",
                side_effect=[
                    {"passed": False, "needs_update_fetch_skill": True, "violation_rule_count": 1, "violation_summaries": [], "violation_examples": []},
                    {"passed": True, "needs_update_fetch_skill": False, "violation_rule_count": 0, "violation_summaries": [], "violation_examples": []},
                ],
            ),
            patch(
                "app.modules.nba_live_text.auto_tune.purge_live_text_for_saishi",
                return_value={"deleted_events": 100},
            ),
            patch(
                "app.modules.nba_live_text.auto_tune.load_segmented_examples_by_saishi_id",
                return_value=[{"live_sid": 1, "pid_text": "第1节", "live_pid": "1", "live_text": "艾顿跳赢了", "segmented_text": "艾顿\\跳赢了"}],
            ),
        ):
            result = auto_tune_next_game_live_text(db=db, http_client=http_client, sample_limit=5)

        self.assertTrue(result["processed"])
        self.assertEqual(result["saishi_id"], "1780738")
        self.assertEqual(fetch_mock.call_count, 2)
        self.assertEqual(sync_mock.call_count, 2)
        self.assertIsNotNone(result["rerun_result"])
        self.assertEqual(result["attempt_count"], 2)
        self.assertEqual(result["stop_reason"], "validation_passed")

    def test_auto_tune_next_game_live_text_stops_without_dead_loop_when_validation_fails_without_new_rules(self) -> None:
        db = Mock()
        http_client = Mock()

        with (
            patch(
                "app.modules.nba_live_text.auto_tune.select_next_game_list_target",
                return_value=GameListAutoTuneTarget(
                    saishi_id="1780738",
                    home_team="湖人",
                    visit_team="勇士",
                    sdate=date(2025, 10, 22),
                    start_time=time(10, 0, 0),
                ),
            ),
            patch(
                "app.modules.nba_live_text.auto_tune.fetch_zhiboba_live_text_events",
                return_value={"pages": 3, "events": 100, "filtered": 2, "finished": True, "last_cursor": 101},
            ) as fetch_mock,
            patch(
                "app.modules.nba_live_text.auto_tune.sync_zhiboba_live_text",
                return_value={"pages": 3, "events": 100, "filtered": 2, "finished": True, "last_cursor": 101},
            ) as sync_mock,
            patch(
                "app.modules.nba_live_text.auto_tune.apply_auto_tune_filter_rules",
                return_value={"applied_rule_count": 0, "applied_rules": []},
            ),
            patch(
                "app.modules.nba_live_text.auto_tune.validate_live_text_segmentation_spec",
                return_value={"passed": False, "needs_update_fetch_skill": True, "violation_rule_count": 1, "violation_summaries": [], "violation_examples": []},
            ),
            patch(
                "app.modules.nba_live_text.auto_tune.load_segmented_examples_by_saishi_id",
                return_value=[],
            ),
        ):
            result = auto_tune_next_game_live_text(db=db, http_client=http_client, sample_limit=5, max_attempts=3)

        self.assertTrue(result["processed"])
        self.assertEqual(fetch_mock.call_count, 1)
        self.assertEqual(sync_mock.call_count, 1)
        self.assertEqual(result["attempt_count"], 1)
        self.assertEqual(result["stop_reason"], "validation_failed_without_new_rules")
        self.assertIsNone(result["rerun_result"])


if __name__ == "__main__":
    unittest.main()
