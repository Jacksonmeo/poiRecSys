# POI 模块数据库迁移文档

> 迁移日期：2026-07-11
>
> 目标：将 `GET /api/pois` 从 Mock CSV 改为 PostgreSQL 查询

---

## 一、修改文件清单

| 文件 | 操作 | 作用 |
|------|------|------|
| `backend/app/core/__init__.py` | 新建 | 核心配置包 |
| `backend/app/core/config.py` | 新建 | 从 `.env` 加载 Settings |
| `backend/app/db/__init__.py` | 新建 | 数据库包 |
| `backend/app/db/database.py` | 新建 | Engine / SessionLocal / Base / get_db |
| `backend/app/models/__init__.py` | 新建 | ORM 模型包 |
| `backend/app/models/poi.py` | 新建 | Poi ORM（映射 `pois` 表） |
| `backend/app/schemas/poi.py` | 新建 | PoiResponse（含兼容字段） |
| `backend/app/services/poi_service.py` | 修改 | 新增 DB 查询函数，保留 CSV 回退 |
| `backend/app/api/poi.py` | 修改 | 使用 get_db 依赖注入和 response_model |
| `backend/app/api/health.py` | 新建 | `/api/health/database` 数据库健康检查 |
| `backend/app/main.py` | 修改 | 注册 health 路由器 |
| `backend/requirements.txt` | 修改 | 新增 sqlalchemy, psycopg, geoalchemy2, pydantic-settings |
| `backend/.env` | 新建 | DATABASE_URL 配置 |

---

## 二、原 Mock CSV 查询链路

```text
Vue3 Page
  → Axios (request.get("/pois"))
    → FastAPI Router (api/poi.py)
      → Service (poi_service.py → get_pois)
        → pandas.read_csv("app/data/poi.csv")
          → return list[dict]
            → JSON: {"data": [...]}
```

CSV 数据列：`poi_id, name, category, lng, lat, address`

---

## 三、修改后 PostgreSQL 查询链路

```text
Vue3 Page
  → Axios (request.get("/pois"))
    → FastAPI Router (api/poi.py, Depends(get_db))
      → Service (poi_service.py → get_pois)
        → SQLAlchemy (select(Poi))
          → psycopg → PostgreSQL pois 表
            → return list[Poi] ORM 实例
              → Pydantic PoiResponse.model_validate()
                → JSON: {"data": [{...}]}
```

查询列：`id, venue_id, venue_category_id, venue_category, latitude, longitude`
（`geom` 由 ORM 加载但不序列化）

---

## 四、数据库连接配置

### .env 文件

```env
DATABASE_URL=postgresql+psycopg://postgres:password@localhost:5432/poi_recommendation
```

### 配置类

```python
# app/core/config.py
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    database_url: str
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")
```

### 数据库架构

- **引擎**：`create_engine(settings.database_url, pool_pre_ping=True)`
- **会话工厂**：`sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)`
- **依赖注入**：`def get_db() -> Generator[Session, None, None]`

---

## 五、如何启动 FastAPI

```bash
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

访问 Swagger：http://127.0.0.1:8000/docs

---

## 六、通过 Swagger 测试

### 6.1 测试 POI 列表

1. 打开 http://127.0.0.1:8000/docs
2. 展开 `GET /api/pois`
3. 点击 "Try it out"
4. 输入 `skip=0`, `limit=20`
5. 点击 "Execute"
6. 预期：返回 20 条 POI，包含 `id`, `venue_id`, `venue_category`, `latitude`, `longitude`

### 6.2 测试类别筛选

1. 先调用 `GET /api/pois/categories` 获取类别列表
2. 复制一个类别名称（如 `Coffee Shop`）
3. 调用 `GET /api/pois?category=Coffee Shop&limit=10`
4. 预期：只返回 Coffee Shop 类别的 POI

### 6.3 测试单个 POI

1. 从第一步结果中复制一个 `venue_id`
2. 调用 `GET /api/pois/{venue_id}`
3. 预期：返回该 POI 的详情；用不存在的 ID 调用则返回 404

### 6.4 测试数据库健康检查

```bash
curl http://127.0.0.1:8000/api/health/database
# 预期：{"status":"ok","database":"postgresql"}
```

---

## 七、确认接口读取的是数据库

1. 在 PostgreSQL 中临时修改一个 POI：

```sql
UPDATE pois SET venue_category = 'Database Test Category' WHERE id = 1;
```

2. 调用 `GET /api/pois?limit=1`，确认返回 `venue_category: "Database Test Category"`

3. 恢复原值：

```sql
UPDATE pois SET venue_category = 'Cosmetics Shop' WHERE id = 1;
```

4. 如果返回的是修改后的值，说明数据库链路已生效（CSV 中的旧值不会变化）

---

## 八、常见报错及解决

| 错误 | 原因 | 解决 |
|------|------|------|
| `ImportError: cannot import name 'get_poi_by_id'` | 旧 recommend_service 依赖此函数 | 已在 poi_service.py 中保留 CSV 回退版本 |
| `OperationalError: could not connect to server` | PostgreSQL 未启动 | 启动 PostgreSQL 服务 |
| `relation "pois" does not exist` | 表不存在 | 确认数据库中已创建 `pois` 表并导入数据 |
| `no pg_hba.conf entry` | PostgreSQL 拒绝连接 | 修改 `pg_hba.conf` 允许本地连接 |
| `can't adapt type 'WKBElement'` | 尝试序列化 geom 字段 | PoiResponse 不包含 geom，只有经纬度 |
| `422 Validation Error` (limit=0) | limit 必须 ≥ 1 | 使用 `limit=1` 或更大的值 |
| `pool_pre_ping` 性能问题 | 每次从池中取连接执行 ping | 这是有意配置，确保连接有效 |

