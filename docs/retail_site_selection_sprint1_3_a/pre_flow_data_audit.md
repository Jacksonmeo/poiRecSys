# GeoAgent Sprint1.3-A 区域行为流向前置数据审计

## 1. 审计目的

本次审计用于确认现有 PostgreSQL/PostGIS 数据能否支持后续区域行为流向分析，重点检查 Session、Checkin、POI 的表结构、关联字段、空间数据和数据完整性。

审计时间：2026-08-03。

审计方式：所有数据库查询均在显式只读事务中执行。本次审计没有修改代码、数据库结构或业务数据。

## 2. 核心结论

- 当前没有独立的 `trajectory` 表，轨迹需要由 `sessions`、`checkins` 和 `pois` 动态构建。
- 已具备流向分析所需的 `session_id`、`user_id`、`venue_id`、时间戳和 `sequence_no` 字段。
- POI 没有持久化区域字段，需要通过 CandidateArea Polygon 和 `pois.geom` 动态判定区域归属。
- 共有 532,290 条 Checkin 同时具有 Session 和序号信息，可作为第一版有序流向分析数据，占全部 Checkin 的 92.7815%。
- 41,413 条 Checkin 同时缺少 `session_id` 和 `sequence_no`，不能直接进入依赖现有 Session/序号的流向查询；未来仍可在口径冻结后重新进行 Session 化。
- 已分配 Session 的数据不存在孤立关联、序号缺口、重复序号、用户不一致或时间倒序问题。

## 3. 数据表结构

### 3.1 sessions

| 字段 | 类型 | 可空 | 说明 |
|---|---|---:|---|
| `id` | bigint | 否 | 主键 |
| `session_id` | varchar | 否 | 全局唯一 Session 标识 |
| `user_id` | varchar | 否 | Session 所属用户 |
| `start_time` | timestamptz | 否 | Session 开始时间 |
| `end_time` | timestamptz | 否 | Session 结束时间 |
| `checkin_count` | integer | 否 | Session 声明的 Checkin 数量 |
| `dataset` | varchar | 否 | 数据集标识，默认 `TKY` |
| `created_at` | timestamptz | 否 | 记录创建时间 |

关键索引：

- `session_id` 唯一 B-tree 索引；
- `(user_id, start_time DESC)` B-tree 索引；
- `dataset` B-tree 索引。

### 3.2 checkins

| 字段 | 类型 | 可空 | 说明 |
|---|---|---:|---|
| `id` | bigint | 否 | 主键 |
| `user_id` | varchar | 否 | 签到用户 ID |
| `venue_id` | varchar | 否 | 签到 POI 的业务标识 |
| `timezone_offset` | integer | 是 | 时区偏移，单位为分钟 |
| `utc_timestamp` | timestamptz | 否 | UTC 签到时间；数据库中没有名为 `timestamp` 的字段 |
| `session_id` | varchar | 是 | 所属 Session |
| `sequence_no` | integer | 是 | Checkin 在 Session 内的顺序号 |

关键索引：

- `(session_id, sequence_no)` B-tree 索引；
- `(user_id, utc_timestamp)` B-tree 索引；
- `venue_id` B-tree 索引。

已存在外键：

- `checkins.user_id → users.user_id`；
- `checkins.venue_id → pois.venue_id`。

当前没有 `checkins.session_id → sessions.session_id` 外键，二者只存在逻辑关联。

### 3.3 pois

| 字段 | 类型 | 可空 | 说明 |
|---|---|---:|---|
| `id` | bigint | 否 | 主键 |
| `venue_id` | varchar | 否 | 唯一 POI 业务标识 |
| `venue_category_id` | varchar | 是 | 类别 ID |
| `venue_category` | varchar | 是 | 类别名称 |
| `latitude` | double precision | 否 | 纬度 |
| `longitude` | double precision | 否 | 经度 |
| `geom` | geometry | 数据库允许为空 | PostGIS 空间点 |
| `display_name` | varchar | 是 | POI 展示名称 |

空间数据核验结果：

- 61,858 条 POI 均具有非空 `geom`；
- 所有 geometry 的类型均为 POINT、SRID 均为 4326，符合当前查询契约；本次未额外审计坐标语义或几何有效性；
- 已存在 `pois.geom` GIST 索引；
- 数据库层允许 `geom` 为空，但 ORM 将其声明为非空，存在数据库约束与 ORM 契约不完全一致的问题；
- 按实际列名检查，未发现名称包含 `area`、`region`、`district`、`ward`、`zone` 的区域字段；这不排除其他名称可能承载相近语义。

