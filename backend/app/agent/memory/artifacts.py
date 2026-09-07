"""工具完整结果的存储边界；单元测试可注入内存实现。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from uuid import uuid4

from fastapi.encoders import jsonable_encoder
from sqlalchemy import select
from sqlalchemy.orm import Session


class ArtifactRepository(ABC):
    """完整工具结果仓储接口。"""

    @abstractmethod
    def save(
        self,
        thread_id: str,
        user_id_hash: str | None,
        tool_name: str,
        payload: dict,
    ) -> str:
        """保存结果并返回稳定 artifact_id。"""

    @abstractmethod
    def get(self, artifact_id: str, thread_id: str) -> dict | None:
        """仅在所属 thread 匹配时返回完整结果。"""


class SqlAlchemyArtifactRepository(ArtifactRepository):
    """使用当前请求的 SQLAlchemy 会话保存 PostgreSQL artifact。"""

    def __init__(self, db: Session) -> None:
        self._db = db

    def save(
        self,
        thread_id: str,
        user_id_hash: str | None,
        tool_name: str,
        payload: dict,
    ) -> str:
        from app.models.agent_artifact import AgentToolArtifact

        artifact_id = f"artifact_{uuid4().hex}"
        try:
            self._db.add(
                AgentToolArtifact(
                    artifact_id=artifact_id,
                    thread_id=thread_id,
                    user_id_hash=user_id_hash,
                    tool_name=tool_name,
                    payload=jsonable_encoder(payload),
                )
            )
            self._db.commit()
        except Exception:
            self._db.rollback()
            raise
        return artifact_id

    def get(self, artifact_id: str, thread_id: str) -> dict | None:
        from app.models.agent_artifact import AgentToolArtifact

        statement = select(AgentToolArtifact.payload).where(
            AgentToolArtifact.artifact_id == artifact_id,
            AgentToolArtifact.thread_id == thread_id,
        )
        return self._db.scalar(statement)


class InMemoryArtifactRepository(ArtifactRepository):
    """不依赖数据库的测试实现。"""

    def __init__(self) -> None:
        self._items: dict[tuple[str, str], dict] = {}

    def save(
        self,
        thread_id: str,
        user_id_hash: str | None,
        tool_name: str,
        payload: dict,
    ) -> str:
        artifact_id = f"artifact_{uuid4().hex}"
        self._items[(thread_id, artifact_id)] = jsonable_encoder(payload)
        return artifact_id

    def get(self, artifact_id: str, thread_id: str) -> dict | None:
        payload = self._items.get((thread_id, artifact_id))
        return dict(payload) if payload is not None else None


def sqlalchemy_artifact_repository(db: Session) -> ArtifactRepository:
    """默认仓储工厂，保持 Runner 与具体 ORM 解耦。"""
    return SqlAlchemyArtifactRepository(db)
