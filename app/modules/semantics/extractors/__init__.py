"""球员关系抽取器模块（Strategy Pattern 实现）。

本模块提供基于策略模式的球员攻防关系抽取架构，包含：
- BaseRelationExtractor: 抽象基类，定义统一接口
- SiameseUIEExtractor: 基于 PaddleNLP UIE 模型的抽取实现
- RuleBasedExtractor: 基于关键词规则的回退抽取实现

使用示例：
    from app.modules.semantics.extractors import (
        BaseRelationExtractor,
        SiameseUIEExtractor,
        RuleBasedExtractor,
        normalize_segmented_text_for_uie,
    )

    # 创建 UIE 抽取器实例
    uie_extractor = SiameseUIEExtractor(model_name="uie-base")
    results = uie_extractor.extract_batch(["库里传球给克莱命中三分"])

    # 创建规则抽取器实例
    rule_extractor = RuleBasedExtractor()
    relations = rule_extractor.extract_from_rows(rows, config)
"""

from app.modules.semantics.extractors.base import BaseRelationExtractor
from app.modules.semantics.extractors.rule_extractor import RuleBasedExtractor
from app.modules.semantics.extractors.uie_extractor import (
    SiameseUIEExtractor,
    normalize_segmented_text_for_uie,
)

__all__ = [
    "BaseRelationExtractor",
    "SiameseUIEExtractor",
    "RuleBasedExtractor",
    "normalize_segmented_text_for_uie",
]
