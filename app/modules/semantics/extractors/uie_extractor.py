from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
from tempfile import TemporaryDirectory
from typing import Any

from app.core.config import settings
from app.modules.semantics.extractors.base import BaseRelationExtractor

logger = logging.getLogger(__name__)

_DEFAULT_RELATION_SCHEMA: list[dict[str, list[str]]] = [
    {"进攻球员": ["防守球员", "协作球员", "进攻动作", "结果", "得分值"]},
    {"防守球员": ["进攻球员", "防守动作", "结果"]},
]


class SiameseUIEExtractor(BaseRelationExtractor):
    """基于 SiameseUIE 模型的球员关系抽取器实现。

    使用 PaddleNLP Taskflow 在子进程中执行信息抽取推理，
    支持自定义模型名称、批处理大小和抽取 Schema。

    继承自 BaseRelationExtractor，实现了 Strategy Pattern 中的具体策略。

    Attributes:
        _model_name: UIE 模型名称（从 settings 或构造参数获取）
        _batch_size: 批量推理时的批次大小
        _schema: UIE 信息抽取的 Schema 定义
        last_backend: 上一次使用的后端标识（继承自基类）

    Example:
        >>> extractor = SiameseUIEExtractor(model_name="uie-base")
        >>> results = extractor.extract_batch(["库里传球给克莱命中三分"])
        >>> print(extractor.get_backend_name())
        'taskflow_subprocess'
    """

    def __init__(
        self,
        *,
        model_name: str | None = None,
        batch_size: int | None = None,
        schema: list[dict[str, list[str]]] | None = None,
        timeout: int = 240,
    ) -> None:
        """初始化 SiameseUIE 抽取器实例。

        Args:
            model_name: PaddleNLP UIE 模型名称，默认使用 settings.SIAMESE_UIE_MODEL_NAME
            batch_size: 批量推理的批次大小，默认使用 settings.SIAMESE_UIE_BATCH_SIZE
            schema: UIE 抽取 Schema 定义，默认使用内置的攻防关系 Schema
            timeout: 子进程超时秒数，默认 240
        """
        super().__init__()
        self._model_name = (model_name or settings.SIAMESE_UIE_MODEL_NAME).strip()
        self._batch_size = max(1, int(batch_size or settings.SIAMESE_UIE_BATCH_SIZE))
        self._schema = schema or _DEFAULT_RELATION_SCHEMA
        self._timeout = timeout

    def extract(self, text: str) -> dict[str, Any]:
        """对单条文本执行 UIE 关系抽取。

        通过调用 extract_batch 方法实现单条文本抽取，
        返回第一条结果或空字典。

        Args:
            text: 待抽取的输入文本

        Returns:
            UIE 抽取结果字典，包含"进攻球员"/"防守球员"等实体关系数据。
            输入为空时返回空字典。
        """
        if not text or not text.strip():
            return {}
        results = self.extract_batch([text])
        return results[0] if results else {}

    def extract_batch(self, texts: list[str]) -> list[dict[str, Any]]:
        """对文本列表批量执行 UIE 推理。

        将输入文本序列化为 JSON 并通过子进程调用 PaddleNLP Taskflow，
        实现与主进程隔离的模型推理。支持超时控制和错误降级。

        Args:
            texts: 待抽取的文本列表（建议已分词的直播文本）

        Returns:
            与输入等长的结果列表。每项为 UIE 抽取结果的字典结构：
            - 成功时：包含"进攻球员"/"防守球员"等键的关系数据
            - 失败时：返回空字典 {}
            - 子进程不可用时：全部返回空字典并设置 backend 为 "unavailable"
        """
        normalized = [(text or "").strip() for text in (texts or [])]
        if not normalized:
            self.last_backend = "empty"
            return []

        raw_results = self._run_taskflow_subprocess(normalized)
        if raw_results is None:
            self.last_backend = "unavailable"
            return [{} for _ in normalized]
        self.last_backend = "taskflow_subprocess"
        if not isinstance(raw_results, list):
            return [{} for _ in normalized]

        normalized_results: list[dict[str, Any]] = []
        for item in raw_results:
            normalized_results.append(item if isinstance(item, dict) else {})
        while len(normalized_results) < len(normalized):
            normalized_results.append({})
        return normalized_results[: len(normalized)]

    def get_backend_name(self) -> str:
        """获取 UIE 抽取器的后端标识。

        Returns:
            固定返回 "siamese_uie" 字符串，用于区分不同抽取策略
        """
        return "siamese_uie"

    def _run_taskflow_subprocess(self, texts: list[str]) -> list[dict[str, Any]] | None:
        """在独立子进程中运行 PaddleNLP Taskflow 推理。

        通过临时文件传递输入输出数据，避免进程间对象序列化问题。
        设置 240 秒超时保护，异常时返回 None 触发规则回退。

        Args:
            texts: 待推理的文本列表

        Returns:
            - 成功：UIE 抽取结果列表
            - 失败/超时：None（调用方应降级到规则抽取器）
        """
        if not texts:
            return []

        with TemporaryDirectory(prefix="siamese_uie_runtime_") as temp_root:
            payload_path = os.path.join(temp_root, "payload.json")
            result_path = os.path.join(temp_root, "result.json")
            with open(payload_path, "w", encoding="utf-8") as fp:
                json.dump(
                    {
                        "texts": texts,
                        "schema": self._schema,
                        "model_name": self._model_name,
                    },
                    fp,
                    ensure_ascii=False,
                )

            runner_code = """
import json
import os
import sys
os.environ.setdefault("FLAGS_enable_pir_api", "0")
from paddlenlp import Taskflow

with open(sys.argv[1], "r", encoding="utf-8") as fp:
    payload = json.load(fp)

extractor = Taskflow(
    "information_extraction",
    schema=payload["schema"],
    model=payload["model_name"],
)
results = extractor(payload["texts"])
with open(sys.argv[2], "w", encoding="utf-8") as fp:
    json.dump(results, fp, ensure_ascii=False)
print("SIAMESE_UIE_OK", flush=True)
"""
            try:
                completed = subprocess.run(
                    [sys.executable, "-X", "faulthandler", "-c", runner_code, payload_path, result_path],
                    capture_output=True,
                    text=True,
                    timeout=self._timeout,
                    env=os.environ.copy(),
                )
            except Exception:
                return None

            if completed.returncode != 0 or "SIAMESE_UIE_OK" not in (completed.stdout or ""):
                return None
            if not os.path.exists(result_path):
                return None
            with open(result_path, "r", encoding="utf-8") as fp:
                loaded = json.load(fp)
            return loaded if isinstance(loaded, list) else None


def normalize_segmented_text_for_uie(segmented_text: str | None, live_text: str | None) -> str:
    """规范化分词文本以适配 UIE 模型输入。

    优先使用分词后的文本，去除转义字符；当分词文本为空时回退到原始直播文本。

    Args:
        segmented_text: 分词后的直播文本（可能包含反斜杠转义）
        live_text: 原始未分词的直播文本

    Returns:
        清洗后的文本字符串，优先返回分词文本内容
    """
    base_text = (segmented_text or "").strip()
    if base_text:
        return base_text.replace("\\", "")
    return (live_text or "").strip()
