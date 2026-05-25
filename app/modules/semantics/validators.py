from __future__ import annotations

from enum import Enum
from typing import Any, Literal, Optional

from pydantic import BaseModel, ValidationError, field_validator

from app.modules.semantics.models import PlayerRelationRecord
from app.modules.semantics.ontology import valid_relation_types


class RelationType(str, Enum):
    """合法的球员关系类型枚举。

    覆盖从直播文本中可提取的全部攻防关系类别，
    与 siamese_uie.py / rule_extractor.py 中实际使用的关系类型保持一致。

    Attributes:
        PASSES_TO: 传球关系（offense）
        ASSIST_TO: 助攻得分关系（offense）
        ATTACKS_AGAINST: 单打对位关系（offense）
        SCORES_OVER: 得分关系（offense）
        STEALS_FROM: 抢断关系（defense）
        BLOCKS: 封盖关系（defense）
        DEFENDS: 防守干扰关系（defense）
        REBOUNDS_OVER: 篮板争抢关系（defense）
        SCREEN_FOR: 掩护挡拆关系（offense）
        FOULS_ON: 犯规关系（defense）
        FORCES_TURNOVER: 造成失误关系（defense）
        CONTESTS_SHOT: 干扰投篮关系（defense）
    """
    PASSES_TO = "passes_to"
    ASSIST_TO = "assist_to"
    ATTACKS_AGAINST = "attacks_against"
    SCORES_OVER = "scores_over"
    STEALS_FROM = "steals_from"
    BLOCKS = "blocks"
    DEFENDS = "defends"
    REBOUNDS_OVER = "rebounds_over"
    SCREEN_FOR = "screen_for"
    FOULS_ON = "fouls_on"
    FORCES_TURNOVER = "forces_turnover"
    CONTESTS_SHOT = "contests_shot"

    @classmethod
    def valid_values(cls) -> list[str]:
        """返回所有合法关系类型的字符串列表。"""
        return valid_relation_types()


class BaseRelationModel(BaseModel):
    """球员关系验证的抽象基类，定义所有关系记录共有的核心字段。

    提供赛事标识、事件来源、关系分类、立场与置信度等基础约束，
    作为 PlayerRelationValidator 和 ContextualRelationValidator 的继承根。

    Attributes:
        saishi_id: 赛事ID，长度限制 1~32 字符
        evidence_event_id: 来源事件ID（live_text_event 表主键），非负整数
        live_sid: 直播文本序号，非负整数
        relation_type: 关系类型，必须是 RelationType 枚举中的合法值
        relation_side: 关系立场，取值范围为 offense（进攻方）或 defense（防守方）
        confidence: 置信度分数，浮点数范围 [0.0, 1.0]

    Example:
        >>> model = BaseRelationModel(
        ...     saishi_id="1780736",
        ...     evidence_event_id=12345,
        ...     live_sid=51,
        ...     relation_type="passes_to",
        ...     relation_side="offense",
        ...     confidence=0.85,
        ... )
        >>> model.relation_type
        'passes_to'
    """
    saishi_id: str
    evidence_event_id: int
    live_sid: int
    relation_type: str
    relation_side: Literal["offense", "defense"]
    confidence: float

    @field_validator("saishi_id")
    @classmethod
    def validate_saishi_id(cls, v: str) -> str:
        """校验 saishi_id 长度在 1~32 字符之间。"""
        if not (1 <= len(v) <= 32):
            raise ValueError(f"saishi_id 长度必须在 1~32 之间，当前长度: {len(v)}")
        return v.strip()

    @field_validator("evidence_event_id")
    @classmethod
    def validate_evidence_event_id(cls, v: int) -> int:
        """校验 evidence_event_id 为非负整数。"""
        if v < 0:
            raise ValueError(f"evidence_event_id 必须为非负整数，当前值: {v}")
        return v

    @field_validator("live_sid")
    @classmethod
    def validate_live_sid(cls, v: int) -> int:
        """校验 live_sid 为非负整数。"""
        if v < 0:
            raise ValueError(f"live_sid 必须为非负整数，当前值: {v}")
        return v

    @field_validator("relation_type")
    @classmethod
    def validate_relation_type(cls, v: str) -> str:
        """校验 relation_type 必须是预定义的合法关系类型之一。"""
        valid = RelationType.valid_values()
        if v not in valid:
            raise ValueError(
                f"relation_type 必须为以下值之一: {valid}，当前值: {v!r}"
            )
        return v

    @field_validator("confidence")
    @classmethod
    def validate_confidence(cls, v: float) -> float:
        """校验 confidence 在 [0.0, 1.0] 区间内。"""
        if not (0.0 <= v <= 1.0):
            raise ValueError(
                f"confidence 必须在 0.0 ~ 1.0 之间，当前值: {v}"
            )
        return round(v, 6)

    model_config = {"extra": "forbid"}


