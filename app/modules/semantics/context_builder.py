from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from app.modules.nba_live_text.zhiboba_livetext import PlayerSegmentationConfig


class EventType(Enum):
    """球权事件类型枚举。

    定义在比赛过程中可能影响球权归属的事件类型，
    用于精确控制状态机的状态转换逻辑。

    Attributes:
        OFFENSIVE_REBOUND: 进攻篮板（同队球员抢到，保持当前球权）
        DEFENSIVE_REBOUND: 防守篮板（对方球员抢到，切换球权）
        STEAL: 抢断（抢断方获得球权）
        SCORE: 得分（可能触发换发球，视情况增加回合数）
        TURNOVER: 失误（对方获得球权）
        FOUL: 犯规（通常不改变球权，但可能导致罚球后换发球）
        POSSESSION_CHANGE: 显式球权切换（如换发球、跳球等）
    """
    OFFENSIVE_REBOUND = "offensive_rebound"
    DEFENSIVE_REBOUND = "defensive_rebound"
    STEAL = "steal"
    SCORE = "score"
    TURNOVER = "turnover"
    FOUL = "foul"
    POSSESSION_CHANGE = "possession_change"


@dataclass(frozen=True)
class EventRelationContext:
    """单条直播文本事件的关系抽取上下文。

    封装从数据库行记录中提取的攻防上下文信息，
    用于在球员关系抽取时提供比赛状态背景。

    Attributes:
        offense_team_id: 当前进攻方球队ID
        offense_team_name: 当前进攻方球队名称
        offense_team_side: 当前进攻方阵营 (home/visit)
        offense_team_score: 当前进攻方得分
        offense_team_points: 本次事件得分值（如进球得2分）
        possession_number: 当前球权序号（用于追踪攻防转换）
        home_score: 主队累计得分
        visit_score: 客队累计得分
    """

    offense_team_id: str | None = None
    offense_team_name: str | None = None
    offense_team_side: str | None = None
    offense_team_score: int | None = None
    offense_team_points: int | None = None
    possession_number: int | None = None
    home_score: int | None = None
    visit_score: int | None = None


