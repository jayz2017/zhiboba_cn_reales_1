from __future__ import annotations

import re
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from .livetext_schema import (
    CONTENT_REMOVE_RULE_TYPE,
    LINE_SKIP_RULE_TYPE,
    LiveTextFilterRule,
    MATCH_MODE_EXACT,
    MATCH_MODE_PREFIX,
    TARGET_LIVE_TEXT,
    TARGET_PID_TEXT,
    ZhibobaLiveTextEventRecord,
)

_LEADING_COMMENT_PREFIX_PATTERN = re.compile(r"^@[^:：]{1,64}[:：]\s*")


def load_live_text_filter_rules(db: Session) -> list[LiveTextFilterRule]:
    rows = db.execute(
        text(
            """
            SELECT rule_type, target_field, match_mode, filter_text
            FROM nba_zhiboba_live_text_filter_rule
            WHERE is_enabled = 1
            ORDER BY sort_order ASC, id ASC
            """
        )
    ).fetchall()
    rules: list[LiveTextFilterRule] = []
    for row in rows:
        rule_type = getattr(row, "rule_type", None)
        target_field = getattr(row, "target_field", None)
        match_mode = getattr(row, "match_mode", None)
        filter_text = getattr(row, "filter_text", None)
        if not all(isinstance(value, str) and value.strip() for value in (rule_type, target_field, match_mode, filter_text)):
            continue
        rules.append(
            LiveTextFilterRule(
                rule_type=rule_type.strip(),
                target_field=target_field.strip(),
                match_mode=match_mode.strip(),
                filter_text=filter_text.strip(),
            )
        )
    return rules


def split_filter_rules(
    rules: list[LiveTextFilterRule],
) -> tuple[list[LiveTextFilterRule], list[LiveTextFilterRule]]:
    line_skip_rules = [rule for rule in rules if rule.rule_type == LINE_SKIP_RULE_TYPE]
    content_remove_rules = [rule for rule in rules if rule.rule_type == CONTENT_REMOVE_RULE_TYPE]
    return line_skip_rules, content_remove_rules


def _get_rule_target_value(*, pid_text: str | None, live_text: str, target_field: str) -> str:
    if target_field == TARGET_PID_TEXT:
        return (pid_text or "").strip()
    return (live_text or "").strip()


def _matches_filter_rule(value: str, rule: LiveTextFilterRule) -> bool:
    if not value or not rule.filter_text:
        return False
    if rule.match_mode == MATCH_MODE_EXACT:
        return value == rule.filter_text
    if rule.match_mode == MATCH_MODE_PREFIX:
        return value.startswith(rule.filter_text)
    return rule.filter_text in value


def count_pending_payload_items(payload: Any) -> int:
    if not isinstance(payload, list):
        return 0
    count = 0
    for item in payload:
        if not isinstance(item, dict):
            continue
        pid_text = item.get("pid_text")
        if isinstance(pid_text, str) and pid_text.strip() == "未赛":
            count += 1
    return count


def count_line_skipped_payload_items(payload: Any, rules: list[LiveTextFilterRule]) -> int:
    if not isinstance(payload, list):
        return 0
    count = 0
    for item in payload:
        if not isinstance(item, dict):
            continue
        pid_text = item.get("pid_text")
        live_text = item.get("live_text")
        pid_text_value = pid_text.strip() if isinstance(pid_text, str) else None
        live_text_value = live_text.strip() if isinstance(live_text, str) else ""
        for rule in rules:
            target_value = _get_rule_target_value(
                pid_text=pid_text_value,
                live_text=live_text_value,
                target_field=rule.target_field,
            )
            if _matches_filter_rule(target_value, rule):
                count += 1
                break
    return count


def _should_skip_record(record: ZhibobaLiveTextEventRecord, rules: list[LiveTextFilterRule]) -> bool:
    for rule in rules:
        target_value = _get_rule_target_value(
            pid_text=record.pid_text,
            live_text=record.live_text,
            target_field=rule.target_field,
        )
        if _matches_filter_rule(target_value, rule):
            return True
    return False


def filter_live_text_records(
    records: list[ZhibobaLiveTextEventRecord], rules: list[LiveTextFilterRule]
) -> list[ZhibobaLiveTextEventRecord]:
    return [record for record in records if not _should_skip_record(record, rules)]


def clean_live_text_for_tokenization(content: str, rules: list[LiveTextFilterRule]) -> str:
    cleaned = (content or "").strip()
    if not cleaned:
        return ""
    cleaned = re.sub(r"\[[^\[\]]*]", "", cleaned)
    cleaned = _LEADING_COMMENT_PREFIX_PATTERN.sub("", cleaned)
    cleaned = re.sub(r"^@\s*", "", cleaned)
    for rule in rules:
        if rule.target_field != TARGET_LIVE_TEXT or not rule.filter_text:
            continue
        if rule.match_mode == MATCH_MODE_EXACT:
            if cleaned == rule.filter_text:
                cleaned = ""
        else:
            cleaned = cleaned.replace(rule.filter_text, "")
    return re.sub(r"\s+", " ", cleaned).strip()