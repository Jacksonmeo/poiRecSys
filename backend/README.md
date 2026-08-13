# Backend

FastAPI 后端，服务于 Agentic GIS 空间决策平台（GeoAgent）。

## 模块

- **Agent 编排**（`app/agent/`）：LangGraph StateGraph（`graph/`）+ LLM 函数调用
  路由（`router_llm.py`，失败降级规则路由）+ 工具注册表（`registry.py`）
- **GIS 数据层**（`app/models/` `app/repositories/` `app/services/`）：POI / 签到 /
  会话 / 推荐结果的 PostgreSQL + PostGIS 查询（SQL 只存在于 Repository 层）
- **选址分析**（`app/site_selection/`）：多候选区指标与区域流向分析领域
- **LLM 客户端**（`app/llm/`）：OpenAI 兼容 + Mock Provider（未配置时自动降级）

## 前置条件

- Python 3.11+
- PostgreSQL + PostGIS（`pois` 表含 `geom` 与 GIST 索引；迁移脚本见 `migrations/`）

## 配置

复制并编辑 `.env`（参考 `.env.example`）：

```env
DATABASE_URL=postgresql+psycopg://user:pass@host:5432/dbname
LLM_PROVIDER=mock          # mock | openai_compat
LLM_BASE_URL=
LLM_API_KEY=
LLM_MODEL=
```

## 启动

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

接口文档：`http://127.0.0.1:8000/docs`

## 测试

```bash
pip install -r requirements-dev.txt
python -m pytest
```

测试自动创建 `poi_recommendation_test` 库（连接凭据取 `TEST_DATABASE_URL` 或
`.env` 的 `DATABASE_URL`）。