@dataclass(frozen=True)
class PossessionStateMachine:
    """智能球权状态机。

    用于在顺序处理直播文本事件时追踪当前球权归属和球权序号。
    实现更精细的回合追踪逻辑，能够区分进攻篮板、防守篮板、抢断等
    不同事件类型对球权的影响。

    设计原则：
    - 不可变性：每次状态变更返回新实例，保证状态可追溯
    - 智能判断：根据事件类型自动决定是否增加回合数
    - 向后兼容：保留旧接口的同时提供更强的功能

    Attributes:
        possession_number: 当前球权序号，从1开始递增
        offense_team_side: 当前持球方阵营 ("home" / "visit" / None)

    Example:
        >>> tracker = PossessionStateMachine()
        >>> tracker = tracker.detect_possession_change(
        ...     "home",
        ...     event_type=EventType.POSSESSION_CHANGE
        ... )
        >>> print(tracker.possession_number, tracker.offense_team_side)
        1 home

        >>> tracker = tracker.detect_possession_change(
        ...     "visit",
        ...     event_type=EventType.STEAL,
        ...     rebounder_team="visit"
        ... )
        >>> print(tracker.possession_number, tracker.offense_team_side)
        2 visit
    """

    possession_number: int = 1
    offense_team_side: str | None = None

    def _is_offensive_rebound(
        self,
        rebounder_team: str | None,
    ) -> bool:
        """判断是否为进攻篮板。

        通过比较抢篮板球员所属球队与当前进攻方阵营来判断。
        如果抢到篮板的球员属于当前进攻方球队，则为进攻篮板。

        Args:
            rebounder_team: 抢篮板球员所属球队的阵营 ("home" / "visit" / None)

        Returns:
            bool: 如果是进攻篮板返回 True，否则返回 False

        Note:
            - 当 rebounder_team 或 offense_team_side 为 None 时，无法判断，
              返回 False（保守策略）
            - 进攻篮板意味着同队保持球权，不增加回合数
        """
        if not rebounder_team or not self.offense_team_side:
            return False
        return rebounder_team == self.offense_team_side

    def detect_possession_change(
        self,
        new_offense_side: str | None,
        *,
        event_type: EventType | None = None,
        is_turnover: bool = False,
        is_steal: bool = False,
        is_rebound: bool = False,
        rebounder_team: str | None = None,
    ) -> PossessionStateMachine:
        """检测并返回更新后的球权状态。

        根据事件类型智能判断是否需要切换球权或增加回合数。
        支持新旧两种调用方式，确保向后兼容性。

        状态转换优先级（从高到低）：
        1. 显式阵营切换且与当前不同 → 递增球权序号并切换阵营
        2. 进攻篮板 (OFFENSIVE_REBOUND) → 保持当前球权和回合数
        3. 防守篮板 (DEFENSIVE_REBOUND) → 切换到抢篮板方并递增序号
        4. 抢断 (STEAL) → 切换到抢断方并递增序号
        5. 失误 (TURNOVER) → 切换到对方并递增序号
        6. 得分 (SCORE) → 根据是否有阵营切换决定是否递增
        7. 犯规 (FOUL) → 通常不改变球权（除非有显式切换）
        8. 首次设置阵营 → 保持当前序号
        9. 无变化 → 返回相同状态

        Args:
            new_offense_side: 新的进攻方阵营 ("home" / "visit" / None)
            event_type: 事件类型枚举，用于精确控制状态转换逻辑
                - EventType.OFFENSIVE_REBOUND: 进攻篮板，保持球权
                - EventType.DEFENSIVE_REBOUND: 防守篮板，切换球权
                - EventType.STEAL: 抢断，切换到抢断方
                - EventType.SCORE: 得分，可能触发换发球
                - EventType.TURNOVER: 失误，对方获得球权
                - EventType.FOUL: 犯规，通常不改变球权
                - EventType.POSSESSION_CHANGE: 显式球权切换
            is_turnover: 是否为失误事件（向后兼容参数）
            is_steal: 是否为抢断事件（向后兼容参数）
            is_rebound: 是否为篮板事件（向后兼容参数）
            rebounder_team: 抢篮板球员所属球队阵营，
                           用于区分进攻/防守篮板

        Returns:
            更新后的 PossessionStateMachine 实例

        Example:
            >>> tracker = PossessionStateMachine(offense_team_side="home")
            >>>
            >>> # 进攻篮板：同队抢到，保持球权
            >>> new_tracker = tracker.detect_possession_change(
            ...     "home",
            ...     event_type=EventType.OFFENSIVE_REBOUND,
            ...     rebounder_team="home"
            ... )
            >>> assert new_tracker.possession_number == 1
            >>> assert new_tracker.offense_team_side == "home"
            >>>
            >>> # 防守篮板：对方抢到，切换球权
            >>> new_tracker = tracker.detect_possession_change(
            ...     "visit",
            ...     event_type=EventType.DEFENSIVE_REBOUND,
            ...     rebounder_team="visit"
            ... )
            >>> assert new_tracker.possession_number == 2
            >>> assert new_tracker.offense_team_side == "visit"

        Note:
            - 当同时提供 event_type 和旧参数（is_turnover 等）时，
              event_type 优先级更高
            - rebounder_team 仅在篮板事件时使用，其他事件可忽略
        """
        if event_type is not None:
            return self._handle_typed_event(
                new_offense_side=new_offense_side,
                event_type=event_type,
                rebounder_team=rebounder_team,
            )

        return self._handle_legacy_event(
            new_offense_side=new_offense_side,
            is_turnover=is_turnover,
            is_steal=is_steal,
            is_rebound=is_rebound,
        )

    def _handle_typed_event(
        self,
        new_offense_side: str | None,
        event_type: EventType,
        rebounder_team: str | None = None,
    ) -> PossessionStateMachine:
        """处理带明确事件类型的状态转换。

        根据不同的事件类型执行相应的状态转换逻辑：
        - 进攻篮板：保持当前球权，不增加回合数
        - 防守篮板：切换到抢篮板方，增加回合数
        - 抢断：切换到抢断方，增加回合数
        - 得分：根据阵营变化决定
        - 失误：切换到对方，增加回合数
        - 犯规：通常保持，除非有显式切换
        - 显式切换：直接切换并增加回合数

        Args:
            new_offense_side: 新的进攻方阵营
            event_type: 事件类型枚举
            rebounder_team: 抢篮板球员所属球队（仅篮板事件使用）

        Returns:
            更新后的状态机实例
        """
        opposite_side = (
            "visit" if self.offense_team_side == "home" else "home"
            if self.offense_team_side else None
        )

        match event_type:
            case EventType.OFFENSIVE_REBOUND:
                if self._is_offensive_rebound(rebounder_team):
                    return PossessionStateMachine(
                        possession_number=self.possession_number,
                        offense_team_side=self.offense_team_side,
                    )
                return PossessionStateMachine(
                    possession_number=self.possession_number + 1,
                    offense_team_side=rebounder_team or opposite_side or new_offense_side,
                )

            case EventType.DEFENSIVE_REBOUND:
                return PossessionStateMachine(
                    possession_number=self.possession_number + 1,
                    offense_team_side=rebounder_team or opposite_side or new_offense_side,
                )

            case EventType.STEAL:
                steal_side = new_offense_side or rebounder_team or opposite_side
                return PossessionStateMachine(
                    possession_number=self.possession_number + 1,
                    offense_team_side=steal_side,
                )

            case EventType.TURNOVER:
                return PossessionStateMachine(
                    possession_number=self.possession_number + 1,
                    offense_team_side=opposite_side or new_offense_side,
                )

            case EventType.SCORE:
                if (new_offense_side and self.offense_team_side and
                        new_offense_side != self.offense_team_side):
                    return PossessionStateMachine(
                        possession_number=self.possession_number + 1,
                        offense_team_side=new_offense_side,
                    )
                return PossessionStateMachine(
                    possession_number=self.possession_number,
                    offense_team_side=new_offense_side or self.offense_team_side,
                )

            case EventType.FOUL:
                if (new_offense_side and self.offense_team_side and
                        new_offense_side != self.offense_team_side):
                    return PossessionStateMachine(
                        possession_number=self.possession_number + 1,
                        offense_team_side=new_offense_side,
                    )
                return PossessionStateMachine(
                    possession_number=self.possession_number,
                    offense_team_side=new_offense_side or self.offense_team_side,
                )

            case EventType.POSSESSION_CHANGE:
                if (new_offense_side and self.offense_team_side and
                        new_offense_side != self.offense_team_side):
                    return PossessionStateMachine(
                        possession_number=self.possession_number + 1,
                        offense_team_side=new_offense_side,
                    )
                if new_offense_side and not self.offense_team_side:
                    return PossessionStateMachine(
                        possession_number=self.possession_number,
                        offense_team_side=new_offense_side,
                    )
                return PossessionStateMachine(
                    possession_number=self.possession_number,
                    offense_team_side=new_offense_side or self.offense_team_side,
                )

            case _:
                return self._handle_legacy_event(new_offense_side)

    def _handle_legacy_event(
        self,
        new_offense_side: str | None,
        *,
        is_turnover: bool = False,
        is_steal: bool = False,
        is_rebound: bool = False,
    ) -> PossessionStateMachine:
        """处理旧版接口调用的事件（向后兼容）。

        保持原有的逻辑不变，确保现有代码无需修改即可正常工作。

        Args:
            new_offense_side: 新的进攻方阵营
            is_turnover: 是否为失误事件
            is_steal: 是否为抢断事件
            is_rebound: 是否为篮板事件

        Returns:
            更新后的状态机实例
        """
        if (new_offense_side and self.offense_team_side and
                new_offense_side != self.offense_team_side):
            return PossessionStateMachine(
                possession_number=self.possession_number + 1,
                offense_team_side=new_offense_side,
            )
        if is_turnover or is_steal or is_rebound:
            if self.offense_team_side:
                opposite_side = (
                    "visit" if self.offense_team_side == "home" else "home"
                )
                return PossessionStateMachine(
                    possession_number=self.possession_number + 1,
                    offense_team_side=opposite_side,
                )
        if new_offense_side and not self.offense_team_side:
            return PossessionStateMachine(
                possession_number=self.possession_number,
                offense_team_side=new_offense_side,
            )
        return PossessionStateMachine(
            possession_number=self.possession_number,
            offense_team_side=new_offense_side or self.offense_team_side,
        )


