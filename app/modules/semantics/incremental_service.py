from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

_SQL_GET_PROGRESS = """
SELECT
    saishi_id,
    last_processed_live_sid,
    total_relations,
    total_events_processed,
    backend_used,
    extraction_status,
    last_extracted_at,
    created_at,
    updated_at
FROM nba_zhiboba_extraction_progress
WHERE saishi_id = :saishi_id
"""

_SQL_UPSERT_PROGRESS = """
INSERT INTO nba_zhiboba_extraction_progress (
    saishi_id,
    last_processed_live_sid,
    total_relations,
    total_events_processed,
    backend_used,
    extraction_status,
    last_extracted_at,
    created_at,
    updated_at
) VALUES (
    :saishi_id,
    :last_processed_live_sid,
    :total_relations,
    :total_events_processed,
    :backend_used,
    :extraction_status,
    :last_extracted_at,
    :created_at,
    :updated_at
) AS new_val
ON DUPLICATE KEY UPDATE
    last_processed_live_sid = new_val.last_processed_live_sid,
    total_relations = new_val.total_relations,
    total_events_processed = new_val.total_events_processed,
    backend_used = new_val.backend_used,
    extraction_status = new_val.extraction_status,
    last_extracted_at = new_val.last_extracted_at,
    updated_at = new_val.updated_at
"""

_SQL_RESET_PROGRESS = """
UPDATE nba_zhiboba_extraction_progress
SET
    last_processed_live_sid = NULL,
    total_relations = 0,
    total_events_processed = 0,
    backend_used = NULL,
    extraction_status = 'idle',
    last_extracted_at = NULL,
    updated_at = :updated_at
WHERE saishi_id = :saishi_id
"""

_SQL_GET_UNPROCESSED_EVENTS = """
SELECT *
FROM nba_zhiboba_live_text_event
WHERE saishi_id = :saishi_id
  AND segmented_text IS NOT NULL
  AND live_sid > :last_processed_live_sid
ORDER BY live_sid ASC
LIMIT :max_rows
"""

_SQL_GET_ALL_EVENTS = """
SELECT *
FROM nba_zhiboba_live_text_event
WHERE saishi_id = :saishi_id
  AND segmented_text IS NOT NULL
ORDER BY live_sid ASC
LIMIT :max_rows
"""

_SQL_COUNT_TOTAL_EVENTS = """
SELECT COUNT(*) AS cnt
FROM nba_zhiboba_live_text_event
WHERE saishi_id = :saishi_id
  AND segmented_text IS NOT NULL
"""


@dataclass(frozen=True)
class ExtractionProgress:
    """抽取进度数据类，表示某场比赛的关系提取进度状态。

    Attributes:
        saishi_id: 赛事ID
        last_processed_live_sid: 上次处理到的最大直播文本序号
        total_relations: 累计提取的关系总数
        total_events_processed: 累计已处理的直播文本事件数
        backend_used: 使用的后端类型（siamese_uie / rule_based）
        extraction_status: 当前抽取状态（idle/running/completed/failed）
        last_extracted_at: 上次抽取完成时间（ISO格式字符串）
        created_at: 进度记录创建时间
        updated_at: 进度记录最后更新时间
    """

    saishi_id: str
    last_processed_live_sid: int | None
    total_relations: int
    total_events_processed: int
    backend_used: str | None
    extraction_status: str | None
    last_extracted_at: str | None
    created_at: str | None
    updated_at: str | None


