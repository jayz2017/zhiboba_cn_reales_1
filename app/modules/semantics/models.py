from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class GameTeamContext:
    """比赛球队上下文信息，用于关联球员与所属球队。

    Attributes:
        home_team_id: 主队ID
        guest_team_id: 客队ID
        home_team_name: 主队名称（可选）
        guest_team_name: 客队名称（可选）
    """
    home_team_id: str
    guest_team_id: str
    home_team_name: str | None = None
    guest_team_name: str | None = None


@dataclass(frozen=True)
class PlayerSegmentationConfig:
    """球员分词配置，包含球员词典、别名映射及球队关联信息。

    Attributes:
        words: 分词使用的球员名称词表
        alias_to_full_name: 球员别名到标准全名的映射字典
        player_to_team_id: 球员名到球队ID的映射字典
        player_to_team_name: 球员名到球队名称的映射字典
        player_to_team_side: 球员名到球队阵营（home/visit）的映射字典
        game_team_context: 比赛球队上下文信息
    """
    words: list[str]
    alias_to_full_name: dict[str, str]
    player_to_team_id: dict[str, str] = field(default_factory=dict)
    player_to_team_name: dict[str, str] = field(default_factory=dict)
    player_to_team_side: dict[str, str] = field(default_factory=dict)
    game_team_context: GameTeamContext | None = None


@dataclass(frozen=True)
class PlayerRelationRecord:
    """球员关系记录，表示从直播文本中提取的攻防关系数据。

    该记录对应数据库表 nba_zhiboba_player_relation 的一行数据，
    包含完整的主体/客体球员信息、球队上下文、比分状态等字段。

    Attributes:
        saishi_id: 赛事ID
        evidence_event_id: 来源事件ID（live_text_event 表主键）
        live_sid: 直播文本序号
        relation_type: 关系类型（如 passes_to、blocks、steals_from 等）
        relation_side: 关系立场（offense/defense）
        subject_player_name: 主体球员姓名
        subject_team_id: 主体球员所在球队ID
        subject_team_name: 主体球员所在球队名称
        subject_team_side: 主体球员所在球队阵营
        subject_team_score: 主体球员所在球队当前得分
        object_player_name: 客体球员姓名
        object_team_id: 客体球员所在球队ID
        object_team_name: 客体球员所在球队名称
        object_team_side: 客体球员所在球队阵营
        object_team_score: 客体球员所在球队当前得分
        offense_team_id: 当前进攻方球队ID
        offense_team_name: 当前进攻方球队名称
        offense_team_side: 当前进攻方阵营
        offense_team_score: 当前进攻方得分
        offense_team_points: 本次进攻得分值
        possession_number: 进攻回合序号
        home_score: 主队总分
        visit_score: 客队总分
        action_text: 动作描述文本
        result_text: 结果描述文本
        score_points: 得分数值
        evidence_text: 原始证据文本（未分词）
        segmented_text: 分词后的证据文本
        extractor_name: 提取器标识（siamese_uie / rule_fallback）
        confidence: 置信度分数（0.0~1.0）
    """
    saishi_id: str
    evidence_event_id: int
    live_sid: int
    relation_type: str
    relation_side: str
    subject_player_name: str
    subject_team_id: str | None
    subject_team_name: str | None
    subject_team_side: str | None
    subject_team_score: int | None
    object_player_name: str
    object_team_id: str | None
    object_team_name: str | None
    object_team_side: str | None
    object_team_score: int | None
    offense_team_id: str | None
    offense_team_name: str | None
    offense_team_side: str | None
    offense_team_score: int | None
    offense_team_points: int | None
    possession_number: int | None
    home_score: int | None
    visit_score: int | None
    action_text: str | None
    result_text: str | None
    score_points: int | None
    evidence_text: str
    segmented_text: str | None
    extractor_name: str
    confidence: float


@dataclass(frozen=True)
class EventRelationContext:
    """事件级关系上下文，用于在单条直播文本事件中传递进攻方与比分状态。

    由 _build_event_context_from_row 函数根据行数据构建，
    作为 build_relation_records_from_uie_result 的参数传入。

    Attributes:
        offense_team_id: 当前进攻方球队ID
        offense_team_name: 当前进攻方球队名称
        offense_team_side: 当前进攻方阵营（home/visit）
        offense_team_score: 当前进攻方累计得分
        offense_team_points: 本次事件产生的得分值
        possession_number: 当前进攻回合序号
        home_score: 主队总分
        visit_score: 客队总分
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
class _PossessionTracker:
    """球权追踪器，用于跨事件维护当前进攻方与回合计数。

    通过 detect_possession_change 方法检测球权转换并递增 possession_number。
    用于 build_relation_records_with_rule_fallback 和 extract_postgame_player_relations 中。

    Attributes:
        possession_number: 当前进攻回合序号（从1开始）
        offense_team_side: 当前进攻方阵营（home/visit）
    """
    possession_number: int = 1
    offense_team_side: str | None = None

    def detect_possession_change(
        self,
        new_offense_side: str | None,
        is_turnover: bool = False,
        is_steal: bool = False,
        is_rebound: bool = False,
    ) -> _PossessionTracker:
        """检测球权是否发生转换，返回新的追踪器实例。

        Args:
            new_offense_side: 新的进攻方阵营
            is_turnover: 是否为失误事件
            is_steal: 是否为抢断事件
            is_rebound: 是否为篮板事件（防守篮板触发转换）

        Returns:
            更新后的 _PossessionTracker 实例
        """
        if new_offense_side and self.offense_team_side and new_offense_side != self.offense_team_side:
            return _PossessionTracker(
                possession_number=self.possession_number + 1,
                offense_team_side=new_offense_side,
            )
        if is_turnover or is_steal or is_rebound:
            if self.offense_team_side:
                opposite_side = "visit" if self.offense_team_side == "home" else "home"
                return _PossessionTracker(
                    possession_number=self.possession_number + 1,
                    offense_team_side=opposite_side,
                )
        if new_offense_side and not self.offense_team_side:
            return _PossessionTracker(
                possession_number=self.possession_number,
                offense_team_side=new_offense_side,
            )
        return _PossessionTracker(
            possession_number=self.possession_number,
            offense_team_side=new_offense_side or self.offense_team_side,
        )


@dataclass(frozen=True)
class _FallbackContext:
    """规则回退提取器的跨事件状态缓存。

    在 build_relation_records_with_rule_fallback 的逐行处理过程中，
    携带上一次识别到的传球者、接球者、进攻者和防守者信息，
    用于在后续事件中补全缺失的角色关系。

    Attributes:
        passer: 上一次识别到的传球者姓名
        receiver: 上一次识别到的接球者姓名
        attacker: 上一次识别到的进攻者姓名
        defender: 上一次识别到的防守者姓名
    """
    passer: str | None = None
    receiver: str | None = None
    attacker: str | None = None
    defender: str | None = None
