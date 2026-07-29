# POI display_name 字段贯通文档

> 日期：2026-07-11
>
> 目标：将数据库 `pois.display_name` 字段完整贯通到前端 Vue3/Cesium 展示

---

## 一、完整数据链路

```text
PostgreSQL pois.display_name (VARCHAR 255)
  ↓ SQLAlchemy ORM (Poi.display_name)
  ↓ Pydantic Schema (PoiResponse.display_name + name computed_field)
  ↓ FastAPI GET /api/pois (JSON response)
  ↓ Axios (request.ts 拦截器解包)
  ↓ TypeScript (Poi.display_name)
  ↓ getPoiDisplayName() 工具函数
  ↓ Vue3 / CesiumMap 组件
```

---

## 二、修改文件清单

### 后端（3 个文件）

| 文件 | 操作 | 说明 |
|------|------|------|
| `backend/app/models/poi.py` | 修改 | 新增 `display_name` ORM 字段 |
| `backend/app/schemas/poi.py` | 修改 | 新增 `display_name` Pydantic 字段；优化 `name` computed_field 降级逻辑 |
| `backend/AGENT_CHANGELOG.md` | 修改 | 记录本轮变更 |

### 前端（5 个文件）

| 文件 | 操作 | 说明 |
|------|------|------|
| `frontend/src/types/index.ts` | 修改 | Poi 接口新增 DB 原生字段 |
| `frontend/src/utils/poi.ts` | 新建 | 统一展示名称工具函数 |
| `frontend/src/components/CesiumMap.vue` | 修改 | label/description 使用工具函数 |
| `frontend/src/views/RecommendationView.vue` | 修改 | 表格/详情使用工具函数 |
| `frontend/AGENT_CHANGELOG.md` | 修改 | 记录本轮变更 |

### 文档（1 个文件）

| 文件 | 操作 | 说明 |
|------|------|------|
| `docs/poi-display-name-integration.md` | 新建 | 本文档 |

---

## 三、后端字段贯通说明

### 3.1 ORM 模型

```python
# app/models/poi.py
display_name: Mapped[str | None] = mapped_column(
    String(255),
    nullable=True,
)
```

- 字段名与数据库列名一致：`display_name`
- 可为空（部分 POI 尚未填充 display_name）

### 3.2 Pydantic Schema

```python
# app/schemas/poi.py
class PoiResponse(BaseModel):
    display_name: str | None = None  # 数据库原生字段

    @computed_field
    @property
    def name(self) -> str:
        """优先级：display_name > category·shortId > shortId"""
        if self.display_name:
            return self.display_name
        if self.venue_category:
            return f"{self.venue_category} · {self.venue_id[-6:]}"
        return self.venue_id[-6:]
```

- `display_name`：直接来自数据库
- `name`：计算字段，优先使用 display_name，为空时智能兜底

### 3.3 API 响应示例

```json
{
  "data": [
    {
      "id": 1,
      "venue_id": "4f0fd5a8e4b03856eeb6c8cb",
      "display_name": "Coffee Shop · b6c8cb",
      "venue_category_id": "4bf58dd8d48988d10c951735",
      "venue_category": "Cosmetics Shop",
      "latitude": 35.70510109,
      "longitude": 139.61959,
      "poi_id": "4f0fd5a8e4b03856eeb6c8cb",
      "name": "Coffee Shop · b6c8cb",
      "category": "Cosmetics Shop",
      "lng": 139.61959,
      "lat": 35.70510109,
      "address": ""
    }
  ]
}
```

---

## 四、前端类型修改说明

### 4.1 Poi 接口（types/index.ts）

```ts
export interface Poi {
  // 数据库原生字段（新增）
  id: number
  venue_id: string
  display_name?: string | null
  venue_category_id?: string | null
  venue_category?: string | null
  latitude: number
  longitude: number
  // 后端兼容字段（Pydantic computed_field）
  poi_id: string
  name: string
  category: string
  lng: number
  lat: number
  address: string
}
```

- 新增字段均为可选，保证旧代码兼容
- `lng`/`lat`/`name`/`category` 等兼容字段仍然存在

### 4.2 工具函数（utils/poi.ts）

```ts
export interface PoiLike {
  venue_id?: string
  display_name?: string | null
  venue_category?: string | null
  name?: string
  poi_id?: string
  category?: string
}

export function getPoiDisplayName(poi: PoiLike): string
export function getPoiShortId(venueId?: string, length?: number): string
```

- `PoiLike` 同时兼容新 DB POI 和旧 CSV POI
- `getPoiDisplayName()` 6 级优先级：
  1. `display_name`（数据库填充）
  2. `name`（CSV 旧字段）
  3. `{category} · {shortId}`（兜底组合）
  4. 仅短 ID
  5. 仅类别
  6. `'POI'`（最终兜底）

---

## 五、地图展示修改说明

### 5.1 CesiumMap.vue

