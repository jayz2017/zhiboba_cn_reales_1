from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.modules.semantics.constants import (
    DEFAULT_CONFIDENCE_VALUES,
    DEFAULT_KEYWORD_GROUPS,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RelationRuleConfig:
    keyword_groups: dict[str, tuple[str, ...]]
    confidence_values: dict[str, float]

    def keywords(self, category: str) -> tuple[str, ...]:
        return self.keyword_groups.get(category, ())

    def confidence(self, config_key: str) -> float:
        return self.confidence_values.get(
            config_key,
            DEFAULT_CONFIDENCE_VALUES.get(config_key, 0.5),
        )


_SQL_LOAD_KEYWORDS = """
SELECT category, keyword, is_enabled
FROM nba_zhiboba_relation_rule_keyword
ORDER BY category ASC, id ASC
""".strip()

_SQL_LOAD_CONFIDENCE = """
SELECT config_key, confidence
FROM nba_zhiboba_relation_confidence
WHERE is_enabled = 1
""".strip()


def default_relation_rule_config() -> RelationRuleConfig:
    return RelationRuleConfig(
        keyword_groups={category: tuple(keywords) for category, keywords in DEFAULT_KEYWORD_GROUPS.items()},
        confidence_values=dict(DEFAULT_CONFIDENCE_VALUES),
    )


def load_relation_rule_config(db: Session | None = None) -> RelationRuleConfig:
    config = default_relation_rule_config()
    if db is None:
        return config

    try:
        keyword_rows = db.execute(text(_SQL_LOAD_KEYWORDS)).mappings().all()
        confidence_rows = db.execute(text(_SQL_LOAD_CONFIDENCE)).mappings().all()
    except Exception as exc:
        logger.warning(
            "relation_rule_config_load_failed_using_defaults",
            extra={"error": str(exc)},
            exc_info=True,
        )
        return config

    keyword_groups = {category: list(keywords) for category, keywords in config.keyword_groups.items()}
    categories_seen: set[str] = set()
    db_keyword_groups: dict[str, list[str]] = {}
    for row in keyword_rows:
        category = _string_value(row, "category")
        keyword = _string_value(row, "keyword")
        if not category or not keyword:
            continue
        categories_seen.add(category)
        if _enabled_value(row, "is_enabled"):
            db_keyword_groups.setdefault(category, []).append(keyword)

    for category in categories_seen:
        keyword_groups[category] = _deduplicate(db_keyword_groups.get(category, []))

    confidence_values = dict(config.confidence_values)
    for row in confidence_rows:
        config_key = _string_value(row, "config_key")
        if not config_key:
            continue
        confidence = _float_value(row, "confidence")
        if confidence is None:
            continue
        confidence_values[config_key] = max(0.0, min(1.0, confidence))

    return RelationRuleConfig(
        keyword_groups={category: tuple(keywords) for category, keywords in keyword_groups.items()},
        confidence_values=confidence_values,
    )


def _string_value(row: Any, key: str) -> str | None:
    value = row.get(key)
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None


def _float_value(row: Any, key: str) -> float | None:
    value = row.get(key)
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _enabled_value(row: Any, key: str) -> bool:
    value = row.get(key)
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip() not in {"", "0", "false", "False"}
    return False


def _deduplicate(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


__all__ = [
    "RelationRuleConfig",
    "default_relation_rule_config",
    "load_relation_rule_config",
]
