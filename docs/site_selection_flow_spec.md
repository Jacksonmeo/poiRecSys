# GeoAgent SiteSelection 区域行为流向分析技术规范

状态：Sprint1.3 实现前冻结规范  
适用配置：`tokyo_coffee_v1` 及后续显式兼容本规范的配置版本  
数据性质：Foursquare Tokyo 2012–2013 历史签到样本

规范依据：

- [Sprint1.3-A 区域行为流向前置数据审计](retail_site_selection_sprint1_3_a/pre_flow_data_audit.md)；
- [tokyo_coffee_v1 版本化配置](../backend/app/site_selection/config/tokyo_coffee_v1.json)；
- [SiteSelection 配置 Schema](../backend/app/schemas/site_selection_config.py)。

本文引用的数据量和索引是 2026-08-03 审计快照，只用于说明当前可行性，不得硬编码到实现。可复核 SQL 见前置数据审计附录。

## 1. 目的与范围

本文档冻结 GeoAgent SiteSelection 区域行为流向分析的第一版实现规范，供后续后端开发、测试和代码 Review 使用。

第一版只回答：在历史签到样本中，用户按既有 Session 顺序从一个 CandidateArea 到另一个 CandidateArea 的相邻转换出现了多少次，涉及多少独立用户和独立 Session。

本规范不包含：

- 综合评分、归一化或权重计算；
- Session 重建或轨迹纠错；
- 推荐模型或 Agent Tool 调用；
- 实时客流、人口、销售额、租金、转化率或成功率推断；
- 新增数据库表、字段、物化视图或前端协议。

## 2. 规范性术语

| 术语 | 定义 |
|---|---|
| CandidateArea | 版本化 SiteSelection 配置中的候选分析区，包含 `area_id`、中心点和 Polygon |
| 有效 Checkin | 满足第 4 节全部过滤条件、可进入有序流向计算的签到记录 |
| 区域状态 | Checkin 映射后的 CandidateArea `area_id`，或内部区域外状态 `outside_candidate_area` |
| 相邻签到对 | 同一 Session 中按 `sequence_no` 排序后相邻的两条有效 Checkin |
| Transition | 相邻签到对映射为两个不同 CandidateArea 后形成的有向跨区域转换 |
| 长 Session | Checkin 数量明显高于常规分布的 Session；当前数据最大长度为 311 |

本文中的“必须”表示实现不可偏离；“建议”表示可以在不改变业务口径的前提下调整。

标识符字段的“为空”统一指 SQL `NULL`，或去除首尾空白后为空字符串。`session_id`、`user_id`、`venue_id` 出现任一上述情况时均视为无效标识符。`sequence_no` 是整数，不存在字符串空值语义。

本规范涉及 `area_id` 字典序时，统一按小写 ASCII 字节顺序比较，等价于数据库 `C` collation；Service 侧必须使用相同的 ASCII/Unicode code point 顺序。当前配置 Schema 已限制 `area_id` 只能包含小写 ASCII 字母、数字和下划线。

## 3. 数据来源

### 3.1 sessions

用途：提供已构建的 Session 边界、用户归属和数据集标识。

使用字段：

- `session_id`：关联 Checkin；
- `user_id`：校验 Session 与 Checkin 属于同一用户；
- `checkin_count`：数据完整性校验；
- `dataset`：第一版只使用 `TKY`；
- `start_time`、`end_time`：用于审计，不重新划分 Session。

### 3.2 checkins

用途：提供 Session 内有序签到行为。

使用字段：

- `id`：稳定记录标识；
- `session_id`：关联 Session；
- `user_id`：用户去重和关联一致性校验；
- `venue_id`：关联 POI；
- `utc_timestamp`：限定观察期并校验时间顺序；
- `sequence_no`：定义 Session 内签到顺序。

### 3.3 pois

用途：提供 Checkin 对应的空间位置。

使用字段：

- `venue_id`：关联 Checkin；
- `geom`：CandidateArea 空间归属计算，类型必须为 POINT、SRID 必须为 4326。

POI 当前没有区域字段。第一版必须通过 PostGIS 动态计算区域归属，不能根据名称、行政区文本或经纬度包围盒猜测区域。

### 3.4 CandidateArea

