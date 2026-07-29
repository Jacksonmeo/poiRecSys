"""FastAPI application entry point.
FastAPI 应用入口，负责创建应用实例、注册中间件和路由。
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import health, metrics, poi, recommend, sessions, users

# 创建 FastAPI 应用实例，配置 OpenAPI 文档元信息
app = FastAPI(
    title="POI Recommendation Visual Platform API",
    version="0.2.0",
    description="POI recommendation result visualization and trajectory analysis API.",
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

# 注册各业务模块的路由，使用 /api 前缀统一对外暴露
app.include_router(poi.router, prefix="/api/pois", tags=["POIs"])
app.include_router(health.router)
app.include_router(users.router, prefix="/api/users", tags=["Users"])
app.include_router(sessions.router, prefix="/api/sessions", tags=["Sessions"])
app.include_router(recommend.router, prefix="/api/recommendations", tags=["Recommendations"])
app.include_router(metrics.router, prefix="/api/metrics", tags=["Metrics"])


@app.get("/", tags=["Health"])
def health_check() -> dict[str, str]:
    """根路径健康检查：返回简单的运行状态确认信息。"""
    return {"message": "POI Recommendation Visual Platform API is running."}
