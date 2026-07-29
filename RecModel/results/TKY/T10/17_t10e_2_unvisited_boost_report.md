# T10e-2: High-confidence Unvisited Boost — 实验报告

**日期**: 2026-07-07  **数据集**: Foursquare TKY
**T9 Baseline**: Test HR@5=49.01%

---

## 一、方法说明

### 1.1 核心思想

在 T10e-1 Visited/Unvisited 分流基础上，对 Unvisited 候选进一步区分：
- **高置信度 Unvisited**（explore_score ≥ 阈值）：给予更强 boost + 固定加分 τ
- **低置信度 Unvisited**（explore_score < 阈值）：保留较弱探索信号

目标是恢复 T10e-1 中受损的 Unseen HR@5，同时保住 Seen 和 NDCG 收益。

### 1.2 分数公式

```
base_score(i) = α*norm_t9(i) + β*poi_transition(i) + γ*intent_geo(i) + δ*local_pop(i)
explore_score(i) = β*poi_transition(i) + γ*intent_geo(i) + δ*local_pop(i)

if candidate_i in user_causal_history:
    final_score(i) = base_score(i) + ρ_seen * revisit_frequency_score(i)
else:
    if explore_score(i) >= explore_threshold:
        final_score(i) = base_score(i) + η_high * explore_score(i) + τ_unvisited
    else:
        final_score(i) = base_score(i) + η_low  * explore_score(i)
```

### 1.3 核心参数

- **explore_threshold**: Val Unvisited 候选 explore_score 的 Q90 分位数
  (阈值 = 0.037339)
- **η_high**: 高置信度 Unvisited 探索权重
- **η_low**: 低置信度 Unvisited 探索权重
- **τ_unvisited**: 高置信度 Unvisited 固定加分
- **ρ_seen**: Visited 候选 revisit 权重（frequency 归一化）

### 1.4 分阶段搜索

**Stage A**: 固定 ρ=0.15, η_low=0.10, τ=0.02，搜索 η_high × threshold_quantile
  - η_high ∈ [0.15, 0.20, 0.25, 0.30, 0.40]
  - threshold_quantile ∈ [50, 60, 70, 80, 90]
  - 组合数: 5×5=25

**Stage B**: 固定 Stage A 最佳 η_high/threshold，搜索 ρ_seen × η_low × τ
  - ρ_seen ∈ [0.10, 0.12, 0.15, 0.18]
  - η_low ∈ [0.05, 0.08, 0.10]
  - τ_unvisited ∈ [0.00, 0.01, 0.02, 0.03, 0.05]
  - 组合数: 4×3×5=60

**Stage C**: 在最佳配置附近微调

固定参数：K=100, norm=zscore, α=1.0, β=0.062, γ=0.10, δ=0.05, revisit_type=frequency

---

## 二、Strict Protocol

| 规则 | 状态 |
|------|------|
| Memory 仅由 train 构建 | ✅ |
| Causal history per-sample time-constrained | ✅ |
| 不使用 target_time 之后的信息 | ✅ |
| val 仅用于超参选择 | ✅ |
| test 仅评估一次 | ✅ |
| 不改变 T9 主干 | ✅ |
| Full-ranking → top-K rerank | ✅ |
| 无 GNN / 无大参数 | ✅ |
| 无训练，eval-only | ✅ |

---

## 三、Val 网格搜索

总组合数: 3 (Stage A: 1, Stage B: 1, Stage C: 1)

### 3.1 Explore Score 分布 (Val Unvisited Candidates)

- **Q90**: 0.037339 ← **选中**

### 3.2 最佳配置

```json
{
  "K": 100,
  "norm": "zscore",
  "alpha": 1.0,
  "beta": 0.062,
  "gamma": 0.1,
  "delta": 0.05,
  "rho_seen": 0.2,
  "eta_low": 0.1,
  "eta_high": 0.15,
  "tau_unvisited": 0.0,
  "explore_threshold": 0.03733944892883301,
  "explore_threshold_quantile": 90,
  "revisit_type": "frequency",
  "best_val_hr5": 46.02,
  "best_val_seen_hr5": 69.79,
  "best_val_unseen_hr5": 12.29,
  "best_val_ndcg5": 0.3289
}
```

