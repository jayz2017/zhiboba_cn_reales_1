from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_v1_router
from app.core.database import dispose_engine


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    dispose_engine()


def create_app() -> FastAPI:
    application = FastAPI(
        title="NBA 数据同步服务 API",
        description="用于拉取并解析直播吧(zhibo8)NBA赛程、季后赛对阵、球队球员等数据的后台服务 API",
        version="1.0.0",
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    application.include_router(api_v1_router, prefix="/api/v1")
    return application


app = create_app()
