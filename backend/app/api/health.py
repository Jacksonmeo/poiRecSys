"""健康检查路由：提供数据库连通性检查和基础健康探测。"""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.database import get_db

router = APIRouter(tags=["Health"])


@router.get("/api/health/database")
def database_health(
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    """检查数据库连接是否正常。

    执行 SELECT 1 以验证 PostgreSQL 连接池可用。
    用于 Kubernetes 就绪探针或运维监控，确认服务与数据库之间的连通性。
    """
    db.execute(text("SELECT 1"))
    return {
        "status": "ok",
        "database": "postgresql",
    }
