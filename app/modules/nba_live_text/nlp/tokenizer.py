from __future__ import annotations

import json
import os
import subprocess
import sys
from tempfile import TemporaryDirectory
from dataclasses import dataclass


@dataclass(frozen=True)
class TokenizeResult:
    tokens: list[str]


class Tokenizer:
    def __init__(self, *, batch_size: int = 8, subprocess_timeout: int = 180) -> None:
        self._taskflow = None
        self._jieba = None
        self._words: list[str] = []
        self._temp_dir: TemporaryDirectory[str] | None = None
        self._batch_size = max(1, int(batch_size))
        self._subprocess_timeout = subprocess_timeout
        self._active_mode: str | None = None
        self._backend: str | None = None

    def __del__(self) -> None:
        self._reset_taskflow()

    def add_words(self, words: list[str]) -> None:
        cleaned = [w.strip() for w in (words or []) if isinstance(w, str) and w.strip()]
        if not cleaned:
            return

        merged = sorted(set(self._words) | set(cleaned))
        if merged != self._words:
            self._words = merged
            self._reset_taskflow()

    def tokenize(self, text: str, *, stopwords: set[str] | None = None) -> TokenizeResult:
        return self.tokenize_batch([text], stopwords=stopwords)[0]

    def tokenize_batch(self, texts: list[str], *, stopwords: set[str] | None = None) -> list[TokenizeResult]:
        normalized = [(text or "").strip() for text in (texts or [])]
        if not normalized:
            return []

        taskflow_inputs: list[str] = []
        input_indexes: list[int] = []
        results = [TokenizeResult(tokens=[]) for _ in normalized]

        for index, content in enumerate(normalized):
            if not content:
                continue
            input_indexes.append(index)
            taskflow_inputs.append(content)

        if not taskflow_inputs:
            return results

        token_lists = self._tokenize_inputs(taskflow_inputs)

        for index, tokens in zip(input_indexes, token_lists, strict=False):
            cleaned_tokens = [t.strip() for t in tokens if isinstance(t, str) and t.strip()]
            if stopwords:
                cleaned_tokens = [t for t in cleaned_tokens if t not in stopwords]
            results[index] = TokenizeResult(tokens=cleaned_tokens)
        return results

    def _tokenize_inputs(self, texts: list[str]) -> list[list[str]]:
        self._ensure_backend()
        if self._backend == "taskflow_inprocess":
            assert self._taskflow is not None
            return self._normalize_output(self._taskflow(texts))
        if self._backend == "taskflow_subprocess":
            token_lists = self._tokenize_batch_with_taskflow_subprocess(texts)
            if token_lists is not None:
                return token_lists
            self._reset_taskflow()
            self._ensure_jieba()
        return self._tokenize_batch_with_jieba(texts)

    def _reset_taskflow(self) -> None:
        self._taskflow = None
        self._jieba = None
        self._active_mode = None
        self._backend = None
        if self._temp_dir is not None:
            self._temp_dir.cleanup()
            self._temp_dir = None

    def _ensure_backend(self) -> None:
        if self._backend is not None:
            return

        # Unit tests patch paddlenlp directly; keep the in-process path for them.
        if "paddlenlp" in sys.modules:
            self._ensure_taskflow_inprocess()
            return

        mode = self._probe_external_taskflow_mode()
        if mode is not None:
            self._active_mode = mode
            self._backend = "taskflow_subprocess"
            return
        self._ensure_jieba()

    def _ensure_taskflow_inprocess(self) -> None:
        if self._backend == "taskflow_inprocess" and self._taskflow is not None:
            return

        os.environ.setdefault("FLAGS_enable_pir_api", "0")
        from paddlenlp import Taskflow

        last_error: Exception | None = None
        for mode in ("accurate", "fast"):
            self._reset_taskflow()
            self._temp_dir = TemporaryDirectory(prefix=f"taskflow_word_seg_{mode}_")
            user_dict = self._write_user_dict(self._temp_dir.name)
            try:
                self._taskflow = Taskflow(
                    "word_segmentation",
                    mode=mode,
                    batch_size=self._batch_size,
                    user_dict=user_dict,
                )
                self._active_mode = mode
                self._backend = "taskflow_inprocess"
                return
            except Exception as exc:  # pragma: no cover - exercised with fallback test
                last_error = exc
                self._reset_taskflow()

        if last_error is not None:
            self._ensure_jieba()

    def _ensure_jieba(self) -> None:
        if self._backend == "jieba" and self._jieba is not None:
            return
        import jieba

        self._jieba = jieba
        for word in self._words:
            self._jieba.add_word(word, freq=10_000)
        self._active_mode = "jieba_fallback"
        self._backend = "jieba"

    def _write_user_dict(self, temp_root: str) -> str | None:
        if not self._words:
            return None

        from pathlib import Path

        user_dict_path = Path(temp_root) / "user_dict.txt"
        user_dict_path.write_text("\n".join(f"{word} 10" for word in self._words) + "\n", encoding="utf-8")
        return str(user_dict_path)

    def _probe_external_taskflow_mode(self) -> str | None:
        for mode in ("accurate", "fast"):
            if self._run_taskflow_probe(mode):
                return mode
        return None

    def _run_taskflow_probe(self, mode: str) -> bool:
        probe_code = """
import os
import sys
os.environ.setdefault("FLAGS_enable_pir_api", "0")
from paddlenlp import Taskflow
taskflow = Taskflow("word_segmentation", mode=sys.argv[1], batch_size=1)
result = taskflow(["测试文本"])
if isinstance(result, list):
    print("TASKFLOW_OK", flush=True)
"""
        try:
            completed = subprocess.run(
                [sys.executable, "-X", "faulthandler", "-c", probe_code, mode],
                capture_output=True,
                text=True,
                timeout=self._subprocess_timeout,
                env=os.environ.copy(),
            )
        except Exception:
            return False
        return completed.returncode == 0 and "TASKFLOW_OK" in (completed.stdout or "")

    def _tokenize_batch_with_taskflow_subprocess(self, texts: list[str]) -> list[list[str]] | None:
        if not texts or not self._active_mode:
            return None

        with TemporaryDirectory(prefix="taskflow_runtime_") as temp_root:
            user_dict = self._write_user_dict(temp_root)
            payload_path = os.path.join(temp_root, "payload.json")
            result_path = os.path.join(temp_root, "result.json")
            with open(payload_path, "w", encoding="utf-8") as fp:
                json.dump(
                    {
                        "texts": texts,
                        "mode": self._active_mode,
                        "batch_size": self._batch_size,
                        "user_dict": user_dict,
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

taskflow = Taskflow(
    "word_segmentation",
    mode=payload["mode"],
    batch_size=payload["batch_size"],
    user_dict=payload.get("user_dict"),
)
result = taskflow(payload["texts"])
with open(sys.argv[2], "w", encoding="utf-8") as fp:
    json.dump(result, fp, ensure_ascii=False)
print("TASKFLOW_BATCH_OK", flush=True)
"""
            try:
                completed = subprocess.run(
                    [sys.executable, "-X", "faulthandler", "-c", runner_code, payload_path, result_path],
                    capture_output=True,
                    text=True,
                    timeout=self._subprocess_timeout,
                    env=os.environ.copy(),
                )
            except Exception:
                return None

            if completed.returncode != 0 or "TASKFLOW_BATCH_OK" not in (completed.stdout or ""):
                return None
            if not os.path.exists(result_path):
                return None
            with open(result_path, "r", encoding="utf-8") as fp:
                raw_results = json.load(fp)
            return self._normalize_output(raw_results)

    def _tokenize_batch_with_jieba(self, texts: list[str]) -> list[list[str]]:
        self._ensure_jieba()
        assert self._jieba is not None
        return [list(self._jieba.cut(text, cut_all=False)) if text else [] for text in texts]

    def _normalize_output(self, raw_results: object) -> list[list[str]]:
        if not isinstance(raw_results, list):
            return []

        if raw_results and all(isinstance(item, str) for item in raw_results):
            return [list(raw_results)]

        normalized: list[list[str]] = []
        for item in raw_results:
            if isinstance(item, list):
                normalized.append([token for token in item if isinstance(token, str)])
            else:
                normalized.append([])
        return normalized
