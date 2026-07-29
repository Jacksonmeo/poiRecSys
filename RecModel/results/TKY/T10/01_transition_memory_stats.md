# T10 Transition Memory 统计诊断报告

**生成日期**: 2026-07-06
**数据集**: Foursquare TKY
**构建脚本**: `src/build_t10_memory.py`
**Top-K 参数**: 100

---

## 一、数据来源说明

### 1.1 Strict Protocol 合规声明

| 检查项 | 状态 | 说明 |
|--------|------|------|
| 仅使用 train 轨迹构建统计 | ✅ | `train_traj` 仅包含 train 划分的轨迹 |
| 未使用 val/test 轨迹 | ✅ | val/test 轨迹未参与任何统计 |
| 未改变 train/val/test 划分 | ✅ | 复用 `time_ordered_split()` |
| 未改变 vocab 构建方式 | ✅ | 复用 `build_vocabularies(train_raw)` |
| 未训练模型 | ✅ | 仅构建统计表 |
| 未引入 GNN | ✅ | 纯计数统计 |

### 1.2 数据规模

| 指标 | 值 |
|------|----|
| Train 轨迹数 | 52,400 |
| Train 用户数 | 2,281 |
| POI 总数（含 PAD） | 7840 |
| 类别总数（含 PAD） | 187 |
| Train 时间范围 | 2012-04-03 19:12:07 → 2012-12-14 11:43:20 |
| Val 开始时间 | 2012-12-14 11:44:54 |
| Test 开始时间 | 2013-01-14 06:26:26 |

**时间顺序**: train < val < test，严格时序划分。

---

## 二、POI Transition 统计

### 2.1 构建方法

从 train 轨迹中提取所有相邻 POI 对 `(poi_i → poi_{i+1})`，
累加计数得到 POI 转移频次矩阵。忽略 PAD token。

### 2.2 稀疏性统计

| 指标 | 值 |
|------|----|
| 总 POI 数（排除 PAD） | 7,839 |
| 有出边的 POI 数 | 7,823 |
| 出边覆盖率 | 99.80% |
| 总转移对次数 | 279,535 |
| 唯一转移对数量 | 113,915 |
| 最小出度 | 1 |
| 平均出度 | 14.56 |
| 中位出度 | 7 |
| 最大出度 | 1201 |
| 稀疏化后平均出度 (top_100) | 13.16 |

### 2.3 转移频次分布

| 分位数 | 频次 |
|--------|------|
| min | 1 |
| p1 | 1 |
| p5 | 1 |
| p25 | 1 |
| p50 (median) | 1 |
| p75 | 2 |
| p95 | 7 |
| p99 | 25 |
| max | 638 |
| mean | 2.4538910591230305 |

**解读**: 转移频次呈典型长尾分布。p50 远小于 mean，说明大多数 POI 对仅出现极少数次，
少数热门转移对占据大部分转移量。

### 2.4 Top-K 覆盖率

| 覆盖层级 | 累积覆盖率 |
|----------|-----------|
| Top-1 出边 | 22.39% |
| Top-5 出边 | 52.58% |
| Top-10 出边 | 66.38% |

**解读**: Top-1/Top-5/Top-10 覆盖率表示每个源 POI 的 top-k 高频目标 POI
在所有转移中占的比例。高覆盖率意味着仅用少量高频转移即可覆盖大部分用户行为。

---

## 三、Intent Transition 统计

### 3.1 构建方法

Intent key = `(last_category_idx, hour_bin)`，其中：

| Hour Bin | 范围 | 标签 |
|----------|------|------|
| 0 | 00:00-05:59 | 深夜/凌晨 |
| 1 | 06:00-11:59 | 上午 |
| 2 | 12:00-17:59 | 下午 |
| 3 | 18:00-23:59 | 晚上 |

对每个 intent key，统计其后出现的所有 POI 及频次。

### 3.2 稀疏性统计

