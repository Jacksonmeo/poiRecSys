# GeoAgent 零售选址 MVP — Sprint 0 总结

## 交付边界

本轮冻结东京咖啡店选址 MVP 的数据契约，完成安全整改和数据完整性核验。项目口径为：基于历史开放空间数据和签到行为，对东京候选分析区进行相对比较。没有实现指标查询、归一化计算、评分、`SiteSelectionRepository`、`SiteSelectionService` 或 `SiteSelectionTool`；没有修改 Agent 响应协议或前端产品页面。

## 新增文件

| 文件 | 用途 |
|---|---|
| `backend/app/site_selection/__init__.py` | 选址领域版本化配置包。 |
| `backend/app/site_selection/config/tokyo_coffee_v1.json` | 已提交的东京咖啡 v1 数据契约及四个生成式 GeoJSON Polygon。 |
| `backend/app/schemas/site_selection_config.py` | Pydantic 严格 Schema 与跨字段校验。 |
| `backend/app/services/site_selection_config_service.py` | 只读取、版本检查和校验配置；未知版本不 fallback。 |
| `backend/scripts/generate_site_selection_config.py` | 使用统一规则可重复生成四个 1 km Polygon。 |
| `backend/scripts/audit_site_selection_data.py` | PostgreSQL/PostGIS 单事务只读完整性核验，输出 JSON 和 Markdown。 |
| `backend/tests/test_site_selection_config.py` | 配置加载、错误分支、候选区和禁止措辞测试。 |
| `backend/.env.example` | 不含连接凭据或 API Key 的后端环境变量模板。 |
| `docs/retail_site_selection_sprint0/data_integrity_report.json` | 当前数据库核验的机器可读结果。 |
| `docs/retail_site_selection_sprint0/data_integrity_report.md` | 当前数据库核验的人类可读结果。 |
| `docs/retail_site_selection_sprint0/security_remediation.md` | 安全整改范围、核验与人工轮换要求。 |
| `docs/retail_site_selection_sprint0/sprint0_summary.md` | 本总结。 |

## 修改文件

| 文件 | 修改内容 |
|---|---|
| `backend/app/core/config.py` | 移除非空数据库和 LLM 凭据默认值，统一环境变量加载。 |
| `Utils/seperate.py` | 移除硬编码数据库连接，要求 `DATABASE_URL`。 |
| `backend/tests/conftest.py` | 移除测试数据库默认凭据。 |
| `backend/pytest.ini` | 固定 backend 测试的 Python 导入路径。 |
| `.gitignore` | 保持原始 Utils 数据集忽略，同时允许提交整改后的脚本。 |
| `README.md`、`backend/README.md`、`docs/poi_database_migration.md` | 清理带凭据形式的默认连接示例。 |

## 配置字段解释

| 字段 | 含义 |
|---|---|
| `config_version` | 唯一支持的冻结版本 `tokyo_coffee_v1`；其他值明确报错。 |
| `city` / `business_type` | 本版本唯一城市 `Tokyo` 与唯一业态 `coffee_shop`。 |
| `ranking_scope` | 固定为 `relative_to_selected_candidates`，只比较选中的候选分析区。 |
| `dataset` | 明确标识 `Foursquare Tokyo 2012-2013 historical check-in sample`、源文件和历史样本限制。 |
| `observation_period` | 样本 UTC 起止时间：2012-04-03T18:17:18Z 至 2013-02-16T02:35:29Z。 |
| `candidate_areas` | `shinjuku`、`shibuya`、`ginza`、`ikebukuro`；各含站点参考中心、1,000 米半径、Polygon 和生成溯源。 |
| `aliases` | 中、日、英文别名到唯一 `area_id` 的映射；所有目标必须存在。 |
| `competitor_categories` | 第一版固定包含 `Coffee Shop` 与 `Café`。 |
| `transport_categories` | 交通类 POI 类别契约，仅供后续实现使用。 |
| `business_mix_groups` | 餐饮、零售、休闲文化、夜间活动的类别分组契约。 |
| `metric_directions` | 五项必需指标的正向/反向比较方向。 |
| `metric_weights` | 五项指标均为 `0.20`，严格校验总和为 `1.0`。 |
| `normalization_method` | 冻结为 `min_max_within_selected_candidates`，本轮未实现计算。 |
| `mandatory_disclosures` | 历史样本、相对比较、1 km 分析区和非经营承诺等强制披露。 |
| `prohibited_claims` | 中英文禁止措辞清单，覆盖人口、实时客流、销售额、租金、转化率、成功率等。 |

五项必需指标 ID 为 `poi_count`、`historical_checkin_count`、`competitor_count`、`transport_poi_count`、`business_mix_diversity`。本轮只冻结名称、方向和权重，没有实现查询或评分。

## Polygon 生成方法

四个候选区统一采用以下方法，不能手写不规则边界：

