from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.modules.nba_live_text.zhiboba_livetext import ensure_live_text_tables
from app.modules.semantics.models import PlayerRelationRecord
from app.modules.semantics.schema import (
    _SQL_UPSERT_PLAYER_RELATION,
    ensure_player_relation_table,
)

logger = logging.getLogger(__name__)


class PlayerRelationRepository:
    """球员关系数据访问层，封装 nba_zhiboba_player_relation 表的 CRUD 操作。

    提供批量写入、按比赛查询、统计信息获取及删除等能力，
    所有数据库操作均包含完整的错误处理与日志记录。
    """

    def __init__(self, db: Session) -> None:
        """初始化 Repository。

        Args:
            db: SQLAlchemy 数据库会话实例
        """
        self._db = db

    def ensure_tables(self) -> None:
        """确保相关表结构存在。

        依次调用 ensure_live_text_tables 和 ensure_player_relation_table，
        创建直播文本事件表、过滤规则表及球员关系表（如不存在）。
        """
        try:
            ensure_live_text_tables(db=self._db)
            logger.debug("live_text_tables_ensured")
        except Exception as exc:
            logger.error(
                "ensure_live_text_tables_failed",
                extra={"error": str(exc)},
                exc_info=True,
            )
            raise

        try:
            ensure_player_relation_table(db=self._db)
            logger.debug("player_relation_table_ensured")
        except Exception as exc:
            logger.error(
                "ensure_player_relation_table_failed",
                extra={"error": str(exc)},
                exc_info=True,
            )
            raise

    def bulk_upsert(
        self,
        relations: list[PlayerRelationRecord],
        batch_size: int = 500,
    ) -> int:
        """批量写入球员关系记录（UPSERT 语义）。

        使用 ON DUPLICATE KEY UPDATE 实现幂等写入，
        当唯一键（saishi_id + evidence_event_id + relation_type + subject_player_name + object_player_name）
        冲突时更新已有记录的非主键字段。

        该方法从 siamese_uie.upsert_player_relations 迁移而来，保持完全一致的行为。

        Args:
            relations: 球员关系记录列表
            batch_size: 每批处理的记录数，默认 500

        Returns:
            成功影响的记录总数

        Raises:
            Exception: 数据库执行失败时抛出原始异常
        """
        if not relations:
            logger.debug("bulk_upsert_skipped_empty")
            return 0

        total_affected = 0
        total_batches = (len(relations) + batch_size - 1) // batch_size

        for batch_index, batch_start in enumerate(
            range(0, len(relations), batch_size)
        ):
            batch = relations[batch_start : batch_start + batch_size]
            params = [
                {
                    "saishi_id": relation.saishi_id,
                    "evidence_event_id": relation.evidence_event_id,
                    "live_sid": relation.live_sid,
                    "relation_type": relation.relation_type,
                    "relation_side": relation.relation_side,
                    "subject_player_name": relation.subject_player_name,
                    "subject_team_id": relation.subject_team_id,
                    "subject_team_name": relation.subject_team_name,
                    "subject_team_side": relation.subject_team_side,
                    "subject_team_score": relation.subject_team_score,
                    "object_player_name": relation.object_player_name,
                    "object_team_id": relation.object_team_id,
                    "object_team_name": relation.object_team_name,
                    "object_team_side": relation.object_team_side,
                    "object_team_score": relation.object_team_score,
                    "offense_team_id": relation.offense_team_id,
                    "offense_team_name": relation.offense_team_name,
                    "offense_team_side": relation.offense_team_side,
                    "offense_team_score": relation.offense_team_score,
                    "offense_team_points": relation.offense_team_points,
                    "possession_number": relation.possession_number,
                    "home_score": relation.home_score,
                    "visit_score": relation.visit_score,
                    "action_text": relation.action_text,
                    "result_text": relation.result_text,
                    "score_points": relation.score_points,
                    "evidence_text": relation.evidence_text,
                    "segmented_text": relation.segmented_text,
                    "extractor_name": relation.extractor_name,
                    "confidence": Decimal(f"{relation.confidence:.4f}"),
                }
                for relation in batch
            ]

            try:
                self._db.execute(text(_SQL_UPSERT_PLAYER_RELATION), params)
                total_affected += len(batch)
            except Exception as exc:
                logger.error(
                    "bulk_upsert_batch_failed",
                    extra={
                        "batch_index": batch_index,
                        "total_batches": total_batches,
                        "batch_size": len(batch),
                        "error": str(exc),
                    },
                    exc_info=True,
                )
                raise

        self._db.commit()
        logger.info(
            "bulk_upsert_completed",
            extra={
                "total_affected": total_affected,
                "total_records": len(relations),
                "total_batches": total_batches,
                "batch_size": batch_size,
            },
        )
        return total_affected

    def get_by_saishi_id(
        self,
        saishi_id: str,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """查询指定比赛的所有球员关系记录。

        Args:
            saishi_id: 比赛 ID（直播吧 saishi_id）
            limit: 最大返回记录数，默认 50

        Returns:
            关系记录字典列表，按 id 倒序排列
        """
        try:
            rows = (
                self._db.execute(
                    text(
                        """
                        SELECT
                          id,
                          saishi_id,
                          evidence_event_id,
                          live_sid,
                          relation_type,
                          relation_side,
                          subject_player_name,
                          subject_team_id,
                          subject_team_name,
                          subject_team_side,
                          subject_team_score,
                          object_player_name,
                          object_team_id,
                          object_team_name,
                          object_team_side,
                          object_team_score,
                          offense_team_id,
                          offense_team_name,
                          offense_team_side,
                          offense_team_score,
                          offense_team_points,
                          possession_number,
                          home_score,
                          visit_score,
                          action_text,
                          result_text,
                          score_points,
                          evidence_text,
                          segmented_text,
                          extractor_name,
                          confidence,
                          created_at,
                          updated_at
                        FROM nba_zhiboba_player_relation
                        WHERE saishi_id = :saishi_id
                        ORDER BY id DESC
                        LIMIT :limit
                        """
                    ),
                    {"saishi_id": saishi_id, "limit": max(1, int(limit))},
                )
                .mappings()
                .all()
            )

            result = [dict(row) for row in rows]
            logger.debug(
                "get_by_saishi_id_completed",
                extra={
                    "saishi_id": saishi_id,
                    "limit": limit,
                    "count": len(result),
                },
            )
            return result

        except Exception as exc:
            logger.error(
                "get_by_saishi_id_failed",
                extra={"saishi_id": saishi_id, "limit": limit, "error": str(exc)},
                exc_info=True,
            )
            raise

    def get_statistics(self, saishi_id: str) -> dict[str, Any]:
        """获取指定比赛的球员关系统计信息。

        包含关系类型分布、涉及球员数量、球队覆盖率等多维度统计。

        Args:
            saishi_id: 比赛 ID（直播吧 saishi_id）

        Returns:
            统计信息字典，包含以下字段：
            - total: 总关系数
            - distinct_live_sids: 涉及的独立事件数
            - relation_types: 关系类型分布 {type: count}
            - distinct_subject_players: 独立主体球员数
            - distinct_object_players: 独立体球员数
            - all_players: 涉及的全部独立球员数
            - teams_covered: 涉及的球队集合
            - extractor_distribution: 提取器分布 {extractor: count}
            - avg_confidence: 平均置信度
            - last_updated_at: 最后更新时间
        """
        try:
            summary_row = self._db.execute(
                text(
                    """
                    SELECT
                      COUNT(*) AS total,
                      COUNT(DISTINCT live_sid) AS distinct_live_sids,
                      COUNT(DISTINCT subject_player_name) AS distinct_subject_players,
                      COUNT(DISTINCT object_player_name) AS distinct_object_players,
                      AVG(confidence) AS avg_confidence,
                      MAX(updated_at) AS last_updated_at
                    FROM nba_zhiboba_player_relation
                    WHERE saishi_id = :saishi_id
                    """
                ),
                {"saishi_id": saishi_id},
            ).mappings().one()

            type_rows = self._db.execute(
                text(
                    """
                    SELECT relation_type, COUNT(*) AS cnt
                    FROM nba_zhiboba_player_relation
                    WHERE saishi_id = :saishi_id
                    GROUP BY relation_type
                    ORDER BY cnt DESC
                    """
                ),
                {"saishi_id": saishi_id},
            ).mappings().all()

            team_rows = self._db.execute(
                text(
                    """
                    SELECT DISTINCT subject_team_id, subject_team_name
                    FROM nba_zhiboba_player_relation
                    WHERE saishi_id = :saishi_id
                      AND subject_team_id IS NOT NULL
                    UNION DISTINCT
                    SELECT DISTINCT object_team_id, object_team_name
                    FROM nba_zhiboba_player_relation
                    WHERE saishi_id = :saishi_id
                      AND object_team_id IS NOT NULL
                    """
                ),
                {"saishi_id": saishi_id},
            ).mappings().all()

            extractor_rows = self._db.execute(
                text(
                    """
                    SELECT extractor_name, COUNT(*) AS cnt
                    FROM nba_zhiboba_player_relation
                    WHERE saishi_id = :saishi_id
                    GROUP BY extractor_name
                    ORDER BY cnt DESC
                    """
                ),
                {"saishi_id": saishi_id},
            ).mappings().all()

            all_player_rows = self._db.execute(
                text(
                    """
                    SELECT player_name FROM (
                        SELECT subject_player_name AS player_name
                        FROM nba_zhiboba_player_relation
                        WHERE saishi_id = :saishi_id
                        UNION
                        SELECT object_player_name AS player_name
                        FROM nba_zhiboba_player_relation
                        WHERE saishi_id = :saishi_id
                    ) AS combined
                    """
                ),
                {"saishi_id": saishi_id},
            ).mappings().all()

            summary = dict(summary_row)
            total = int(summary.get("total") or 0)

            result: dict[str, Any] = {
                "saishi_id": saishi_id,
                "total": total,
                "distinct_live_sids": int(summary.get("distinct_live_sids") or 0),
                "relation_types": {
                    str(row["relation_type"]): int(row["cnt"]) for row in type_rows
                },
                "distinct_subject_players": int(
                    summary.get("distinct_subject_players") or 0
                ),
                "distinct_object_players": int(
                    summary.get("distinct_object_players") or 0
                ),
                "all_players": len(all_player_rows),
                "teams_covered": [
                    {
                        "team_id": row["subject_team_id"],
                        "team_name": row["subject_team_name"],
                    }
                    for row in team_rows
                    if row["subject_team_id"]
                ],
                "extractor_distribution": {
                    str(row["extractor_name"]): int(row["cnt"])
                    for row in extractor_rows
                },
                "avg_confidence": float(summary.get("avg_confidence") or 0.0),
                "last_updated_at": str(summary.get("last_updated_at") or ""),
            }

            logger.debug(
                "get_statistics_completed",
                extra={"saishi_id": saishi_id, "total": total},
            )
            return result

        except Exception as exc:
            logger.error(
                "get_statistics_failed",
                extra={"saishi_id": saishi_id, "error": str(exc)},
                exc_info=True,
            )
            raise

    def delete_by_saishi_id(self, saishi_id: str) -> int:
        """删除指定比赛的所有球员关系记录。

        Args:
            saishi_id: 比赛 ID（直播吧 saishi_id）

        Returns:
            删除的记录数
        """
        try:
            result = self._db.execute(
                text(
                    """
                    DELETE FROM nba_zhiboba_player_relation
                    WHERE saishi_id = :saishi_id
                    """
                ),
                {"saishi_id": saishi_id},
            )
            deleted = result.rowcount
            self._db.commit()

            logger.info(
                "delete_by_saishi_id_completed",
                extra={"saishi_id": saishi_id, "deleted": deleted},
            )
            return deleted

        except Exception as exc:
            self._db.rollback()
            logger.error(
                "delete_by_saishi_id_failed",
                extra={"saishi_id": saishi_id, "error": str(exc)},
                exc_info=True,
            )
            raise
