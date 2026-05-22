from __future__ import annotations

from dataclasses import dataclass
from datetime import date, time

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.modules.nba_live_text.zhiboba_livetext import (
    LINE_SKIP_RULE_TYPE,
    MATCH_MODE_CONTAINS,
    MATCH_MODE_EXACT,
    TARGET_LIVE_TEXT,
    TARGET_PID_TEXT,
    clean_live_text_for_tokenization,
    fetch_zhiboba_live_text_events,
    load_live_text_filter_rules,
    split_filter_rules,
    sync_zhiboba_live_text,
)
from app.utils.http.client import HttpClient

_SQL_INSERT_FILTER_RULE_IGNORE = """
INSERT IGNORE INTO nba_zhiboba_live_text_filter_rule
  (rule_type, target_field, match_mode, filter_text, is_enabled, sort_order)
VALUES
  (:rule_type, :target_field, :match_mode, :filter_text, 1, :sort_order)
""".strip()


@dataclass(frozen=True)
class GameListAutoTuneTarget:
    saishi_id: str
    home_team: str | None
    visit_team: str | None
    sdate: date | None
    start_time: time | None


def select_next_game_list_target(db: Session) -> GameListAutoTuneTarget | None:
    row = db.execute(
        text(
            """
            SELECT
              game.id AS saishi_id,
              game.home_team,
              game.visit_team,
              game.sdate,
              game.`start` AS start_time,
              COALESCE(event_stats.event_count, 0) AS event_count
            FROM game_list AS game
            LEFT JOIN (
              SELECT saishi_id, COUNT(*) AS event_count
              FROM nba_zhiboba_live_text_event
              GROUP BY saishi_id
            ) AS event_stats
              ON event_stats.saishi_id = game.id
            WHERE UPPER(TRIM(COALESCE(game.type, 'NBA'))) = 'NBA'
            ORDER BY
              CASE WHEN COALESCE(event_stats.event_count, 0) = 0 THEN 0 ELSE 1 END ASC,
              game.sdate ASC,
              game.`start` ASC,
              game.id ASC
            LIMIT 1
            """
        )
    ).fetchone()
    if not row:
        return None

    saishi_id = getattr(row, "saishi_id", None)
    if not isinstance(saishi_id, str) or not saishi_id.strip():
        return None

    home_team = getattr(row, "home_team", None)
    visit_team = getattr(row, "visit_team", None)
    sdate = getattr(row, "sdate", None)
    start_time = getattr(row, "start_time", None)
    return GameListAutoTuneTarget(
        saishi_id=saishi_id.strip(),
        home_team=home_team.strip() if isinstance(home_team, str) and home_team.strip() else None,
        visit_team=visit_team.strip() if isinstance(visit_team, str) and visit_team.strip() else None,
        sdate=sdate if isinstance(sdate, date) else None,
        start_time=start_time if isinstance(start_time, time) else None,
    )


def purge_live_text_for_saishi(db: Session, saishi_id: str) -> dict[str, int]:
    event_count = db.execute(
        text("SELECT COUNT(*) FROM nba_zhiboba_live_text_event WHERE saishi_id = :saishi_id"),
        {"saishi_id": saishi_id},
    ).scalar() or 0

    db.execute(
        text("DELETE FROM nba_zhiboba_live_text_event WHERE saishi_id = :saishi_id"),
        {"saishi_id": saishi_id},
    )
    db.commit()
    return {"deleted_events": int(event_count)}


def apply_auto_tune_filter_rules(db: Session, saishi_id: str) -> dict[str, int | list[str]]:
    rules = load_live_text_filter_rules(db=db)
    _, content_remove_rules = split_filter_rules(rules)
    rows = db.execute(
        text(
            """
            SELECT live_text, COUNT(*) AS hit_count
            FROM nba_zhiboba_live_text_event
            WHERE saishi_id = :saishi_id
              AND (segmented_text IS NULL OR TRIM(segmented_text) = '')
              AND live_text IS NOT NULL
              AND TRIM(live_text) <> ''
            GROUP BY live_text
            ORDER BY hit_count DESC, live_text ASC
            """
        ),
        {"saishi_id": saishi_id},
    ).fetchall()

    applied_rules: list[str] = []
    sort_order = 9000
    for row in rows:
        live_text = getattr(row, "live_text", None)
        if not isinstance(live_text, str) or not live_text.strip():
            continue
        cleaned = clean_live_text_for_tokenization(live_text, content_remove_rules)
        if cleaned:
            continue
        normalized_live_text = live_text.strip()
        db.execute(
            text(_SQL_INSERT_FILTER_RULE_IGNORE),
            {
                "rule_type": LINE_SKIP_RULE_TYPE,
                "target_field": TARGET_LIVE_TEXT,
                "match_mode": MATCH_MODE_EXACT,
                "filter_text": normalized_live_text,
                "sort_order": sort_order,
            },
        )
        applied_rules.append(normalized_live_text)
        sort_order += 1

    db.commit()
    return {"applied_rule_count": len(applied_rules), "applied_rules": applied_rules}