## 4. 字段关系

```text
users.user_id
     1
     │ 外键
     └──────< checkins.user_id

sessions.session_id
     1
     │ 逻辑关联，无数据库外键
     └ - - -< checkins.session_id
                    │
                    ├── sequence_no
                    ├── utc_timestamp
                    └── venue_id
                          │ 外键
                          ▼
                    pois.venue_id
                          │
                          └── geom POINT/4326
                                 │ ST_Covers
                                 ▼
                       CandidateArea Polygon
```

字段可用性如下：

| 所需字段 | 是否存在 | 所在表 | 备注 |
|---|---:|---|---|
| `session_id` | 是 | `sessions`、`checkins` | Checkin 中允许为空 |
| `user_id` | 是 | `sessions`、`checkins` | 已分配记录中用户关系一致 |
| `venue_id` | 是 | `checkins`、`pois` | 存在数据库外键 |
| 时间戳 | 是 | `checkins.utc_timestamp` | `timestamptz`，不存在字面字段 `timestamp` |
| `sequence_no` | 是 | `checkins` | Checkin 中允许为空 |
| POI 区域字段 | 否 | — | 需要通过 PostGIS 动态计算 |
| 独立 trajectory 表 | 否 | — | 轨迹由现有三表组合得到 |

## 5. 当前数据量与完整性

### 5.1 数据规模

| 指标 | 结果 |
|---|---:|
| Session 数量 | 79,312 |
| 平均 Session 长度（`sessions.checkin_count`） | 6.7113 |
| 平均实际关联 Checkin 数 | 6.7113 |
| Session 长度中位数 | 4 |
| Session 长度 P95 | 21 |
| Session 最小长度 | 2 |
| Session 最大长度 | 311 |
| POI 数量 | 61,858 |
| Checkin 数量 | 573,703 |
| 已分配 Session 和序号的 Checkin | 532,290 |
| 未分配 Session 和序号的 Checkin | 41,413 |
| 完整 Session 序列的原始相邻签到对 | 452,978 |

Session 长度的平均值、中位数、P95、最小值和最大值均基于 `sessions.checkin_count`。由于所有 Session 的声明数量都与实际关联数量一致，这些统计与按实际关联 Checkin 计算的结果一致。

532,290 是可进入有序分析的 Checkin 数量，不是区域转移数量。当前所有 Session 都至少包含两条 Checkin，因此完整 Session 序列可精确产生 `532,290 - 79,312 = 452,978` 个原始相邻签到对；空间归属和业务过滤后的区域转移数不会超过该值。

### 5.2 关键字段完整率

| 字段 | 非空数量 | 非空比例 |
|---|---:|---:|
| `checkins.user_id` | 573,703 | 100% |
| `checkins.venue_id` | 573,703 | 100% |
| `checkins.utc_timestamp` | 573,703 | 100% |
| `checkins.session_id` | 532,290 | 92.7815% |
| `checkins.sequence_no` | 532,290 | 92.7815% |

### 5.3 关联和顺序质量

| 检查项 | 异常数量 |
|---|---:|
| `sessions.checkin_count` 与实际数量不一致 | 0 |
| 已填写 `session_id` 但无法关联 Session | 0 |
| 无法关联 POI 的 Checkin | 0 |
| Session 用户与 Checkin 用户不一致 | 0 |
| 存在序号缺口或重复序号的 Session | 0 |
| 按 `sequence_no` 排列后时间倒序 | 0 |
| 只有 `session_id`、没有 `sequence_no` | 0 |
| 只有 `sequence_no`、没有 `session_id` | 0 |

上述质量检查采用以下口径：

- Session 数量不一致：比较 `sessions.checkin_count` 与按 `checkins.session_id` 聚合的实际行数；
- 孤立 Session 关联：`checkins.session_id` 非空但无法关联 `sessions.session_id`；
- 孤立 POI 关联：`checkins.venue_id` 无法关联 `pois.venue_id`；
- 用户不一致：同一 `session_id` 下 `checkins.user_id <> sessions.user_id`；
- 序号缺口或重复：每个 Session 必须满足最小序号为 1、最大序号等于行数、去重序号数等于行数；
- 时间倒序：按 `session_id, sequence_no, checkins.id` 排序后，当前 `utc_timestamp` 早于上一条记录。

### 5.4 数据集与时间范围

