import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from app.modules.nba_live_text.nlp.tokenizer import Tokenizer


class FakeTaskflow:
    init_calls: list[tuple[str, dict]] = []
    last_inputs: list[str] | None = None
    response: list[list[str]] = []
    fail_modes: set[str] = set()

    def __init__(self, task: str, **kwargs) -> None:
        if kwargs.get("mode") in type(self).fail_modes:
            raise RuntimeError(f"mode init failed: {kwargs.get('mode')}")
        type(self).init_calls.append((task, kwargs))

    def __call__(self, inputs: list[str]) -> list[list[str]]:
        type(self).last_inputs = list(inputs)
        return type(self).response


class TestTokenizer(unittest.TestCase):
    def setUp(self) -> None:
        FakeTaskflow.init_calls = []
        FakeTaskflow.last_inputs = None
        FakeTaskflow.response = []
        FakeTaskflow.fail_modes = set()

    def test_tokenize_batch_uses_taskflow_and_user_dict(self) -> None:
        fake_module = types.SimpleNamespace(Taskflow=FakeTaskflow)
        FakeTaskflow.response = [["詹姆斯", "突破", "啊", "上篮", "命中"], ["库里", "三分", "命中"]]

        with patch.dict(sys.modules, {"paddlenlp": fake_module}):
            tokenizer = Tokenizer(batch_size=4)
            tokenizer.add_words(["詹姆斯", "库里"])
            results = tokenizer.tokenize_batch(
                ["詹姆斯突破啊上篮命中", "库里三分命中"],
                stopwords={"啊"},
            )

        self.assertEqual([item.tokens for item in results], [["詹姆斯", "突破", "上篮", "命中"], ["库里", "三分", "命中"]])
        self.assertEqual(FakeTaskflow.last_inputs, ["詹姆斯突破啊上篮命中", "库里三分命中"])
        self.assertEqual(len(FakeTaskflow.init_calls), 1)

        task_name, kwargs = FakeTaskflow.init_calls[0]
        self.assertEqual(task_name, "word_segmentation")
        self.assertEqual(kwargs["mode"], "accurate")
        self.assertEqual(kwargs["batch_size"], 4)

        user_dict_path = Path(kwargs["user_dict"])
        self.assertTrue(user_dict_path.exists())
        self.assertEqual(user_dict_path.read_text(encoding="utf-8"), "库里 10\n詹姆斯 10\n")

    def test_tokenize_falls_back_to_fast_when_accurate_unavailable(self) -> None:
        fake_module = types.SimpleNamespace(Taskflow=FakeTaskflow)
        FakeTaskflow.response = [["艾顿", "跳", "赢", "了"]]
        FakeTaskflow.fail_modes = {"accurate"}

        with patch.dict(sys.modules, {"paddlenlp": fake_module}):
            tokenizer = Tokenizer()
            tokenizer.add_words(["艾顿"])
            results = tokenizer.tokenize_batch(["艾顿跳赢了"], stopwords=None)

        self.assertEqual([item.tokens for item in results], [["艾顿", "跳", "赢", "了"]])
        self.assertEqual([kwargs["mode"] for _, kwargs in FakeTaskflow.init_calls], ["fast"])

    def test_tokenize_handles_empty_text(self) -> None:
        fake_module = types.SimpleNamespace(Taskflow=FakeTaskflow)
        FakeTaskflow.response = [["杜兰特", "中投"]]

        with patch.dict(sys.modules, {"paddlenlp": fake_module}):
            tokenizer = Tokenizer()
            results = tokenizer.tokenize_batch(["", "杜兰特中投"], stopwords=None)

        self.assertEqual([item.tokens for item in results], [[], ["杜兰特", "中投"]])


if __name__ == "__main__":
    unittest.main()