def load_segmented_examples_by_saishi_id(db: Session, saishi_id: str, *, limit: int = 10) -> list[dict[str, str | int]]:
    rows = db.execute(
        text(
            """
            SELECT live_sid, pid_text, live_pid, live_text, segmented_text
            FROM nba_zhiboba_live_text_event
            WHERE saishi_id = :saishi_id
              AND segmented_text IS NOT NULL
              AND TRIM(segmented_text) <> ''
            ORDER BY live_sid ASC
            LIMIT :limit_rows
            """
        ),
        {"saishi_id": saishi_id, "limit_rows": max(1, int(limit))},
    ).fetchall()
    examples: list[dict[str, str | int]] = []
    for row in rows:
        examples.append(
            {
                "live_sid": int(getattr(row, "live_sid")),
                "pid_text": (getattr(row, "pid_text", None) or ""),
                "live_pid": (getattr(row, "live_pid", None) or ""),
                "live_text": getattr(row, "live_text", ""),
                "segmented_text": getattr(row, "segmented_text", ""),
            }
        )
    return examples


def validate_live_text_segmentation_spec(
    db: Session,
    saishi_id: str,
    *,
    sample_limit: int = 20,
) -> dict[str, object]:
    rule_rows = db.execute(
        text(
            """
            SELECT id, target_field, match_mode, filter_text
            FROM nba_zhiboba_live_text_filter_rule
            WHERE is_enabled = 1
              AND rule_type = :rule_type
              AND target_field IN (:target_pid_text, :target_live_text)
              AND match_mode IN (:match_mode_exact, :match_mode_contains)
            ORDER BY sort_order ASC, id ASC
            """
        ),
        {
            "rule_type": LINE_SKIP_RULE_TYPE,
            "target_pid_text": TARGET_PID_TEXT,
            "target_live_text": TARGET_LIVE_TEXT,
            "match_mode_exact": MATCH_MODE_EXACT,
            "match_mode_contains": MATCH_MODE_CONTAINS,
        },
    ).fetchall()

    violation_summaries: list[dict[str, object]] = []
    violation_examples: list[dict[str, object]] = []

    for row in rule_rows:
        rule_id = int(getattr(row, "id"))
        target_field = getattr(row, "target_field", "")
        match_mode = getattr(row, "match_mode", "")
        filter_text = getattr(row, "filter_text", "")
        if not isinstance(filter_text, str) or not filter_text.strip():
            continue
        normalized_filter_text = filter_text.strip()
        like_text = f"%{normalized_filter_text}%"

        if match_mode == MATCH_MODE_EXACT and target_field == TARGET_PID_TEXT:
            count_sql = """
                SELECT COUNT(*)
                FROM nba_zhiboba_live_text_event
                WHERE saishi_id = :saishi_id
                  AND pid_text = :filter_text
                  AND segmented_text IS NOT NULL
                  AND TRIM(segmented_text) <> ''
            """
            sample_sql = """
                SELECT saishi_id, live_sid, pid_text, live_text, segmented_text
                FROM nba_zhiboba_live_text_event
                WHERE saishi_id = :saishi_id
                  AND pid_text = :filter_text
                  AND segmented_text IS NOT NULL
                  AND TRIM(segmented_text) <> ''
                ORDER BY live_sid ASC
                LIMIT :limit_rows
            """
        elif match_mode == MATCH_MODE_EXACT and target_field == TARGET_LIVE_TEXT:
            count_sql = """
                SELECT COUNT(*)
                FROM nba_zhiboba_live_text_event
                WHERE saishi_id = :saishi_id
                  AND live_text = :filter_text
                  AND segmented_text IS NOT NULL
                  AND TRIM(segmented_text) <> ''
            """
            sample_sql = """
                SELECT saishi_id, live_sid, pid_text, live_text, segmented_text
                FROM nba_zhiboba_live_text_event
                WHERE saishi_id = :saishi_id
                  AND live_text = :filter_text
                  AND segmented_text IS NOT NULL
                  AND TRIM(segmented_text) <> ''
                ORDER BY live_sid ASC
                LIMIT :limit_rows
            """
        elif match_mode == MATCH_MODE_CONTAINS and target_field == TARGET_PID_TEXT:
            count_sql = """
                SELECT COUNT(*)
                FROM nba_zhiboba_live_text_event
                WHERE saishi_id = :saishi_id
                  AND (
                    (pid_text IS NOT NULL AND pid_text LIKE :filter_text_like)
                    OR (segmented_text IS NOT NULL AND segmented_text LIKE :filter_text_like)
                  )
            """
            sample_sql = """
                SELECT saishi_id, live_sid, pid_text, live_text, segmented_text
                FROM nba_zhiboba_live_text_event
                WHERE saishi_id = :saishi_id
                  AND (
                    (pid_text IS NOT NULL AND pid_text LIKE :filter_text_like)
                    OR (segmented_text IS NOT NULL AND segmented_text LIKE :filter_text_like)
                  )
                ORDER BY live_sid ASC
                LIMIT :limit_rows
            """
        else:
            count_sql = """
                SELECT COUNT(*)
                FROM nba_zhiboba_live_text_event
                WHERE saishi_id = :saishi_id
                  AND (
                    (live_text IS NOT NULL AND live_text LIKE :filter_text_like)
                    OR (segmented_text IS NOT NULL AND segmented_text LIKE :filter_text_like)
                  )
            """
            sample_sql = """
                SELECT saishi_id, live_sid, pid_text, live_text, segmented_text
                FROM nba_zhiboba_live_text_event
                WHERE saishi_id = :saishi_id
                  AND (
                    (live_text IS NOT NULL AND live_text LIKE :filter_text_like)
                    OR (segmented_text IS NOT NULL AND segmented_text LIKE :filter_text_like)
                  )
                ORDER BY live_sid ASC
                LIMIT :limit_rows
            """

        params = {
            "saishi_id": saishi_id,
            "filter_text": normalized_filter_text,
            "filter_text_like": like_text,
            "limit_rows": max(1, int(sample_limit)),
        }
        violation_count = int(db.execute(text(count_sql), params).scalar() or 0)
        if violation_count <= 0:
            continue

        violation_summaries.append(
            {
                "rule_id": rule_id,
                "target_field": target_field,
                "match_mode": match_mode,
                "filter_text": normalized_filter_text,
                "violation_count": violation_count,
            }
        )
        sample_rows = db.execute(text(sample_sql), params).fetchall()
        for sample_row in sample_rows:
            if len(violation_examples) >= max(1, int(sample_limit)):
                break
            violation_examples.append(
                {
                    "rule_id": rule_id,
                    "target_field": target_field,
                    "match_mode": match_mode,
                    "filter_text": normalized_filter_text,
                    "saishi_id": getattr(sample_row, "saishi_id", ""),
                    "live_sid": int(getattr(sample_row, "live_sid")),
                    "pid_text": getattr(sample_row, "pid_text", "") or "",
                    "live_text": getattr(sample_row, "live_text", "") or "",
                    "segmented_text": getattr(sample_row, "segmented_text", "") or "",
                }
            )
        if len(violation_examples) >= max(1, int(sample_limit)):
            break

    return {
        "passed": len(violation_summaries) == 0,
        "needs_update_fetch_skill": len(violation_summaries) > 0,
        "violation_rule_count": len(violation_summaries),
        "violation_summaries": violation_summaries,
        "violation_examples": violation_examples,
    }


