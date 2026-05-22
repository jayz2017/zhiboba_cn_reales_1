from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.modules.nba_schedule.game_list_by_date import sync_game_list_by_date
from app.modules.nba_schedule.zhiboba_schedule import sync_zhiboba_schedule
from app.modules.nba_schedule.zhiboba_playoffs import sync_zhiboba_playoffs
from app.modules.nba_schedule.player_alias import sync_player_aliases
from app.modules.nba_schedule.zhiboba_team_players import (
    bind_players_team_id_by_zhiboba_team_id,
    sync_all_zhiboba_team_players,
    sync_zhiboba_team_players,
    sync_zhiboba_team_players_by_master_team_id,
)
from app.utils.http.client import HttpClient


router = APIRouter()


@router.post("/schedule/zhiboba/sync", summary="同步常规赛/总赛程")
def zhiboba_schedule_sync(
    year: int | None = Query(None, description="要同步的年份(YYYY)，若不传则按当前时间自动计算"), 
    db: Session = Depends(get_db)
) -> dict:
    """
    拉取直播吧指定年份的全部赛程信息，并自动增量（upsert）落库到 `nba_zhiboba_yj_gamelist` 表中。
    """
    http_client = HttpClient()
    return sync_zhiboba_schedule(db=db, http_client=http_client, year=year)

@router.post("/schedule/zhiboba/playoffs/sync", summary="同步季后赛对阵赛程")
def zhiboba_playoffs_sync(
    year: int | None = Query(None, description="要同步的年份(YYYY)，若不传则按当前时间自动计算"), 
    db: Session = Depends(get_db)
) -> dict:
    """
    拉取直播吧季后赛（含总决赛）对阵数据，过滤掉待定场次，并落库到 `nba_zhiboba_yj_gamelist` 表中。
    """
    http_client = HttpClient()
    return sync_zhiboba_playoffs(db=db, http_client=http_client, year=year)


@router.post("/schedule/game-list/sync/by-date", summary="按指定日期同步赛程明细到 game_list", tags=["赛程明细"])
def game_list_sync_by_date(
    game_date: str = Query(..., description="指定比赛日期，格式 YYYY-MM-DD"),
    db: Session = Depends(get_db),
) -> dict:
    """
    从 `nba_zhiboba_yj_gamelist` 读取指定日期赛程，
    按 `home_id / guest_id -> nba_teams_name_data.zhiboba_team_id`
    关联补全 `home_team / visit_team`，并写入 `game_list`。
    """
    try:
        target_date = date.fromisoformat(game_date)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="game_date 格式必须为 YYYY-MM-DD") from exc
    http_client = HttpClient()
    return sync_game_list_by_date(db=db, http_client=http_client, game_date=target_date)


@router.post("/player-alias/sync", summary="同步比赛球员中文别名", tags=["球员别名"])
def player_alias_sync(
    saishi_id: str | None = Query(None, description="可选，比赛ID；不传则自动从 nba_zhiboba_yj_gamelist 全量读取"),
    db: Session = Depends(get_db),
) -> dict:
    """
    从 `nba_zhiboba_yj_gamelist` 读取 `game_date + saishi_id`，请求球员别名接口，
    解析 `player_id` 与 `player_name_cn`，并按 `player_id + alias_name`
    去重写入 `player_alias_name_info`。
    """
    http_client = HttpClient()
    return sync_player_aliases(db=db, http_client=http_client, saishi_id=saishi_id)

@router.post("/team/zhiboba/players/sync", summary="同步指定球队球员列表并自动补齐 player_code", tags=["球队球员"])
def zhiboba_team_players_sync(
    team_id: str = Query(..., description="直播吧球队的ID，例如老鹰队为 6916；接口会自动按球员 playerId 二次请求详情并写入 player_code"), 
    db: Session = Depends(get_db)
) -> dict:
    """
    根据给定的 `team_id` 拉取球队主页的全部球员信息，随后按每个球员的 `playerId`
    自动请求详情接口补充 `playerCode`，并将薪资、位置、球衣号码、`player_code`
    一并写入 `nba_players_name_data` 表。
    """
    http_client = HttpClient()
    return sync_zhiboba_team_players(db=db, http_client=http_client, team_id=team_id)


@router.post("/team/zhiboba/players/sync/all", summary="自动同步全部 NBA 球队球员并补齐 player_code", tags=["球队球员"])
def zhiboba_all_team_players_sync(
    db: Session = Depends(get_db)
) -> dict:
    """
    无需任何入参，自动从 `nba_teams_name_data` 读取 `type='NBA'` 的球队数据集，
    逐条取出 `zhiboba_team_id`，再循环调用球队球员抓取逻辑，
    并为每位球员补充详情接口中的 `playerCode` 后落库到 `nba_players_name_data`。
    """
    http_client = HttpClient()
    return sync_all_zhiboba_team_players(db=db, http_client=http_client)


@router.post("/team/players/sync/by-team-id", summary="按球队主表 team_id 同步球员并自动补齐 player_code", tags=["球队球员"])
def zhiboba_team_players_sync_by_master_team_id(
    team_id: str = Query(..., description="球队主表中的 team_id，例如湖人队的官方/全局 team_id；接口会自动补充 player_code"),
    db: Session = Depends(get_db),
) -> dict:
    """
    先从 `nba_teams_name_data` 按 `team_id` 查询对应的 `zhiboba_team_id`，
    再拉取直播吧球队主页的球员信息，并按每个球员的 `playerId`
    自动补齐详情接口中的 `playerCode`，统一落库到 `nba_players_name_data`。
    """
    http_client = HttpClient()
    try:
        return sync_zhiboba_team_players_by_master_team_id(db=db, http_client=http_client, team_id=team_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/team/players/bind/team-id/by-zhiboba-team-id", summary="按 zhiboba_team_id 绑定球员表 team_id", tags=["球队球员"])
def bind_players_team_id_by_zhiboba_team_id_api(
    zhiboba_team_id: str = Query(..., description="球队主表中的 zhiboba_team_id，例如 6916"),
    db: Session = Depends(get_db),
) -> dict:
    """
    按 `zhiboba_team_id` 在 `nba_teams_name_data` 中匹配球队信息，取出 `team_name` 与 `team_id`，
    然后在 `nba_players_name_data` 中按 `team_name` 批量更新球员记录的 `team_id`。
    """
    try:
        return bind_players_team_id_by_zhiboba_team_id(db=db, zhiboba_team_id=zhiboba_team_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


