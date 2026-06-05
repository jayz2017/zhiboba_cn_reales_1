"""
增量抽取服务 (incremental_service.py) 单元测试

测试 ExtractionProgressTracker 和 IncrementalExtractorService 的核心逻辑，
通过 Mock DB 层实现快速、无外部依赖的验证。
"""

import unittest
from unittest.mock import MagicMock, patch

from app.modules.semantics.incremental_service import (
    ExtractionProgress,
    ExtractionProgressTracker,
    IncrementalExtractResult,
    IncrementalExtractorService,
)


# ---------------------------------------------------------------------------
# Fake DB helpers
# ---------------------------------------------------------------------------

class _FakeRow(dict):
    """模拟 SQLAlchemy RowMapping——同时支持 dict[key] 和 attr.key 访问。"""

    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError:
            raise AttributeError(name)


def _fake_mapping_row(**kwargs):
    """构建一个支持 .mappings() 链式调用的假行结果。"""
    mapping = _FakeRow(**kwargs)
    fake = MagicMock()
    fake.mappings.return_value = mapping
    return fake


def _fake_mapping_rows(rows: list[dict]):
    """构建一个返回多行映射结果的假对象。"""
    mappings = [_FakeRow(**r) for r in rows]
    fake = MagicMock()
    fake.mappings.return_value = fake
    fake.all.return_value = mappings
    return fake


def _make_progress_row(**overrides):
    defaults = {
        "saishi_id": "1780736",
        "last_processed_live_sid": 100,
        "total_relations": 42,
        "total_events_processed": 200,
        "backend_used": "rule_based",
        "extraction_status": "completed",
        "last_extracted_at": "2026-01-01T00:00:00+00:00",
        "created_at": "2026-01-01T00:00:00+00:00",
        "updated_at": "2026-01-01T00:00:00+00:00",
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# ExtractionProgressTracker tests
# ---------------------------------------------------------------------------

class TestExtractionProgressTracker(unittest.TestCase):
    """ExtractionProgressTracker 的单元测试——通过 FakeDb 模拟数据库交互。"""

    def setUp(self):
        self.tracker = ExtractionProgressTracker()

    def test_get_progress_returns_progress_when_row_exists(self):
        """当进度记录存在时，返回完整的 ExtractionProgress 对象。"""
        db = MagicMock()
        row = _make_progress_row()
        db.execute.return_value = _fake_mapping_row(one_or_none=lambda: _FakeRow(**row))

        result = self.tracker.get_progress(db, "1780736")

        self.assertIsNotNone(result)
        self.assertEqual(result.saishi_id, "1780736")
        self.assertEqual(result.last_processed_live_sid, 100)
        self.assertEqual(result.total_relations, 42)
        self.assertEqual(result.total_events_processed, 200)
        self.assertEqual(result.backend_used, "rule_based")
        self.assertEqual(result.extraction_status, "completed")

    def test_get_progress_returns_none_when_no_row(self):
        """当进度记录不存在时，返回 None。"""
        db = MagicMock()
        db.execute.return_value = _fake_mapping_row(one_or_none=lambda: None)

        result = self.tracker.get_progress(db, "1780736")

        self.assertIsNone(result)

    def test_get_progress_handles_null_last_processed_live_sid(self):
        """当 last_processed_live_sid 为 NULL 时，返回 None。"""
        db = MagicMock()
        row = _make_progress_row(last_processed_live_sid=None)
        db.execute.return_value = _fake_mapping_row(one_or_none=lambda: _FakeRow(**row))

        result = self.tracker.get_progress(db, "1780736")

        self.assertIsNone(result.last_processed_live_sid)

    def test_update_progress_calls_execute_and_commit(self):
        """update_progress 应调用 db.execute 和 db.commit。"""
        db = MagicMock()
        self.tracker.update_progress(
            db, "1780736",
            last_processed_live_sid=200,
            total_relations=50,
            total_events_processed=250,
            backend_used="rule_based",
            extraction_status="completed",
        )

        db.execute.assert_called_once()
        db.commit.assert_called_once()

    def test_update_progress_rolls_back_on_error(self):
        """update_progress 出错时应回滚。"""
        db = MagicMock()
        db.execute.side_effect = RuntimeError("db error")

        with self.assertRaises(RuntimeError):
            self.tracker.update_progress(db, "1780736")
        db.rollback.assert_called_once()

    def test_reset_progress_calls_execute_and_commit(self):
        """reset_progress 应调用 db.execute 并提交。"""
        db = MagicMock()
        self.tracker.reset_progress(db, "1780736")

        db.execute.assert_called_once()
        db.commit.assert_called_once()

    def test_get_unprocessed_events_uses_all_events_when_no_progress(self):
        """没有进度记录时，应查询全部事件（全量模式）。"""
        db = MagicMock()
        # get_progress → None
        db.execute.side_effect = [
            _fake_mapping_row(one_or_none=lambda: None),  # get_progress
            _fake_mapping_rows([{"live_sid": 1, "segmented_text": "a\\b"}, {"live_sid": 2, "segmented_text": "c\\d"}]),  # get events
        ]

        result = self.tracker.get_unprocessed_events(db, "1780736", max_rows=10)

        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["live_sid"], 1)
        self.assertEqual(result[1]["live_sid"], 2)

    def test_get_unprocessed_events_uses_incremental_sql_when_progress_exists(self):
        """有进度记录时，应使用增量 SQL（live_sid > last_processed_live_sid）。"""
        db = MagicMock()
        progress_row = _make_progress_row(last_processed_live_sid=50)
        db.execute.side_effect = [
            _fake_mapping_row(one_or_none=lambda: _FakeRow(**progress_row)),  # get_progress
            _fake_mapping_rows([{"live_sid": 51, "segmented_text": "a\\b"}]),  # get events
        ]

        result = self.tracker.get_unprocessed_events(db, "1780736", max_rows=10)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["live_sid"], 51)

    def test_get_total_events_count_returns_count(self):
        """应正确返回总事件计数。"""
        db = MagicMock()
        db.execute.return_value = _fake_mapping_row(one=lambda: _FakeRow(cnt=500))

        result = self.tracker.get_total_events_count(db, "1780736")

        self.assertEqual(result, 500)