来源：经过严格校验的版本化 SiteSelection 配置。

使用字段：

- `area_id`：区域稳定标识；
- `center`：Polygon 重叠时的唯一归属判定；
- `polygon`：POI 空间归属；
- `analysis_radius_m` 和 `polygon_provenance`：确认所有候选区采用一致生成规则。

第一版使用配置指定的观察期。对 `tokyo_coffee_v1`，观察期为 2012-04-03 18:17:18 UTC 至 2013-02-16 02:35:29 UTC，起止时刻均包含。

调用方必须使用现有严格配置加载器完成版本、区域 ID、Polygon、中心点、半径和 provenance 校验。配置验证失败时必须终止分析，不得在 Flow Analysis 内修复 Polygon、补中心点或回退配置版本。

## 4. 数据过滤规则

### 4.1 必须使用的 Checkin

过滤必须按“先选择完整 Session，再使用该 Session 的全部 Checkin”执行，禁止先逐条删除 Checkin 后重新连接前后记录。

候选 Session 必须满足：

1. 能通过 `session_id` 关联到 `sessions`；
2. `sessions.dataset = 'TKY'`；
3. 该 `session_id` 关联的每条 Checkin 都满足 `sequence_no` 非空且为正整数；
4. 每条 Checkin 和 Session 的 `user_id` 均非空且字符串完全相同；
5. 每条 `utc_timestamp` 都位于配置观察期内，起止时刻均包含；
6. 每条 Checkin 都能通过 `venue_id` 关联到 POI；
7. 每个关联 POI 的 `geom` 都非空、非 EMPTY、类型为 POINT、SRID 为 4326，且经纬度为有限值并处于 WGS84 合法范围；
8. 整个 Session 通过第 4.4 节完整性校验。

只有整个候选 Session 通过全部条件时，该 Session 的全部 Checkin 才成为有效 Checkin。任何一条记录失败都必须排除整个 Session，不得删除失败记录后让其前后 Checkin 形成新的相邻关系。

数据库审计表明当前 532,290 条 Checkin 同时具有 `session_id` 和 `sequence_no`，但实现不能把该数量硬编码为业务常量。

### 4.2 `session_id` 为空

`session_id` 为空的 Checkin 必须排除，不允许按 `user_id` 和时间在流向查询中临时重建 Session。由于该记录无法可靠归入某个既有 Session，它不会触发其他 Session 被排除。

原因：Session 重建属于独立数据处理口径，临时重建会使结果无法与现有 `sessions` 数据和审计结果保持一致。

### 4.3 `sequence_no` 为空

`sequence_no` 为空且 `session_id` 非空时，所属整个 Session 必须排除，不允许只删除该 Checkin，也不允许使用 `utc_timestamp` 推断顺序。

原因：时间戳可能相同，且现有 Session 契约已明确以 `sequence_no` 为主顺序。

### 4.4 Session 完整性

完整性校验针对该 `session_id` 在 `checkins` 表中的全部原始关联记录，必须在观察期、POI 或空间条件可能删除记录之前完成。进入分析的 Session 必须满足：

- 序号最小值为 1；
- 序号最大值等于 Session 实际 Checkin 数；
- 去重后的序号数量等于 Session 实际 Checkin 数；
- 按 `sequence_no` 排序后 `utc_timestamp` 不倒序；
- `sessions.checkin_count` 等于实际关联 Checkin 数。

发现违反上述条件的 Session 时，第一版必须将整个 Session 排除并记录“异常 Session 数量”；一条异常 Session 只计一次，不因同时违反多个条件而重复计数。不得在查询中自动补号、排序纠正或部分保留。当前审计中的异常 Session 数为 0。

第一版不裁剪跨观察期 Session：只要 Session 中有一条 Checkin 位于观察期外，就排除整个 Session。`tokyo_coffee_v1` 当前数据全部位于配置观察期内；未来缩短观察期需要修订本规范，而不能静默改为截断 Session。

## 5. 区域归属规则

### 5.1 基本映射

POI 与 CandidateArea 的命中关系必须使用 `ST_Covers(candidate_polygon, pois.geom)` 判断：

