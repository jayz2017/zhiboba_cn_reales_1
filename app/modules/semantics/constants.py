from __future__ import annotations

_BLOCK_KEYWORDS = ("盖帽", "封盖", "帽", "大帽")
_STEAL_KEYWORDS = ("抢断", "断下", "断球")
_FOUL_KEYWORDS = ("犯规",)
_TURNOVER_KEYWORDS = ("造成失误", "逼出失误", "逼失误")
_CONTEST_KEYWORDS = ("干扰", "封到", "扑防")
_SCORE_KEYWORDS = ("命中", "打进", "上进", "抛进", "投进", "罚进", "扣进", "绝杀", "补进")
_SCREEN_KEYWORDS = ("挡拆", "掩护")
_PASS_KEYWORDS = (
    "递给",
    "分给",
    "分球",
    "分右侧",
    "分左侧",
    "分外线",
    "分底线",
    "分底角",
    "回球",
    "传球",
    "横传",
    "直传",
    "斜传",
    "击地",
    "手递手",
)
_ATTACK_KEYWORDS = ("对位", "面对", "单打", "强攻", "突破", "背打")
_REBOUND_KEYWORDS = ("篮板", "前场板", "后场板")
_HELP_DEFENSE_KEYWORDS = ("协防", "补防", "扑防", "干扰")

CONFIDENCE_PASS = 0.68
CONFIDENCE_PASS_LOW = 0.62
CONFIDENCE_ATTACK = 0.72
CONFIDENCE_STEAL = 0.85
CONFIDENCE_BLOCK = 0.88
CONFIDENCE_SCORE_OVER_CONTEST = 0.66
CONFIDENCE_DEFENDS_CONTEST = 0.70
CONFIDENCE_ASSIST = 0.74
CONFIDENCE_SCORE_OVER = 0.79
CONFIDENCE_SCORE_OVER_IMPLICIT = 0.68
CONFIDENCE_REBOUND = 0.61
CONFIDENCE_RULE_FALLBACK = 0.60

DEFAULT_KEYWORD_GROUPS: dict[str, tuple[str, ...]] = {
    "block": _BLOCK_KEYWORDS,
    "steal": _STEAL_KEYWORDS,
    "foul": _FOUL_KEYWORDS,
    "turnover": _TURNOVER_KEYWORDS,
    "contest": _CONTEST_KEYWORDS,
    "score": _SCORE_KEYWORDS,
    "screen": _SCREEN_KEYWORDS,
    "pass": _PASS_KEYWORDS,
    "attack": _ATTACK_KEYWORDS,
    "rebound": _REBOUND_KEYWORDS,
    "help_defense": _HELP_DEFENSE_KEYWORDS,
}

KEYWORD_CATEGORY_DESCRIPTIONS: dict[str, str] = {
    "block": "封盖/盖帽动作关键词",
    "steal": "抢断动作关键词",
    "foul": "犯规动作关键词",
    "turnover": "造成失误动作关键词",
    "contest": "投篮干扰/扑防动作关键词",
    "score": "得分结果关键词",
    "screen": "掩护/挡拆动作关键词",
    "pass": "传球动作关键词",
    "attack": "进攻对位/单打动作关键词",
    "rebound": "篮板动作关键词",
    "help_defense": "协防/补防动作关键词",
}

DEFAULT_CONFIDENCE_VALUES: dict[str, float] = {
    "CONFIDENCE_PASS": CONFIDENCE_PASS,
    "CONFIDENCE_PASS_LOW": CONFIDENCE_PASS_LOW,
    "CONFIDENCE_ATTACK": CONFIDENCE_ATTACK,
    "CONFIDENCE_STEAL": CONFIDENCE_STEAL,
    "CONFIDENCE_BLOCK": CONFIDENCE_BLOCK,
    "CONFIDENCE_SCORE_OVER_CONTEST": CONFIDENCE_SCORE_OVER_CONTEST,
    "CONFIDENCE_DEFENDS_CONTEST": CONFIDENCE_DEFENDS_CONTEST,
    "CONFIDENCE_ASSIST": CONFIDENCE_ASSIST,
    "CONFIDENCE_SCORE_OVER": CONFIDENCE_SCORE_OVER,
    "CONFIDENCE_SCORE_OVER_IMPLICIT": CONFIDENCE_SCORE_OVER_IMPLICIT,
    "CONFIDENCE_REBOUND": CONFIDENCE_REBOUND,
    "CONFIDENCE_RULE_FALLBACK": CONFIDENCE_RULE_FALLBACK,
}

CONFIDENCE_DESCRIPTIONS: dict[str, str] = {
    "CONFIDENCE_PASS": "明确传球关系置信度",
    "CONFIDENCE_PASS_LOW": "上下文推断传球关系置信度",
    "CONFIDENCE_ATTACK": "进攻对位关系置信度",
    "CONFIDENCE_STEAL": "抢断关系置信度",
    "CONFIDENCE_BLOCK": "封盖关系置信度",
    "CONFIDENCE_SCORE_OVER_CONTEST": "协防干扰后得分关系置信度",
    "CONFIDENCE_DEFENDS_CONTEST": "协防/干扰防守关系置信度",
    "CONFIDENCE_ASSIST": "助攻关系置信度",
    "CONFIDENCE_SCORE_OVER": "得分压制防守人关系置信度",
    "CONFIDENCE_SCORE_OVER_IMPLICIT": "隐式得分压制关系置信度",
    "CONFIDENCE_REBOUND": "篮板关系置信度",
    "CONFIDENCE_RULE_FALLBACK": "规则兜底默认置信度",
}