1. 为每个站点冻结一个 WGS84 中心点，坐标字段与 GeoJSON 均明确使用经度在前、纬度在后。
2. 使用平均地球半径 `6,371,008.8 m`，按球面 destination-point 公式，从中心沿 `[0°, 360°)` 的 64 个等间隔方位角（步长 `5.625°`）各移动 `1,000 m`。
3. 将第一个点复制到末尾形成闭合 exterior ring，输出单环 GeoJSON `Polygon`。
4. Schema 检查坐标范围、至少四个位置、闭合、至少三个不同顶点、非零面积、无自交、64 段溯源一致，并用 Haversine 距离逐点复核 1,000 米半径（容差 1 米）。

相同半径、相同分段数和相同测地生成规则保证四区面积基本一致。它们统一称为“站点周边 1 km 分析区”，不称为官方商圈边界。

## 安全整改

- 后端数据库 URL 改为必填环境配置；缺失时明确失败。
- LLM 默认 provider 改为 `mock`，endpoint、API Key 和模型不再携带非空默认值。
- 旧导入脚本不再包含任何数据库主机、账户或密码。
- 测试不再使用硬编码数据库兜底凭据。
- `backend/.env.example` 中所有敏感字段保持空值；本地 `.env` 继续被忽略。
- 已扫描的受版本控制代码与文档已清理凭据默认值，但 Git 历史未改写；本地 `.env` 未纳入扫描或文档输出。已暴露的 LLM 密钥和任何被复用的数据库密码必须人工撤销/轮换。详见 `security_remediation.md`。

## 数据完整性核验结果

核验于 2026-08-03 通过当前可用 PostgreSQL/PostGIS 执行。脚本在查询前设置单事务 `READ ONLY`，数据库不可用时会以非零状态明确失败且不会生成伪造结果。

| 核验项 | 结果 |
|---|---:|
| POI 总数 | 61,858 |
| checkin 总数 | 573,703 |
| session 总数 | 79,312 |
| `checkins.session_id` 非空 | 532,290（92.78%） |
| `checkins.sequence_no` 非空 | 532,290（92.78%） |
| session 实际 checkin 数不一致 | 0 |
| 无法关联 POI 的 checkin | 0 |
| `pois.geom` GIST 索引 | 存在（`idx_pois_geom`） |
| 全部关键 B-tree 索引 | 否；存在 2 项缺口 |

| area_id | 1 km 内 POI | Coffee Shop + Café | 历史签到 |
|---|---:|---:|---:|
| `shinjuku` | 3,160 | 195 | 40,374 |
| `shibuya` | 2,527 | 201 | 26,009 |
| `ginza` | 2,725 | 199 | 21,483 |
| `ikebukuro` | 1,642 | 111 | 22,002 |

关键普通索引缺口为 `pois(venue_category)` 和以 `checkins(utc_timestamp)` 为首列的 B-tree 索引。Sprint 0 只核验并报告，没有修改数据库或新增索引。完整索引匹配明细见 `data_integrity_report.md` 和 JSON 报告。

## 未解决风险

1. 联合分布确认 41,413 条签到的 `session_id` 与 `sequence_no` 同时为空，单边为空数量均为 0。现有会话构建规则会排除单签到片段，但数据库未保存未分配原因，后续必须区分“按规则排除”和“处理失败”。
2. 两项关键普通索引缺失可能影响后续类别和时间维度查询；是否新增索引需在后续数据库变更 Sprint 中评估并走迁移，不在本轮处理。
3. 数据来自 2012-2013 年历史自选签到样本，存在年代、平台用户和自选择偏差，只能支持样本内相对比较。
4. 站点中心点已版本化，但仍需产品/数据负责人确认其业务参考点选择；变更中心点必须发布新配置版本，不能原地静默修改。
5. Polygon 是 64 段测地圆近似。对 1 km 分析尺度足够稳定，但不是测绘或法定边界。
6. Git 历史仍可能包含已暴露凭据；必须人工轮换并规划历史清理。
7. `relative_to_selected_candidates` 在 v1 中以配置内固定四区为候选母集；若未来允许请求时选择子集，必须发布新契约明确归一化母集，禁止静默改变口径。
8. 五项指标的聚合、去重、类别匹配和 `business_mix_diversity` 公式尚未冻结；这是后续实现前必须解决的契约风险，本轮按要求没有实现指标查询或评分。
9. 前端 production build 仍有既有的大 chunk 告警；本轮未修改前端，也未扩展范围处理该问题。

## 测试结果

| 命令 | 结果 |
|---|---|
| `pytest`（backend） | 通过：86 passed，3 warnings，5.18s。包含新增 8 个配置契约测试。 |
| `npm run lint`（frontend） | 通过；Windows PowerShell 策略阻止 `npm.ps1` 后使用等价的 `npm.cmd run lint` 执行。 |
| `npm run build`（frontend） | 通过；Vite 转换 2,333 个模块并生成 production bundle。 |

测试于 2026-08-03 在 Windows / PowerShell、Python 3.13.5 环境的当前未提交工作树执行，因此没有可引用的新 commit。pytest 告警原文为 Starlette `TestClient` 建议安装 `httpx2`，另有当前环境无权写 `.pytest_cache` 的提示；不影响测试通过。构建告警为依赖注释处理和大于 500 kB 的 chunk；不影响构建成功。当前环境已安装 requirements 声明的 psycopg 3，后端测试未跳过。
