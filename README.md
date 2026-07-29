<!-- 项目总说明：描述前后端职责、启动方式和主要接口，方便后续接手。 -->
# POI Recommendation Visual Platform

基于 Vue 3 + FastAPI 的 Next POI 推荐结果可视化分析平台骨架。项目通过 CSV / JSON mock 数据打通 POI、用户轨迹、推荐结果和模型指标的前后端联调。

## Project Structure

<!-- 目录结构说明：backend 提供接口，frontend 提供可视化页面。 -->

```text
.
├── backend/             # FastAPI mock API
│   └── app/data/        # CSV / JSON mock data
└── frontend/            # Vue 3 + Vite application
```

## Start Backend

<!-- 后端启动命令：安装依赖后使用 Uvicorn 启动 FastAPI 应用。 -->

```bash
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

API documentation is available at `http://127.0.0.1:8000/docs`.

## Start Frontend

<!-- 前端启动命令：安装依赖后启动 Vite 开发服务器。 -->

```bash
cd frontend
npm install
npm run dev
```

Open the local Vite URL, normally `http://localhost:5173`.

## API Routes

<!-- 接口清单：前端 api 目录中的封装与下面路径一一对应。 -->

- `GET /api/pois`
- `GET /api/pois/categories`
- `GET /api/pois/{poi_id}`
- `GET /api/trajectories/users`
- `GET /api/trajectories/users/{user_id}`
- `GET /api/trajectories/users/{user_id}/sessions/{session_id}`
- `GET /api/recommendations`
- `GET /api/recommendations/{user_id}`
- `GET /api/recommendations/{user_id}/{session_id}`
- `GET /api/metrics/models`
- `GET /api/metrics/ablation`
- `GET /api/metrics/seen-unseen`
