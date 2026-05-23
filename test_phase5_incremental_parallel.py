#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Phase 5 高级特性测试脚本
========================

测试内容：
1. 增量更新（Incremental Update）- 只处理新增的直播文本
2. 并行处理（Parallel Processing）- 多场比赛并发抽取

使用方法：
    python test_phase5_incremental_parallel.py [--saishi-id 1780736] [--parallel-ids 1780736,1780738]

环境要求：
    - FastAPI 服务已启动 (http://localhost:8000)
    - 数据库连接正常
    - 测试比赛数据已存在
"""

import argparse
import json
import sys
import time
from datetime import datetime

try:
    import requests
except ImportError:
    print("[ERROR] 请先安装 requests 库: pip install requests")
    sys.exit(1)

BASE_URL = "http://localhost:8000/api/v1"


def print_separator(title: str = "") -> None:
    """打印分隔线"""
    width = 80
    if title:
        print(f"\n{'=' * width}")
        print(f"  {title}")
        print(f"{'=' * width}\n")
    else:
        print(f"{'-' * width}")


def print_test_result(test_name: str, passed: bool, details: str = "") -> None:
    """打印测试结果"""
    status = "[PASS]" if passed else "[FAIL]"
    print(f"{status} {test_name}")
    if details:
        print(f"      {details}")


def test_incremental_extraction(saishi_id: str, force_full: bool = False) -> dict:
    """
    测试增量抽取 API

    Args:
        saishi_id: 比赛ID
        force_full: 是否强制全量重抽

    Returns:
        API 响应字典
    """
    print_separator("测试 1: 增量抽取关系 (Incremental Extraction)")

    url = f"{BASE_URL}/live-text/zhiboba/relations/extract/incremental"
    params = {
        "saishi_id": saishi_id,
        "max_rows": 100,
        "sample_limit": 5,
        "force_full": force_full,
    }

    print(f"[INFO] 请求 URL: {url}")
    print(f"[INFO] 参数: {params}")

    try:
        start_time = time.time()
        response = requests.post(url, params=params, timeout=120)
        elapsed = time.time() - start_time

        print(f"\n[INFO] HTTP 状态码: {response.status_code}")
        print(f"[INFO] 响应耗时: {elapsed:.2f}s")

        if response.status_code != 200:
            print(f"[ERROR] HTTP 请求失败: {response.text}")
            return {"success": False, "error": f"HTTP {response.status_code}"}

        data = response.json()

        # 打印完整响应（格式化）
        print("\n[RESPONSE] 完整响应:")
        print(json.dumps(data, indent=2, ensure_ascii=False))

        # 验证响应结构
        tests_passed = 0
        tests_total = 0

        # 测试 1: 基本字段存在性
        tests_total += 1
        required_fields = [
            "processed", "mode", "saishi_id", "new_events_count",
            "total_events_to_date", "progress_pct", "relations_inserted",
            "backend", "is_first_extraction", "elapsed_seconds", "error_message"
        ]
        missing_fields = [f for f in required_fields if f not in data]
        if not missing_fields:
            print_test_result("基本字段完整性检查", True)
            tests_passed += 1
        else:
            print_test_result("基本字段完整性检查", False, f"缺少字段: {missing_fields}")

        # 测试 2: processed 标志
        tests_total += 1
        if data.get("processed") is True:
            print_test_result("processed 标志为 True", True)
            tests_passed += 1
        else:
            print_test_result("processed 标志为 True", False, f"值: {data.get('processed')}")

        # 测试 3: mode 字段值
        tests_total += 1
        expected_mode = "full" if force_full else "incremental"
        if data.get("mode") == expected_mode:
            print_test_result(f"mode 字段正确 ({expected_mode})", True)
            tests_passed += 1
        else:
            print_test_result(
                f"mode 字段正确 ({expected_mode})",
                False,
                f"实际值: {data.get('mode')}"
            )

        # 测试 4: new_events_count 类型
        tests_total += 1
        if isinstance(data.get("new_events_count"), int):
            print_test_result("new_events_count 为整数", True)
            tests_passed += 1
        else:
            print_test_result(
                "new_events_count 为整数",
                False,
                f"类型: {type(data.get('new_events_count')).__name__}"
            )

        # 测试 5: progress_pct 范围
        tests_total += 1
        pct = data.get("progress_pct", -1)
        if 0.0 <= pct <= 100.0:
            print_test_result(f"progress_pct 在有效范围 [0-100] ({pct}%)", True)
            tests_passed += 1
        else:
            print_test_result(
                "progress_pct 在有效范围 [0-100]",
                False,
                f"值: {pct}"
            )

        # 测试 6: is_first_extraction 类型
        tests_total += 1
        if isinstance(data.get("is_first_extraction"), bool):
            print_test_result("is_first_extraction 为布尔值", True)
            tests_passed += 1
        else:
            print_test_result(
                "is_first_extraction 为布尔值",
                False,
                f"类型: {type(data.get('is_first_extraction')).__name__}"
            )

        # 测试 7: backend 字段
        tests_total += 1
        backend = data.get("backend")
        if backend in ["siamese_uie", "rule_based", "unknown", None]:
            print_test_result(f"backend 字段有效 ({backend})", True)
            tests_passed += 1
        else:
            print_test_result("backend 字段有效", False, f"值: {backend}")

        # 测试 8: samples 字段（如果有的话）
        tests_total += 1
        samples = data.get("samples")
        if samples is not None:
            if isinstance(samples, list):
                print_test_result(f"samples 为列表 (长度: {len(samples)})", True)
                tests_passed += 1
                # 打印抽样数据预览
                if len(samples) > 0:
                    print(f"\n[SAMPLES] 关系抽样预览 (前3条):")
                    for i, sample in enumerate(samples[:3], 1):
                        print(f"  [{i}] {json.dumps(sample, indent=4, ensure_ascii=False)[:200]}...")
            else:
                print_test_result("samples 为列表", False, f"类型: {type(samples).__name__}")
        else:
            print_test_result("samples 字段为 None 或空", True)
            tests_passed += 1

        # 测试 9: error_message（成功时应为 None）
        tests_total += 1
        if data.get("error_message") is None:
            print_test_result("error_message 为 None（无错误）", True)
            tests_passed += 1
        else:
            print_test_result(
                "error_message 为 None",
                False,
                f"错误信息: {data.get('error_message')}"
            )

        # 测试 10: elapsed_seconds 合理性
        tests_total += 1
        elapsed_sec = data.get("elapsed_seconds", 0)
        if isinstance(elapsed_sec, (int, float)) and elapsed_sec >= 0:
            print_test_result(f"elapsed_seconds 合理 ({elapsed_sec}s)", True)
            tests_passed += 1
        else:
            print_test_result(
                "elapsed_seconds 合理",
                False,
                f"值: {elapsed_sec}"
            )

        # 汇总
        print_separator("增量抽取测试汇总")
        print(f"测试通过: {tests_passed}/{tests_total}")
        if tests_passed == tests_total:
            print("[RESULT] 所有测试通过!")
        else:
            print(f"[RESULT] {tests_total - tests_passed} 个测试失败")

        data["test_results"] = {"passed": tests_passed, "total": tests_total}
        return data

    except requests.exceptions.ConnectionError:
        print("[ERROR] 无法连接到 FastAPI 服务，请确认服务已启动在 http://localhost:8000")
        return {"success": False, "error": "Connection refused"}
    except requests.exceptions.Timeout:
        print("[ERROR] 请求超时")
        return {"success": False, "error": "Timeout"}
    except Exception as e:
        print(f"[ERROR] 未知错误: {e}")
        import traceback
        traceback.print_exc()
        return {"success": False, "error": str(e)}


def test_parallel_extraction(saishi_ids: list[str]) -> dict:
    """
    测试并行批量抽取 API

    Args:
        saishi_ids: 比赛ID列表

    Returns:
        API 响应字典
    """
    print_separator("测试 2: 并行批量抽取 (Parallel Batch Extraction)")

    if len(saishi_ids) < 2:
        print("[WARN] 并行测试需要至少 2 个比赛ID，当前只有 1 个，将复制使用")
        saishi_ids = saishi_ids * 2

    url = f"{BASE_URL}/live-text/zhiboba/relations/extract/batch-parallel"
    params = {
        "saishi_ids": ",".join(saishi_ids),
        "max_workers": min(3, len(saishi_ids)),
        "timeout_per_game": 120,
        "max_rows": 100,
        "sample_limit": 3,
        "force_full": False,
    }

    print(f"[INFO] 请求 URL: {url}")
    print(f"[INFO] 参数: {params}")

    try:
        start_time = time.time()
        response = requests.post(url, params=params, timeout=300)
        elapsed = time.time() - start_time

        print(f"\n[INFO] HTTP 状态码: {response.status_code}")
        print(f"[INFO] 响应耗时: {elapsed:.2f}s")

        if response.status_code != 200:
            print(f"[ERROR] HTTP 请求失败: {response.text}")
            return {"success": False, "error": f"HTTP {response.status_code}"}

        data = response.json()

        # 打印完整响应
        print("\n[RESPONSE] 完整响应:")
        print(json.dumps(data, indent=2, ensure_ascii=False))

        # 验证响应结构
        tests_passed = 0
        tests_total = 0

        # 测试 1: 基本字段
        tests_total += 1
        required_fields = ["processed", "mode", "parallel_config", "summary", "per_game_results"]
        missing_fields = [f for f in required_fields if f not in data]
        if not missing_fields:
            print_test_result("并行响应基本字段完整", True)
            tests_passed += 1
        else:
            print_test_result("并行响应基本字段完整", False, f"缺少: {missing_fields}")

        # 测试 2: mode 值
        tests_total += 1
        if data.get("mode") == "parallel_batch":
            print_test_result("mode 为 'parallel_batch'", True)
            tests_passed += 1
        else:
            print_test_result("mode 为 'parallel_batch'", False, f"值: {data.get('mode')}")

        # 测试 3: parallel_config
        tests_total += 1
        config = data.get("parallel_config", {})
        config_fields = ["games_requested", "max_workers", "timeout_per_game"]
        if all(k in config for k in config_fields):
            print_test_result(
                f"parallel_config 完整 (games={config['games_requested']}, workers={config['max_workers']})",
                True
            )
            tests_passed += 1
        else:
            print_test_result("parallel_config 完整", False, f"缺少字段")

        # 测试 4: summary
        tests_total += 1
        summary = data.get("summary", {})
        summary_fields = ["successful_games", "failed_games", "total_events_processed",
                         "total_relations_inserted", "success_rate"]
        if all(k in summary for k in summary_fields):
            print_test_result(
                f"summary 完整 (成功={summary['successful_games']}, 失败={summary['failed_games']}, "
                f"成功率={summary['success_rate']})",
                True
            )
            tests_passed += 1
        else:
            print_test_result("summary 完整", False, f"缺少字段")

        # 测试 5: per_game_results 数量
        tests_total += 1
        results = data.get("per_game_results", [])
        if len(results) == len(saishi_ids):
            print_test_result(
                f"per_game_results 数量匹配 (期望={len(saishi_ids)}, 实际={len(results)})",
                True
            )
            tests_passed += 1
        else:
            print_test_result(
                "per_game_results 数量匹配",
                False,
                f"期望={len(saishi_ids)}, 实际={len(results)}"
            )

        # 测试 6: 每场比赛结果格式
        tests_total += 1
        if results:
            first_result = results[0]
            result_fields = ["saishi_id", "is_incremental", "new_events_count",
                           "relations_inserted", "backend", "error_message"]
            if all(k in first_result for k in result_fields):
                print_test_result("单场结果字段格式正确", True)
                tests_passed += 1
            else:
                missing = [k for k in result_fields if k not in first_result]
                print_test_result("单场结果字段格式正确", False, f"缺少: {missing}")

            # 打印每场比赛的结果摘要
            print("\n[PER-GAME] 各场比赛结果摘要:")
            for i, r in enumerate(results, 1):
                status = "OK" if r.get("error_message") is None else f"ERROR: {r.get('error_message')}"
                print(f"  [{i}] saishi_id={r.get('saishi_id')} | "
                      f"events={r.get('new_events_count')} | "
                      f"relations={r.get('relations_inserted')} | "
                      f"progress={r.get('progress_pct')}% | "
                      f"backend={r.get('backend')} | {status}")
        else:
            print_test_result("单场结果字段格式正确", False, "results 为空")

        # 测试 7: 总耗时合理性
        tests_total += 1
        if elapsed < 300:  # 5分钟内应该完成
            print_test_result(f"总耗时合理 ({elapsed:.2f}s)", True)
            tests_passed += 1
        else:
            print_test_result("总耗时合理", False, f"耗时过长: {elapsed:.2f}s")

        # 汇总
        print_separator("并行抽取测试汇总")
        print(f"测试通过: {tests_passed}/{tests_total}")
        if tests_passed == tests_total:
            print("[RESULT] 所有测试通过!")
        else:
            print(f"[RESULT] {tests_total - tests_passed} 个测试失败")

        data["test_results"] = {"passed": tests_passed, "total": tests_total}
        return data

    except requests.exceptions.ConnectionError:
        print("[ERROR] 无法连接到 FastAPI 服务")
        return {"success": False, "error": "Connection refused"}
    except requests.exceptions.Timeout:
        print("[ERROR] 请求超时（并行处理可能需要更长时间）")
        return {"success": False, "error": "Timeout"}
    except Exception as e:
        print(f"[ERROR] 未知错误: {e}")
        import traceback
        traceback.print_exc()
        return {"success": False, "error": str(e)}


def test_incremental_flow(saishi_id: str) -> None:
    """
    测试完整的增量流程：
    1. 第一次抽取（全量）
    2. 第二次抽取（应为增量，new_events_count=0）
    3. 强制全量重抽
    """
    print_separator("测试 3: 完整增量流程 (Full Incremental Flow)")

    print("[STEP 1] 第一次抽取（应该是首次抽取，is_first_extraction=True）")
    result1 = test_incremental_extraction(saishi_id, force_full=False)

    if not result1.get("test_results"):
        print("[WARN] 第一次抽取失败，跳过后续流程测试")
        return

    print("\n[STEP 2] 第二次抽取（应该是增量模式，new_events_count=0 或很小）")
    time.sleep(1)  # 等待 1 秒确保时间戳不同
    result2 = test_incremental_extraction(saishi_id, force_full=False)

    if result2.get("test_results"):
        # 验证第二次确实是增量模式
        if result2.get("is_incremental") is True:
            print_test_result("第二次抽取识别为增量模式", True)
        else:
            print_test_result(
                "第二次抽取识别为增量模式",
                False,
                f"is_incremental={result2.get('is_incremental')}"
            )

        # 验证 new_events_count 应该为 0（因为没有新数据）
        if result2.get("new_events_count") == 0:
            print_test_result("第二次抽取 new_events_count=0（符合预期）", True)
        elif result2.get("new_events_count") < result1.get("new_events_count", 0):
            print_test_result(
                f"第二次抽取事件数减少 ({result2.get('new_events_count')} < {result1.get('new_events_count')})",
                True
            )
        else:
            print_test_result(
                "第二次抽取 new_events_count 应较小",
                False,
                f"第一次={result1.get('new_events_count')}, 第二次={result2.get('new_events_count')}"
            )

    print("\n[STEP 3] 强制全量重抽（force_full=True）")
    result3 = test_incremental_extraction(saishi_id, force_full=True)

    if result3.get("test_results"):
        if result3.get("mode") == "full":
            print_test_result("强制全量重抽 mode='full'", True)
        else:
            print_test_result(
                "强制全量重抽 mode='full'",
                False,
                f"mode={result3.get('mode')}"
            )


def main():
    """主函数"""
    parser = argparse.ArgumentParser(
        description="Phase 5 高级特性测试：增量更新和并行处理",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 测试单场比赛的增量抽取
  python test_phase5_incremental_parallel.py --saishi-id 1780736

  # 测试多场比赛的并行抽取
  python test_phase5_incremental_parallel.py --parallel-ids 1780736,1780738

  # 运行全部测试
  python test_phase5_incremental_parallel.py --saishi-id 1780736 --parallel-ids 1780736,1780738 --all
        """
    )

    parser.add_argument(
        "--saishi-id",
        type=str,
        default="1780736",
        help="用于增量抽取测试的比赛ID（默认: 1780736）"
    )
    parser.add_argument(
        "--parallel-ids",
        type=str,
        default=None,
        help="用于并行抽取测试的比赛ID列表，逗号分隔（例如: 1780736,1780738）"
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="运行所有测试（包括完整增量流程）"
    )

    args = parser.parse_args()

    print("=" * 80)
    print("  Phase 5 高级特性测试套件")
    print(f"  Incremental Update & Parallel Processing")
    print(f"  时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 80)

    # 测试 1: 增量抽取
    incremental_result = test_incremental_extraction(args.saishi_id)

    # 测试 2: 并行抽取（如果提供了多个 ID）
    parallel_result = None
    if args.parallel_ids:
        ids_list = [sid.strip() for sid in args.parallel_ids.split(",") if sid.strip()]
        if ids_list:
            parallel_result = test_parallel_extraction(ids_list)

    # 测试 3: 完整增量流程（如果指定了 --all）
    if args.all:
        test_incremental_flow(args.saishi_id)

    # 最终汇总
    print_separator("最终测试汇总")

    total_tests = 0
    passed_tests = 0

    for name, result in [("增量抽取", incremental_result), ("并行抽取", parallel_result)]:
        if result and "test_results" in result:
            tr = result["test_results"]
            total_tests += tr["total"]
            passed_tests += tr["passed"]

    if total_tests > 0:
        print(f"总测试数: {total_tests}")
        print(f"通过数量: {passed_tests}")
        print(f"通过率: {passed_tests / total_tests * 100:.1f}%")
        print()

        if passed_tests == total_tests:
            print("[SUCCESS] Phase 5 所有测试通过! 增量更新和并行处理功能正常。")
            sys.exit(0)
        else:
            print(f"[FAILURE] {total_tests - passed_tests} 个测试未通过，请检查上方详细信息。")
            sys.exit(1)
    else:
        print("[WARN] 未执行任何测试")
        sys.exit(2)


if __name__ == "__main__":
    main()
