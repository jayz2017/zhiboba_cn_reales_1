from fastapi import APIRouter

from app.api.v1.endpoints.health import router as health_router
from app.api.v1.endpoints.live_text import router as live_text_router
from app.api.v1.endpoints.schedule import router as schedule_router


api_v1_router = APIRouter()
api_v1_router.include_router(health_router, tags=["系统健康检查"])
api_v1_router.include_router(schedule_router, tags=["数据同步服务"])
api_v1_router.include_router(live_text_router, tags=["比赛直播文本"])
