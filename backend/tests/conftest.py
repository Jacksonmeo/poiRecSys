"""pytest 共享夹具。

测试策略：真实 PostgreSQL/PostGIS 集成测试。
- 测试库名：poi_recommendation_test（不存在时自动创建，并确保 postgis 扩展）
- 连接凭据：优先取 TEST_DATABASE_URL 环境变量；否则读取 backend/.env 的
  DATABASE_URL 并替换库名为测试库；再兜底本地开发默认值。
- 每个用例前 TRUNCATE 全部表，保证用例互不影响。
"""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlsplit

import psycopg
import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url

BACKEND_DIR = Path(__file__).resolve().parents[1]

TEST_DB_NAME = "poi_recommendation_test"


def _resolve_base_url() -> str:
    """解析可用的数据库 URL（不带测试库名即可，仅用于管理连接）。"""
    explicit = os.environ.get("TEST_DATABASE_URL")
    if explicit:
        return explicit

    # 读取 backend/.env 中的 DATABASE_URL（本地开发凭据，未入库）
    env_file = BACKEND_DIR / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("DATABASE_URL="):
                return line.split("=", 1)[1].strip()

    raise RuntimeError(
        "TEST_DATABASE_URL or DATABASE_URL in backend/.env is required for "
        "PostgreSQL/PostGIS integration tests"
    )


def _ensure_test_database() -> str:
    """确保测试数据库存在并启用 postgis，返回测试库 URL（SQLAlchemy 格式）。"""
    base_url = _resolve_base_url()
    url = make_url(base_url.replace("postgresql+psycopg://", "postgresql://", 1))
    admin_dsn = f"postgresql://{url.username}:{url.password}@{url.host}:{url.port or 5432}/postgres"
    test_dsn = f"postgresql://{url.username}:{url.password}@{url.host}:{url.port or 5432}/{TEST_DB_NAME}"

    with psycopg.connect(admin_dsn, autocommit=True, connect_timeout=5) as conn:
        exists = conn.execute(
            "SELECT 1 FROM pg_database WHERE datname = %s", (TEST_DB_NAME,)
        ).fetchone()
        if not exists:
            conn.execute(f'CREATE DATABASE "{TEST_DB_NAME}"')

    with psycopg.connect(test_dsn, autocommit=True, connect_timeout=5) as conn:
        conn.execute("CREATE EXTENSION IF NOT EXISTS postgis")

    return f"postgresql+psycopg://{url.username}:{url.password}@{url.host}:{url.port or 5432}/{TEST_DB_NAME}"


# ── 关键：在导入 app 之前把 DATABASE_URL 指向测试库 ───────────────────
os.environ["DATABASE_URL"] = _ensure_test_database()
os.environ.setdefault("AGENT_CONTEXT_BACKEND", "memory")

from fastapi.testclient import TestClient  # noqa: E402

from app.db.database import Base, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models.checkin import Checkin  # noqa: E402,F401
from app.models.poi import Poi  # noqa: E402,F401
from app.models.recommendation_result import RecommendationResult  # noqa: E402,F401
from app.models.session import UserSession  # noqa: E402,F401
from app.models.user import User  # noqa: E402,F401
from app.db.database import SessionLocal  # noqa: E402

client = TestClient(app)


@pytest.fixture(scope="session", autouse=True)
def _setup_database():
    """会话级：建表一次，会话结束后销毁。"""
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield
    engine.dispose()


@pytest.fixture(autouse=True)
def _clean_tables(_setup_database):
    """用例级：每个用例前清空全部表，避免数据串扰。"""
    with engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            conn.execute(text(f'TRUNCATE TABLE "{table.name}" RESTART IDENTITY CASCADE'))
    yield


@pytest.fixture
def seed_data():
    """构造一组最小的业务数据（用户/POI/签到/会话/推荐结果）。

    返回的 dict 含各实体的关键 ID，供用例断言使用。
    """

    def _seed() -> dict:
        db = SessionLocal()
        try:
            return _build_seed_payload(db)
        finally:
            db.close()

    return _seed


def _build_seed_payload(db) -> dict:
    """写入全部种子数据并提交，返回关键 ID 集合。"""
    users = _seed_users(db)
    pois = _seed_pois(db)
    _seed_session_and_checkins(db)
    _seed_recommendations(db)
    db.commit()
    return {
        "users": users,
        "pois": pois,
        "session_id": "sess_001",
        "target_poi_id": "poi_park",
        "model_name": "T10e2_CausalMemoryFusion",
    }


def _seed_users(db) -> list[str]:
    """写入两个用户并返回 user_id 列表。"""
    users = [User(user_id=f"user_{i}") for i in range(1, 3)]
    db.add_all(users)
    return ["user_1", "user_2"]


def _seed_pois(db) -> list[str]:
    """写入四个带空间几何的 POI 并返回 venue_id 列表。"""
    poi_specs = [
        ("poi_coffee", "Central Coffee", "Coffee Shop", 139.700, 35.680),
        ("poi_ramen", "Tokyo Ramen", "Ramen /  Noodle House", 139.710, 35.690),
        ("poi_park", None, "Park", 139.720, 35.670),
        ("poi_mall", "Tokyo Mall", "Shopping Mall", 139.730, 35.700),
    ]
    pois = []
    for venue_id, display_name, category, lng, lat in poi_specs:
        from geoalchemy2 import WKTElement

        pois.append(
            Poi(
                venue_id=venue_id,
                display_name=display_name,
                venue_category=category,
                latitude=lat,
                longitude=lng,
                geom=WKTElement(f"POINT({lng} {lat})", srid=4326),
            )
        )
    db.add_all(pois)
    return ["poi_coffee", "poi_ramen", "poi_park", "poi_mall"]


def _seed_session_and_checkins(db) -> None:
    """写入一个会话与三个签到（最后一个 park 作为推荐目标）。"""
    session = UserSession(
        session_id="sess_001",
        user_id="user_1",
        start_time="2026-01-01 10:00:00+00:00",
        end_time="2026-01-01 12:00:00+00:00",
        checkin_count=3,
        dataset="TKY",
    )
    db.add(session)

    checkins = [
        Checkin(
            user_id="user_1",
            venue_id="poi_coffee",
            timezone_offset=540,
            utc_timestamp="2026-01-01 10:00:00+00:00",
            session_id="sess_001",
            sequence_no=1,
        ),
        Checkin(
            user_id="user_1",
            venue_id="poi_ramen",
            timezone_offset=540,
            utc_timestamp="2026-01-01 11:00:00+00:00",
            session_id="sess_001",
            sequence_no=2,
        ),
        Checkin(
            user_id="user_1",
            venue_id="poi_park",
            timezone_offset=540,
            utc_timestamp="2026-01-01 12:00:00+00:00",
            session_id="sess_001",
            sequence_no=3,
        ),
    ]
    db.add_all(checkins)


def _seed_recommendations(db) -> None:
    """写入目标 poi_park 的三条推荐候选结果。"""
    candidates = [
        ("poi_coffee", 1, 0.95),
        ("poi_ramen", 2, 0.82),
        ("poi_mall", 3, 0.61),
    ]
    db.add_all(
        [
            RecommendationResult(
                session_id="sess_001",
                user_id="user_1",
                dataset="TKY",
                model_name="T10e2_CausalMemoryFusion",
                target_poi_id="poi_park",
                poi_id=venue_id,
                rank=rank,
                score=score,
            )
            for venue_id, rank, score in candidates
        ]
    )


@pytest.fixture
def seeded(seed_data):
    """执行一次 seed 并返回 ID 集合。"""
    return seed_data()
