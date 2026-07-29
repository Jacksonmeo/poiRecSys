"""数据库引擎与会话管理。

兼容 SQLAlchemy 2.x，提供声明式基类 Base 和 FastAPI 依赖注入 get_db。
"""

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import settings


class Base(DeclarativeBase):
    """SQLAlchemy 声明式基类，所有 ORM 模型均继承自它。"""

    pass


# 创建 SQLAlchemy 数据库引擎，pool_pre_ping=True 确保连接池中的连接在使用前经过有效性检测
engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
)

# 创建会话工厂，每次请求通过 get_db 依赖注入获取独立会话
# autoflush=False 避免隐式刷新，expire_on_commit=False 避免提交后属性过期
SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
)


def get_db() -> Generator[Session, None, None]:
    """FastAPI 依赖注入：为每个请求创建数据库会话，请求结束后自动关闭。

    用法：
        @router.get("/")
        def list_items(db: Annotated[Session, Depends(get_db)]):
            ...
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        # 无论请求成功或异常，确保数据库连接被归还连接池
        db.close()
