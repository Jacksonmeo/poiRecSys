# Frontend

Vue 3 + TypeScript + Vite 前端，服务于 Agentic GIS 空间决策平台（GeoAgent）。

## 页面

- `/workspace`：空间决策工作台（产品主页面）— Agent 自然语言对话 + Mapbox 地图渲染 +
  工具执行时间线 + 结构化产物（选址 Artifact）
- `/explore/poi`：POI 探索（类别 / 空间分布）
- `/explore/mobility`：移动轨迹探索（签到序列）
- `/spatial`：空间分析（格网密度热力）

## 启动

```bash
npm install
npm run dev
```

Vite 默认在 `http://localhost:5173` 提供服务；后端地址默认
`http://127.0.0.1:8000/api`，可通过 `VITE_API_BASE_URL` 覆盖。
地图渲染需要 Mapbox Token：复制 `.env.example` 为 `.env` 并填入
`VITE_MAPBOX_TOKEN`。

## 检查

```bash
npm run lint    # ESLint
npm run build   # vue-tsc 类型检查 + Vite 构建
npm run test    # Vitest 单元测试
```