- Polygon 内部点计入该区域；
- Polygon 边界点也计入该区域；
- Polygon 和 POI geometry 均使用 SRID 4326；
- 每个配置版本必须使用自身携带的 Polygon，不能使用另一版本的区域结果。

区域归属应先按唯一 POI 计算，再通过 `venue_id` 关联 Checkin，避免对同一 POI 的每条 Checkin 重复执行空间判断。

### 5.2 区域外状态

未被任何 CandidateArea 覆盖的 POI 必须映射为内部保留状态：

`outside_candidate_area`

规则如下：

- 该状态必须保留到相邻签到对生成完成；
- 不允许先删除区域外 Checkin，再连接其前后两个候选区签到；
- 第一版最终 `AreaFlowResult` 不输出以该状态为起点或终点的记录；
- 区域外状态只用于阻断虚假的候选区直接转换，不属于 CandidateArea，也不能参与区域排名。

示例：原始序列为 `shinjuku → outside_candidate_area → shibuya` 时，不得生成 `shinjuku → shibuya`。

### 5.3 Polygon 重叠

一条 POI 可能同时被多个 CandidateArea Polygon 覆盖。第一版必须在生成相邻签到对之前将其归属为唯一 CandidateArea：

1. 只在所有命中的 CandidateArea 中比较；
2. 使用 PostGIS `ST_Distance(poi_geography, center_geography, true)` 的 WGS84 椭球距离计算 POI 到各命中区域中心点的距离，单位为米，不做预先四舍五入；
3. 选择距离最近的 CandidateArea；
4. 查询排序以完整距离值升序、`area_id` 字典序升序，距离完全相同时由 `area_id` 决定。

不得复制 Checkin 形成多条区域记录，也不得按 CandidateArea 在配置文件中的数组顺序决定归属。

## 6. 流向计算规则

### 6.1 顺序与相邻关系

流向必须在每个 Session 内独立计算：

1. 按 `sequence_no` 升序排列有效 Checkin；
2. 以相邻两条 Checkin 的区域状态形成有向签到对；
3. 不允许跨 Session 形成签到对；
4. `sequence_no` 是业务顺序，`checkins.id` 只可用于确定性审计，不得改变合法序号顺序。

有向关系必须保留方向，`shinjuku → shibuya` 与 `shibuya → shinjuku` 是两条不同流向。

### 6.2 Transition 纳入条件

相邻签到对必须同时满足以下条件才能成为最终 Transition：

- 起点和终点都属于配置中的 CandidateArea；
- 起点和终点均不是 `outside_candidate_area`；
- `source_area != target_area`。

第一版不统计同一区域转移。连续两条签到都位于同一 CandidateArea 时，不增加 `flow_count`，也不影响后续签到的原始相邻关系。

### 6.3 重复转换计数

同一 Session 可以多次贡献同一个有向区域对。例如 `A → B → A → B` 对 `A → B` 贡献两次 `flow_count`。

聚合口径：

- `flow_count`：符合条件的相邻 Transition 行数；
- `unique_users`：对同一 `source_area + target_area` 的 `user_id` 去重数量；
- `unique_sessions`：对同一 `source_area + target_area` 的 `session_id` 去重数量。

每个 Session 只属于一个用户，因此必须满足 `1 <= unique_users <= unique_sessions <= flow_count`。同一用户跨多个 Session 产生同一流向时，`flow_count` 和 `unique_sessions` 可以增加，但 `unique_users` 只计一次。

### 6.4 长 Session

第一版不按长度截断 Session，也不设置额外时间间隔阈值：

- 使用现有 Session 边界和全部合法 Checkin；
- 长 Session 中每一对原始相邻签到都按相同规则处理；
- 不因 Session 较长而抽样或降低权重；
- 长 Session 可能产生较多 `flow_count`，必须同时输出 `unique_users` 和 `unique_sessions` 供调用方判断集中度。

当前 Session 最大长度为 311。若未来需要限制长 Session，必须建立新配置版本或单独修订本规范，不能在 Repository 中增加隐式阈值。

### 6.5 空结果与排序

- 只返回 `flow_count > 0` 的有向区域对；
- 不为没有流向的区域组合生成零值记录；
- 结果按 `flow_count` 降序，其次按 `source_area`、`target_area` 的 ASCII/C 字典序升序，保证确定性。

## 7. 输出 Schema