- 79,312 条 Session 的 `dataset` 均为 `TKY`，对应 532,290 条已 Session 化 Checkin；
- 全部 Checkin 的时间范围为 2012-04-03 18:17:18 UTC 至 2013-02-16 02:35:29 UTC；
- 未 Session 化 Checkin 自身没有 `dataset` 字段，不能仅通过数据库关系证明其数据集归属。其时间范围与东京历史样本重合，但归属仍依赖数据导入来源和外部数据契约。

## 6. 区域流向分析所需数据链路

第一版区域流向可以通过以下只读链路构建：

1. 从版本化 SiteSelection 配置取得 CandidateArea Polygon；
2. 仅选择 `session_id` 和 `sequence_no` 均非空的 Checkin；
3. 使用 `checkins.venue_id = pois.venue_id` 关联签到点和空间位置；
4. 保留完整签到序列，通过 LEFT JOIN/条件聚合使用 `ST_Covers(area_polygon, pois.geom)` 判定区域；未命中候选区的签到先标记为 `outside_candidate_areas`，不能提前删除；
5. 若一个 POI 命中多个 Polygon，必须先按冻结的唯一归属规则消歧，避免一条 Checkin 扩展成多行；
6. 通过 `checkins.session_id = sessions.session_id` 关联 Session；
7. 按 `session_id, sequence_no` 排列完整签到序列；
8. 使用窗口函数取得相邻签到的前一区域，构造 `origin_area → destination_area`；
9. 按起点区域和终点区域汇总历史样本中的转换次数。

```text
Session
  → 有序 Checkin
  → POI 空间位置
  → CandidateArea/区域外状态动态归属
  → 相邻区域对
  → 区域流向汇总
```

## 7. 数据缺口与风险

1. **未 Session 化记录**：41,413 条 Checkin 同时缺少 `session_id` 和 `sequence_no`，占 7.2185%，不能直接进入当前依赖已有 Session/序号的流向查询；未来可在独立口径下重新 Session 化，也可用于不依赖顺序的时间或空间聚合。
2. **缺少区域字段**：POI 没有持久化区域归属，每次分析都需要根据指定版本的 Polygon 动态计算。
3. **缺少 Session 外键**：`checkins.session_id` 没有数据库外键。当前数据不存在孤立记录，但数据库不能持续强制保证该关系。
4. **数据集归属不完整**：`dataset` 只存在于 `sessions`。全部 Session 均标记为 `TKY`，但未 Session 化的 Checkin 无法通过数据库关系确认数据集。
5. **空间约束漂移**：实际数据库允许 `pois.geom` 为空，虽然当前数据均非空、类型均为 POINT、SRID 均为 4326。
6. **流向口径尚未冻结**：尚未明确区域外签到、Polygon 重叠、同区连续签到和长 Session 的处理规则。
7. **历史样本限制**：结果只能描述 Foursquare Tokyo 2012–2013 历史签到样本中的相对行为模式，不能解释为实时客流或当前市场规模。

## 8. 推荐下一步实现方案

### 8.1 先冻结流向契约

实现查询前需要明确：

- 计算过程中必须保留 `outside_candidate_areas` 占位；最终输出是否展示、汇总或过滤涉及区域外的转移仍需冻结；
- 是否统计同一区域到同一区域的自循环；
- POI 同时落入多个 Polygon 时的唯一归属规则；
- 是否对超长 Session 设置分析上限；
- 输出是否包含原始转换次数、独立用户数和独立 Session 数；
- 输出必须携带的 `config_version`、观察期和历史样本披露。

建议保留区域外状态。直接删除区域外 Checkin 可能把原本不相邻的两个候选区域连接起来，形成虚假的直接流向。

### 8.2 第一版查询策略

第一版建议保持只读和动态计算：

1. 使用当前 532,290 条已 Session 化记录；
2. Repository 完成 Checkin、POI、Session 关联，并在保留完整序列的前提下生成区域归属和相邻区域对；
3. Service 只负责业务口径校验和结果组合，不计算综合评分；
4. 使用真实 PostgreSQL/PostGIS 测试库验证边界点、区域外点、自循环和跨区转换；
5. 通过 `EXPLAIN (ANALYZE, BUFFERS)` 评估动态空间归属性能；
6. 只有在性能不能接受时，再评估持久化或缓存 POI 区域映射。

## 9. 审计结论

当前数据库已经具备实现区域行为流向分析的核心数据链路。Session 化子集的关联、序号和时间顺序质量良好；在区域外状态和 Polygon 重叠归属规则冻结后，可以作为 Sprint1.3 后续实现的输入。

