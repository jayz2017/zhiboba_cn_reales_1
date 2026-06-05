"""
全量 API 接口测试 —— 覆盖所有 19 个 endpoints 的输入校验、响应结构、错误处理
"""

import unittest
from unittest.mock import MagicMock, Mock, patch

from fastapi.testclient import TestClient

from app.core.database import get_db
from app.main import create_app


def _fake_db():
    """返回一个 Mock 数据库会话。"""
    db = MagicMock()
    db.execute.return_value = MagicMock()
    return db


def _make_client(override_db=None):
    app = create_app()
    app.dependency_overrides[get_db] = lambda: override_db or _fake_db()
    return TestClient(app)


class TestHealthEndpoint(unittest.TestCase):
    def test_health_ok(self):
        db = _fake_db()
        client = _make_client(override_db=db)
        response = client.get("/api/v1/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})

    def test_health_db_down(self):
        db = _fake_db()
        db.execute.side_effect = RuntimeError("db down")
        client = _make_client(override_db=db)
        response = client.get("/api/v1/health")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["status"], "error")


class TestScheduleEndpoints(unittest.TestCase):
    def setUp(self):
        self.db = _fake_db()
        self.client = _make_client(override_db=self.db)

    @patch("app.api.v1.endpoints.schedule.sync_zhiboba_schedule")
    def test_schedule_sync(self, mock_sync):
        mock_sync.return_value = {"games": 10, "upserted": 10}
        response = self.client.post("/api/v1/schedule/zhiboba/sync")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"games": 10, "upserted": 10})

    @patch("app.api.v1.endpoints.schedule.sync_zhiboba_playoffs")
    def test_playoffs_sync(self, mock_sync):
        mock_sync.return_value = {"games": 5, "upserted": 5}
        response = self.client.post("/api/v1/schedule/zhiboba/playoffs/sync")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"games": 5, "upserted": 5})

    @patch("app.api.v1.endpoints.schedule.sync_game_list_by_date")
    def test_game_list_by_date_valid(self, mock_sync):
        mock_sync.return_value = {"games": 3, "upserted": 3}
        response = self.client.post("/api/v1/schedule/game-list/sync/by-date?game_date=2025-06-15")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"games": 3, "upserted": 3})

    def test_game_list_by_date_invalid_format(self):
        response = self.client.post("/api/v1/schedule/game-list/sync/by-date?game_date=not-a-date")
        self.assertEqual(response.status_code, 400)
        self.assertIn("YYYY-MM-DD", response.json()["detail"])

    def test_game_list_by_date_missing_param(self):
        response = self.client.post("/api/v1/schedule/game-list/sync/by-date")
        self.assertEqual(response.status_code, 422)


class TestPlayerEndpoints(unittest.TestCase):
    def setUp(self):
        self.db = _fake_db()
        self.client = _make_client(override_db=self.db)

    @patch("app.api.v1.endpoints.schedule.sync_player_aliases")
    def test_player_alias_sync(self, mock_sync):
        mock_sync.return_value = {"aliases": 5, "upserted": 5}
        response = self.client.post("/api/v1/player-alias/sync?saishi_id=1780736")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"aliases": 5, "upserted": 5})

    @patch("app.api.v1.endpoints.schedule.sync_zhiboba_team_players")
    def test_team_players_sync(self, mock_sync):
        mock_sync.return_value = {"players": 15, "upserted": 15}
        response = self.client.post("/api/v1/team/zhiboba/players/sync?team_id=6916")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"players": 15, "upserted": 15})

    def test_team_players_sync_missing_team_id(self):
        response = self.client.post("/api/v1/team/zhiboba/players/sync")
        self.assertEqual(response.status_code, 422)

    @patch("app.api.v1.endpoints.schedule.sync_all_zhiboba_team_players")
    def test_all_team_players_sync(self, mock_sync):
        mock_sync.return_value = {"teams": 30, "players": 450, "upserted": 450}
        response = self.client.post("/api/v1/team/zhiboba/players/sync/all")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"teams": 30, "players": 450, "upserted": 450})

    @patch("app.api.v1.endpoints.schedule.sync_zhiboba_team_players_by_master_team_id")
    def test_team_players_by_master_team_id(self, mock_sync):
        mock_sync.return_value = {"players": 15, "upserted": 15}
        response = self.client.post("/api/v1/team/players/sync/by-team-id?team_id=1610612747")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"players": 15, "upserted": 15})

    def test_team_players_by_master_team_id_not_found(self):
        response = self.client.post("/api/v1/team/players/sync/by-team-id?team_id=notfound")
        self.assertEqual(response.status_code, 404)

    @patch("app.api.v1.endpoints.schedule.bind_players_team_id_by_zhiboba_team_id")
    def test_bind_players_team_id(self, mock_bind):
        mock_bind.return_value = {"updated": 15}
        response = self.client.post("/api/v1/team/players/bind/team-id/by-zhiboba-team-id?zhiboba_team_id=6916")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"updated": 15})

    def test_bind_players_team_id_not_found(self):
        response = self.client.post("/api/v1/team/players/bind/team-id/by-zhiboba-team-id?zhiboba_team_id=notfound")
        self.assertEqual(response.status_code, 404)

    @patch("app.api.v1.endpoints.schedule.sync_nba_china_players")
    def test_nba_china_players_sync(self, mock_sync):
        mock_sync.return_value = {"pages": 3, "players": 150, "matched": 140, "new": 10}
        response = self.client.post("/api/v1/team/nba-china/players/sync")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"pages": 3, "players": 150, "matched": 140, "new": 10})


