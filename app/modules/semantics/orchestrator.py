from __future__ import annotations

import logging
import time
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.modules.nba_live_text.zhiboba_livetext import (
    LIVE_TEXT_SOURCE_ZHIBOBA,
    ensure_live_text_tables,
    load_player_segmentation_config,
)
from app.modules.semantics.models import (
    PlayerRelationRecord,
    _PossessionTracker,
)
from app.modules.semantics.schema import (
    _SQL_UPSERT_PLAYER_RELATION,
    ensure_player_relation_table,
    ensure_relation_rule_config_tables,
)
from app.modules.semantics.ontology import format_relation_sample
from app.modules.semantics.quality_filters import QualityFilterConfig, RelationQualityFilter
from app.modules.semantics.rule_config import load_relation_rule_config
from app.modules.semantics.siamese_uie import (
    SiameseUIEExtractor,
    _build_event_context_from_row,
    build_relation_records_with_rule_fallback,
)
from app.modules.semantics.uie_result_parser import (
    build_relation_records_from_uie_result,
    normalize_segmented_text_for_uie,
)

logger = logging.getLogger(__name__)


def upsert_player_relations(db: Session, relations: list[PlayerRelationRecord], batch_size: int = 500) -> int:
    if not relations:
        return 0

    total_affected = 0
    for batch_start in range(0, len(relations), batch_size):
        batch = relations[batch_start:batch_start + batch_size]
        params = [
            {
                "saishi_id": relation.saishi_id,
                "evidence_event_id": relation.evidence_event_id,
                "live_sid": relation.live_sid,
                "source": relation.source,
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
        db.execute(text(_SQL_UPSERT_PLAYER_RELATION), params)
        total_affected += len(batch)
    
    db.commit()
    return total_affected


def extract_postgame_player_relations(
    db: Session,
    *,
    saishi_id: str,
    max_rows: int = 5000,
    sample_limit: int = 20,
) -> dict[str, Any]:
    start_time = time.time()
    logger.info("relation_extraction_started", extra={"saishi_id": saishi_id, "max_rows": max_rows})

    ensure_live_text_tables(db=db)
    ensure_player_relation_table(db=db)
    ensure_relation_rule_config_tables(db=db)
    rule_config = load_relation_rule_config(db=db)
    segmentation_config = load_player_segmentation_config(db=db, saishi_id=saishi_id)
    
    rows = db.execute(
        text(
            """
            SELECT
              id,
              saishi_id,
              live_sid,
              source,
              live_text,
              segmented_text,
              current_player_name,
              score_points,
              home_score,
              visit_score,
              score_team_side
            FROM nba_zhiboba_live_text_event
            WHERE saishi_id = :saishi_id
              AND source = :source
              AND segmented_text IS NOT NULL
              AND TRIM(segmented_text) <> ''
            ORDER BY live_sid ASC
            LIMIT :limit_rows
            """
        ),
        {
            "saishi_id": saishi_id,
            "source": LIVE_TEXT_SOURCE_ZHIBOBA,
            "limit_rows": max(1, int(max_rows)),
        },
    ).mappings().all()
    
    logger.info("events_loaded", extra={"saishi_id": saishi_id, "event_count": len(rows)})
    
    if not rows:
        logger.warning("no_segmented_events_found", extra={"saishi_id": saishi_id})
        return {
            "processed": False,
            "saishi_id": saishi_id,
            "message": "未找到已完成分词的直播文本记录",
            "events": 0,
            "relations": 0,
            "backend": "empty",
            "samples": [],
        }

    extractor = SiameseUIEExtractor()
    model_inputs = [normalize_segmented_text_for_uie(row["segmented_text"], row["live_text"]) for row in rows]
    
    logger.info("uie_model_inference_start", extra={"saishi_id": saishi_id, "input_count": len(model_inputs)})
    raw_results = extractor.extract_batch(model_inputs)
    logger.info("uie_model_inference_complete", extra={
        "saishi_id": saishi_id,
        "backend": extractor.last_backend,
        "duration_seconds": round(time.time() - start_time, 2)
    })

    relation_records: list[PlayerRelationRecord] = []
    samples: list[dict[str, Any]] = []
    possession_tracker = _PossessionTracker()

    for idx, (row, raw_result) in enumerate(zip(rows, raw_results, strict=False)):
        current_player_name = row["current_player_name"] if isinstance(row["current_player_name"], str) else None

        event_context, possession_tracker = _build_event_context_from_row(
            row=dict(row),
            segmentation_config=segmentation_config,
            possession_tracker=possession_tracker,
        )

        built_relations: list[PlayerRelationRecord] = []
        try:
            built_relations = build_relation_records_from_uie_result(
                saishi_id=row["saishi_id"],
                evidence_event_id=int(row["id"]),
                live_sid=int(row["live_sid"]),
                live_text=row["live_text"],
                segmented_text=row["segmented_text"],
                current_player_name=current_player_name,
                score_points=int(row["score_points"]) if row["score_points"] is not None else None,
                uie_result=raw_result,
                segmentation_config=segmentation_config,
                event_context=event_context,
                rule_config=rule_config,
                source=str(row.get("source") or LIVE_TEXT_SOURCE_ZHIBOBA),
            )
            relation_records.extend(built_relations)
            
            if (idx + 1) % 100 == 0:
                logger.info("processing_progress", extra={
                    "saishi_id": saishi_id,
                    "processed": idx + 1,
                    "total": len(rows),
                    "relations_so_far": len(relation_records),
                    "progress_pct": round((idx + 1) / len(rows) * 100, 1)
                })
                
        except Exception as e:
            logger.error("row_processing_failed", extra={
                "saishi_id": saishi_id,
                "live_sid": row.get("live_sid"),
                "error": str(e),
                "index": idx
            }, exc_info=True)
            continue

        if built_relations and len(samples) < max(1, int(sample_limit)):
            for relation in built_relations:
                if len(samples) >= max(1, int(sample_limit)):
                    break
                samples.append(format_relation_sample(relation))

    if not relation_records and extractor.last_backend == "unavailable":
        logger.info("falling_back_to_rule_extractor", extra={"saishi_id": saishi_id})
        possession_tracker_fallback = _PossessionTracker()
        relation_records = build_relation_records_with_rule_fallback(
            rows=[dict(row) for row in rows],
            segmentation_config=segmentation_config,
            rule_config=rule_config,
        )
        for relation in relation_records[: max(1, int(sample_limit))]:
            samples.append(format_relation_sample(relation))
        if relation_records:
            extractor.last_backend = "rule_fallback"

    logger.info("applying_quality_filters", extra={
        "saishi_id": saishi_id,
        "raw_relations_count": len(relation_records)
    })
    
    quality_filter = RelationQualityFilter(config=QualityFilterConfig(
        min_confidence=0.5,
        block_self_relations=True,
        dedup_strategy="highest_confidence"
    ))
    filter_result = quality_filter.filter(relation_records)
    filtered_relations = filter_result.filtered_relations
    
    logger.info("quality_filtering_completed", extra={
        "saishi_id": saishi_id,
        "original_count": filter_result.original_count,
        "filtered_count": filter_result.filtered_count,
        "removed_count": filter_result.original_count - filter_result.filtered_count,
        "pass_rate": f"{filter_result.pass_rate:.1f}%",
        "removal_reasons": filter_result.removal_reasons
    })

    logger.info("persisting_relations_to_db", extra={
        "saishi_id": saishi_id,
        "relations_count": len(filtered_relations),
        "backend": extractor.last_backend
    })
    
    inserted = upsert_player_relations(db=db, relations=filtered_relations)
    
    duration = round(time.time() - start_time, 2)
    logger.info("relation_extraction_completed", extra={
        "saishi_id": saishi_id,
        "events": len(rows),
        "relations_raw": len(relation_records),
        "relations_filtered": len(filtered_relations),
        "relations_inserted": inserted,
        "backend": extractor.last_backend,
        "model_name": settings.SIAMESE_UIE_MODEL_NAME,
        "duration_seconds": duration,
        "samples_returned": len(samples),
        "quality_pass_rate": f"{filter_result.pass_rate:.1f}%"
    })
    
    return {
        "processed": True,
        "saishi_id": saishi_id,
        "events": len(rows),
        "relations": inserted,
        "relations_raw": len(relation_records),
        "relations_filtered": len(filtered_relations),
        "relations_inserted": inserted,
        "backend": extractor.last_backend,
        "model_name": settings.SIAMESE_UIE_MODEL_NAME,
        "quality_stats": {
            "original_count": filter_result.original_count,
            "filtered_count": filter_result.filtered_count,
            "removed_count": filter_result.original_count - filter_result.filtered_count,
            "pass_rate": round(filter_result.pass_rate, 2),
            "removal_reasons": filter_result.removal_reasons
        },
        "samples": samples,
    }


__all__ = [
    "upsert_player_relations",
    "extract_postgame_player_relations",
]