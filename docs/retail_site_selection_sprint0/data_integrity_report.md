# GeoAgent Sprint 0 数据完整性核验报告

- 生成时间（UTC）：`2026-08-03T09:39:25.682881+00:00`
- 配置版本：`tokyo_coffee_v1`
- 配置 SHA-256：`e4f303b2a4465ca6c8865920ad217e471a34fc3997a7789515275996317ab441`
- 审计脚本 SHA-256：`89a7a137df99218f0f369b6070d215fd0efc1f8ac0e2db7c1e7b3ecf69a9ba6e`
- 数据口径：Foursquare Tokyo 2012-2013 historical check-in sample
- 数据库状态：可用
- 数据库上下文：`postgres` / `public` / PostgreSQL `18.4`
- 事务上下文：`read committed` / snapshot `2977:2977:`
- 执行方式：单事务 `READ ONLY`；未修改数据库

## 总量与完整性

| 核验项 | 结果 |
|---|---:|
| POI 总数 | 61,858 |
| checkin 总数 | 573,703 |
| session 总数 | 79,312 |
| `checkins.session_id` 非空 | 532,290 / 573,703 (92.78%) |
| `checkins.sequence_no` 非空 | 532,290 / 573,703 (92.78%) |
| session 实际 checkin 数与 `sessions.checkin_count` 不一致数量 | 0 |
| 无法关联 POI 的 checkin 数量 | 0 |

### session 字段联合分布

| `session_id` | `sequence_no` | checkin 数量 |
|---|---|---:|
| 非空 | 非空 | 532,290 |
| 空 | 空 | 41,413 |
| 非空 | 空 | 0 |
| 空 | 非空 | 0 |

## 统一 1 km 候选分析区

以下统计使用配置中由站点中心和统一 1,000 米半径生成的 Polygon。

| area_id | POI | Coffee Shop + Café | 历史签到 |
|---|---:|---:|---:|
| `shinjuku` | 3,160 | 195 | 40,374 |
| `shibuya` | 2,527 | 201 | 26,009 |
| `ginza` | 2,725 | 199 | 21,483 |
| `ikebukuro` | 1,642 | 111 | 22,002 |

## 索引核验

- `pois.geom` GIST 索引：存在
- 全部关键 B-tree 索引：存在缺口

| 关键索引需求 | 表 | 列前缀 | 状态 | 匹配索引 |
|---|---|---|---|---|
| `pois_venue_id` | `pois` | `venue_id` | 存在 | `pois_venue_id_key` |
| `pois_venue_category` | `pois` | `venue_category` | 缺失 | — |
| `checkins_user_id` | `checkins` | `user_id` | 存在 | `idx_checkins_user_time` |
| `checkins_venue_id` | `checkins` | `venue_id` | 存在 | `idx_checkins_venue` |
| `checkins_utc_timestamp` | `checkins` | `utc_timestamp` | 缺失 | — |
| `checkins_session_id` | `checkins` | `session_id` | 存在 | `idx_checkins_session_sequence` |
| `checkins_session_sequence` | `checkins` | `session_id, sequence_no` | 存在 | `idx_checkins_session_sequence` |
| `sessions_session_id` | `sessions` | `session_id` | 存在 | `sessions_session_id_key` |
| `sessions_user_id` | `sessions` | `user_id` | 存在 | `idx_sessions_user_start_time` |

## 查询语义

- POI 总量按 `pois` 行计数；候选区计数使用 `ST_Covers`，因此包含 Polygon 边界上的点。
- Coffee Shop 与 Café 使用 `venue_category` 大小写敏感的精确匹配，不做模糊归类。
- 历史签到按 `checkins.venue_id = pois.venue_id` 关联后逐条计数；无法关联 POI 的记录不进入候选区计数。
- session 不一致数量按每个 `sessions.session_id` 的实际关联 checkin 行数与 `checkin_count` 比较。
- 索引检查接受以所需列为最左前缀的 B-tree，并单独要求 `pois.geom` 的 GIST。

## 解释边界

本报告只核验历史开放空间数据与签到样本的完整性和候选区内样本计数。候选区是统一规则生成的站点周边 1 km 分析区，不是官方商圈边界；这些结果不构成当前经营表现或未来结果的承诺。