class TestLiveTextEndpoints(unittest.TestCase):
    def setUp(self):
        self.db = _fake_db()
        self.client = _make_client(override_db=self.db)

    @patch("app.api.v1.endpoints.live_text.auto_tune_next_game_live_text")
    def test_auto_tune_next(self, mock_tune):
        mock_tune.return_value = {"processed": True, "saishi_id": "1780738"}
        response = self.client.post("/api/v1/live-text/zhiboba/auto-tune/next")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["processed"], True)

    @patch("app.api.v1.endpoints.live_text.fetch_zhiboba_live_text_events")
    def test_fetch_live_text(self, mock_fetch):
        mock_fetch.return_value = {"pages": 3, "events": 100, "finished": True}
        response = self.client.post("/api/v1/live-text/zhiboba/fetch?saishi_id=1780736")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["finished"], True)

    def test_fetch_live_text_missing_saishi_id(self):
        response = self.client.post("/api/v1/live-text/zhiboba/fetch")
        self.assertEqual(response.status_code, 422)

    @patch("app.api.v1.endpoints.live_text.sync_zhiboba_live_text")
    def test_sync_live_text(self, mock_sync):
        mock_sync.return_value = {"pages": 3, "events": 100, "finished": True}
        response = self.client.post("/api/v1/live-text/zhiboba/sync?saishi_id=1780736")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["finished"], True)

    def test_sync_live_text_missing_saishi_id(self):
        response = self.client.post("/api/v1/live-text/zhiboba/sync")
        self.assertEqual(response.status_code, 422)

    @patch("app.api.v1.endpoints.live_text.extract_postgame_player_relations")
    def test_relations_extract(self, mock_extract):
        mock_extract.return_value = {
            "processed": True, "saishi_id": "1780736",
            "relations_count": 42, "backend": "siamese_uie",
            "quality_stats": {"pass_rate": 0.85}, "samples": [],
        }
        response = self.client.post("/api/v1/live-text/zhiboba/relations/extract?saishi_id=1780736")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["processed"], True)

    def test_relations_extract_missing_saishi_id(self):
        response = self.client.post("/api/v1/live-text/zhiboba/relations/extract")
        self.assertEqual(response.status_code, 422)

    @patch("app.api.v1.endpoints.live_text.IncrementalExtractorService")
    def test_relations_extract_incremental(self, mock_svc_cls):
        mock_svc = MagicMock()
        from app.modules.semantics.incremental_service import IncrementalExtractResult
        mock_svc.extract_incremental.return_value = IncrementalExtractResult(
            saishi_id="1780736", is_incremental=True, is_first_extraction=False,
            new_events_count=10, total_events_to_date=100, progress_pct=10.0,
            relations_inserted=5, backend="rule_based", elapsed_seconds=0.5,
        )
        mock_svc_cls.return_value = mock_svc
        response = self.client.post("/api/v1/live-text/zhiboba/relations/extract/incremental?saishi_id=1780736")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["processed"])
        self.assertEqual(data["saishi_id"], "1780736")
        self.assertEqual(data["mode"], "incremental")

    def test_relations_extract_incremental_missing_saishi_id(self):
        response = self.client.post("/api/v1/live-text/zhiboba/relations/extract/incremental")
        self.assertEqual(response.status_code, 422)

    @patch("app.api.v1.endpoints.live_text.sync_nba_china_live_text")
    def test_nba_china_sync(self, mock_sync):
        mock_sync.return_value = {"periods": 4, "events": 200, "finished": True}
        response = self.client.post("/api/v1/live-text/nba-china/sync?game_id=0042500316")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["finished"], True)

    def test_nba_china_sync_missing_game_id(self):
        response = self.client.post("/api/v1/live-text/nba-china/sync")
        self.assertEqual(response.status_code, 422)

    @patch("app.api.v1.endpoints.live_text.extract_nba_china_player_relations")
    def test_nba_china_relations_extract(self, mock_extract):
        mock_extract.return_value = {
            "processed": True, "game_id": "0042500316",
            "relations_count": 30, "backend": "rule_based", "samples": [],
        }
        response = self.client.post("/api/v1/live-text/nba-china/relations/extract?game_id=0042500316")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["processed"], True)

    def test_nba_china_relations_extract_missing_game_id(self):
        response = self.client.post("/api/v1/live-text/nba-china/relations/extract")
        self.assertEqual(response.status_code, 422)

    @patch("app.api.v1.endpoints.live_text.sync_and_extract_nba_china_live_text")
    def test_nba_china_sync_and_extract(self, mock_sync):
        mock_sync.return_value = {
            "processed": True, "game_id": "0042500316",
            "sync": {"periods": 4, "events": 200},
            "extract": {"relations_count": 30},
        }
        response = self.client.post("/api/v1/live-text/nba-china/sync-and-extract?game_id=0042500316")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["processed"], True)

    def test_nba_china_sync_and_extract_missing_game_id(self):
        response = self.client.post("/api/v1/live-text/nba-china/sync-and-extract")
        self.assertEqual(response.status_code, 422)