### 7.1 AreaFlowResult

`AreaFlowResult` 只表示一个有向候选区域对的原始历史行为聚合，不包含得分、归一化值或业务建议。

| 字段 | 类型 | 约束 | 含义 |
|---|---|---|---|
| `source_area` | string | 必须是当前配置中的 CandidateArea `area_id` | 流向起点 |
| `target_area` | string | 必须是当前配置中的 CandidateArea `area_id`，且不同于起点 | 流向终点 |
| `flow_count` | integer | 大于 0 | 相邻有向 Transition 总数 |
| `unique_users` | integer | 1 至 `unique_sessions` | 产生该流向的去重用户数 |
| `unique_sessions` | integer | `unique_users` 至 `flow_count` | 产生该流向的去重 Session 数 |

Schema 必须拒绝未知字段。数值字段必须使用整数，不允许浮点数或字符串强制转换。

区域外状态不得出现在 `source_area` 或 `target_area`。配置版本、观察期和历史样本披露属于调用上下文，不得通过给 `AreaFlowResult` 临时添加字段解决；若未来需要响应级元数据，应另行冻结响应 Schema。

## 8. 数据处理链路

```text
版本化 CandidateArea
        │
        ▼
POI 唯一区域归属（含 outside_candidate_area）
        │
        ▼
过滤后的 sessions + checkins + pois
        │
        ▼
按 session_id / sequence_no 保留完整区域状态序列
        │
        ▼
生成原始相邻签到对
        │
        ├── 排除区域外端点
        ├── 排除同区域对
        ▼
按 source_area / target_area 聚合
        │
        ▼
AreaFlowResult 列表
```

必须先形成包含区域外状态的完整相邻关系，再执行最终 Transition 过滤。改变这两个步骤的顺序会改变业务结果。

## 9. 现有架构中的职责边界

### Repository

负责：

- 使用现有 SQLAlchemy Session 访问数据库；
- 关联 `sessions`、`checkins` 和 `pois`；
- 执行 PostGIS 区域归属；
- 按 Session 生成相邻签到对；
- 在数据库中完成 `flow_count`、去重用户数和去重 Session 数聚合；
- 每个有向区域对返回一行，字段为 `source_area`、`target_area`、`flow_count`、`unique_users`、`unique_sessions`，所有计数使用数据库整数类型。

不得负责：

- 综合评分、权重或归一化；
- 业务解释和推荐文案；
- 读取环境变量或创建数据库连接；
- 修改数据库结构或数据。

### Service

负责：

- 接收经过验证的 CandidateArea 和配置上下文；
- 调用 Repository；
- 校验 Repository 返回的区域 ID 和计数关系；
- 转换并排序 `AreaFlowResult`。

Service 不得包含 SQL、PostGIS 函数或 Session 重建逻辑。

### Schema

负责冻结 `AreaFlowResult` 的类型和字段约束。第一版不得在该 Schema 中提前加入评分、占比、排名、解释或可视化字段。

## 10. 性能考虑

### 10.1 PostGIS 动态计算

第一版采用动态空间归属，不新增 POI 区域字段或映射表。建议在单次查询中：

1. 将当前配置的 CandidateArea Polygon 只转换一次；
2. 先按唯一 POI 计算区域归属；
3. 再将 POI 区域结果关联到 Checkin；
4. 在数据库中完成窗口计算和聚合，只向 Service 返回聚合结果。

这可以避免把 532,290 条 Checkin 全部加载到应用内存，也避免对同一 POI 重复执行空间判断。

### 10.2 索引使用

当前可利用的关键索引：

- `pois.geom` GIST 索引：支持 CandidateArea Polygon 与 POI 点的空间过滤；
- `pois.venue_id` 唯一 B-tree 索引：支持 Checkin 与 POI 关联；
- `checkins.venue_id` B-tree 索引：支持 Checkin 与 POI 关联；
- `checkins(session_id, sequence_no)` B-tree 索引：支持 Session 内排序；
- `sessions.session_id` 唯一 B-tree 索引：支持 Session 关联；
- `sessions.dataset` B-tree 索引：支持 `TKY` 数据集过滤。

