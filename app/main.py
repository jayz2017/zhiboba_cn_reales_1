import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1.router import api_v1_router
from app.core.database import dispose_engine

logger = logging.getLogger(__name__)


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
    @application.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        logger.error("unhandled_exception", extra={
            "path": str(request.url.path),
            "method": request.method,
        }, exc_info=True)
        return JSONResponse(
            status_code=500,
            content={
                "error": "internal_server_error",
                "detail": "服务器内部错误，请稍后重试",
                "path": str(request.url.path),
            },
        )

    @application.exception_handler(ValueError)
    async def value_error_handler(request: Request, exc: ValueError):
        logger.warning("value_error", extra={
            "path": str(request.url.path),
            "detail": str(exc),
        })
        return JSONResponse(
            status_code=400,
            content={
                "error": "bad_request",
                "detail": str(exc),
                "path": str(request.url.path),
            },
        )

    application.include_router(api_v1_router, prefix="/api/v1")
    return application


app = create_app()

if __name__ == "__main__":
    import uvicorn
    from app.core.config import settings
    uvicorn.run("app.main:app", host="0.0.0.0", port=settings.SERVER_PORT, reload=True)