---

## 九、POI 响应字段说明

```json
{
  "id": 1,
  "venue_id": "4f0fd5a8e4b03856eeb6c8cb",
  "venue_category_id": "4bf58dd8d48988d10c951735",
  "venue_category": "Cosmetics Shop",
  "latitude": 35.70510109,
  "longitude": 139.61959,

  "_以下为前端兼容字段_": "",
  "poi_id": "4f0fd5a8e4b03856eeb6c8cb",
  "name": "4f0fd5a8e4b03856eeb6c8cb",
  "category": "Cosmetics Shop",
  "lng": 139.61959,
  "lat": 35.70510109,
  "address": ""
}
```

**关键说明：**
- 数据库原生字段：`id`, `venue_id`, `venue_category_id`, `venue_category`, `latitude`, `longitude`
- 前端兼容字段（computed）：`poi_id`, `name`, `category`, `lng`, `lat`, `address`
- `name` 当前返回 `venue_id`（DB 无独立 name 列），地图标注会显示 Foursquare ID
- `address` 始终为空字符串（DB 无 address 列）

---

## 十、代码分层架构

```text
app/
├── main.py              # FastAPI 入口，注册路由
├── core/
│   └── config.py        # Settings（.env → pydantic-settings）
├── db/
│   └── database.py      # Engine, SessionLocal, Base, get_db
├── models/
│   └── poi.py           # Poi ORM（映射 pois 表）
├── schemas/
│   └── poi.py           # PoiResponse（含 computed_field 兼容）
├── services/
│   └── poi_service.py   # get_pois/get_categories/get_poi_by_venue_id (DB)
│                        # get_poi_by_id (CSV 回退，供推荐模块)
├── api/
│   ├── poi.py           # POI Router（Depends(get_db)）
│   └── health.py        # 健康检查
└── data/
    └── poi.csv          # 保留，供其他未迁移模块使用
```

---

## 十一、下一步：地图视窗范围查询规划

当前实现的是全量分页查询 + 类别筛选。下一步实现空间范围查询时：

1. **新增 Query 参数**：`min_lng`, `min_lat`, `max_lng`, `max_lat`
2. **使用 PostGIS 函数**：`ST_MakeEnvelope` + `ST_Intersects`
3. **SQLAlchemy 写法**：

```python
from geoalchemy2.functions import ST_MakeEnvelope, ST_Intersects

envelope = ST_MakeEnvelope(min_lng, min_lat, max_lng, max_lat, 4326)
stmt = stmt.where(ST_Intersects(Poi.geom, envelope))
```

4. 前端 Cesium 地图组件需要：
   - 监听地图视窗变化事件
   - 获取当前视口 BoundingBox
   - 发送带空间范围参数的请求
   - 增量更新 POI 图层

---

## 十二、变更验证清单

- [x] `GET /api/pois` 返回 PostgreSQL 数据
- [x] POI 列表包含 `id, venue_id, venue_category, latitude, longitude`
- [x] 前端兼容字段 `lng, lat, name, category` 自动生成
- [x] 类别筛选 `?category=Coffee Shop` 正常工作
- [x] 单 POI 查询 `/api/pois/{venue_id}` 正常
- [x] 不存在的 POI 返回 404
- [x] 无效参数（limit=0）返回 422
- [x] `GET /api/pois/categories` 返回数据库类别
- [x] `/api/health/database` 返回数据库健康状态
- [x] Swagger 文档完整显示所有接口
- [x] 其他模块（trajectory, recommend, metrics）仍正常运行
- [x] CSV 文件和数据目录未被删除
- [x] 数据库密码不在代码中硬编码
- [x] `geom` 字段不直接返回给前端
