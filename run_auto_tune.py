#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
比赛文本自动调优执行脚本
"""

import sys
import json
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from app.core.database import SessionLocal
from app.utils.http.client import HttpClient
from app.modules.nba_live_text.auto_tune import auto_tune_next_game_live_text


def print_section(title: str) -> None:
    """打印标题分隔线"""
    print("\n" + "=" * 80)
    print(f"  {title}")
    print("=" * 80 + "\n")


def main() -> int:
    print_section("比赛文本自动调优")
    print(f"项目根目录: {project_root}")

    # 获取数据库会话和 HTTP 客户端
    db = SessionLocal()
    http_client = HttpClient()

    try:
        print("正在从 game_list 选择下一场比赛并执行自动调优...")
        result = auto_tune_next_game_live_text(
            db=db,
            http_client=http_client,
            sample_limit=15,
            max_attempts=3,
        )

        # 打印完整结果（格式化）
        print("\n完整输出结果:")
        print(json.dumps(result, indent=2, ensure_ascii=False))

        print_section("执行结果摘要")

        if not result.get("processed"):
            print(f"  ⚠️ {result.get('message')}")
            return 1

        print(f"  🎯 处理的比赛: {result.get('home_team')} vs {result.get('visit_team')}")
        print(f"  🏷️ saishi_id: {result.get('saishi_id')}")
        print(f"  📅 比赛日期: {result.get('sdate')}")
        print(f"  ⏱️  开始时间: {result.get('start_time')}")
        print(f"  🚀 尝试次数: {result.get('attempt_count')} / {result.get('max_attempts')}")
        print(f"  🛑 停止原因: {result.get('stop_reason')}")

        # 打印抓取与分词统计
        fetch_result = result.get("fetch_result", {})
        sync_result = result.get("sync_result", {})
        if fetch_result:
            print(f"\n  📊 抓取统计:")
            print(f"    - 总页数: {fetch_result.get('pages')}")
            print(f"    - 总事件数: {fetch_result.get('events')}")
            print(f"    - 已过滤: {fetch_result.get('filtered')}")
            print(f"    - 已完成: {fetch_result.get('finished')}")

        if sync_result:
            print(f"\n  📊 分词统计:")
            print(f"    - 成功数: {sync_result.get('success')}")
            print(f"    - 失败数: {sync_result.get('failed')}")
            print(f"    - 跳过数: {sync_result.get('skipped')}")
            print(f"    - 总计: {sync_result.get('total')}")

        # 打印调优结果
        tune_result = result.get("tune_result", {})
        if tune_result:
            print(f"\n  🎛️ 调优结果:")
            print(f"    - 新增规则数: {tune_result.get('applied_rule_count')}")
            if tune_result.get("applied_rules"):
                print(f"    - 新增规则: {tune_result.get('applied_rules')}")

        # 打印规格校验结果
        validation_result = result.get("validation_result", {})
        if validation_result:
            print(f"\n  ✅ 规格校验:")
            print(f"    - 通过: {'是' if validation_result.get('passed') else '否'}")
            print(f"    - 违规规则数: {validation_result.get('violation_rule_count')}")
            if validation_result.get("violation_summaries"):
                print(f"    - 违规详情: {validation_result.get('violation_summaries')}")

        # 打印分词样例
        segmented_examples = result.get("segmented_examples", [])
        if segmented_examples:
            print(f"\n  📝 分词样例 ({len(segmented_examples)} 条):")
            for i, example in enumerate(segmented_examples[:10], 1):
                print(f"\n    [{i}] live_sid={example.get('live_sid')}")
                print(f"      pid_text: {repr(example.get('pid_text'))}")
                print(f"      live_text: {repr(example.get('live_text'))}")
                print(f"      segmented_text: {repr(example.get('segmented_text'))}")

        print_section("自动调优执行完成")
        return 0

    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
