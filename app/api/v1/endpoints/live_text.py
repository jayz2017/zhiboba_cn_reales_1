from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.modules.nba_live_text.auto_tune import auto_tune_next_game_live_text
from app.modules.semantics.siamese_uie import extract_postgame_player_relations
from app.modules.nba_live_text.zhiboba_livetext import (
    fetch_zhiboba_live_text_events,
    sync_zhiboba_live_text,
)
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