# ---------------------------------------------------------------------------
# IncrementalExtractorService tests
# ---------------------------------------------------------------------------

class TestIncrementalExtractorService(unittest.TestCase):
    """IncrementalExtractorService 的核心逻辑测试——通过 patch 隔离底层抽取。"""

    def setUp(self):
        self.service = IncrementalExtractorService(
            default_max_rows=100,
            default_batch_size=10,
            default_timeout_seconds=60.0,
        )

    def _make_db_for_progress(self, progress_row: dict | None, total_events: int = 0, unprocessed: list | None = None):
        """构建一个模拟 DB，支持进度查询、事件计数、未处理事件获取。"""
        db = MagicMock()

        if unprocessed is None:
            unprocessed = []

        def _execute_side_effect(sql, *args, **kwargs):
            sql_str = str(sql)
            fake = MagicMock()
            if "nba_zhiboba_extraction_progress" in sql_str and "SELECT" in sql_str.upper():
                if progress_row:
                    fake.mappings.return_value = fake
                    fake.one_or_none.return_value = _FakeRow(**progress_row)
                else:
                    fake.mappings.return_value = fake
                    fake.one_or_none.return_value = None
            elif "COUNT(*)" in sql_str:
                fake.mappings.return_value = fake
                fake.one.return_value = _FakeRow(cnt=total_events)
            elif "SELECT *" in sql_str and "nba_zhiboba_live_text_event" in sql_str:
                fake.mappings.return_value = fake
                fake.all.return_value = [_FakeRow(**r) for r in unprocessed]
            else:
                # INSERT/UPDATE/DELETE
                pass
            return fake

        db.execute.side_effect = _execute_side_effect
        return db

    def _make_event(self, live_sid: int, text: str = "a\\b"):
        return {"live_sid": live_sid, "segmented_text": text, "saishi_id": "1780736", "source": "zhiboba"}

    # ---- extract_incremental ----

    def test_extract_incremental_first_extraction(self):
        """首次抽取：is_first_extraction=True, is_incremental=False, 处理全部事件。"""
        events = [self._make_event(1), self._make_event(2)]
        db = self._make_db_for_progress(
            progress_row=None,
            total_events=2,
            unprocessed=events,
        )

        with patch.object(self.service, "_do_extract", return_value=(5, "rule_based", None)):
            result = self.service.extract_incremental(db, "1780736", max_rows=100)

        self.assertTrue(result.is_first_extraction)
        self.assertFalse(result.is_incremental)
        self.assertEqual(result.new_events_count, 2)
        self.assertEqual(result.relations_inserted, 5)
        self.assertEqual(result.backend, "rule_based")
        self.assertEqual(result.progress_pct, 100.0)
        self.assertIsNone(result.error_message)

    def test_extract_incremental_second_run_finds_no_new_events(self):
        """第二次增量抽取：无新事件时，new_events_count=0 且 is_incremental=True。"""
        progress_row = _make_progress_row(last_processed_live_sid=100, total_events_processed=50)
        db = self._make_db_for_progress(
            progress_row=progress_row,
            total_events=50,
            unprocessed=[],
        )

        with patch.object(self.service, "_do_extract", return_value=(0, None, None)):
            result = self.service.extract_incremental(db, "1780736", max_rows=100)

        self.assertFalse(result.is_first_extraction)
        self.assertTrue(result.is_incremental)
        self.assertEqual(result.new_events_count, 0)
        self.assertEqual(result.relations_inserted, 0)
        self.assertIsNone(result.error_message)

    def test_extract_incremental_has_new_events(self):
        """增量模式下有新事件时，应正确抽取并更新进度。"""
        progress_row = _make_progress_row(last_processed_live_sid=50, total_events_processed=50)
        new_events = [self._make_event(51), self._make_event(52), self._make_event(53)]
        db = self._make_db_for_progress(
            progress_row=progress_row,
            total_events=53,
            unprocessed=new_events,
        )

        with patch.object(self.service, "_do_extract", return_value=(3, "rule_based", None)):
            result = self.service.extract_incremental(db, "1780736", max_rows=100)

        self.assertFalse(result.is_first_extraction)
        self.assertTrue(result.is_incremental)
        self.assertEqual(result.new_events_count, 3)
        self.assertEqual(result.relations_inserted, 3)
        self.assertEqual(result.total_events_to_date, 53)

    def test_extract_incremental_force_full(self):
        """force_full=True 时应重置进度，以全量模式重新抽取。"""
        events = [self._make_event(1), self._make_event(2)]
        db = self._make_db_for_progress(
            progress_row=None,
            total_events=2,
            unprocessed=events,
        )

        with patch.object(self.service, "_do_extract", return_value=(10, "rule_based", None)):
            result = self.service.extract_incremental(db, "1780736", force_full=True, max_rows=100)

        self.assertTrue(result.is_first_extraction)
        self.assertFalse(result.is_incremental)
        self.assertEqual(result.new_events_count, 2)

    def test_extract_incremental_handles_exception_gracefully(self):
        """抽取过程中发生异常时，应返回带 error_message 的结果而非抛出。"""
        db = self._make_db_for_progress(
            progress_row=None,
            total_events=10,
            unprocessed=[self._make_event(1)],
        )

        with patch.object(self.service, "_do_extract", side_effect=RuntimeError("extraction failed")):
            result = self.service.extract_incremental(db, "1780736", max_rows=100)

        self.assertIsNotNone(result.error_message)
        self.assertIn("extraction failed", result.error_message)
        self.assertEqual(result.relations_inserted, 0)
        self.assertEqual(result.new_events_count, 0)

    # ---- extract_batch_incremental ----

    def test_extract_batch_incremental_processes_all_ids(self):
        """批量抽取应处理所有比赛ID，返回等长结果列表。"""
        db = MagicMock()

        def _fake_extract(db, saishi_id, **opts):
            return IncrementalExtractResult(
                saishi_id=saishi_id,
                is_incremental=False,
                is_first_extraction=True,
                new_events_count=5,
                total_events_to_date=5,
                progress_pct=50.0,
                relations_inserted=3,
                backend="rule_based",
                samples=None,
                error_message=None,
                elapsed_seconds=0.1,
            )

        with patch.object(self.service, "extract_incremental", side_effect=_fake_extract):
            results = self.service.extract_batch_incremental(db, ["A", "B", "C"])

        self.assertEqual(len(results), 3)
        self.assertEqual([r.saishi_id for r in results], ["A", "B", "C"])
        for r in results:
            self.assertIsNone(r.error_message)

    def test_extract_batch_incremental_isolates_errors(self):
        """批量抽取中，单场失败不应中断后续场次，失败信息应记录在 error_message 中。"""
        db = MagicMock()

        def _fake_extract(db, saishi_id, **opts):
            if saishi_id == "B":
                return IncrementalExtractResult(
                    saishi_id=saishi_id,
                    is_incremental=False,
                    error_message="Extraction failed for B",
                    elapsed_seconds=0.0,
                )
            return IncrementalExtractResult(
                saishi_id=saishi_id,
                is_incremental=False,
                is_first_extraction=True,
                new_events_count=5,
                total_events_to_date=5,
                progress_pct=50.0,
                relations_inserted=3,
                backend="rule_based",
                elapsed_seconds=0.1,
            )

        with patch.object(self.service, "extract_incremental", side_effect=_fake_extract):
            results = self.service.extract_batch_incremental(db, ["A", "B", "C"])

        self.assertEqual(len(results), 3)
        self.assertIsNone(results[0].error_message)
        self.assertIsNotNone(results[1].error_message)
        self.assertIn("failed for B", results[1].error_message)
        self.assertIsNone(results[2].error_message)

    # ---- extract_parallel ----

    @patch("app.core.database.SessionLocal")
    def test_extract_parallel_runs_all_games_concurrently(self, mock_session_local):
        """并行抽取应处理所有比赛ID，返回等长结果列表。"""
        mock_session = MagicMock()
        mock_session_local.return_value = mock_session

        def _fake_extract(thread_db, saishi_id, **opts):
            return IncrementalExtractResult(
                saishi_id=saishi_id,
                is_incremental=False,
                is_first_extraction=True,
                new_events_count=3,
                total_events_to_date=3,
                progress_pct=100.0,
                relations_inserted=2,
                backend="rule_based",
                elapsed_seconds=0.05,
            )

        with patch.object(self.service, "extract_incremental", side_effect=_fake_extract):
            results = self.service.extract_parallel(
                MagicMock(), ["X", "Y", "Z"], max_workers=2
            )

        self.assertEqual(len(results), 3)
        self.assertEqual({r.saishi_id for r in results}, {"X", "Y", "Z"})
        for r in results:
            self.assertIsNone(r.error_message)

    @patch("app.core.database.SessionLocal")
    def test_extract_parallel_isolates_worker_errors(self, mock_session_local):
        """并行抽取中，单个 worker 失败不应影响其他 worker。"""
        mock_session = MagicMock()
        mock_session_local.return_value = mock_session

        def _fake_extract(thread_db, saishi_id, **opts):
            if saishi_id == "Y":
                raise RuntimeError("worker crash")
            return IncrementalExtractResult(
                saishi_id=saishi_id,
                is_incremental=False,
                is_first_extraction=True,
                new_events_count=3,
                total_events_to_date=3,
                progress_pct=100.0,
                relations_inserted=2,
                backend="rule_based",
                elapsed_seconds=0.05,
            )

        with patch.object(self.service, "extract_incremental", side_effect=_fake_extract):
            results = self.service.extract_parallel(
                MagicMock(), ["X", "Y", "Z"], max_workers=2
            )

        self.assertEqual(len(results), 3)
        self.assertIsNone(results[0].error_message)
        self.assertIsNotNone(results[1].error_message)
        self.assertIn("worker crash", results[1].error_message)
        self.assertIsNone(results[2].error_message)