_PossessionTracker = PossessionStateMachine


def _build_event_context_from_row(
    row: dict[str, Any],
    segmentation_config: PlayerSegmentationConfig,
    possession_tracker: _PossessionTracker,
) -> tuple[EventRelationContext, _PossessionTracker]:
    """从数据库行记录构建事件关系上下文。

    从 nba_zhiboba_live_text_event 表的一行记录中提取比分、得分方等信息，
    结合球权追踪器生成完整的 EventRelationContext。

    Args:
        row: 数据库行字典，需包含以下字段：
            - home_score: 主队得分
            - visit_score: 客队得分
            - score_points: 本次事件得分值
            - score_team_side: 得分方阵营 ("home" / "visit" / "both" / None)
        segmentation_config: 球员分词配置，包含球队映射信息
        possession_tracker: 当前球权追踪器实例

    Returns:
        元组 (event_context, updated_tracker):
            - event_context: 构建好的事件关系上下文
            - updated_tracker: 更新后的球权追踪器
    """
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


def _get_player_team_info(
    player_name: str,
    segmentation_config: PlayerSegmentationConfig,
    home_score: int | None = None,
    visit_score: int | None = None,
) -> tuple[str | None, str | None, str | None, int | None]:
    """查询球员所属球队信息。

    根据球员姓名从分词配置中查找其所属球队的ID、名称、阵营和得分。

    Args:
        player_name: 球员姓名（需与配置中的key匹配）
        segmentation_config: 球员分词配置，包含球员-球队映射字典
        home_score: 主队当前得分
        visit_score: 客队当前得分

    Returns:
        四元组 (team_id, team_name, team_side, team_score):
            - team_id: 球队ID，未找到时为None
            - team_name: 球队名称，未找到时为None
            - team_side: 球队阵营 ("home" / "visit")，未找到时为None
            - team_score: 球队当前得分
    """
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


