from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.modules.nba_live_text.auto_tune import auto_tune_next_game_live_text
from app.modules.semantics.siamese_uie import extract_postgame_player_relations
from app.modules.nba_live_text.zhiboba_livetext import (
    fetch_zhiboba_live_text_events,
    sync_zhiboba_live_text,
)
from app.modules.semantics.incremental_service import IncrementalExtractorService
from app.utils.http.client import HttpClient


router = APIRouter()


@router.post("/live-text/zhiboba/auto-tune/next", summary="从 game_list 自动抓取比赛文本并调优过滤规则", tags=["比赛直播文本"])
def zhiboba_live_text_auto_tune_next(
    sample_limit: int = Query(10, description="返回分词样例条数，默认 10"),
    max_attempts: int = Query(3, description="自动调优最大尝试轮数，默认 3，用于防止死循环"),
    db: Session = Depends(get_db),
) -> dict:
    http_client = HttpClient()
    return auto_tune_next_game_live_text(
        db=db,
        http_client=http_client,
        sample_limit=sample_limit,
        max_attempts=max_attempts,
    )


@router.post("/live-text/zhiboba/fetch", summary="抓取比赛直播文本原始事件", tags=["比赛直播文本"])
def zhiboba_live_text_fetch(
    saishi_id: str = Query(..., description="比赛ID（直播吧 saishi_id）"),
    start_cursor: int = Query(1, description="游标起点（默认 1）"),
    page_size: int = Query(10, description="每页条数（默认 10，对应 page_10）"),
    db: Session = Depends(get_db),
) -> dict:
    http_client = HttpClient()
    return fetch_zhiboba_live_text_events(
        db=db,
        http_client=http_client,
        saishi_id=saishi_id,
        start_cursor=start_cursor,
        page_size=page_size,
    )


@router.post("/live-text/zhiboba/sync", summary="同步比赛直播文本并分词", tags=["比赛直播文本"])
def zhiboba_live_text_sync(
    saishi_id: str = Query(..., description="比赛ID（直播吧 saishi_id）"),
    start_cursor: int = Query(1, description="游标起点（默认 1）"),
    page_size: int = Query(10, description="每页条数（默认 10，对应 page_10）"),
    db: Session = Depends(get_db),
) -> dict:
    http_client = HttpClient()
    return sync_zhiboba_live_text(
        db=db,
        http_client=http_client,
        saishi_id=saishi_id,
        start_cursor=start_cursor,
        page_size=page_size,
    )


@router.post("/live-text/zhiboba/relations/extract", summary="使用 SiameseUIE 抽取赛后球员攻防关系", tags=["比赛直播文本"])
def zhiboba_live_text_relation_extract(
    saishi_id: str = Query(..., description="比赛ID（直播吧 saishi_id）"),
    max_rows: int = Query(5000, description="最多读取多少条已分词事件，默认 5000"),
    sample_limit: int = Query(20, description="返回关系抽样条数，默认 20"),
    db: Session = Depends(get_db),
) -> dict:
    return extract_postgame_player_relations(
        db=db,
        saishi_id=saishi_id,
        max_rows=max_rows,
        sample_limit=sample_limit,
    )


@router.post(
    "/live-text/zhiboba/relations/extract/incremental",
    summary="增量抽取关系（只处理新增直播文本）",
    tags=["比赛直播文本 - Phase 5 高级特性"],
)
def zhiboba_live_text_relation_extract_incremental(
    saishi_id: str = Query(..., description="比赛ID（直播吧 saishi_id）"),
    max_rows: int = Query(1000, description="本次最多处理多少条新事件，默认 1000"),
    sample_limit: int = Query(20, description="返回关系抽样条数，默认 20"),
    force_full: bool = Query(False, description="是否强制全量重抽（忽略进度），默认 false"),
    db: Session = Depends(get_db),
) -> dict:
    """
    增量抽取球员关系（Phase 5 高级特性）
    
    - 只处理自上次抽取后新增的直播文本事件
    - 自动记录处理进度到 nba_zhiboba_extraction_progress 表
    - 支持断点续传，适合长时间运行的比赛实时抽取
    
    **使用场景**:
    - 比赛进行中的实时增量抽取
    - 历史数据补全（避免重复处理已处理的文本）
    - 大数据量场景下的分批处理
    """
    service = IncrementalExtractorService(default_max_rows=max_rows)
    
    result = service.extract_incremental(
        db=db,
        saishi_id=saishi_id,
        force_full=force_full,
        sample_limit=sample_limit,
    )
    
    return {
        "processed": True,
        "mode": "incremental" if not force_full else "full",
        "saishi_id": saishi_id,
        "new_events_count": result.new_events_count,
        "total_events_to_date": result.total_events_to_date,
        "progress_pct": result.progress_pct,
        "relations_inserted": result.relations_inserted,
        "backend": result.backend or "unknown",
        "is_first_extraction": result.is_first_extraction,
        "elapsed_seconds": round(result.elapsed_seconds, 2),
        "samples": result.samples or [],
        "error_message": result.error_message,
    }