正式开发前仍需冻结区域外状态、重叠归属、自循环和输出口径。第一版不需要新增轨迹表或修改 POI 结构，优先采用基于现有表和版本化 Polygon 的只读动态查询。

## 10. 复核查询口径

以下 SQL 展示本报告核心结论的复核口径。执行时应先开启事务并设置 `SET TRANSACTION READ ONLY`，执行完成后回滚事务。

### 10.1 核心数量和平均 Session 长度

```sql
SELECT
    (SELECT COUNT(*) FROM sessions) AS session_count,
    (SELECT AVG(checkin_count::numeric) FROM sessions) AS avg_session_length,
    (SELECT COUNT(*) FROM pois) AS poi_count,
    (SELECT COUNT(*) FROM checkins) AS checkin_count,
    (SELECT COUNT(*) FROM checkins WHERE session_id IS NOT NULL)
        AS sessionized_checkin_count;
```

### 10.2 Session 实际长度一致性

```sql
WITH actual AS (
    SELECT session_id, COUNT(*) AS actual_count
    FROM checkins
    WHERE session_id IS NOT NULL
    GROUP BY session_id
)
SELECT COUNT(*) AS mismatch_count
FROM sessions AS s
LEFT JOIN actual ON actual.session_id = s.session_id
WHERE s.checkin_count <> COALESCE(actual.actual_count, 0);
```

### 10.3 序号完整性

```sql
WITH sequence_quality AS (
    SELECT
        session_id,
        COUNT(*) AS row_count,
        COUNT(DISTINCT sequence_no) AS distinct_sequence_count,
        MIN(sequence_no) AS min_sequence,
        MAX(sequence_no) AS max_sequence
    FROM checkins
    WHERE session_id IS NOT NULL
    GROUP BY session_id
)
SELECT COUNT(*) AS invalid_session_count
FROM sequence_quality
WHERE min_sequence <> 1
   OR max_sequence <> row_count
   OR distinct_sequence_count <> row_count;
```

### 10.4 时间顺序

```sql
WITH ordered_checkins AS (
    SELECT
        session_id,
        utc_timestamp,
        LAG(utc_timestamp) OVER (
            PARTITION BY session_id
            ORDER BY sequence_no, id
        ) AS previous_timestamp
    FROM checkins
    WHERE session_id IS NOT NULL
      AND sequence_no IS NOT NULL
)
SELECT COUNT(*) AS timestamp_order_violations
FROM ordered_checkins
WHERE previous_timestamp IS NOT NULL
  AND utc_timestamp < previous_timestamp;
```

### 10.5 空间字段和数据范围

```sql
SELECT
    COUNT(*) FILTER (WHERE geom IS NULL) AS geom_null_count,
    COUNT(*) FILTER (WHERE geom IS NOT NULL AND ST_SRID(geom) <> 4326)
        AS wrong_srid_count
FROM pois;

SELECT dataset, COUNT(*) AS session_count, SUM(checkin_count) AS checkin_count
FROM sessions
GROUP BY dataset;

SELECT MIN(utc_timestamp), MAX(utc_timestamp)
FROM checkins;
```

### 10.6 联合空值、孤立关联和 geometry 类型

```sql
SELECT
    COUNT(*) FILTER (
        WHERE session_id IS NOT NULL AND sequence_no IS NOT NULL
    ) AS both_session_fields_non_null,
    COUNT(*) FILTER (
        WHERE session_id IS NULL AND sequence_no IS NULL
    ) AS both_session_fields_null,
    COUNT(*) FILTER (
        WHERE session_id IS NULL AND sequence_no IS NOT NULL
    ) AS sequence_without_session,
    COUNT(*) FILTER (
        WHERE session_id IS NOT NULL AND sequence_no IS NULL
    ) AS session_without_sequence
FROM checkins;

SELECT
    COUNT(*) FILTER (
        WHERE c.session_id IS NOT NULL AND s.session_id IS NULL
    ) AS orphan_session_checkins,
    COUNT(*) FILTER (WHERE p.venue_id IS NULL) AS orphan_poi_checkins,
    COUNT(*) FILTER (
        WHERE s.session_id IS NOT NULL AND c.user_id <> s.user_id
    ) AS session_user_mismatches
FROM checkins AS c
LEFT JOIN sessions AS s ON s.session_id = c.session_id
LEFT JOIN pois AS p ON p.venue_id = c.venue_id;

SELECT GeometryType(geom) AS geometry_type, ST_SRID(geom) AS srid, COUNT(*)
FROM pois
WHERE geom IS NOT NULL
GROUP BY GeometryType(geom), ST_SRID(geom);
```
