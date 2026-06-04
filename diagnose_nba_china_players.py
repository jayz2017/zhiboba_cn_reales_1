#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
NBA中国球员匹配诊断脚本
=======================

从 NBA China API 拉取球员数据，与数据库中已有球员进行匹配，
输出未匹配球员的详细原因分析，方便排查调整。

使用方法:
    python diagnose_nba_china_players.py [--sample-limit 30] [--max-pages 5]
"""

import logging
import sys
from pathlib import Path

project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)

from app.core.database import SessionLocal
from app.utils.http.client import HttpClient
from app.modules.nba_schedule.nba_china_players import (
    diagnose_unmatched_nba_china_players,
    fetch_nba_china_player_records,
    find_unmatched_nba_china_player_records,
    load_existing_player_code_map,
    normalize_player_code,
    _serialize_player_record,
    _log_unmatched_player,
)


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description="NBA中国球员匹配诊断")
    parser.add_argument("--sample-limit", type=int, default=30, help="未匹配球员抽样数量")
    parser.add_argument("--max-pages", type=int, default=5, help="最大拉取页数")
    parser.add_argument("--page-size", type=int, default=50, help="每页球员数")
    args = parser.parse_args()

    print("=" * 80)
    print("  NBA China 球员匹配诊断")
    print("=" * 80)

    db = SessionLocal()
    http_client = HttpClient()

    try:
        print("\n[1/3] 从 NBA China API 拉取球员数据...")
        fetched = fetch_nba_china_player_records(
            http_client=http_client,
            page_size=args.page_size,
            max_pages=args.max_pages,
        )
        print(f"  拉取完成: {fetched.pages} 页, {len(fetched.records)} 名球员, 总计 {fetched.total_count}")

        print("\n[2/3] 与数据库已有球员进行匹配...")
        existing_map = load_existing_player_code_map(db=db)
        print(f"  数据库已有 player_code 映射: {len(existing_map)} 条")

        matched, unmatched = find_unmatched_nba_china_player_records(db=db, records=fetched.records)
        print(f"  匹配成功: {matched}")
        print(f"  未匹配: {len(unmatched)}")

        if not unmatched:
            print("\n[3/3] 所有球员均已匹配，无需调整!")
            return 0

        print(f"\n[3/3] 输出未匹配球员详细原因 (共 {len(unmatched)} 名):")
        print("-" * 80)

        for i, record in enumerate(unmatched[:args.sample_limit], 1):
            normalized_code = normalize_player_code(record.player_code)

            reasons = _diagnose_reason(db, record, normalized_code, existing_map)

            print(f"\n  [{i}] player_id={record.player_id}")
            print(f"      player_code: {record.player_code}")
            print(f"      normalized_code: {normalized_code}")
            print(f"      nba_player_name: {record.nba_player_name}")
            print(f"      team_name: {record.team_name}")
            print(f"      jersey_no: {record.nba_jersey_number}")
            print(f"      未匹配原因: {'; '.join(reasons)}")

            _log_unmatched_player(record=record, normalized_code=normalized_code, db=db)

        if len(unmatched) > args.sample_limit:
            print(f"\n  ... 还有 {len(unmatched) - args.sample_limit} 名未匹配球员未显示")

        print("\n" + "=" * 80)
        print(f"  诊断完成: 匹配 {matched}/{len(fetched.records)}, 未匹配 {len(unmatched)}")
        print(f"  匹配率: {matched / max(1, len(fetched.records)) * 100:.1f}%")
        print("=" * 80)

        return 0

    finally:
        db.close()


def _diagnose_reason(
    db,
    record,
    normalized_code: str | None,
    existing_map: dict[str, int],
) -> list[str]:
    """诊断未匹配原因，返回原因列表。"""
    reasons: list[str] = []

    if not normalized_code:
        reasons.append("normalized_code为空(player_code无法规范化)")
        return reasons

    if normalized_code in existing_map:
        reasons.append(f"[BUG] normalized_code='{normalized_code}'实际存在于existing_map但未被匹配")
        return reasons

    import re
    from sqlalchemy import text

    code_variants = []
    pc = record.player_code
    if pc:
        code_variants.append(pc.replace("_", "-"))
        code_variants.append(pc.replace("_", "."))
        code_variants.append(pc.replace("-", "_"))
        code_variants.append(pc.replace("-", "."))
        code_variants.append(pc.replace(".", "_"))
        code_variants.append(pc.replace(".", "-"))
        parts = re.split(r"[_\-\.]", pc)
        if len(parts) >= 2:
            cap = "".join(p.capitalize() for p in parts)
            code_variants.append(cap)
            code_variants.append(cap[0].lower() + cap[1:])

    variant_found = False
    for variant in code_variants:
        nv = normalize_player_code(variant)
        if nv and nv != normalized_code and nv in existing_map:
            reasons.append(
                f"变体'{variant}'(normalized='{nv}')匹配到id={existing_map[nv]}, "
                f"但主码'{normalized_code}'未匹配(分隔符差异)"
            )
            variant_found = True
            break

    if not variant_found and record.nba_player_name:
        name_row = db.execute(
            text(
                "SELECT id, zhiboba_player_name, en_player_name, player_code "
                "FROM nba_players_name_data "
                "WHERE zhiboba_player_name LIKE :name OR en_player_name LIKE :name "
                "LIMIT 3"
            ),
            {"name": f"%{record.nba_player_name}%"},
        ).fetchall()
        if name_row:
            for row in name_row:
                reasons.append(
                    f"按名称'{record.nba_player_name}'找到id={getattr(row, 'id')}, "
                    f"zhiboba_name='{getattr(row, 'zhiboba_player_name', None)}', "
                    f"en_name='{getattr(row, 'en_player_name', None)}', "
                    f"player_code='{getattr(row, 'player_code', None)}'不匹配"
                )
        else:
            reasons.append(
                f"数据库中无player_code匹配(normalized='{normalized_code}'), "
                f"且按名称'{record.nba_player_name}'也未找到"
            )
    elif not variant_found:
        reasons.append(f"数据库中无player_code匹配(normalized='{normalized_code}'), 且nba_player_name为空无法回退")

    if not record.nba_player_name:
        reasons.append("nba_player_name为空(无法按名称回退匹配)")
    if not record.team_name:
        reasons.append("team_name为空(无法按球队缩小范围)")

    return reasons


if __name__ == "__main__":
    sys.exit(main())