@router.post(
    "/live-text/zhiboba/relations/extract/batch-parallel",
    summary="并行批量抽取多场比赛的关系",
    tags=["比赛直播文本 - Phase 5 高级特性"],
)
def zhiboba_live_text_relation_extract_batch_parallel(
    saishi_ids: str = Query(
        ...,
        description="多个比赛ID，逗号分隔（例如：1780736,1780738,1780740）"
    ),
    max_workers: int = Query(3, description="并行线程数，默认 3（建议 1-5）"),
    timeout_per_game: int = Query(300, description="单场比赛超时时间（秒），默认 300"),
    max_rows: int = Query(5000, description="单场最多读取多少条已分词事件，默认 5000"),
    sample_limit: int = Query(10, description="每场返回关系抽样条数，默认 10"),
    force_full: bool = Query(False, description="是否强制全量重抽，默认 false"),
    db: Session = Depends(get_db),
) -> dict:
    """
    并行批量抽取多场比赛的球员关系（Phase 5 高级特性）
    
    - 使用线程池并发处理多场比赛
    - 每场比赛独立数据库会话，避免锁竞争
    - 单场失败不影响其他场次的处理
    - 支持超时控制和错误隔离
    
    **使用场景**:
    - 批量处理历史比赛数据
    - 赛后快速分析多场比赛
    - 数据迁移和补全
    - 高性能批量作业
    
    **性能说明**:
    - 3 线程并行 vs 串行：预计提速 2-3 倍
    - 建议最大 concurrent workers <= CPU 核心数
    """
    import json as _json
    
    # 解析比赛ID列表
    ids_list = [sid.strip() for sid in saishi_ids.split(",") if sid.strip()]
    
    if not ids_list:
        return {
            "processed": False,
            "error": "No valid saishi_ids provided",
            "games_requested": 0,
            "results": [],
        }
    
    if len(ids_list) > 20:
        return {
            "processed": False,
            "error": "Too many games (max 20 per request)",
            "games_requested": len(ids_list),
            "results": [],
        }
    
    # 创建服务实例
    service = IncrementalExtractorService(default_max_rows=max_rows)
    
    # 执行并行抽取
    results = service.extract_parallel(
        db=db,
        saishi_ids=ids_list,
        max_workers=min(max_workers, len(ids_list)),
        timeout=timeout_per_game,
        force_full=force_full,
        sample_limit=sample_limit,
    )

    # 将 IncrementalExtractResult 对象转换为字典
    results_dicts = []
    for r in results:
        results_dicts.append({
            "saishi_id": r.saishi_id,
            "is_incremental": r.is_incremental,
            "is_first_extraction": r.is_first_extraction,
            "new_events_count": r.new_events_count,
            "total_events_to_date": r.total_events_to_date,
            "progress_pct": r.progress_pct,
            "relations_inserted": r.relations_inserted,
            "backend": r.backend or "unknown",
            "samples": r.samples or [],
            "error_message": r.error_message,
            "elapsed_seconds": round(r.elapsed_seconds, 2),
        })

    # 统计汇总
    total_events = sum(r.total_events_to_date for r in results)
    total_relations = sum(r.relations_inserted for r in results)
    successful = sum(1 for r in results if r.error_message is None)
    failed = len(results) - successful
    
    return {
        "processed": True,
        "mode": "parallel_batch",
        "parallel_config": {
            "games_requested": len(ids_list),
            "max_workers": min(max_workers, len(ids_list)),
            "timeout_per_game": timeout_per_game,
        },
        "summary": {
            "successful_games": successful,
            "failed_games": failed,
            "total_events_processed": total_events,
            "total_relations_inserted": total_relations,
            "success_rate": f"{successful / len(results) * 100:.1f}%" if results else "N/A",
        },
        "per_game_results": results_dicts,
    }