**最佳 Val HR@5**: 46.02% (T9 Val HR@5=44.18%)
**最佳 Val Seen HR@5**: 69.79%
**最佳 Val Unseen HR@5**: 12.29%
**最佳 Val NDCG@5**: 0.3289

### 3.3 Stage A Top-5 (η_high × threshold)

| # | η_high | Q | HR@5 | Seen HR@5 | Unseen HR@5 | NDCG@5 |
|---|--------|---|------|-----------|-------------|--------|
| 1 | 0.150 | 90 | 45.60% | 68.46% | 13.18% | 0.3265 |

### 3.4 Stage B Top-5 (ρ_seen × η_low × τ)

| # | ρ_seen | η_low | τ | HR@5 | Seen HR@5 | Unseen HR@5 | NDCG@5 |
|---|--------|-------|-----|------|-----------|-------------|--------|
| 1 | 0.200 | 0.100 | 0.000 | 46.02% | 69.79% | 12.29% | 0.3289 |

---

## 四、Test 评估结果

### 4.1 主要指标

| 指标 | T9 | V1 | V1.1 | V1.3 | T10e-1 | **T10e-2** | Δ vs T10e-1 |
|------|-----|-----|------|------|--------|-----------|-------------|
| HR@1 | 0.00% | 19.96% | 20.50% | 20.10% | 21.31% | **21.30%** | -0.01% |
| HR@5 | 49.01% | 49.35% | 51.07% | 50.39% | 50.54% | **50.86%** | +0.32% |
| HR@10 | 0.00% | 59.06% | 60.92% | 60.38% | 60.30% | **60.61%** | +0.31% |
| NDCG@5 | 0.0000 | - | - | - | 0.3693 | **0.3706** | +0.0013 |
| NDCG@10 | 0.0000 | - | - | - | 0.4011 | **0.4024** | +0.0013 |
| MRR@5 | 0.0000 | - | - | - | 0.3239 | **0.3247** | +0.0008 |
| MRR@10 | 0.0000 | - | - | - | 0.3372 | **0.3379** | +0.0007 |

### 4.2 Seen/Unseen 对比

| 指标 | T9 | V1 | V1.1 | T10e-1 | **T10e-2** | Δ vs T10e-1 | Δ vs T9 |
|------|-----|-----|------|--------|-----------|-------------|---------|
| Seen HR@5 | 71.11% | 70.68% | 75.66% | 73.62% | **74.37%** | +0.75% | +3.26% |
| Unseen HR@5 | 12.01% | 13.63% | 9.90% | 11.91% | **11.49%** | -0.42% | -0.52% |
| Seen HR@1 | - | - | - | 0.00% | **32.45%** | - | - |
| Unseen HR@1 | - | - | - | 0.00% | **2.63%** | - | - |
| Seen HR@10 | - | - | - | 0.00% | **85.00%** | - | - |
| Unseen HR@10 | - | - | - | 0.00% | **19.77%** | - | - |

### 4.3 Flip 分析（vs T9）

- T9 miss@5 → T10e-2 hit@5: **937**
- T9 hit@5 → T10e-2 miss@5: **387**
- **Net Gain vs T9: +550**

### 4.4 Flip 分析（vs T10e-1）

- T10e-1 miss@5 → T10e-2 hit@5: **28**
- T10e-1 hit@5 → T10e-2 miss@5: **14**
- **Net Gain vs T10e-1: +14**

### 4.5 Rank Change

- T9 mean rank: 29.75 → T10e-2: 28.63 (Δ=-1.12)
- Seen: T9=11.23 → T10e-2=9.59
- Unseen: T9=60.74 → T10e-2=60.50

### 4.6 Top-5 Visited/Unvisited 比例

- T10e-1: visited=73.7%, unvisited=26.3%
- T10e-2: visited=75.6%, unvisited=24.4%
- Δ visited ratio: +1.9pp

### 4.7 High-confidence Boost 诊断