| 指标 | 值 |
|------|----|
| 类别数 | 186 |
| 小时桶数 | 4 |
| 最大可能 intent key 数 | 744 |
| 实际出现的 intent key 数 | 662 |
| Intent 覆盖率 | 88.98% |
| 每 intent 平均候选 POI 数 | 123.04 |
| 每 intent 中位候选 POI 数 | 21 |
| 总意图转移次数 | 279,535 |
| 唯一意图转移对 | 81,453 |

### 3.3 最常见的 20 个 Intent Key

| Intent Key | 总频次 | 唯一目标 POI 数 | Top-3 目标 POI (idx, 频次) |
|-----------|--------|----------------|---------------------------|
| (Train Station, 上午 06:00-11:59) | 54,968 | 5007 | (POI#44, 2168), (POI#144, 2073), (POI#191, 1187) |
| (Train Station, 深夜 00:00-05:59) | 32,087 | 4214 | (POI#144, 1322), (POI#44, 1097), (POI#191, 678) |
| (Train Station, 晚上 18:00-23:59) | 24,348 | 2685 | (POI#44, 1031), (POI#191, 549), (POI#144, 481) |
| (Train Station, 下午 12:00-17:59) | 18,779 | 2994 | (POI#44, 666), (POI#144, 548), (POI#191, 522) |
| (Subway, 上午 06:00-11:59) | 11,476 | 2038 | (POI#144, 181), (POI#44, 172), (POI#89, 171) |
| (Subway, 深夜 00:00-05:59) | 7,367 | 1698 | (POI#44, 134), (POI#89, 107), (POI#4797, 90) |
| (Subway, 晚上 18:00-23:59) | 4,683 | 919 | (POI#3277, 98), (POI#98, 61), (POI#524, 56) |
| (Electronics Store, 上午 06:00-11:59) | 4,404 | 1343 | (POI#144, 324), (POI#44, 119), (POI#635, 94) |
| (Subway, 下午 12:00-17:59) | 3,840 | 1039 | (POI#89, 72), (POI#2714, 63), (POI#726, 55) |
| (Mall, 上午 06:00-11:59) | 3,290 | 1374 | (POI#44, 55), (POI#89, 47), (POI#210, 44) |
| (Bookstore, 上午 06:00-11:59) | 2,596 | 965 | (POI#144, 116), (POI#116, 72), (POI#635, 70) |
| (Food & Drink Shop, 上午 06:00-11:59) | 2,586 | 1149 | (POI#3274, 43), (POI#3147, 37), (POI#211, 32) |
| (Arcade, 上午 06:00-11:59) | 2,134 | 727 | (POI#144, 105), (POI#191, 82), (POI#44, 62) |
| (Convenience Store, 上午 06:00-11:59) | 2,040 | 876 | (POI#89, 25), (POI#144, 24), (POI#3245, 21) |
| (Hobby Shop, 上午 06:00-11:59) | 1,857 | 674 | (POI#144, 143), (POI#635, 55), (POI#44, 52) |
| (Electronics Store, 深夜 00:00-05:59) | 1,798 | 797 | (POI#144, 107), (POI#635, 47), (POI#4828, 33) |
| (Mall, 深夜 00:00-05:59) | 1,792 | 919 | (POI#1139, 47), (POI#144, 23), (POI#89, 23) |
| (Ramen /  Noodle House, 上午 06:00-11:59) | 1,753 | 920 | (POI#144, 86), (POI#44, 45), (POI#635, 31) |
| (Bar, 上午 06:00-11:59) | 1,748 | 754 | (POI#144, 117), (POI#44, 48), (POI#915, 36) |
| (Office, 深夜 00:00-05:59) | 1,660 | 733 | (POI#519, 36), (POI#4463, 33), (POI#144, 29) |

**解读**: 最常见的 intent key 反映了用户在不同时段+不同类别场景下的典型移动模式。
这些高频意图可以为 Unseen POI 推荐提供群体级先验。

---

## 四、Category Transition 矩阵概览

### 4.1 统计

| 指标 | 值 |
|------|----|
| 类别数 | 186 |
| 有出边的类别数 | 186 |
| 类别平均出度 | 42.45 |
| 总类别转移次数 | 279,535 |
| 唯一类别对数量 | 7895 |
| 矩阵密度 | 0.2282

### 4.2 最常见的 30 个类别转移

| 源类别 | 目标类别 | 频次 |
|--------|---------|------|
| Train Station | Train Station | 84,643 |
| Subway | Subway | 11,786 |
| Subway | Train Station | 7,602 |
| Train Station | Subway | 7,144 |
| Train Station | Convenience Store | 2,296 |
| Train Station | Electronics Store | 2,201 |
| Train Station | Mall | 2,155 |
| Convenience Store | Train Station | 2,095 |
| Electronics Store | Train Station | 1,940 |
| Train Station | Food & Drink Shop | 1,693 |
| Mall | Train Station | 1,671 |
| Train Station | Ramen /  Noodle House | 1,572 |
| Food & Drink Shop | Train Station | 1,478 |
| Ramen /  Noodle House | Train Station | 1,411 |
| Train Station | Bar | 1,312 |
| Train Station | Office | 1,284 |
| Train Station | Arcade | 1,272 |
| Train Station | Bus Station | 1,248 |
| Bar | Train Station | 1,219 |
| Bus Station | Train Station | 1,203 |
| Arcade | Train Station | 1,157 |
| Train Station | Bookstore | 1,103 |
| Office | Train Station | 1,103 |
| Train Station | Fast Food Restaurant | 1,054 |
| College Academic Building | College Academic Building | 1,008 |
| Electronics Store | Electronics Store | 1,005 |
| Train Station | Bridge | 989 |
| Bus Station | Bus Station | 977 |
| Train Station | Coffee Shop | 951 |
| Bookstore | Train Station | 950 |

**解读**: 类别转移矩阵反映了用户在不同场所类型之间的移动规律。
例如 'Food→Shop'、'Office→Food' 等模式是城市出行的基本规律。
T10 将利用这些群体级规律来增强 Unseen POI 的推荐。

---

## 五、Other-Users Transition Memory 实现评估

### 5.1 设计动机

为了验证「群体信息不是当前用户自己的历史」，需要支持查询「排除当前用户后的全局转移」。
这确保 T10 的 transition bias 确实来自**其他用户**的行为模式，而非当前用户的个人历史（后者已被 T9 覆盖）。

### 5.2 实现方案对比

| 方案 | 描述 | 内存 | 查询延迟 | 可行性 |
|------|------|------|---------|--------|
| A: 全矩阵 | 每用户 V×V 稠密矩阵 | 522.16 GB | 低 | ❌ 不可行 |
| **B: 运行时减法** | 全局稀疏 + per-user 贡献 | **7.9 MB** | 低 | ✅ **推荐** |
| C: 按需计算 | 零额外存储 | 0 MB | 极高 | ⚠️ 慢 |

### 5.3 推荐方案 B 详细评估

- **全局稀疏转移表**: 5.98 MB（top-100 per source POI）
- **每用户平均唯一转移对**: 71.8
- **每用户最多唯一转移对**: 578
- **Per-user 存储**: 1.87 MB
- **总内存估算**: **7.86 MB**

### 5.4 实现建议

在 T10a 阶段暂不实现 other-users transfer memory。
先用全局 POI transition + intent transition 验证效果。
如果 T10a 的 Unseen 提升显著，T10b 再引入 other-users 排除逻辑。
实现方式：
```python
def query_other_users_transition(src_poi, user_id):
    global_probs = global_transition_probs[src_poi]
    user_counts = per_user_transition_counts[user_id].get(src_poi, {})
    other_counts = global_counts[src_poi] - user_counts
    return normalize(other_counts.clamp(min=0))
```

---

## 六、与 T9 Unseen 瓶颈的关系分析

### 6.1 T9 现状回顾

| 指标 | T9 Full | T9 Seen | T9 Unseen |
|------|---------|---------|-----------|
| 样本数 | 29,806 | 18,660 (62.6%) | 11,146 (37.4%) |
| HR@5 | 49.01% | 71.11% | 12.01% |

### 6.2 Unseen 瓶颈的成因

T9 的因果长期记忆通过 Attention Pooling 将用户历史 POI 聚合成 h_long。
这种机制天然倾向于推荐用户**之前访问过的 POI**（Seen 场景），
对于用户从未访问过的 POI（Unseen 场景），h_long 提供的信号有限。

当 gate_mean=0.4892（接近 0.5），模型在短期和长期之间均衡融合，
但 h_long 中缺乏对 Unseen POI 的先验信息，导致 Unseen 场景的推荐退化到
纯短期编码器（T5 水平）。

### 6.3 Transition Memory 如何帮助 Unseen

Transition memory 提供的是**群体级**的转移规律，而非个人历史：

1. **POI Transition**: 给定当前 POI，群体最常访问的下一个 POI 是哪些？
   → 即使用户本人从未去过，群体规律可以推荐合理的 Unseen 候选。

2. **Intent Transition**: 给定当前类别 + 时段，群体最常去哪些 POI？
   → 更高层级的抽象，泛化能力更强，对 Unseen POI 的覆盖更广。

3. **Category Transition**: 从「Food」类别通常转移到「Shop」还是「Office」？
   → 粗粒度先验，可以在 POI 级打分前缩小候选范围。

### 6.4 预期效果

基于 POI 转移覆盖率分析：
- Top-1 出边覆盖率 = 22.39%
- Top-5 出边覆盖率 = 52.58%
- Top-10 出边覆盖率 = 66.38%

Intent 级别有 662 个有效 intent key，
每 intent 平均 123.04 个候选 POI，
提供了比纯 POI 级转移更丰富的泛化信号。

**保守预期**：T10a 可将 Unseen HR@5 从 12.01% 提升至 14–16%，
整体 HR@5 从 49.01% 提升至 50–51%（接近或超过 T8 的 51.03%）。

---

## 七、是否可以进入 T10a？

### ✅ 建议立即进入 T10a

**理由**:

1. **统计基础已就绪**: POI transition、intent transition、category transition 统计表已构建完成。
2. **Strict protocol 合规**: 所有统计仅使用 train 数据，无泄露风险。
3. **技术路线清晰**: 采用 T7b ResidualDistanceScoring 的代码模式，在 logits 层增加轻量 transition bias。
4. **内存可控**: 稀疏转移表内存 < 10 MB。
5. **可学习参数极少**: 仅需 gamma（标量）+ fine-tune transition embedding（~几千参数）。

### T10a 实现建议

1. **第一步（推荐优先）**: 实现残差式类别转移偏置（category transition bias），
   直接使用预计算的类别转移概率作为 logits 上的加法偏置。
   代码模式完全复用 T7b `ResidualDistanceScoring`。

2. **第二步（可选增强）**: 增加 intent transition bias，
   结合 POI 级和类别级信号。

3. **第三步（T10b）**: 引入 other-users exclusion 逻辑，
   确保群体信号不包含当前用户自身的历史。

### 风险与缓解

| 风险 | 缓解措施 |
|------|---------|
| Transition bias 过强抑制语义信号 | 使用 sigmoid(-3.0) 弱初始化 gamma ≈ 0.047 |
| 类别过渡矩阵过于稀疏 | 使用拉普拉斯平滑或 back-off 到全局 POI 频率 |
| Seen 场景不需要 transition bias | 可通过 gate 控制或仅在 Unseen 样本上生效 |
| Overhead 影响训练速度 | 使用预计算 embedding lookup，零运行时计算 |

---

## 八、输出文件清单

| 文件 | 说明 |
|------|------|
| `results/TKY/T10/t10_poi_transition_top100.pkl` | POI 级稀疏转移表 |
| `results/TKY/T10/t10_poi_transition_stats.json` | POI 转移统计 JSON |
| `results/TKY/T10/t10_intent_transition_top100.pkl` | 意图级稀疏转移表 |
| `results/TKY/T10/t10_category_transition_stats.json` | 类别转移 + 意图统计 JSON |
| `results/TKY/T10/t10_other_users_cost.json` | Other-users 成本评估 |
| `results/TKY/T10/01_transition_memory_stats.md` | 本中文统计诊断报告 |

---

*报告由 `src/build_t10_memory.py` 自动生成于 2026-07-06。所有分析以中文呈现。*