def _canonical_text(value: str | None) -> str:
    return (value or "").replace("\\", "").replace(" ", "").strip()


def _extract_player_mentions_from_segmented_text(
    text_value: str,
    alias_to_full_name: dict[str, str],
) -> list[str]:
    content = _canonical_text(text_value)
    if not content:
        return []

    matches: list[tuple[int, int, str]] = []
    candidates = sorted(set(alias_to_full_name.values()) | set(alias_to_full_name.keys()), key=len, reverse=True)
    for candidate in candidates:
        normalized_candidate = _canonical_text(candidate)
        if not normalized_candidate:
            continue
        start_index = 0
        while True:
            found_at = content.find(normalized_candidate, start_index)
            if found_at < 0:
                break
            canonical_name = alias_to_full_name.get(candidate, candidate)
            matches.append((found_at, len(normalized_candidate), canonical_name))
            start_index = found_at + len(normalized_candidate)

    matches.sort(key=lambda item: (item[0], -item[1]))
    deduped: list[str] = []
    occupied_ranges: list[tuple[int, int]] = []
    for start, length, player_name in matches:
        end = start + length
        if any(not (end <= occ_start or start >= occ_end) for occ_start, occ_end in occupied_ranges):
            continue
        occupied_ranges.append((start, end))
        if player_name not in deduped:
            deduped.append(player_name)
    return deduped


def _row_score_points(row: dict[str, Any]) -> int | None:
    score_points = row.get("score_points")
    return int(score_points) if score_points is not None else None
