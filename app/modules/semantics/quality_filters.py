from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Literal

from app.modules.semantics.models import PlayerRelationRecord

logger = logging.getLogger(__name__)

_OFFENSE_RELATION_TYPES = frozenset({
    "passes_to", "assist_to", "attacks_against", "scores_over",
    "screen_for", "rebounds_over",
})

_DEFENSE_RELATION_TYPES = frozenset({
    "blocks", "steals_from", "defends", "rebounds_over",
    "fouls_on", "forces_turnover", "contests_shot",
})

_SELF_CONFLICT_TYPES: dict[frozenset[str], str] = {
    frozenset({"passes_to", "steals_from"}): "cannot_pass_and_steal",
    frozenset({"assist_to", "blocks"}): "cannot_assist_and_block",
}


@dataclass(frozen=True)
class QualityFilterConfig:
    """关系数据质量过滤器配置。

    Attributes:
        min_confidence: 最低置信度阈值，低于此值的关系将被过滤
        max_text_length: 最大文本长度（字符数），超过将被过滤
        require_team_info: 是否强制要求主体和客体都有球队信息
        block_self_relations: 是否阻止 subject == object 的自指关系
        dedup_strategy: 去重策略，first_win 保留首次出现、last_win 保留最后一次、
                        highest_confidence 保留置信度最高者
    """
    min_confidence: float = 0.5
    max_text_length: int = 500
    require_team_info: bool = False
    block_self_relations: bool = True
    dedup_strategy: Literal["first_win", "last_win", "highest_confidence"] = "first_win"

    def __post_init__(self) -> None:
        object.__setattr__(self, "min_confidence", max(0.0, min(1.0, self.min_confidence)))
        object.__setattr__(self, "max_text_length", max(1, self.max_text_length))
        valid_strategies = {"first_win", "last_win", "highest_confidence"}
        if self.dedup_strategy not in valid_strategies:
            raise ValueError(
                f"dedup_strategy must be one of {valid_strategies}, got '{self.dedup_strategy}'"
            )


@dataclass
class FilterResult:
    """过滤结果数据类。

    Attributes:
        filtered_relations: 通过所有过滤规则的关系记录列表
        original_count: 过滤前的原始记录数量
        filtered_count: 被移除的记录数量
        removal_reasons: 按原因统计的移除记录数量映射
    """
    filtered_relations: list[PlayerRelationRecord]
    original_count: int
    filtered_count: int
    removal_reasons: dict[str, int] = field(default_factory=dict)

    @property
    def pass_rate(self) -> float:
        """计算通过率。"""
        if self.original_count == 0:
            return 1.0
        return len(self.filtered_relations) / self.original_count

    def summary(self) -> str:
        """生成可读的过滤结果摘要。"""
        lines = [
            f"质量过滤完成: 原始={self.original_count}, "
            f"通过={len(self.filtered_relations)}, "
            f"移除={self.filtered_count}, 通过率={self.pass_rate:.1%}",
        ]
        if self.removal_reasons:
            lines.append("移除原因统计:")
            for reason, count in sorted(self.removal_reasons.items(), key=lambda x: -x[1]):
                lines.append(f"  - {reason}: {count}")
        return "\n".join(lines)


