from __future__ import annotations

import logging
from typing import Any

from app.modules.nba_live_text.zhiboba_livetext import normalize_player_name
from app.modules.semantics.context_builder import (
    _canonical_text,
    _extract_player_mentions_from_segmented_text,
    _row_score_points,
)
from app.modules.semantics.extractors.base import BaseRelationExtractor
from app.modules.semantics.models import (
    EventRelationContext,
    PlayerRelationRecord,
    PlayerSegmentationConfig,
    _FallbackContext,
    _PossessionTracker,
)
from app.modules.semantics.rule_config import (
    RelationRuleConfig,
    default_relation_rule_config,
)

logger = logging.getLogger(__name__)



class RuleBasedExtractor(BaseRelationExtractor):
    """基于关键词规则的球员关系抽取器实现。

    当 UIE 模型不可用时作为回退策略，通过匹配直播文本中的动作关键词
    （传球、抢断、封盖、得分、篮板等）识别球员间的攻防关系。

    继承自 BaseRelationExtractor，实现了 Strategy Pattern 中的具体策略。
    核心逻辑提取自 siamese_uie.build_relation_records_with_rule_fallback()。

    Attributes:
        last_backend: 上一次使用的后端标识（继承自基类，固定为 "rule_fallback"）

    Example:
        >>> extractor = RuleBasedExtractor()
        >>> rows = [{"live_text": "...", "segmented_text": "...", ...}]
        >>> config = load_player_segmentation_config(db, saishi_id)
        >>> relations = extractor.extract_from_rows(rows, config)
        >>> print(len(relations))
        42
    """

    def __init__(self, rule_config: RelationRuleConfig | None = None) -> None:
        """初始化规则抽取器实例。"""
        super().__init__()
        self.last_backend = "rule_fallback"
        self._rule_config = rule_config or default_relation_rule_config()

    def extract(self, text: str) -> dict[str, Any]:
        """对单条文本执行规则匹配（接口兼容实现）。

        规则抽取器主要设计用于批量行数据处理，单条文本抽取返回空字典。
        实际关系构建请使用 extract_from_rows 方法。

        Args:
            text: 输入文本（此方法不使用该参数）

        Returns:
            空字典，表示规则抽取器不提供单条文本的独立抽取结果
        """
        return {}

    def get_backend_name(self) -> str:
        """获取规则抽取器的后端标识。

        Returns:
            固定返回 "rule_fallback" 字符串
        """
        return "rule_fallback"

    def extract_from_rows(
        self,
        rows: list[dict[str, Any]],
        segmentation_config: PlayerSegmentationConfig,
    ) -> list[PlayerRelationRecord]:
        """从数据库行列表中批量提取球员关系记录。

        这是规则抽取器的核心方法，逐行分析直播文本事件，
        通过关键词匹配和上下文状态追踪构建攻防关系记录。

        处理流程：
        1. 提取每行的球员提及（基于分词文本）
        2. 按优先级匹配动作关键词：传球 > 对位 > 抢断 > 封盖 > 协防干扰 > 得分 > 篮板
        3. 维护跨事件的 FallbackContext 状态缓存
        4. 使用 PossessionTracker 追踪球权转换

        Args:
            rows: 数据库查询结果行列表，每行需包含以下字段：
                - live_text: 原始直播文本
                - segmented_text: 分词后的文本
                - current_player_name: 当前持球球员名
                - score_points: 得分数值
                - home_score/visit_score: 比分
                - score_team_side: 得分方阵营
                - id/live_sid/saishi_id: 主键与外键字段
            segmentation_config: 球员分词配置，包含别名映射和球队关联

        Returns:
            提取到的球员关系记录列表，每条记录包含主体/客体球员、
            关系类型、置信度、球队上下文等完整信息
        """
        relation_records: list[PlayerRelationRecord] = []
        seen_keys: set[tuple[str, str, str, int]] = set()
        context = _FallbackContext()
        possession_tracker = _PossessionTracker()

        for row in rows:
            evidence_text = row["live_text"]
            segmented_text = row["segmented_text"]
            canonical_live_text = _canonical_text(row["live_text"])
            canonical_segmented = _canonical_text(row["segmented_text"])
            player_mentions = _extract_player_mentions_from_segmented_text(
                segmented_text or row["live_text"],
                segmentation_config.alias_to_full_name,
            )
            score_points = _row_score_points(row)
            current_player_name = row["current_player_name"] if isinstance(row["current_player_name"], str) else None
            normalized_current = normalize_player_name(current_player_name, segmentation_config.alias_to_full_name) if current_player_name else None

            event_context, possession_tracker = self._build_event_context_from_row(
                row=row,
                segmentation_config=segmentation_config,
                possession_tracker=possession_tracker,
            )

            passer = player_mentions[0] if player_mentions else context.passer
            receiver = player_mentions[1] if len(player_mentions) > 1 else None
            primary_player = player_mentions[0] if player_mentions else normalized_current

            processed, possession_tracker = self._process_pass_keywords(
                canonical_live_text, player_mentions, context, possession_tracker,
                row, segmentation_config, event_context, evidence_text, segmented_text,
                relation_records, seen_keys, primary_player, normalized_current,
            )
            if processed:
                continue

            if self._process_attack_keywords(
                canonical_live_text, player_mentions, context,
                row, segmentation_config, event_context, evidence_text, segmented_text,
                relation_records, seen_keys, primary_player,
            ):
                continue

            processed, possession_tracker = self._process_steal_keywords(
                canonical_live_text, player_mentions, context, possession_tracker,
                row, segmentation_config, event_context, evidence_text, segmented_text,
                relation_records, seen_keys, primary_player,
            )
            if processed:
                continue

            if self._process_block_keywords(
                canonical_live_text, player_mentions, context,
                row, segmentation_config, event_context, evidence_text, segmented_text,
                relation_records, seen_keys, primary_player,
            ):
                continue

            if self._process_contest_keywords(
                canonical_live_text, primary_player, context,
                row, segmentation_config, event_context, evidence_text, segmented_text,
                relation_records, seen_keys,
            ):
                continue

            if self._process_scoring_events(
                score_points, primary_player, context,
                row, segmentation_config, event_context, evidence_text, segmented_text,
                relation_records, seen_keys, player_mentions,
            ):
                continue

            processed, possession_tracker = self._process_rebound_keywords(
                canonical_live_text, primary_player, context, possession_tracker,
                row, segmentation_config, event_context, evidence_text, segmented_text,
                relation_records, seen_keys,
            )
            if processed:
                continue

            if primary_player:
                context = _FallbackContext(
                    passer=context.passer,
                    receiver=context.receiver,
                    attacker=primary_player,
                    defender=context.defender,
                )

        return relation_records


    @staticmethod
    def _get_player_team_info(
        player_name: str,
        segmentation_config: PlayerSegmentationConfig,
        home_score: int | None = None,
        visit_score: int | None = None,
    ) -> tuple[str | None, str | None, str | None, int | None]:
        """获取球员的球队信息元组。"""
        if not player_name or not segmentation_config.player_to_team_id:
            return None, None, None, None

        team_id = segmentation_config.player_to_team_id.get(player_name)
        team_name = segmentation_config.player_to_team_name.get(player_name)
        team_side = segmentation_config.player_to_team_side.get(player_name)

        team_score = None
        if team_side == "home":
            team_score = home_score
        elif team_side == "visit":
            team_score = visit_score

        return team_id, team_name, team_side, team_score

    def _build_event_context_from_row(
        self,
        row: dict[str, Any],
        segmentation_config: PlayerSegmentationConfig,
        possession_tracker: _PossessionTracker,
    ) -> tuple[EventRelationContext, _PossessionTracker]:
        """从行数据构建事件级关系上下文。"""
        home_score = row.get("home_score")
        visit_score = row.get("visit_score")
        score_points = row.get("score_points")
        score_team_side = row.get("score_team_side")

        home_score_val = int(home_score) if isinstance(home_score, (int, float)) and home_score is not None else None
        visit_score_val = int(visit_score) if isinstance(visit_score, (int, float)) and visit_score is not None else None
        score_points_val = int(score_points) if isinstance(score_points, (int, float)) and score_points is not None else None

        offense_side = score_team_side if isinstance(score_team_side, str) and score_team_side.strip() else None
        if offense_side == "both":
            offense_side = None

        updated_tracker = possession_tracker.detect_possession_change(offense_side)

        offense_team_id = None
        offense_team_name = None
        offense_team_score = None

        if segmentation_config.game_team_context:
            if offense_side == "home":
                offense_team_id = segmentation_config.game_team_context.home_team_id
                offense_team_name = segmentation_config.game_team_context.home_team_name
                offense_team_score = home_score_val
            elif offense_side == "visit":
                offense_team_id = segmentation_config.game_team_context.guest_team_id
                offense_team_name = segmentation_config.game_team_context.guest_team_name
                offense_team_score = visit_score_val

        context = EventRelationContext(
            offense_team_id=offense_team_id,
            offense_team_name=offense_team_name,
            offense_team_side=updated_tracker.offense_team_side,
            offense_team_score=offense_team_score,
            offense_team_points=score_points_val,
            possession_number=updated_tracker.possession_number,
            home_score=home_score_val,
            visit_score=visit_score_val,
        )

        return context, updated_tracker


    def _append_relation_if_new(
        self,
        relation_records: list[PlayerRelationRecord],
        seen_keys: set[tuple[str, str, str, int]],
        *,
        saishi_id: str,
        evidence_event_id: int,
        live_sid: int,
        relation_type: str,
        relation_side: str,
        subject_player_name: str,
        object_player_name: str,
        action_text: str | None,
        result_text: str | None,
        score_points: int | None,
        evidence_text: str,
        segmented_text: str | None,
        confidence: float,
        event_context: EventRelationContext | None = None,
        subject_team_id: str | None = None,
        subject_team_name: str | None = None,
        subject_team_side: str | None = None,
        subject_team_score: int | None = None,
        object_team_id: str | None = None,
        object_team_name: str | None = None,
        object_team_side: str | None = None,
        object_team_score: int | None = None,
    ) -> None:
        """去重追加关系记录到结果列表。"""
        key = (subject_player_name.strip(), relation_type.strip(), object_player_name.strip(), live_sid)
        if key in seen_keys:
            return
        seen_keys.add(key)
        ctx = event_context or EventRelationContext()
        relation_records.append(
            PlayerRelationRecord(
                saishi_id=saishi_id,
                evidence_event_id=evidence_event_id,
                live_sid=live_sid,
                relation_type=relation_type,
                relation_side=relation_side,
                subject_player_name=subject_player_name.strip(),
                subject_team_id=subject_team_id,
                subject_team_name=subject_team_name,
                subject_team_side=subject_team_side,
                subject_team_score=subject_team_score,
                object_player_name=object_player_name.strip(),
                object_team_id=object_team_id,
                object_team_name=object_team_name,
                object_team_side=object_team_side,
                object_team_score=object_team_score,
                offense_team_id=ctx.offense_team_id,
                offense_team_name=ctx.offense_team_name,
                offense_team_side=ctx.offense_team_side,
                offense_team_score=ctx.offense_team_score,
                offense_team_points=ctx.offense_team_points,
                possession_number=ctx.possession_number,
                home_score=ctx.home_score,
                visit_score=ctx.visit_score,
                action_text=(action_text or "").strip() or None,
                result_text=(result_text or "").strip() or None,
                score_points=score_points,
                evidence_text=evidence_text,
                segmented_text=segmented_text,
                extractor_name="rule_fallback",
                confidence=confidence,
            )
        )

    def _process_pass_keywords(
        self,
        canonical_live_text: str,
        player_mentions: list[str],
        context: _FallbackContext,
        possession_tracker: _PossessionTracker,
        row: dict[str, Any],
        segmentation_config: PlayerSegmentationConfig,
        event_context: EventRelationContext,
        evidence_text: str,
        segmented_text: str | None,
        relation_records: list[PlayerRelationRecord],
        seen_keys: set[tuple[str, str, str, int]],
        primary_player: str | None,
        normalized_current: str | None,
    ) -> tuple[bool, _PossessionTracker]:
        """处理传球关键词匹配逻辑。"""
        if not any(keyword in canonical_live_text for keyword in self._rule_config.keywords("pass")):
            return False, possession_tracker

        is_steal_event = any(keyword in canonical_live_text for keyword in self._rule_config.keywords("steal"))
        if is_steal_event:
            possession_tracker = possession_tracker.detect_possession_change(None, is_steal=True)

        if len(player_mentions) >= 2:
            passer = player_mentions[0]
            receiver = player_mentions[-1]
            sub_team = self._get_player_team_info(passer, segmentation_config, event_context.home_score, event_context.visit_score)
            obj_team = self._get_player_team_info(receiver, segmentation_config, event_context.home_score, event_context.visit_score)
            self._append_relation_if_new(
                relation_records, seen_keys,
                saishi_id=row["saishi_id"],
                evidence_event_id=int(row["id"]),
                live_sid=int(row["live_sid"]),
                relation_type="passes_to",
                relation_side="offense",
                subject_player_name=passer,
                object_player_name=receiver,
                action_text="传球",
                result_text=None,
                score_points=None,
                evidence_text=evidence_text,
                segmented_text=segmented_text,
                confidence=self._rule_config.confidence("CONFIDENCE_PASS"),
                event_context=event_context,
                subject_team_id=sub_team[0],
                subject_team_name=sub_team[1],
                subject_team_side=sub_team[2],
                subject_team_score=sub_team[3],
                object_team_id=obj_team[0],
                object_team_name=obj_team[1],
                object_team_side=obj_team[2],
                object_team_score=obj_team[3],
            )
            return True, possession_tracker

        if len(player_mentions) == 1 and context.attacker and player_mentions[0] != context.attacker:
            sub_team = self._get_player_team_info(context.attacker, segmentation_config, event_context.home_score, event_context.visit_score)
            obj_team = self._get_player_team_info(player_mentions[0], segmentation_config, event_context.home_score, event_context.visit_score)
            self._append_relation_if_new(
                relation_records, seen_keys,
                saishi_id=row["saishi_id"],
                evidence_event_id=int(row["id"]),
                live_sid=int(row["live_sid"]),
                relation_type="passes_to",
                relation_side="offense",
                subject_player_name=context.attacker,
                object_player_name=player_mentions[0],
                action_text="传球",
                result_text=None,
                score_points=None,
                evidence_text=evidence_text,
                segmented_text=segmented_text,
                confidence=self._rule_config.confidence("CONFIDENCE_PASS_LOW"),
                event_context=event_context,
                subject_team_id=sub_team[0],
                subject_team_name=sub_team[1],
                subject_team_side=sub_team[2],
                subject_team_score=sub_team[3],
                object_team_id=obj_team[0],
                object_team_name=obj_team[1],
                object_team_side=obj_team[2],
                object_team_score=obj_team[3],
            )
            return True, possession_tracker

        return False, possession_tracker

    def _process_attack_keywords(
        self,
        canonical_live_text: str,
        player_mentions: list[str],
        context: _FallbackContext,
        row: dict[str, Any],
        segmentation_config: PlayerSegmentationConfig,
        event_context: EventRelationContext,
        evidence_text: str,
        segmented_text: str | None,
        relation_records: list[PlayerRelationRecord],
        seen_keys: set[tuple[str, str, str, int]],
        primary_player: str | None,
    ) -> bool:
        """处理对位/单打关键词匹配逻辑。"""
        if "对位" not in canonical_live_text and not (
            any(keyword in canonical_live_text for keyword in self._rule_config.keywords("attack")) and len(player_mentions) >= 2
        ):
            return False

        if len(player_mentions) >= 2:
            attacker = player_mentions[0]
            defender = player_mentions[-1]
        else:
            attacker = primary_player
            defender = player_mentions[0] if player_mentions else None

        if attacker and defender and attacker != defender:
            sub_team = self._get_player_team_info(attacker, segmentation_config, event_context.home_score, event_context.visit_score)
            obj_team = self._get_player_team_info(defender, segmentation_config, event_context.home_score, event_context.visit_score)
            self._append_relation_if_new(
                relation_records, seen_keys,
                saishi_id=row["saishi_id"],
                evidence_event_id=int(row["id"]),
                live_sid=int(row["live_sid"]),
                relation_type="attacks_against",
                relation_side="offense",
                subject_player_name=attacker,
                object_player_name=defender,
                action_text="单打对位",
                result_text=None,
                score_points=None,
                evidence_text=evidence_text,
                segmented_text=segmented_text,
                confidence=self._rule_config.confidence("CONFIDENCE_ATTACK"),
                event_context=event_context,
                subject_team_id=sub_team[0],
                subject_team_name=sub_team[1],
                subject_team_side=sub_team[2],
                subject_team_score=sub_team[3],
                object_team_id=obj_team[0],
                object_team_name=obj_team[1],
                object_team_side=obj_team[2],
                object_team_score=obj_team[3],
            )
            return True

        return False

    def _process_steal_keywords(
        self,
        canonical_live_text: str,
        player_mentions: list[str],
        context: _FallbackContext,
        possession_tracker: _PossessionTracker,
        row: dict[str, Any],
        segmentation_config: PlayerSegmentationConfig,
        event_context: EventRelationContext,
        evidence_text: str,
        segmented_text: str | None,
        relation_records: list[PlayerRelationRecord],
        seen_keys: set[tuple[str, str, str, int]],
        primary_player: str | None,
    ) -> tuple[bool, _PossessionTracker]:
        """处理抢断关键词匹配逻辑。"""
        if not any(keyword in canonical_live_text for keyword in self._rule_config.keywords("steal")):
            return False, possession_tracker

        possession_tracker = possession_tracker.detect_possession_change(None, is_steal=True)

        if len(player_mentions) >= 2:
            stealer, victim = player_mentions[0], player_mentions[-1]
        elif primary_player and context.attacker and primary_player != context.attacker:
            stealer, victim = primary_player, context.attacker
        else:
            stealer, victim = None, None

        if stealer and victim:
            sub_team = self._get_player_team_info(stealer, segmentation_config, event_context.home_score, event_context.visit_score)
            obj_team = self._get_player_team_info(victim, segmentation_config, event_context.home_score, event_context.visit_score)
            self._append_relation_if_new(
                relation_records, seen_keys,
                saishi_id=row["saishi_id"],
                evidence_event_id=int(row["id"]),
                live_sid=int(row["live_sid"]),
                relation_type="steals_from",
                relation_side="defense",
                subject_player_name=stealer,
                object_player_name=victim,
                action_text="抢断",
                result_text=None,
                score_points=None,
                evidence_text=evidence_text,
                segmented_text=segmented_text,
                confidence=self._rule_config.confidence("CONFIDENCE_STEAL"),
                event_context=event_context,
                subject_team_id=sub_team[0],
                subject_team_name=sub_team[1],
                subject_team_side=sub_team[2],
                subject_team_score=sub_team[3],
                object_team_id=obj_team[0],
                object_team_name=obj_team[1],
                object_team_side=obj_team[2],
                object_team_score=obj_team[3],
            )
            return True, possession_tracker

        return False, possession_tracker

    def _process_block_keywords(
        self,
        canonical_live_text: str,
        player_mentions: list[str],
        context: _FallbackContext,
        row: dict[str, Any],
        segmentation_config: PlayerSegmentationConfig,
        event_context: EventRelationContext,
        evidence_text: str,
        segmented_text: str | None,
        relation_records: list[PlayerRelationRecord],
        seen_keys: set[tuple[str, str, str, int]],
        primary_player: str | None,
    ) -> bool:
        """处理封盖关键词匹配逻辑。"""
        if not any(keyword in canonical_live_text for keyword in self._rule_config.keywords("block")):
            return False

        if len(player_mentions) >= 2:
            blocker, victim = player_mentions[0], player_mentions[-1]
        elif primary_player and context.attacker and primary_player != context.attacker:
            blocker, victim = primary_player, context.attacker
        else:
            blocker, victim = None, None

        if blocker and victim:
            sub_team = self._get_player_team_info(blocker, segmentation_config, event_context.home_score, event_context.visit_score)
            obj_team = self._get_player_team_info(victim, segmentation_config, event_context.home_score, event_context.visit_score)
            self._append_relation_if_new(
                relation_records, seen_keys,
                saishi_id=row["saishi_id"],
                evidence_event_id=int(row["id"]),
                live_sid=int(row["live_sid"]),
                relation_type="blocks",
                relation_side="defense",
                subject_player_name=blocker,
                object_player_name=victim,
                action_text="封盖",
                result_text=None,
                score_points=None,
                evidence_text=evidence_text,
                segmented_text=segmented_text,
                confidence=self._rule_config.confidence("CONFIDENCE_BLOCK"),
                event_context=event_context,
                subject_team_id=sub_team[0],
                subject_team_name=sub_team[1],
                subject_team_side=sub_team[2],
                subject_team_score=sub_team[3],
                object_team_id=obj_team[0],
                object_team_name=obj_team[1],
                object_team_side=obj_team[2],
                object_team_score=obj_team[3],
            )
            return True

        return False

    def _process_contest_keywords(
        self,
        canonical_live_text: str,
        primary_player: str | None,
        context: _FallbackContext,
        row: dict[str, Any],
        segmentation_config: PlayerSegmentationConfig,
        event_context: EventRelationContext,
        evidence_text: str,
        segmented_text: str | None,
        relation_records: list[PlayerRelationRecord],
        seen_keys: set[tuple[str, str, str, int]],
    ) -> bool:
        """处理协防/干扰关键词匹配逻辑。"""
        if not any(keyword in canonical_live_text for keyword in self._rule_config.keywords("help_defense")):
            return False

        defender = primary_player
        attacker = context.attacker or context.receiver
        if defender and attacker and defender != attacker:
            att_team = self._get_player_team_info(attacker, segmentation_config, event_context.home_score, event_context.visit_score)
            def_team = self._get_player_team_info(defender, segmentation_config, event_context.home_score, event_context.visit_score)
            self._append_relation_if_new(
                relation_records, seen_keys,
                saishi_id=row["saishi_id"],
                evidence_event_id=int(row["id"]),
                live_sid=int(row["live_sid"]),
                relation_type="scores_over",
                relation_side="offense",
                subject_player_name=attacker,
                object_player_name=defender,
                action_text="得分",
                result_text="命中",
                score_points=_row_score_points(row),
                evidence_text=evidence_text,
                segmented_text=segmented_text,
                confidence=self._rule_config.confidence("CONFIDENCE_SCORE_OVER_CONTEST"),
                event_context=event_context,
                subject_team_id=att_team[0],
                subject_team_name=att_team[1],
                subject_team_side=att_team[2],
                subject_team_score=att_team[3],
                object_team_id=def_team[0],
                object_team_name=def_team[1],
                object_team_side=def_team[2],
                object_team_score=def_team[3],
            )
            self._append_relation_if_new(
                relation_records, seen_keys,
                saishi_id=row["saishi_id"],
                evidence_event_id=int(row["id"]),
                live_sid=int(row["live_sid"]),
                relation_type="defends",
                relation_side="defense",
                subject_player_name=defender,
                object_player_name=attacker,
                action_text="协防干扰",
                result_text=None,
                score_points=None,
                evidence_text=evidence_text,
                segmented_text=segmented_text,
                confidence=self._rule_config.confidence("CONFIDENCE_DEFENDS_CONTEST"),
                event_context=event_context,
                subject_team_id=def_team[0],
                subject_team_name=def_team[1],
                subject_team_side=def_team[2],
                subject_team_score=def_team[3],
                object_team_id=att_team[0],
                object_team_name=att_team[1],
                object_team_side=att_team[2],
                object_team_score=att_team[3],
            )
            return True

        return False

    def _process_scoring_events(
        self,
        score_points: int | None,
        primary_player: str | None,
        context: _FallbackContext,
        row: dict[str, Any],
        segmentation_config: PlayerSegmentationConfig,
        event_context: EventRelationContext,
        evidence_text: str,
        segmented_text: str | None,
        relation_records: list[PlayerRelationRecord],
        seen_keys: set[tuple[str, str, str, int]],
        player_mentions: list[str],
    ) -> bool:
        """处理得分事件的关系构建逻辑。"""
        if score_points is None or score_points <= 0:
            return False

        scorer = primary_player or context.receiver or context.attacker
        if scorer and context.passer and context.passer != scorer:
            pass_team = self._get_player_team_info(context.passer, segmentation_config, event_context.home_score, event_context.visit_score)
            scorer_team = self._get_player_team_info(scorer, segmentation_config, event_context.home_score, event_context.visit_score)
            self._append_relation_if_new(
                relation_records, seen_keys,
                saishi_id=row["saishi_id"],
                evidence_event_id=int(row["id"]),
                live_sid=int(row["live_sid"]),
                relation_type="assist_to",
                relation_side="offense",
                subject_player_name=context.passer,
                object_player_name=scorer,
                action_text="助攻",
                result_text="得分",
                score_points=score_points,
                evidence_text=evidence_text,
                segmented_text=segmented_text,
                confidence=self._rule_config.confidence("CONFIDENCE_ASSIST"),
                event_context=event_context,
                subject_team_id=pass_team[0],
                subject_team_name=pass_team[1],
                subject_team_side=pass_team[2],
                subject_team_score=pass_team[3],
                object_team_id=scorer_team[0],
                object_team_name=scorer_team[1],
                object_team_side=scorer_team[2],
                object_team_score=scorer_team[3],
            )

        if scorer and context.defender and context.defender != scorer:
            scorer_team = self._get_player_team_info(scorer, segmentation_config, event_context.home_score, event_context.visit_score)
            def_team = self._get_player_team_info(context.defender, segmentation_config, event_context.home_score, event_context.visit_score)
            self._append_relation_if_new(
                relation_records, seen_keys,
                saishi_id=row["saishi_id"],
                evidence_event_id=int(row["id"]),
                live_sid=int(row["live_sid"]),
                relation_type="scores_over",
                relation_side="offense",
                subject_player_name=scorer,
                object_player_name=context.defender,
                action_text="得分",
                result_text="命中",
                score_points=score_points,
                evidence_text=evidence_text,
                segmented_text=segmented_text,
                confidence=self._rule_config.confidence("CONFIDENCE_SCORE_OVER"),
                event_context=event_context,
                subject_team_id=scorer_team[0],
                subject_team_name=scorer_team[1],
                subject_team_side=scorer_team[2],
                subject_team_score=scorer_team[3],
                object_team_id=def_team[0],
                object_team_name=def_team[1],
                object_team_side=def_team[2],
                object_team_score=def_team[3],
            )

        if scorer and not context.defender and len(player_mentions) >= 2:
            defender = player_mentions[-1]
            if defender != scorer:
                scorer_team = self._get_player_team_info(scorer, segmentation_config, event_context.home_score, event_context.visit_score)
                def_team = self._get_player_team_info(defender, segmentation_config, event_context.home_score, event_context.visit_score)
                self._append_relation_if_new(
                    relation_records, seen_keys,
                    saishi_id=row["saishi_id"],
                    evidence_event_id=int(row["id"]),
                    live_sid=int(row["live_sid"]),
                    relation_type="scores_over",
                    relation_side="offense",
                    subject_player_name=scorer,
                    object_player_name=defender,
                    action_text="得分",
                    result_text="命中",
                    score_points=score_points,
                    evidence_text=evidence_text,
                    segmented_text=segmented_text,
                    confidence=self._rule_config.confidence("CONFIDENCE_SCORE_OVER_IMPLICIT"),
                    event_context=event_context,
                    subject_team_id=scorer_team[0],
                    subject_team_name=scorer_team[1],
                    subject_team_side=scorer_team[2],
                    subject_team_score=scorer_team[3],
                    object_team_id=def_team[0],
                    object_team_name=def_team[1],
                    object_team_side=def_team[2],
                    object_team_score=def_team[3],
                )

        return True

    def _process_rebound_keywords(
        self,
        canonical_live_text: str,
        primary_player: str | None,
        context: _FallbackContext,
        possession_tracker: _PossessionTracker,
        row: dict[str, Any],
        segmentation_config: PlayerSegmentationConfig,
        event_context: EventRelationContext,
        evidence_text: str,
        segmented_text: str | None,
        relation_records: list[PlayerRelationRecord],
        seen_keys: set[tuple[str, str, str, int]],
    ) -> tuple[bool, _PossessionTracker]:
        """处理篮板关键词匹配逻辑。"""
        if not any(keyword in canonical_live_text for keyword in self._rule_config.keywords("rebound")):
            return False, possession_tracker
        if not primary_player or not context.attacker or primary_player == context.attacker:
            return False, possession_tracker

        possession_tracker = possession_tracker.detect_possession_change(None, is_rebound=True)

        rebr_team = self._get_player_team_info(primary_player, segmentation_config, event_context.home_score, event_context.visit_score)
        att_team = self._get_player_team_info(context.attacker, segmentation_config, event_context.home_score, event_context.visit_score)
        self._append_relation_if_new(
            relation_records, seen_keys,
            saishi_id=row["saishi_id"],
            evidence_event_id=int(row["id"]),
            live_sid=int(row["live_sid"]),
            relation_type="rebounds_over",
            relation_side="defense",
            subject_player_name=primary_player,
            object_player_name=context.attacker,
            action_text="篮板",
            result_text=None,
            score_points=None,
            evidence_text=evidence_text,
            segmented_text=segmented_text,
            confidence=self._rule_config.confidence("CONFIDENCE_REBOUND"),
            event_context=event_context,
            subject_team_id=rebr_team[0],
            subject_team_name=rebr_team[1],
            subject_team_side=rebr_team[2],
            subject_team_score=rebr_team[3],
            object_team_id=att_team[0],
            object_team_name=att_team[1],
            object_team_side=att_team[2],
            object_team_score=att_team[3],
        )
        return True, possession_tracker
