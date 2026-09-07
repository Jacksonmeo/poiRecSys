"""健康检查路由：提供数据库连通性检查和基础健康探测。"""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.response import ApiResponse
from app.db.database import get_db

router = APIRouter(tags=["Health"])


@router.get("/api/health/database")
def database_health(
    db: Annotated[Session, Depends(get_db)],
) -> ApiResponse[dict]:
    """检查数据库连接是否正常。

    执行 SELECT 1 以验证 PostgreSQL 连接池可用。
    """
    db.execute(text("SELECT 1"))
    return ApiResponse(data={"status": "ok", "database": "postgresql"})
