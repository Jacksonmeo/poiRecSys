"""FastAPI application entry point.
FastAPI 应用入口，负责创建应用实例、注册中间件、全局异常处理器和路由。
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import HTTPException, RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from app.agent.memory.runtime import close_agent_context_runtime
from app.api import (
    agent,
    analysis,
    health,
    poi,
    sessions,
    site_selection,
    users,
)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """应用退出时释放 LangGraph PostgreSQL 连接池和 Redis 客户端。"""
    yield
    close_agent_context_runtime()


# 创建 FastAPI 应用实例，配置 OpenAPI 文档元信息
app = FastAPI(
    title="POI Recommendation Visual Platform API",
    version="0.5.0",
    description="POI recommendation result visualization, trajectory analysis, PostGIS spatial analysis and Agent tool-calling API.",
    lifespan=lifespan,
)

# 配置 CORS 中间件，允许前端开发服务器跨域访问
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── 全局异常处理器：所有异常统一转换为 {code, message, data} 格式 ────────
# 各 Router 不再需要 try/except 包装，直接让异常向上传播到这里。


@app.exception_handler(SQLAlchemyError)
async def database_error_handler(request: Request, exc: SQLAlchemyError) -> JSONResponse:
    """数据库查询异常统一返回 500。"""
    return JSONResponse(
        status_code=500,
        content={"code": 500, "message": "数据库查询失败，请稍后重试。", "data": None},
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    """业务异常（404/422 等）按原状态码返回，message 携带详情。"""
    return JSONResponse(
        status_code=exc.status_code,
        content={"code": exc.status_code, "message": str(exc.detail), "data": None},
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """请求参数校验失败统一返回 422。"""
    return JSONResponse(
        status_code=422,
        content={"code": 422, "message": "请求参数校验失败。", "data": None},
    )


# 注册各业务模块的路由，使用 /api 前缀统一对外暴露
app.include_router(poi.router, prefix="/api/pois", tags=["POIs"])
app.include_router(health.router)
app.include_router(users.router, prefix="/api/users", tags=["Users"])
app.include_router(sessions.router, prefix="/api/sessions", tags=["Sessions"])
app.include_router(analysis.router, prefix="/api/analysis", tags=["Spatial Analysis"])
app.include_router(agent.router, prefix="/api/agent", tags=["Agent"])
app.include_router(
    site_selection.router,
    prefix="/api/site-selection",
    tags=["Site Selection"],
)


@app.get("/", tags=["Health"])
def health_check() -> dict[str, str]:
    """根路径健康检查：返回简单的运行状态确认信息。"""
    return {"message": "POI Recommendation Visual Platform API is running."}