class PlayerRelationValidator(BaseRelationModel):
    """球员关系验证模型，在基类基础上扩展主体/客体球员及动作细节字段。

    用于验证从 UIE 模型或规则抽取器输出的单条关系记录，
    确保主体与客体不是同一球员，且得分数值符合篮球规则约束。

    Attributes:
        subject_player_name: 主体球员姓名，长度限制 1~100 字符
        object_player_name: 客体球员姓名，长度限制 1~100 字符
        action_text: 动作描述文本（如「传球」「抢断」），可选
        result_text: 结果描述文本（如「得分」「封盖」），可选
        score_points: 得分数值，篮球单次最多 3 分（投篮）+ 罚球 2 分，
                     为安全起见上限设为 5 分，可选

    Example:
        >>> validator = PlayerRelationValidator(
        ...     saishi_id="1780736",
        ...     evidence_event_id=12345,
        ...     live_sid=51,
        ...     relation_type="assist_to",
        ...     relation_side="offense",
        ...     confidence=0.74,
        ...     subject_player_name="谢伊·吉尔杰斯-亚历山大",
        ...     object_player_name="亚瑟",
        ...     action_text="助攻",
        ...     result_text="得分",
        ...     score_points=2,
        ... )
        >>> validator.score_points
        2
    """
    subject_player_name: str
    object_player_name: str
    action_text: Optional[str] = None
    result_text: Optional[str] = None
    score_points: Optional[int] = None

    @field_validator("subject_player_name")
    @classmethod
    def validate_subject_player_name(cls, v: str) -> str:
        """校验主体球员姓名长度在 1~100 字符之间。"""
        stripped = v.strip()
        if not (1 <= len(stripped) <= 100):
            raise ValueError(
                f"subject_player_name 长度必须在 1~100 之间，当前长度: {len(stripped)}"
            )
        return stripped

    @field_validator("object_player_name")
    @classmethod
    def validate_object_player_name(cls, v: str) -> str:
        """校验客体球员姓名长度在 1~100 字符之间。"""
        stripped = v.strip()
        if not (1 <= len(stripped) <= 100):
            raise ValueError(
                f"object_player_name 长度必须在 1~100 之间，当前长度: {len(stripped)}"
            )
        return stripped

    @field_validator("score_points")
    @classmethod
    def validate_score_points(cls, v: Optional[int]) -> Optional[int]:
        """校验得分数值为非负整数且不超过 5（篮球单次最大合理得分）。"""
        if v is None:
            return None
        if v < 0 or v > 5:
            raise ValueError(
                f"score_points 必须在 0~5 之间（含罚球加成），当前值: {v}"
            )
        return v

    @field_validator("object_player_name")
    @classmethod
    def validate_subject_not_equal_object(
        cls, v: str, info: Any
    ) -> str:
        """确保主体球员与客体球员不是同一人。"""
        subject = info.data.get("subject_player_name") if isinstance(info.data, dict) else None
        if subject is not None and v.strip() == subject.strip():
            raise ValueError(
                f"subject_player_name 与 object_player_name 不能相同，当前均为: {v!r}"
            )
        return v


class ContextualRelationValidator(PlayerRelationValidator):
    """带比赛上下文的完整关系验证模型，在 PlayerRelationValidator 基础上扩展球队/比分上下文字段。

    用于需要完整比赛状态信息的关系记录验证场景，
    包含进攻方归属、球权回合序号、双方实时比分等字段。

    Attributes:
        offense_team_id: 当前进攻方球队ID，可选
        offense_team_name: 当前进攻方球队名称，可选
        offense_team_side: 当前进攻方阵营（home/visit），可选
        possession_number: 进攻回合序号，从 1 开始，可选
        home_score: 主队总分，非负整数，可选
        visit_score: 客队总分，非负整数，可选

    Example:
        >>> validator = ContextualRelationValidator(
        ...     saishi_id="1780736",
        ...     evidence_event_id=12345,
        ...     live_sid=112,
        ...     relation_type="rebounds_over",
        ...     relation_side="defense",
        ...     confidence=0.61,
        ...     subject_player_name="阿尔佩伦·申京",
        ...     object_player_name="卡森·华莱士",
        ...     action_text="篮板",
        ...     offense_team_id="11",
        ...     offense_team_name="火箭",
        ...     offense_team_side="home",
        ...     possession_number=12,
        ...     home_score=88,
        ...     visit_score=94,
        ... )
        >>> validator.home_score
        88
    """
    offense_team_id: Optional[str] = None
    offense_team_name: Optional[str] = None
    offense_team_side: Optional[Literal["home", "visit"]] = None
    possession_number: Optional[int] = None
    home_score: Optional[int] = None
    visit_score: Optional[int] = None

    @field_validator("possession_number")
    @classmethod
    def validate_possession_number(cls, v: Optional[int]) -> Optional[int]:
        """校验进攻回合序号为正整数（从 1 开始）。"""
        if v is None:
            return None
        if v < 1:
            raise ValueError(
                f"possession_number 必须为正整数（>=1），当前值: {v}"
            )
        return v

    @field_validator("home_score")
    @classmethod
    def validate_home_score(cls, v: Optional[int]) -> Optional[int]:
        """校验主队总分为非负整数。"""
        if v is None:
            return None
        if v < 0:
            raise ValueError(f"home_score 必须为非负整数，当前值: {v}")
        return v

    @field_validator("visit_score")
    @classmethod
    def validate_visit_score(cls, v: Optional[int]) -> Optional[int]:
        """校验客队总分为非负整数。"""
        if v is None:
            return None
        if v < 0:
            raise ValueError(f"visit_score 必须为非负整数，当前值: {v}")
        return v


