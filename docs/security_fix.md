# 安全修复记录：Mapbox Token 泄露

> 日期：2026-08-01
> 严重级别：🔴 高（密钥类敏感信息进入工作区/源码）

---

## 一、问题描述

`frontend/src/composables/useMap.ts` 中 Mapbox GL 访问 Token 以**明文硬编码**形式存在：

```ts
// 修复前（已删除）
const MAPBOX_TOKEN =
  import.meta.env.VITE_MAPBOX_TOKEN ||
  "pk.eyJ1IjoicHhramRxbm4iLCJhIjoiY21zNXJuZmR1MDhwaTJ4c2Q0bjF4cGtsNiJ9.xxx"
```

**影响分析：**

| 项目 | 状态 |
|---|---|
| Token 是否进入 git 历史 | ✅ 未进入（`git log --all -S "pk.eyJ1IjoicHhramRxbm4i"` 无命中；历史版本为占位符 `YOUR_MAPBOX_TOKEN`） |
| Token 是否可能被外部获取 | 仓库未公开推送的情况下风险低；但若推送公开仓库/面试演示分享，立即泄露 |
| 泄露后果 | 他人可盗用你的 Mapbox 配额，产生费用或服务被限流 |

---

## 二、修复措施

### 2.1 移除硬编码

- [useMap.ts](frontend/src/composables/useMap.ts)：删除 `|| "pk.eyJ..."` 兜底逻辑，仅保留环境变量读取；缺失时打印明确错误并跳过地图初始化：

```ts
// 修复后
const MAPBOX_TOKEN: string | undefined = import.meta.env.VITE_MAPBOX_TOKEN
// initMap 中：
if (!MAPBOX_TOKEN) {
  console.error("[useMap] 缺少 VITE_MAPBOX_TOKEN，请在 frontend/.env 中配置后重启 dev server。")
  return
}
```

### 2.2 环境变量接管

| 文件 | 作用 | 是否提交 |
|---|---|---|
| `frontend/.env` | 真实 Token（VITE_ 前缀由 Vite 自动注入） | ❌ 已 gitignore |
| `frontend/.env.example` | 占位模板 + 注释说明，含 VITE_API_BASE_URL 示例 | ✅ 可安全提交 |

### 2.3 .gitignore 强化

```
.env
.env.*
!.env.example     # 新增：模板文件放行
```

（同时移除 `docs/` 整目录忽略，使审计/变更文档可入库，见 changelog。）

### 2.4 全仓库敏感配置扫描结果

对全部被跟踪文件（排除 node_modules / lock 文件）扫描 `sk-*`、`api_key`、`secret`、`password`、`token` 等模式：

| 位置 | 内容 | 处置 |
|---|---|---|
| `frontend/src/composables/useMap.ts` | Mapbox Token | ✅ 本次修复 |
| `backend/README.md:19` | 文档示例 `postgres:password@...` | ⚠️ 仅文档占位示例，非真实凭据，无需处理 |
| `backend/app/core/config.py` | 默认值 `postgres:postgres@localhost` | ⚠️ 本地开发默认值，部署必须 env 覆盖（代码注释已声明） |
| `backend/.env`（本地） | 真实 DATABASE_URL | ✅ 已被 .gitignore 忽略，未入库 |
| `frontend/.env`（本次新建） | 真实 Mapbox Token | ✅ 已被 .gitignore 忽略 |

**结论：除本次修复的 Token 外，无其他敏感配置入库。**

---

## 三、遗留风险与建议

1. **建议吊销并轮换 Token**：虽然 Token 未进入 git 历史，但曾以明文存在于工作区。稳妥做法：登录 mapbox.com → Account → Tokens → Revoke 旧 token → 创建新 token 填入 `frontend/.env`。（Mapbox 公共 token 为 `pk.` 开头，被盗用主要是配额损失。）
2. **防止再次泄露**：已在 .gitignore 兜底；提交前建议执行 `git diff --cached` 检查。
3. 若未来推送公开仓库，可考虑 Mapbox 域名白名单（限制仅特定域名可调用）。

---

## 四、验证

- `grep -rn "pk.eyJ" frontend/src/` → 无命中 ✅
- `git check-ignore frontend/.env` → 命中（已忽略）✅
- `git log --all -S "pk.eyJ1IjoicHhramRxbm4i"` → 无提交（未入历史）✅
