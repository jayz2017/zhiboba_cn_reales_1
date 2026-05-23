from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class BaseRelationExtractor(ABC):
    """球员关系抽取器的抽象基类，定义 Strategy Pattern 的统一接口。

    所有具体抽取器（UIE模型、规则引擎等）必须继承此类并实现 extract 方法。
    该基类提供了批量处理的默认实现以及后端名称标识接口。

    Attributes:
        last_backend: 上一次使用的后端标识字符串
    """

    def __init__(self) -> None:
        self.last_backend: str = "uninitialized"

    @abstractmethod
    def extract(self, text: str) -> dict[str, Any]:
        """对单条文本执行关系抽取。

        Args:
            text: 待抽取的输入文本（通常为分词后的直播文本）

        Returns:
            抽取结果字典，结构由具体子类定义。
            UIE 抽取器返回包含"进攻球员"/"防守球员"等键的字典；
            规则抽取器可能返回空字典或简化结构。

        Raises:
            NotImplementedError: 子类未实现此方法时抛出
        """
        raise NotImplementedError

    def extract_batch(self, texts: list[str]) -> list[dict[str, Any]]:
        """对文本列表批量执行关系抽取。

        默认实现逐条调用 extract() 方法。子类可重写以优化批量性能
        （如 UIE 抽取器使用 subprocess 批量推理）。

        Args:
            texts: 待抽取的文本列表

        Returns:
            与输入等长的抽取结果列表，每项对应一条文本的抽取结果。
            输入为空列表时返回空列表。
        """
        normalized = [(text or "").strip() for text in (texts or [])]
        if not normalized:
            self.last_backend = "empty"
            return []
        results: list[dict[str, Any]] = []
        for text in normalized:
            try:
                result = self.extract(text)
                results.append(result if isinstance(result, dict) else {})
            except Exception:
                results.append({})
        return results

    def get_backend_name(self) -> str:
        """获取当前抽取器的后端标识名称。

        用于日志记录和结果溯源，标识本次抽取使用的算法/模型。

        Returns:
            后端名称字符串（如 "siamese_uie"、"rule_fallback" 等）
        """
        return self.last_backend