实现 Review 必须使用只读执行计划分析验证空间归属、关联、排序和聚合成本，并确认 GIST 索引可被查询条件利用。优化器在数据量较小或统计信息不同的情况下可以合理选择顺序扫描，因此不得把“必须出现特定索引名”作为正确性条件；若未使用索引，Review 必须记录查询计划选择原因。

### 10.3 缓存策略

第一版不需要持久化缓存，也不新增缓存表或物化视图。原因：

- 当前只有 61,858 个 POI 和四个 CandidateArea；
- Polygon 与 `config_version` 强绑定；
- 在缺少真实性能数据前引入缓存会增加失效和一致性复杂度。

允许使用单次请求或单次查询生命周期内的 POI 区域中间结果，但不得跨配置版本复用。

只有在真实查询计划和基准测试证明动态计算不可接受时，才进入独立缓存设计。未来缓存必须至少以 `config_version`、候选区域集合和 Polygon 内容摘要作为失效键；该能力不属于本规范第一版实现范围。

## 11. 错误处理与可观测性

- 未知或未支持的 `config_version` 必须明确失败，不得回退到其他版本；
- 数据库不可用时必须返回明确错误，不得返回空流向冒充成功；
- Session 完整性异常必须记录聚合数量，不得记录用户 ID、Session ID 或完整轨迹；
- 无法关联 POI、无效 geometry、跨观察期等 Session 级排除原因必须分别记录聚合数量；同一 Session 在总异常数中只计一次；
- 不得在日志中输出数据库连接凭据；
- 空结果是合法业务结果，但必须与数据库错误区分；
- 日志和文档必须说明结果来自历史签到样本，不能使用实时客流等禁止表述。

## 12. 实现验收条件

后续实现必须至少通过以下测试：

1. `session_id` 为空时只排除该条无法归属的 Checkin；非空 `session_id` 关联的任一 Checkin 出现空 `sequence_no` 时，排除所属整个 Session；
2. Session 中任一 Checkin 无法关联 POI、geometry 无效或越过观察期时，整个 Session 被排除且不会桥接前后签到；
3. Polygon 内部点和边界点均正确归属；
4. 区域外 Checkin 阻断前后候选区的虚假直接转换；
5. 重叠 Polygon 按 WGS84 geography 中心距离和 `area_id` 规则唯一归属；
6. `A → B` 与 `B → A` 分别计数；
7. `A → A` 不进入输出；
8. 同一 Session 重复产生 `A → B` 时，`flow_count` 逐次累计，`unique_sessions` 只计一次；
9. 同一用户跨 Session 产生相同流向时，`unique_users` 只计一次；
10. 长 Session 不被截断；
11. 空结果返回空列表，不伪造零值区域对；
12. 输出满足 `unique_users <= unique_sessions <= flow_count` 且排序稳定；
13. Repository 使用真实 PostgreSQL/PostGIS 测试库验证空间和窗口查询；
14. Service 测试不依赖 SQL，验证 `AreaFlowResult` 组合和约束；
15. 现有全部后端测试保持通过。

## 13. 冻结决策摘要

| 决策项 | 第一版规则 |
|---|---|
| Checkin 范围 | 仅使用整体通过完整性、关联、空间和观察期校验的 Session 中的全部记录 |
| 空 `session_id` | 只排除该条无法归属的 Checkin，不临时重建 Session |
| 空 `sequence_no` | 若 `session_id` 非空，则排除所属整个 Session，不用时间戳推断 |
| 区域判定 | `ST_Covers`，包含边界 |
| 区域外点 | 计算过程保留为 `outside_candidate_area`，最终不输出相关边 |
| Polygon 重叠 | 命中区中心 WGS84 geography 椭球距离最近；同距按 `area_id` ASCII/C 字典序 |
| 相邻关系 | 同一 Session 内按 `sequence_no` 的原始相邻签到 |
| 同区域转移 | 不统计 |
| 长 Session | 不截断、不降权、不增加额外时间阈值 |
| 流向方向 | 有向，正反方向分别统计 |
| 缓存 | 第一版不做持久化缓存 |
| 输出 | `AreaFlowResult` 原始整数计数，不包含评分或解释 |

对上述任一规则的修改都会改变流向统计口径，必须通过新的规范版本或明确的设计修订完成，不能作为实现细节静默改变。