| 位置 | 修改前 | 修改后 |
|------|--------|--------|
| POI 标签文字 | `poi.name \|\| ""` | `getPoiDisplayName(poi)` |
| POI 描述 HTML | `<b>${poi.name}</b>` | `<b>${displayName}</b><br/>${category}<br/><small>${venue_id}</small>` |
| 标签可见性 | 始终显示 | POI 地图：隐藏（`show: !!poi.rank`）；推荐候选：显示排名 |
| MapPoint 接口 | lng, lat, name, category, rank, score | + display_name, venue_id, venue_category, poi_id |

### 5.2 标签显示策略

- **POI 地图页**（PoiMap.vue）：`addPoiLayer` 传入的 POI 无 `rank` → 标签 `show: false`
- **推荐详情页**（RecommendationView.vue）：候选 POI 有 `rank` → 标签 `show: true`，显示排名
- **点击时**：Cesium infoBox 显示名称、类别和完整 `venue_id`

---

## 六、表格和详情修改说明

### 6.1 RecommendationView.vue

| 位置 | 修改前 | 修改后 |
|------|--------|--------|
| 候选表格 POI 列 | `prop="name"` | `getPoiDisplayName(row)` |
| 真实目标文本 | `detail.target_poi.name` | `getPoiDisplayName(detail.target_poi)` |

### 6.2 PoiMap.vue

无需修改 — 该页面仅负责加载 POI 列表并传递给 `addPoiLayer`，不自行渲染名称。

---

## 七、Swagger 测试结果

### 7.1 测试命令

```bash
curl -s "http://127.0.0.1:8000/api/pois?limit=2" | python -m json.tool
```

### 7.2 验证项

| 检查项 | 结果 |
|--------|------|
| `display_name` 字段存在 | ✅ |
| `display_name` 值为非空字符串 | ✅ |
| `name` 计算字段等于 `display_name`（当 display_name 非空时） | ✅ |
| `display_name` 为空时 `name` 使用 fallback | ✅ |
| 原有字段（`venue_id`, `latitude`, `longitude` 等）不受影响 | ✅ |
| Swagger 文档（`/docs`）可正常访问 | ✅ |

---

## 八、前端联调验证步骤

1. **启动后端**：
   ```bash
   cd backend && uvicorn app.main:app --reload --port 8000
   ```

2. **启动前端**：
   ```bash
   cd frontend && npm run dev
   ```

3. **验证 POI 地图页**（http://localhost:5173/pois）：
   - POI 点位不再显示永久标签
   - 点击 POI 时 infoBox 显示名称、类别和完整 venue_id
   - 类别筛选下拉框正常工作

4. **验证推荐结果页**（http://localhost:5173/recommendations）：
   - 候选 POI 显示排名标签
   - 表格中的 POI 列显示 display_name
   - 真实目标显示 display_name

5. **数据库验证**：
   ```sql
   UPDATE pois SET display_name = 'Test Display Name' WHERE id = 1;
   ```
   刷新前端 → `display_name` 变化 → 恢复原值

---

## 九、是否仍存在使用 venue_id 作为名称的代码

| 位置 | 状态 |
|------|------|
| CesiumMap.vue — POI 标签 text | ✅ 已改用 `getPoiDisplayName` |
| CesiumMap.vue — POI 描述 HTML | ✅ 完整 venue_id 仅以 `<small>` 参考形式展示 |
| RecommendationView.vue — 表格 POI 列 | ✅ 已改用 `getPoiDisplayName` |
| RecommendationView.vue — 真实目标 | ✅ 已改用 `getPoiDisplayName` |
| RecommendationView.vue — addPoiLayer 目标 | ⚠️ 手动拼接 `真实目标: ${name}` — 保留供推荐页面明确标识 |
| Pydantic Schema — computed_field `name` | ✅ 自动使用 display_name 或 fallback |
| CSV 回退函数 `get_poi_by_id` | ⚠️ 返回旧 CSV 格式（poi_id/name/category）— 待后续迁移 |

---

## 十、display_name 填充建议

当前数据库 `display_name` 列已存在但可能部分为空。建议通过以下方式填充：

1. **基于 venue_category + venue_id 生成**（当前 API fallback 的逻辑）：
   ```sql
   UPDATE pois
   SET display_name = venue_category || ' · ' || RIGHT(venue_id, 6)
   WHERE display_name IS NULL OR display_name = '';
   ```

2. **从原始数据源导入真实名称**：如果原始 Foursquare 数据包含 `name` 字段，导入到 `display_name` 列。

3. **填充后无需修改任何代码**：API 的 `name` computed_field 会自动返回正确的 display_name。

---

## 十一、下一步建议

1. **数据库填充**：为 `display_name` 列批量填充真实 POI 名称
2. **移除 CSV 回退**：迁移 recommend 和 trajectory 模块到数据库后，移除 `get_poi_by_id` 和 CSV 依赖
3. **前端类型简化**：所有模块迁移后，移除 `Poi` 接口中的兼容字段（`poi_id`, `name`, `category`, `lng`, `lat`, `address`），统一使用 DB 原生字段
4. **地图 hover 提示**：后续可增加 Cesium `ScreenSpaceEventHandler` 实现鼠标悬停时显示 tooltip
5. **地图视窗查询**：使用 `ST_MakeEnvelope` + `ST_Intersects` 实现按地图视口范围增量加载 POI
