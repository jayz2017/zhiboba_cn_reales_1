from __future__ import annotations

_BLOCK_KEYWORDS = ("盖帽", "封盖", "帽", "大帽")
_STEAL_KEYWORDS = ("抢断", "断下", "断球")
_FOUL_KEYWORDS = ("犯规",)
_TURNOVER_KEYWORDS = ("造成失误", "逼出失误", "逼失误")
_CONTEST_KEYWORDS = ("干扰", "封到", "扑防")
_SCORE_KEYWORDS = ("命中", "打进", "上进", "抛进", "投进", "罚进", "扣进", "绝杀", "补进")
_SCREEN_KEYWORDS = ("挡拆", "掩护")
_PASS_KEYWORDS = ("递给", "分球", "回球", "传球", "横传", "直传", "斜传", "手递手")
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