class RelationQualityFilter:
    """多层关系数据质量过滤器。

    按顺序执行以下过滤管道：
    1. 移除自指关系 (subject == object)
    2. 置信度阈值过滤
    3. 文本长度校验
    4. 球队逻辑一致性检查
    5. 冲突解决
    6. 去重

    示例::

        config = QualityFilterConfig(min_confidence=0.6, block_self_relations=True)
        filter_instance = RelationQualityFilter(config)
        result = filter_instance.filter(relations)
        print(result.summary())
    """

    def __init__(self, config: QualityFilterConfig | None = None) -> None:
        self.config = config or QualityFilterConfig()
        self._removal_reasons: dict[str, int] = defaultdict(int)

    def filter(self, relations: list[PlayerRelationRecord]) -> FilterResult:
        """执行完整过滤管道。

        Args:
            relations: 待过滤的球员关系记录列表

        Returns:
            FilterResult 包含过滤后的记录及统计信息
        """
        self._removal_reasons = defaultdict(int)
        original_count = len(relations)
        logger.info("开始质量过滤, 输入记录数=%d, 配置=%s", original_count, self.config)

        if not relations:
            logger.info("输入为空列表, 直接返回空结果")
            return FilterResult(
                filtered_relations=[],
                original_count=0,
                filtered_count=0,
                removal_reasons={},
            )

        current = list(relations)

        if self.config.block_self_relations:
            current = self._remove_self_loops(current)

        current = self._apply_confidence_threshold(current)
        current = self._validate_text_length(current)

        if self.config.require_team_info:
            current = self._validate_team_consistency(current)

        current = self._resolve_conflicts(current)
        current = self._deduplicate(current)

        filtered_count = original_count - len(current)
        reasons = dict(self._removal_reasons)

        logger.info(
            "质量过滤完成: 原始=%d, 通过=%d, 移除=%d, 原因=%s",
            original_count, len(current), filtered_count, reasons,
        )

        return FilterResult(
            filtered_relations=current,
            original_count=original_count,
            filtered_count=filtered_count,
            removal_reasons=reasons,
        )

    def _remove_self_loops(self, relations: list[PlayerRelationRecord]) -> list[PlayerRelationRecord]:
        """移除 subject == object 的自指关系。"""
        result = [
            r for r in relations
            if r.subject_player_name != r.object_player_name
        ]
        removed = len(relations) - len(result)
        if removed > 0:
            self._removal_reasons["self_loop"] += removed
            logger.debug("移除自指关系: %d 条", removed)
        return result

    def _apply_confidence_threshold(
        self, relations: list[PlayerRelationRecord]
    ) -> list[PlayerRelationRecord]:
        """过滤低于置信度阈值的记录。"""
        threshold = self.config.min_confidence
        result = [r for r in relations if r.confidence >= threshold]
        removed = len(relations) - len(result)
        if removed > 0:
            self._removal_reasons["low_confidence"] += removed
            logger.debug("置信度过滤(<%.2f): 移除 %d 条", threshold, removed)
        return result

    def _validate_text_length(self, relations: list[PlayerRelationRecord]) -> list[PlayerRelationRecord]:
        """过滤证据文本超过最大长度的记录。"""
        max_len = self.config.max_text_length
        result = [
            r for r in relations
            if len(r.evidence_text) <= max_len
        ]
        removed = len(relations) - len(result)
        if removed > 0:
            self._removal_reasons["text_too_long"] += removed
            logger.debug("文本长度过滤(>%d): 移除 %d 条", max_len, removed)
        return result

    def _validate_team_consistency(
        self, relations: list[PlayerRelationRecord]
    ) -> list[PlayerRelationRecord]:
        """检查球队逻辑一致性。

        规则：
        - 主体和客体都必须有球队信息
        - 同一球队的球员之间不能存在某些矛盾关系（如自己助攻自己得分）
        - 进攻方关系要求 subject 与 offense_team 一致
        """
        result: list[PlayerRelationRecord] = []
        for rel in relations:
            if not rel.subject_team_id or not rel.object_team_id:
                self._removal_reasons["missing_team_info"] += 1
                logger.debug(
                    "缺少球队信息: subject=%s(%s), object=%s(%s)",
                    rel.subject_player_name, rel.subject_team_id,
                    rel.object_player_name, rel.object_team_id,
                )
                continue

            same_team = (
                rel.subject_team_id == rel.object_team_id
                and rel.subject_team_id is not None
            )
            if same_team and rel.relation_type in ("steals_from", "blocks"):
                self._removal_reasons["same_team_conflict"] += 1
                logger.debug(
                    "同队冲突关系: %s -> %s [%s]",
                    rel.subject_player_name, rel.object_player_name, rel.relation_type,
                )
                continue

            if (
                rel.relation_type in _OFFENSE_RELATION_TYPES
                and rel.offense_team_id
                and rel.subject_team_id != rel.offense_team_id
            ):
                self._removal_reasons["offense_side_mismatch"] += 1
                logger.debug(
                    "进攻方不匹配: subject_team=%s, offense_team=%s, type=%s",
                    rel.subject_team_id, rel.offense_team_id, rel.relation_type,
                )
                continue

            result.append(rel)

        return result

    def _resolve_conflicts(self, relations: list[PlayerRelationRecord]) -> list[PlayerRelationRecord]:
        """解决同一对球员在同一事件中的冲突关系。

        例如：同一场比赛中 A 对 B 同时有助攻和单打，
        根据优先级保留更合理的关系。
        """
        event_key_map: dict[tuple[str, str, str], list[PlayerRelationRecord]] = defaultdict(list)
        for rel in relations:
            key = (rel.saishi_id, rel.evidence_event_id, rel.live_sid)
            normalized_subject = rel.subject_player_name.strip().lower()
            normalized_object = rel.object_player_name.strip().lower()
            pair_key = (
                key[0], key[1], key[2],
                min(normalized_subject, normalized_object),
                max(normalized_subject, normalized_object),
            )
            event_key_map[pair_key].append(rel)

        result: list[PlayerRelationRecord] = []
        for pair_key, group in event_key_map.items():
            resolved = self._resolve_group_conflict(group)
            result.extend(resolved)

        return result

    def _resolve_group_conflict(
        self, group: list[PlayerRelationRecord]
    ) -> list[PlayerRelationRecord]:
        """对同一事件中同一对球员的多条关系进行冲突解决。"""
        if len(group) <= 1:
            return group

        type_set = {r.relation_type for r in group}
        for conflict_types, reason in _SELF_CONFLICT_TYPES.items():
            if conflict_types.issubset(type_set):
                kept = max(group, key=lambda r: r.confidence)
                removed_count = len(group) - 1
                self._removal_reasons[reason] += removed_count
                logger.debug(
                    "冲突解决[%s]: 保留 %s->%s [%s], 移除 %d 条",
                    reason, kept.subject_player_name, kept.object_player_name,
                    kept.relation_type, removed_count,
                )
                return [kept]

        offense_rels = [r for r in group if r.relation_type in _OFFENSE_RELATION_TYPES]
        defense_rels = [r for r in group if r.relation_type in _DEFENSE_RELATION_TYPES]

        if offense_rels and defense_rels:
            best_offense = max(offense_rels, key=lambda r: r.confidence)
            best_defense = max(defense_rels, key=lambda r: r.confidence)
            removed_count = len(group) - 2
            if removed_count > 0:
                self._removal_reasons["offense_defense_dedup"] += removed_count
            return [best_offense, best_defense]

        best = max(group, key=lambda r: r.confidence)
        removed_count = len(group) - 1
        if removed_count > 0:
            self._removal_reasons["conflict_keep_best"] += removed_count
        return [best]

    def _deduplicate(self, relations: list[PlayerRelationRecord]) -> list[PlayerRelationRecord]:
        """基于唯一键去重。

        唯一键由 (saishi_id, evidence_event_id, relation_type,
        subject_player_name, object_player_name) 组成。
        """
        seen_keys: set[tuple[str, int, str, str, str]] = set()
        result: list[PlayerRelationRecord] = []

        strategy = self.config.dedup_strategy

        if strategy == "last_win":
            relations = list(reversed(relations))

        candidate_map: dict[
            tuple[str, int, str, str, str], PlayerRelationRecord
        ] = {}

        for rel in relations:
            key = (
                rel.saishi_id,
                rel.evidence_event_id,
                rel.relation_type,
                rel.subject_player_name,
                rel.object_player_name,
            )
            if key in seen_keys:
                if strategy == "highest_confidence":
                    existing = candidate_map[key]
                    if rel.confidence > existing.confidence:
                        candidate_map[key] = rel
                continue
            seen_keys.add(key)
            candidate_map[key] = rel

        deduped = list(candidate_map.values())
        removed = len(relations) - len(deduped)
        if removed > 0:
            self._removal_reasons["duplicate"] += removed
            logger.debug("去重(strategy=%s): 移除 %d 条", strategy, removed)

        return deduped