def auto_tune_next_game_live_text(
    db: Session,
    http_client: HttpClient,
    *,
    sample_limit: int = 10,
    max_attempts: int = 3,
) -> dict[str, object]:
    target = select_next_game_list_target(db=db)
    if target is None:
        return {
            "message": "game_list 中没有可处理的比赛数据",
            "processed": False,
        }

    attempt_results: list[dict[str, object]] = []
    fetch_result: dict[str, object] | None = None
    sync_result: dict[str, object] | None = None
    tune_result: dict[str, object] | None = None
    validation_result: dict[str, object] | None = None
    rerun_result: dict[str, object] | None = None
    stop_reason = "validation_passed"

    for attempt in range(1, max(1, int(max_attempts)) + 1):
        fetch_result = fetch_zhiboba_live_text_events(
            db=db,
            http_client=http_client,
            saishi_id=target.saishi_id,
        )
        sync_result = sync_zhiboba_live_text(
            db=db,
            http_client=http_client,
            saishi_id=target.saishi_id,
        )
        tune_result = apply_auto_tune_filter_rules(db=db, saishi_id=target.saishi_id)
        validation_result = validate_live_text_segmentation_spec(
            db=db,
            saishi_id=target.saishi_id,
            sample_limit=sample_limit,
        )
        attempt_results.append(
            {
                "attempt": attempt,
                "fetch_result": fetch_result,
                "sync_result": sync_result,
                "tune_result": tune_result,
                "validation_result": validation_result,
            }
        )

        if bool(validation_result["passed"]):
            stop_reason = "validation_passed"
            break

        if int(tune_result["applied_rule_count"]) <= 0:
            stop_reason = "validation_failed_without_new_rules"
            break

        if attempt >= max(1, int(max_attempts)):
            stop_reason = "reached_max_attempts"
            break

        purge_result = purge_live_text_for_saishi(db=db, saishi_id=target.saishi_id)
        rerun_result = {
            "attempt": attempt,
            "purge_result": purge_result,
        }

    return {
        "processed": True,
        "saishi_id": target.saishi_id,
        "home_team": target.home_team,
        "visit_team": target.visit_team,
        "sdate": target.sdate.isoformat() if target.sdate else None,
        "start_time": target.start_time.isoformat() if target.start_time else None,
        "fetch_result": fetch_result,
        "sync_result": sync_result,
        "tune_result": tune_result,
        "validation_result": validation_result,
        "rerun_result": rerun_result,
        "attempt_count": len(attempt_results),
        "max_attempts": max(1, int(max_attempts)),
        "stop_reason": stop_reason,
        "attempt_results": attempt_results,
        "segmented_examples": load_segmented_examples_by_saishi_id(
            db=db,
            saishi_id=target.saishi_id,
            limit=sample_limit,
        ),
    }