def validate_relation_record(record: PlayerRelationRecord) -> ContextualRelationValidator:
    """将 PlayerRelationRecord dataclass 转换并验证为 Pydantic 模型。

    该函数作为 dataclass 到 Pydantic 模型的桥梁，
    对从 UIE 或规则抽取器产出的原始关系记录执行完整的结构化校验，
    包括字段类型、取值范围、枚举合法性及业务规则（如 subject != object）。

    Args:
        record: 待验证的 PlayerRelationRecord frozen dataclass 实例

    Returns:
        通过全部校验的 ContextualRelationValidator 实例

    Raises:
        ValidationError: 当任意字段不满足约束条件时抛出 Pydantic 验证错误，
                        错误消息包含具体字段名和失败原因

    Example:
        >>> from app.modules.semantics.models import PlayerRelationRecord
        >>> record = PlayerRelationRecord(
        ...     saishi_id="1780736",
        ...     evidence_event_id=12345,
        ...     live_sid=51,
        ...     relation_type="assist_to",
        ...     relation_side="offense",
        ...     subject_player_name="谢伊·吉尔杰斯-亚历山大",
        ...     subject_team_id=None,
        ...     subject_team_name=None,
        ...     subject_team_side=None,
        ...     subject_team_score=None,
        ...     object_player_name="亚瑟",
        ...     object_team_id=None,
        ...     object_team_name=None,
        ...     object_team_side=None,
        ...     object_team_score=None,
        ...     offense_team_id=None,
        ...     offense_team_name=None,
        ...     offense_team_side=None,
        ...     offense_team_score=None,
        ...     offense_team_points=None,
        ...     possession_number=None,
        ...     home_score=None,
        ...     visit_score=None,
        ...     action_text="助攻",
        ...     result_text="得分",
        ...     score_points=2,
        ...     evidence_text="切入上篮打进！AND ONE",
        ...     segmented_text="切入\\上篮\\打进\\AND\\ONE",
        ...     extractor_name="siamese_uie",
        ...     confidence=0.74,
        ... )
        >>> validated = validate_relation_record(record)
        >>> validated.subject_player_name
        '谢伊·吉尔杰斯-亚历山大'
        >>> validated.confidence
        0.74
    """
    return ContextualRelationValidator(
        saishi_id=record.saishi_id,
        evidence_event_id=record.evidence_event_id,
        live_sid=record.live_sid,
        relation_type=record.relation_type,
        relation_side=record.relation_side,
        confidence=record.confidence,
        subject_player_name=record.subject_player_name,
        object_player_name=record.object_player_name,
        action_text=record.action_text,
        result_text=record.result_text,
        score_points=record.score_points,
        offense_team_id=record.offense_team_id,
        offense_team_name=record.offense_team_name,
        offense_team_side=record.offense_team_side,
        possession_number=record.possession_number,
        home_score=record.home_score,
        visit_score=record.visit_score,
    )


def batch_validate_relations(
    records: list[PlayerRelationRecord],
) -> tuple[list[ContextualRelationValidator], list[dict[str, Any]]]:
    """批量验证一组 PlayerRelationRecord 记录，分离通过和失败的条目。

    逐条调用 validate_relation_record 进行校验，
    将验证通过的记录收集到有效列表中，
    同时为每条失败记录捕获详细的错误信息（包含索引位置和具体原因），
    方便调用方进行日志记录或后续修复处理。

    Args:
        records: 待批量验证的 PlayerRelationRecord 列表

    Returns:
        一个二元组：
        - 第一个元素为通过验证的 ContextualRelationValidator 列表（保持原始顺序）
        - 第二个元素为验证失败的详情列表，每个元素为字典格式::

            {
                "index": int,           # 原始列表中的索引位置
                "saishi_id": str,       # 赛事ID（用于定位问题记录）
                "evidence_event_id": int,
                "live_sid": int,
                "errors": list[dict],   # Pydantic ValidationError.errors() 输出
            }

    Example:
        >>> records = [record1, record2, record_bad]
        >>> valid_list, errors_list = batch_validate_relations(records)
        >>> print(f"通过: {len(valid_list)}, 失败: {len(errors_list)}")
        通过: 2, 失败: 1
        >>> for err in errors_list:
        ...     print(f"[{err['index']}] event_id={err['evidence_event_id']} "
        ...           f"errors={err['errors']}")
    """
    valid_list: list[ContextualRelationValidator] = []
    errors_list: list[dict[str, Any]] = []

    for idx, record in enumerate(records):
        try:
            validated = validate_relation_record(record)
            valid_list.append(validated)
        except ValidationError as exc:
            errors_list.append({
                "index": idx,
                "saishi_id": record.saishi_id,
                "evidence_event_id": record.evidence_event_id,
                "live_sid": record.live_sid,
                "errors": exc.errors(),
            })

    return valid_list, errors_list