class TestBatchParallelEndpoint(unittest.TestCase):
    def setUp(self):
        self.db = _fake_db()
        self.client = _make_client(override_db=self.db)

    @patch("app.api.v1.endpoints.live_text.IncrementalExtractorService")
    def test_batch_parallel_valid(self, mock_svc_cls):
        from app.modules.semantics.incremental_service import IncrementalExtractResult
        mock_svc = MagicMock()
        mock_svc.extract_parallel.return_value = [
            IncrementalExtractResult(saishi_id="A", is_incremental=False, is_first_extraction=True,
                new_events_count=5, total_events_to_date=5, progress_pct=100.0,
                relations_inserted=3, backend="rule_based", elapsed_seconds=0.1),
            IncrementalExtractResult(saishi_id="B", is_incremental=False, is_first_extraction=True,
                new_events_count=3, total_events_to_date=3, progress_pct=100.0,
                relations_inserted=2, backend="rule_based", elapsed_seconds=0.1),
        ]
        mock_svc_cls.return_value = mock_svc
        response = self.client.post("/api/v1/live-text/zhiboba/relations/extract/batch-parallel?saishi_ids=A,B")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["processed"])
        self.assertEqual(data["summary"]["successful_games"], 2)
        self.assertEqual(len(data["per_game_results"]), 2)

    def test_batch_parallel_missing_saishi_ids(self):
        response = self.client.post("/api/v1/live-text/zhiboba/relations/extract/batch-parallel")
        self.assertEqual(response.status_code, 422)

    def test_batch_parallel_empty_ids(self):
        response = self.client.post("/api/v1/live-text/zhiboba/relations/extract/batch-parallel?saishi_ids=,")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertFalse(data["processed"])
        self.assertIn("No valid", data["error"])

    def test_batch_parallel_too_many_ids(self):
        ids = ",".join(str(i) for i in range(1, 22))
        response = self.client.post(f"/api/v1/live-text/zhiboba/relations/extract/batch-parallel?saishi_ids={ids}")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertFalse(data["processed"])
        self.assertIn("Too many", data["error"])


class TestGlobalExceptionHandler(unittest.TestCase):
    def test_global_exception_handler_exists(self):
        """验证全局异常处理器已注册到 FastAPI app 上。"""
        app = create_app()
        # 检查异常处理器已注册
        self.assertIn(Exception, app.exception_handlers)
        self.assertIn(ValueError, app.exception_handlers)

    def test_value_error_handler_returns_400(self):
        """ValueError 应被全局处理器捕获并返回 400。"""
        client = _make_client()
        response = client.post("/api/v1/schedule/game-list/sync/by-date?game_date=not-a-date")
        self.assertEqual(response.status_code, 400)
        self.assertIn("YYYY-MM-DD", response.json()["detail"])


class TestResponseStructures(unittest.TestCase):
    """验证关键 API 响应 JSON 结构是否完整。"""

    def setUp(self):
        self.db = _fake_db()
        self.client = _make_client(override_db=self.db)

    @patch("app.api.v1.endpoints.schedule.sync_zhiboba_schedule")
    def test_schedule_sync_response_structure(self, mock_sync):
        mock_sync.return_value = {"games": 10, "upserted": 10}
        response = self.client.post("/api/v1/schedule/zhiboba/sync")
        data = response.json()
        self.assertIn("games", data)
        self.assertIn("upserted", data)
        self.assertIsInstance(data["games"], int)
        self.assertIsInstance(data["upserted"], int)

    @patch("app.api.v1.endpoints.live_text.extract_postgame_player_relations")
    def test_relations_extract_response_structure(self, mock_extract):
        mock_extract.return_value = {
            "processed": True, "saishi_id": "1780736",
            "relations_count": 42, "backend": "siamese_uie",
            "quality_stats": {"pass_rate": 0.85, "total": 50, "passed": 42, "removed": 8},
            "samples": [],
        }
        response = self.client.post("/api/v1/live-text/zhiboba/relations/extract?saishi_id=1780736")
        data = response.json()
        self.assertIn("processed", data)
        self.assertIn("saishi_id", data)
        self.assertIn("relations_count", data)
        self.assertIn("backend", data)
        self.assertIn("quality_stats", data)

    @patch("app.api.v1.endpoints.schedule.sync_nba_china_players")
    def test_nba_china_players_response_structure(self, mock_sync):
        mock_sync.return_value = {"pages": 3, "players": 150, "matched": 140, "new": 10}
        response = self.client.post("/api/v1/team/nba-china/players/sync")
        data = response.json()
        self.assertIn("pages", data)
        self.assertIn("players", data)
        self.assertIn("matched", data)
        self.assertIn("new", data)


if __name__ == "__main__":
    unittest.main()