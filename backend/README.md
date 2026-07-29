# Backend

FastAPI API for the POI recommendation visual analysis platform.

- **POI 模块**：已迁移至 PostgreSQL/PostGIS（2026-07-11）
- **其他模块**（trajectory / recommend / metrics）：仍使用 Mock CSV/JSON

## Prerequisites

- Python 3.11+
- PostgreSQL + PostGIS（POI 模块需要）
- 数据库 `pois` 表已创建并导入数据

## Configuration

复制并编辑 `.env` 文件设置数据库连接：

```env
DATABASE_URL=postgresql+psycopg://postgres:password@localhost:5432/poi_recommendation
```

## Start

```bash
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

Open `http://127.0.0.1:8000/docs` to inspect and test the API.

## Data Sources

| 模块 | 数据源 | 状态 |
|------|--------|------|
| POI | PostgreSQL `pois` 表 | ✅ 已迁移 |
| Trajectory | `app/data/trajectory.csv` | Mock |
| Recommend | PostgreSQL `recommendation_results` | Offline T10e-2 inference |
| Metrics | `app/data/metrics.json` | Mock |

## Migration Docs

详见 [docs/poi_database_migration.md](../docs/poi_database_migration.md)
