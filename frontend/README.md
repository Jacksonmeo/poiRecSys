<!-- 前端说明：记录 Vue 可视化应用的启动方式和后端接口地址。 -->
# Frontend

Vue 3 + TypeScript + Vite UI for POI recommendation result visualization.

## Start

<!-- 启动步骤：进入 frontend 目录后安装依赖并启动 Vite。 -->

```bash
cd frontend
npm install
npm run dev
```

Vite serves the app at `http://localhost:5173` by default. The frontend expects the FastAPI service on `http://127.0.0.1:8000/api`; override it with `VITE_API_BASE_URL` when needed.