@dataclass(frozen=True)
class IncrementalExtractResult:
    """增量抽取结果数据类。

    Attributes:
        saishi_id: 赛事ID
        is_incremental: 是否为增量模式（True=增量，False=全量）
        is_first_extraction: 是否为首次抽取（无历史进度记录）
        new_events_count: 本次处理的新事件数
        total_events_to_date: 累计已处理的事件总数
        progress_pct: 完成百分比（0.0~100.0）
        relations_inserted: 本次插入的关系数
        backend: 使用的抽取后端（siamese_uie / rule_based / unknown）
        samples: 抽样返回的关系记录列表（用于预览）
        error_message: 错误信息（成功时为None）
        elapsed_seconds: 耗时（秒）
    """

    saishi_id: str
    is_incremental: bool
    is_first_extraction: bool = False
    new_events_count: int = 0
    total_events_to_date: int = 0
    progress_pct: float = 0.0
    relations_inserted: int = 0
    backend: str | None = None
    samples: list | None = None
    error_message: str | None = None
    elapsed_seconds: float = 0.0


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ExtractionProgressTracker:
    """抽取进度追踪器，管理每场比赛的关系提取进度。

    通过 nba_zhiboba_extraction_progress 表持久化进度信息，
    支持查询、更新、重置操作，以及获取未处理的直播文本事件。

    典型使用流程：
        tracker = ExtractionProgressTracker()
        progress = tracker.get_progress(db, "1780736")
        events = tracker.get_unprocessed_events(db, "1780736", max_rows=500)
        # ... 执行抽取 ...
        tracker.update_progress(db, "1780736", last_processed_live_sid=1234, total_events_processed=5678)
    """

    def ensure_table(self, db: Session) -> None:
        """确保进度追踪表已创建（若不存在则自动创建）。

        Args:
            db: SQLAlchemy 数据库会话
        """
        from app.modules.semantics.schema import ensure_extraction_progress_table
        try:
            ensure_extraction_progress_table(db)
            logger.debug("extraction_progress_table_ensured")
        except Exception as exc:
            logger.warning(
                "ensure_table_failed",
                extra={"error": str(exc)},
                exc_info=True,
            )

    def get_progress(self, db: Session, saishi_id: str) -> ExtractionProgress | None:
        """查询某比赛的抽取进度。

        Args:
            db: SQLAlchemy 数据库会话
            saishi_id: 赛事ID

        Returns:
            ExtractionProgress 实例，若该比赛无进度记录则返回 None
        """
        try:
            row = db.execute(
                text(_SQL_GET_PROGRESS),
                {"saishi_id": saishi_id},
            ).mappings().one_or_none()

            if row is None:
                logger.debug(
                    "progress_not_found",
                    extra={"saishi_id": saishi_id},
                )
                return None

            result = ExtractionProgress(
                saishi_id=str(row["saishi_id"]),
                last_processed_live_sid=int(row["last_processed_live_sid"]) if row.get("last_processed_live_sid") is not None else None,
                total_relations=int(row["total_relations"] or 0),
                total_events_processed=int(row["total_events_processed"] or 0),
                backend_used=str(row["backend_used"]) if row.get("backend_used") else None,
                extraction_status=str(row["extraction_status"]) if row.get("extraction_status") else None,
                last_extracted_at=str(row["last_extracted_at"]) if row.get("last_extracted_at") else None,
                created_at=str(row["created_at"]) if row.get("created_at") else None,
                updated_at=str(row["updated_at"]) if row.get("updated_at") else None,
            )

            logger.debug(
                "get_progress_ok",
                extra={
                    "saishi_id": saishi_id,
                    "last_processed_live_sid": result.last_processed_live_sid,
                    "total_relations": result.total_relations,
                    "total_events_processed": result.total_events_processed,
                    "backend_used": result.backend_used,
                    "extraction_status": result.extraction_status,
                },
            )
            return result

        except Exception as exc:
            logger.error(
                "get_progress_failed",
                extra={"saishi_id": saishi_id, "error": str(exc)},
                exc_info=True,
            )
            raise

    def update_progress(self, db: Session, saishi_id: str, **kwargs: Any) -> None:
        """更新某比赛的抽取进度。

        支持更新的字段：
            - last_processed_live_sid: int | None - 最新处理的 live_sid
            - total_relations: int - 累计关系数
            - total_events_processed: int - 累计处理事件数
            - backend_used: str | None - 使用的后端类型
            - extraction_status: str | None - 抽取状态
            - last_extracted_at: str | None - 最后抽取时间（不传则自动取当前时间）

        Args:
            db: SQLAlchemy 数据库会话
            saishi_id: 赛事ID
            **kwargs: 要更新的字段值
        """
        now = _now_iso()
        params: dict[str, Any] = {
            "saishi_id": saishi_id,
            "last_processed_live_sid": kwargs.get("last_processed_live_sid"),
            "total_relations": kwargs.get("total_relations", 0),
            "total_events_processed": kwargs.get("total_events_processed", 0),
            "backend_used": kwargs.get("backend_used"),
            "extraction_status": kwargs.get("extraction_status", "completed"),
            "last_extracted_at": kwargs.get("last_extracted_at", now),
            "created_at": now,
            "updated_at": now,
        }

        try:
            db.execute(text(_SQL_UPSERT_PROGRESS), params)
            db.commit()

            logger.info(
                "progress_updated",
                extra={
                    "saishi_id": saishi_id,
                    "last_processed_live_sid": params["last_processed_live_sid"],
                    "total_relations": params["total_relations"],
                    "total_events_processed": params["total_events_processed"],
                    "backend_used": params["backend_used"],
                    "extraction_status": params["extraction_status"],
                },
            )

        except Exception as exc:
            db.rollback()
            logger.error(
                "update_progress_failed",
                extra={"saishi_id": saishi_id, "error": str(exc)},
                exc_info=True,
            )
            raise

    def reset_progress(self, db: Session, saishi_id: str) -> None:
        """重置某比赛的抽取进度（用于重新全量抽取）。

        将 last_processed_live_sid、total_processed、total_events、last_extracted_at
        全部清空/归零，使下次增量抽取时从第一条开始处理。

        Args:
            db: SQLAlchemy 数据库会话
            saishi_id: 赛事ID
        """
        try:
            db.execute(
                text(_SQL_RESET_PROGRESS),
                {"saishi_id": saishi_id, "updated_at": _now_iso()},
            )
            db.commit()

            logger.info(
                "progress_reset",
                extra={"saishi_id": saishi_id},
            )

        except Exception as exc:
            db.rollback()
            logger.error(
                "reset_progress_failed",
                extra={"saishi_id": saishi_id, "error": str(exc)},
                exc_info=True,
            )
            raise

    def get_unprocessed_events(
        self,
        db: Session,
        saishi_id: str,
        max_rows: int = 500,
    ) -> list[dict[str, Any]]:
        """获取某比赛中尚未处理的直播文本事件。

        查询条件：
            - saishi_id 匹配
            - segmented_text IS NOT NULL（已有分词结果）
            - live_sid > last_processed_live_sid（或无进度记录时取全部）

        结果按 live_sid 升序排列，限制返回行数。

        Args:
            db: SQLAlchemy 数据库会话
            saishi_id: 赛事ID
            max_rows: 最大返回行数，默认 500

        Returns:
            未处理的事件字典列表
        """
        try:
            progress = self.get_progress(db, saishi_id)
            last_sid = progress.last_processed_live_sid if progress else 0

            if last_sid is None or last_sid <= 0:
                sql = _SQL_GET_ALL_EVENTS
                params = {
                    "saishi_id": saishi_id,
                    "max_rows": max(1, int(max_rows)),
                }
            else:
                sql = _SQL_GET_UNPROCESSED_EVENTS
                params = {
                    "saishi_id": saishi_id,
                    "last_processed_live_sid": last_sid,
                    "max_rows": max(1, int(max_rows)),
                }

            rows = (
                db.execute(text(sql), params)
                .mappings()
                .all()
            )

            result = [dict(row) for row in rows]

            logger.info(
                "unprocessed_events_fetched",
                extra={
                    "saishi_id": saishi_id,
                    "count": len(result),
                    "max_rows": max_rows,
                    "has_progress": progress is not None,
                    "last_processed_live_sid": progress.last_processed_live_sid if progress else None,
                },
            )
            return result

        except Exception as exc:
            logger.error(
                "get_unprocessed_events_failed",
                extra={"saishi_id": saishi_id, "max_rows": max_rows, "error": str(exc)},
                exc_info=True,
            )
            raise

    def get_total_events_count(self, db: Session, saishi_id: str) -> int:
        """获取某比赛的总可处理事件数（有分词结果的）。

        Args:
            db: SQLAlchemy 数据库会话
            saishi_id: 赛事ID

        Returns:
            总事件数
        """
        try:
            row = db.execute(
                text(_SQL_COUNT_TOTAL_EVENTS),
                {"saishi_id": saishi_id},
            ).mappings().one()
            count = int(row["cnt"] or 0)

            logger.debug(
                "total_events_count",
                extra={"saishi_id": saishi_id, "count": count},
            )
            return count

        except Exception as exc:
            logger.error(
                "get_total_events_count_failed",
                extra={"saishi_id": saishi_id, "error": str(exc)},
                exc_info=True,
            )
            raise