# ---------------------------------------------------------------------------
# IncrementalExtractResult dataclass tests
# ---------------------------------------------------------------------------

class TestIncrementalExtractResult(unittest.TestCase):
    """IncrementalExtractResult 数据类的构造与默认值测试。"""

    def test_default_values(self):
        result = IncrementalExtractResult(saishi_id="test", is_incremental=False)
        self.assertFalse(result.is_first_extraction)
        self.assertEqual(result.new_events_count, 0)
        self.assertEqual(result.total_events_to_date, 0)
        self.assertEqual(result.progress_pct, 0.0)
        self.assertEqual(result.relations_inserted, 0)
        self.assertIsNone(result.backend)
        self.assertIsNone(result.samples)
        self.assertIsNone(result.error_message)
        self.assertEqual(result.elapsed_seconds, 0.0)

    def test_full_construction(self):
        samples = [{"player": "curry"}]
        result = IncrementalExtractResult(
            saishi_id="1780736",
            is_incremental=True,
            is_first_extraction=False,
            new_events_count=10,
            total_events_to_date=50,
            progress_pct=20.0,
            relations_inserted=8,
            backend="siamese_uie",
            samples=samples,
            error_message=None,
            elapsed_seconds=1.5,
        )
        self.assertTrue(result.is_incremental)
        self.assertEqual(result.samples, samples)
        self.assertEqual(result.backend, "siamese_uie")
        self.assertEqual(result.elapsed_seconds, 1.5)


if __name__ == "__main__":
    unittest.main()