- 触发 high-confidence boost 的样本数: 28776 / 29806 (96.5%)
- High-confidence unvisited 候选总数: 251555
- 平均每样本 high-conf 候选数: 8.4
- Unseen target 命中 high-confidence: 2882 / 11146 (25.9%)
- High-confidence target hit@5: 1131 / 2882 (39.2%)
- Unseen target top-5 命中: 1281 / 11146 (11.5%)

---

## 五、核心问题回答

| # | 问题 | 回答 |
|---|------|------|
| 1 | Overall HR@5: **50.86%** (T9=49.01%, T10e-1=50.54%) |
| 2 | Seen HR@5: **74.37%** (T10e-1=73.62%) |
| 3 | Unseen HR@5: **11.49%** (T9=12.01%, T10e-1=11.91%) |
| 4 | NDCG@5: **0.3706** (T9=0.3687, T10e-1=0.3693) |
| 5 | MRR@10: **0.3379** (T10e-1=0.3372) |
| 6 | T9 miss→T10e-2 hit: **937** |
| 7 | T9 hit→T10e-2 miss: **387** |
| 8 | Net gain vs T9: **+550** |
| 9 | High-confidence boost 是否恢复 Unseen: **否** (T10e-2=11.49% vs T10e-1=11.91%) |
| 10 | 是否伤害 Seen: **否** (T10e-2=74.37% vs T10e-1=73.62%) |
| 11 | 是否提升 NDCG/MRR: NDCG@5 ✅、MRR@10 ✅ |
| 12 | 新增参数量: **0** — 纯 rerank，无新增可学习参数 |
| 13 | 推理开销: **1018.1ms** |

---

## 六、案例研究

### 6.1 T10e-1 miss → T10e-2 hit（5 例）

| Target | Seen? | T10e-1 Rank | T10e-2 Rank | High-Conf? | 分析 |
|--------|-------|-------------|-------------|------------|------|
| 3057 | True | 6 | 5 | False | 综合效果 |
| 197 | True | 6 | 5 | False | 综合效果 |
| 325 | True | 6 | 4 | False | 综合效果 |
| 5694 | True | 6 | 5 | False | 综合效果 |
| 75 | True | 7 | 5 | False | 综合效果 |

### 6.2 T10e-1 hit → T10e-2 miss（5 例）

| Target | Seen? | T10e-1 Rank | T10e-2 Rank | 分析 |
|--------|-------|-------------|-------------|------|
| 415 | True | 5 | 6 | revisit 保护减弱 |
| 3990 | True | 5 | 6 | revisit 保护减弱 |
| 144 | True | 5 | 6 | revisit 保护减弱 |
| 2155 | True | 5 | 6 | revisit 保护减弱 |
| 310 | False | 4 | 6 | HC/Low 分割导致排序变化 |

---

## 七、与各版本对比总结

| 模型 | HR@5 | Seen HR@5 | Unseen HR@5 | NDCG@5 | MRR@10 | 特点 |
|------|------|-----------|-------------|--------|--------|------|
| T9 | 49.01% | 71.11% | 12.01% | 0.3687 | 0.3370 | 基线 |
| V1 | 49.35% | 70.68% | 13.63% | 0.3559 | 0.3233 | 轻量 rerank |
| V1.1 | 51.07% | 75.66% | 9.90% | 0.3715 | 0.3280 | revisit 统治 |
| V1.3 | 50.39% | 74.00% | 10.86% | 0.3699 | - | 分段权重 |
| T10e-1 | 50.54% | 73.62% | 11.91% | 0.3693 | 0.3372 | 分流 rerank |
| **T10e-2** | **50.86%** | **74.37%** | **11.49%** | **0.3706** | **0.3379** | HC Unvisited Boost |

---

## 八、输出文件

- Val Grid CSV: `results/TKY/T10/t10e_2_unvisited_boost_val_grid.csv`
- Test CSV: `results/TKY/T10/t10e_2_unvisited_boost_test_result.csv`
- 诊断 JSON: `t10e_2_unvisited_boost_diagnostics.json`
- 案例 CSV: `t10e_2_unvisited_boost_cases.csv`
- 报告: `results/TKY/T10/17_t10e_2_unvisited_boost_report.md`

---

*报告由 src/run_t10e_2_unvisited_boost.py 自动生成于 2026-07-07。所有分析以中文呈现。*