class IncrementalExtractorService:
    """增量抽取服务，封装单场/批量/并行的关系提取流程。

    核心职责：
        1. 查询进度 → 判断增量/全量模式
        2. 获取新增的未处理事件
        3. 调用底层提取器执行抽取
        4. 更新进度并返回结构化结果

    支持三种调用方式：
        - extract_incremental: 单场比赛增量抽取
        - extract_batch_incremental: 多场比赛顺序批量抽取
        - extract_parallel: 多场比赛并行抽取（ThreadPoolExecutor）

    典型用法::

        service = IncrementalExtractorService()
        result = service.extract_incremental(db, "1780736", max_rows=1000)

        # 批量
        results = service.extract_batch_incremental(db, ["1780736", "1780738"])

        # 并行
        results = service.extract_parallel(db, ["1780736", "1780738", "1780740"], max_workers=3)
    """

    def __init__(
        self,
        *,
        default_max_rows: int = 500,
        default_batch_size: int = 50,
        default_timeout_seconds: float = 300.0,
    ) -> None:
        """初始化增量抽取服务。

        Args:
            default_max_rows: 默认每次获取的最大事件数
            default_batch_size: 默认提交批次大小
            default_timeout_seconds: 并行模式下单场比赛超时秒数
        """
        self._tracker = ExtractionProgressTracker()
        self._default_max_rows = max(1, int(default_max_rows))
        self._default_batch_size = max(1, int(default_batch_size))
        self._default_timeout_seconds = max(1.0, float(default_timeout_seconds))

    def extract_incremental(
        self,
        db: Session,
        saishi_id: str,
        **options: Any,
    ) -> IncrementalExtractResult:
        """单场比赛增量抽取主方法。

        执行流程：
            1. 查询当前进度 → 判断是否为增量模式
            2. 统计总事件数
            3. 获取未处理的新增事件
            4. 若有新事件则调用 _do_extract 执行抽取
            5. 更新进度（last_processed_live_sid、total_processed 等）
            6. 构建并返回 IncrementalExtractResult

        Args:
            db: SQLAlchemy 数据库会话
            saishi_id: 赛事ID
            **options: 可选参数
                - max_rows: int - 本次最多处理的事件数（默认 500）
                - force_full: bool - 强制全量重抽（默认 False）

        Returns:
            IncrementalExtractResult 包含完整的抽取结果与进度信息
        """
        start_time = time.monotonic()
        max_rows = int(options.get("max_rows", self._default_max_rows))
        force_full = bool(options.get("force_full", False))

        logger.info(
            "extract_incremental_start",
            extra={
                "saishi_id": saishi_id,
                "max_rows": max_rows,
                "force_full": force_full,
            },
        )

        try:
            self._tracker.ensure_table(db)

            if force_full:
                logger.info(
                    "force_full_reset",
                    extra={"saishi_id": saishi_id},
                )
                self._tracker.reset_progress(db, saishi_id)

            progress = self._tracker.get_progress(db, saishi_id)
            is_first_extraction = progress is None
            is_incremental = not is_first_extraction and progress is not None and progress.last_processed_live_sid is not None

            total_events = self._tracker.get_total_events_count(db, saishi_id)

            unprocessed = self._tracker.get_unprocessed_events(
                db, saishi_id, max_rows=max_rows
            )

            new_events_count = len(unprocessed)
            relations_inserted = 0
            backend_used = None
            samples_list = None

            if new_events_count > 0:
                relations_inserted, backend_used, samples_list = self._do_extract(
                    db, saishi_id, unprocessed,
                    sample_limit=int(options.get("sample_limit", 0))
                )

                max_live_sid = max(
                    (int(event.get("live_sid") or 0) for event in unprocessed),
                    default=0,
                )

                prev_processed = progress.total_events_processed if progress else 0
                new_total_processed = prev_processed + new_events_count
                prev_relations = progress.total_relations if progress else 0
                new_total_relations = prev_relations + relations_inserted

                self._tracker.update_progress(
                    db,
                    saishi_id,
                    last_processed_live_sid=max_live_sid,
                    total_relations=new_total_relations,
                    total_events_processed=new_total_processed,
                    backend_used=backend_used,
                    extraction_status="completed",
                )
            else:
                if total_events > 0 and (progress is None or progress.total_events_processed == 0):
                    self._tracker.update_progress(
                        db,
                        saishi_id,
                        last_processed_live_sid=progress.last_processed_live_sid if progress else None,
                        total_events_processed=progress.total_events_processed if progress else 0,
                        extraction_status="completed",
                    )

            total_to_date = (progress.total_events_processed if progress else 0) + new_events_count
            progress_pct = (total_to_date / total_events * 100.0) if total_events > 0 else 100.0
            elapsed = time.monotonic() - start_time

            result = IncrementalExtractResult(
                saishi_id=saishi_id,
                is_incremental=is_incremental,
                is_first_extraction=is_first_extraction,
                new_events_count=new_events_count,
                total_events_to_date=total_to_date,
                progress_pct=round(progress_pct, 2),
                relations_inserted=relations_inserted,
                backend=backend_used,
                samples=samples_list,
                error_message=None,
                elapsed_seconds=round(elapsed, 3),
            )

            logger.info(
                "extract_incremental_completed",
                extra={
                    "saishi_id": saishi_id,
                    "is_incremental": is_incremental,
                    "new_events_count": new_events_count,
                    "total_to_date": total_to_date,
                    "progress_pct": result.progress_pct,
                    "relations_inserted": relations_inserted,
                    "elapsed_seconds": result.elapsed_seconds,
                },
            )
            return result

        except Exception as exc:
            elapsed = time.monotonic() - start_time
            error_msg = str(exc)

            logger.error(
                "extract_incremental_failed",
                extra={
                    "saishi_id": saishi_id,
                    "error": error_msg,
                    "elapsed_seconds": round(elapsed, 3),
                },
                exc_info=True,
            )

            return IncrementalExtractResult(
                saishi_id=saishi_id,
                is_incremental=False,
                is_first_extraction=False,
                new_events_count=0,
                total_events_to_date=0,
                progress_pct=0.0,
                relations_inserted=0,
                backend=None,
                samples=None,
                error_message=error_msg,
                elapsed_seconds=round(elapsed, 3),
            )

    def extract_batch_incremental(
        self,
        db: Session,
        saishi_ids: list[str],
        **options: Any,
    ) -> list[IncrementalExtractResult]:
        """多场比赛顺序批量增量抽取。

        按 saishi_ids 列表顺序逐场调用 extract_incremental，
        单场失败不会中断后续场次，错误信息记录在对应结果的 error_message 中。

        Args:
            db: SQLAlchemy 数据库会话
            saishi_ids: 赛事ID列表
            **options: 传递给 extract_incremental 的可选参数

        Returns:
            IncrementalExtractResult 列表，顺序与输入一致
        """
        results: list[IncrementalExtractResult] = []
        total = len(saishi_ids)

        logger.info(
            "extract_batch_start",
            extra={"total_games": total, "saishi_ids": saishi_ids},
        )

        for index, sid in enumerate(saishi_ids, start=1):
            logger.info(
                "batch_processing_game",
                extra={"index": index, "total": total, "saishi_id": sid},
            )
            result = self.extract_incremental(db, sid, **options)
            results.append(result)

        success_count = sum(1 for r in results if r.error_message is None)
        fail_count = total - success_count

        logger.info(
            "extract_batch_completed",
            extra={
                "total": total,
                "success": success_count,
                "fail": fail_count,
            },
        )
        return results

    def extract_parallel(
        self,
        db: Session,
        saishi_ids: list[str],
        max_workers: int = 3,
        **options: Any,
    ) -> list[IncrementalExtractResult]:
        """多场比赛并行增量抽取。

        使用 concurrent.futures.ThreadPoolExecutor 并发执行多场比赛的抽取，
        每场比赛在独立线程中运行，通过 thread-local session 隔离数据库连接。

        特性：
            - 单场失败不影响其他场次（错误隔离）
            - 支持超时控制（单场默认 300 秒）
            - 结果顺序与输入 saishi_ids 一致

        注意：
            由于 SQLAlchemy Session 非线程安全，每个线程会创建独立的 Session。
            请确保数据库连接池配置足够大以支持并发连接数。

        Args:
            db: SQLAlchemy 数据库会话（仅用于获取 engine，实际使用时各线程自建 session）
            saishi_ids: 赛事ID列表
            max_workers: 最大并行线程数，默认 3
            **options: 传递给 extract_incremental 的可选参数

        Returns:
            IncrementalExtractResult 列表，顺序与输入一致
        """
        from app.core.database import SessionLocal

        workers = max(1, min(int(max_workers), len(saishi_ids), 8))
        timeout = float(options.get("timeout", self._default_timeout_seconds))

        logger.info(
            "extract_parallel_start",
            extra={
                "total_games": len(saishi_ids),
                "max_workers": workers,
                "timeout_seconds": timeout,
                "saishi_ids": saishi_ids,
            },
        )

        results_map: dict[str, IncrementalExtractResult] = {}

        def _worker(sid: str) -> IncrementalExtractResult:
            thread_db = SessionLocal()
            try:
                return self.extract_incremental(thread_db, sid, **options)
            finally:
                thread_db.close()

        with ThreadPoolExecutor(max_workers=workers) as executor:
            future_to_sid = {
                executor.submit(_worker, sid): sid for sid in saishi_ids
            }

            for future in as_completed(future_to_sid):
                sid = future_to_sid[future]
                try:
                    result = future.result(timeout=timeout)
                    results_map[sid] = result
                except Exception as exc:
                    logger.error(
                        "parallel_worker_failed",
                        extra={"saishi_id": sid, "error": str(exc)},
                        exc_info=True,
                    )
                    results_map[sid] = IncrementalExtractResult(
                        saishi_id=sid,
                        is_incremental=False,
                        is_first_extraction=False,
                        new_events_count=0,
                        total_events_to_date=0,
                        progress_pct=0.0,
                        relations_inserted=0,
                        backend=None,
                        samples=None,
                        error_message=f"Worker error: {exc}",
                        elapsed_seconds=0.0,
                    )

        ordered_results = [results_map[sid] for sid in saishi_ids if sid in results_map]

        success_count = sum(1 for r in ordered_results if r.error_message is None)
        fail_count = len(ordered_results) - success_count

        logger.info(
            "extract_parallel_completed",
            extra={
                "total": len(ordered_results),
                "success": success_count,
                "fail": fail_count,
                "workers_used": workers,
            },
        )
        return ordered_results

    def _do_extract(
        self,
        db: Session,
        saishi_id: str,
        events: list[dict[str, Any]],
        sample_limit: int = 0,
    ) -> tuple[int, str | None, list | None]:
        """执行实际的抽取逻辑（可被子类覆盖或注入依赖）。

        默认实现：遍历事件列表，对每条分词文本调用 extract_relations_from_text，
        收集所有关系后通过 PlayerRelationRepository.bulk_upsert 写入数据库。

        Args:
            db: SQLAlchemy 数据库会话
            saishi_id: 赛事ID
            events: 未处理的直播文本事件列表
            sample_limit: 返回抽样关系数（0=不返回）

        Returns:
            tuple[int, str | None, list | None]:
                - 本次插入的关系记录数
                - 使用的后端类型（siamese_uie / rule_based）
                - 抽样关系列表（sample_limit > 0 时返回）
        """
        from app.modules.semantics.extractors.rule_extractor import RuleBasedExtractor
        from app.modules.semantics.repository import PlayerRelationRepository
        from app.modules.semantics.rule_config import load_relation_rule_config
        from app.modules.semantics.schema import ensure_relation_rule_config_tables
        from app.modules.nba_live_text.zhiboba_livetext import load_player_segmentation_config

        repo = PlayerRelationRepository(db)
        all_relations: list[Any] = []
        backend_used = "rule_based"

        try:
            ensure_relation_rule_config_tables(db=db)
            rule_config = load_relation_rule_config(db=db)
            extractor = RuleBasedExtractor(rule_config=rule_config)
            segmentation_config = load_player_segmentation_config(db=db, saishi_id=saishi_id)
            all_relations = extractor.extract_from_rows(
                rows=events,
                segmentation_config=segmentation_config,
            )
            backend_used = "rule_based"
        except Exception as exc:
            logger.error(
                "rule_extractor_failed",
                extra={"saishi_id": saishi_id, "error": str(exc)},
                exc_info=True,
            )
            return 0, None, None

        if not all_relations:
            logger.debug(
                "no_relations_extracted",
                extra={"saishi_id": saishi_id, "events_count": len(events)},
            )
            return 0, None, None

        inserted = repo.bulk_upsert(all_relations, batch_size=self._default_batch_size)

        samples = None
        if sample_limit > 0 and all_relations:
            samples = [r.to_dict() if hasattr(r, 'to_dict') else dict(r) for r in all_relations[:sample_limit]]

        logger.info(
            "do_extract_completed",
            extra={
                "saishi_id": saishi_id,
                "events_processed": len(events),
                "relations_found": len(all_relations),
                "relations_inserted": inserted,
                "backend_used": backend_used,
            },
        )
        return inserted, backend_used, samples
