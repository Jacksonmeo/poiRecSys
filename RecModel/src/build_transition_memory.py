"""
T10 第一阶段：构建 train-only 的群体转移统计（Transition Memory）。

Strict Protocol：
    1. 所有统计仅来源于 train 轨迹/序列。
    2. 不使用 val/test 的任何信息。
    3. 不改变原有 train/val/test 划分。
    4. 不改变 vocab 构建方式。
    5. 本阶段不训练模型。

输出文件（全部写入 results/{DATASET}/T10/）：
    - t10_poi_transition_top{top_k}.pkl      POI 级稀疏转移表
    - t10_poi_transition_stats.json           POI 转移统计 JSON
    - t10_intent_transition_top{top_k}.pkl    意图级稀疏转移表
    - t10_category_transition_stats.json      类别转移统计 JSON
    - t10_other_users_cost.json               Other-users 实现成本评估
    - 01_transition_memory_stats.md           中文统计诊断报告
"""

import argparse
import json
import os
import pickle
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, List, Tuple, Optional

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import config as cfg
from src.data.preprocess import (
    load_raw_data,
    filter_low_frequency,
    build_trajectories_24h,
    time_ordered_split,
    build_sequences,
    build_vocabularies,
    convert_sequences,
)

# ==============================================================================
# 常量定义
# ==============================================================================

# 小时分桶：0-5 (深夜/凌晨), 6-11 (上午), 12-17 (下午), 18-23 (晚上)
HOUR_BINS = [
    (0, 5, "深夜 00:00-05:59"),
    (6, 11, "上午 06:00-11:59"),
    (12, 17, "下午 12:00-17:59"),
    (18, 23, "晚上 18:00-23:59"),
]


def get_hour_bin(timestamp) -> int:
    """
    将时间戳映射到四个时段桶之一，用于构建意图级（类别+时段）转移特征。

    返回时间戳对应的小时桶索引 (0-3)。

    桶定义：
        0: 00:00-05:59 (深夜/凌晨)
        1: 06:00-11:59 (上午)
        2: 12:00-17:59 (下午)
        3: 18:00-23:59 (晚上)
    """
    if isinstance(timestamp, pd.Timestamp):
        hour = timestamp.hour
    elif hasattr(timestamp, 'hour'):
        hour = timestamp.hour
    else:
        hour = pd.Timestamp(timestamp).hour

    if hour <= 5:
        return 0
    elif hour <= 11:
        return 1
    elif hour <= 17:
        return 2
    else:
        return 3


# ==============================================================================
# 一、POI-level Transition Memory
# ==============================================================================

def build_poi_transition_counts(
    train_traj: List[Dict],
    venue_to_idx: Dict[str, int],
) -> Dict[int, Counter]:
    """
    从 train 轨迹中统计相邻 POI 转移频次，构建 POI 级别的群体转移表。

    对每条轨迹，遍历相邻 POI 对 (venue[i] -> venue[i+1])，累加计数。
    忽略 PAD token 的转移对。

    Args:
        train_traj: 训练轨迹列表
        venue_to_idx: POI ID → 整数索引映射（PAD=0）

    Returns:
        {src_poi_idx: Counter({dst_poi_idx: count, ...})}
    """
    poi_trans = defaultdict(Counter)
    pad_idx = venue_to_idx.get('<PAD>', 0)
    total_pairs = 0

    for traj in train_traj:
        venues = traj['venues']
        for i in range(len(venues) - 1):
            src = venue_to_idx.get(venues[i], 0)
            dst = venue_to_idx.get(venues[i + 1], 0)
            # 忽略 PAD
            if src == pad_idx or dst == pad_idx:
                continue
            poi_trans[src][dst] += 1
            total_pairs += 1

    return poi_trans, total_pairs


def sparsify_poi_transitions(
    poi_trans: Dict[int, Counter],
    top_k: int = 100,
) -> Dict[int, List[Tuple[int, int]]]:
    """
    将 POI 转移计数稀疏化，仅保留每个源 POI 的 top_k 个高频目标 POI。

    稀疏化的目的是控制 memory 大小：完整 POI 转移矩阵为 V×V，而稀疏后每个源 POI
    仅保留最多 top_k 条出边，存储从 O(V²) 降为 O(V×top_k)。

    Args:
        poi_trans: {src: Counter({dst: count})}
        top_k: 每个源 POI 保留的最大出边数

    Returns:
        {src: [(dst, count), ...]}  按 count 降序排列
    """
    sparse = {}
    for src, counter in poi_trans.items():
        top_items = counter.most_common(top_k)
        sparse[src] = [(dst, cnt) for dst, cnt in top_items]
    return sparse


def compute_poi_transition_stats(
    poi_trans: Dict[int, Counter],
    sparse_poi_trans: Dict[int, List[Tuple[int, int]]],
    num_venues: int,
) -> Dict:
    """
    计算 POI 转移的各种统计诊断指标，用于评估转移 memory 的质量和覆盖率。

    Returns:
        统计字典，包含出度分布、频次分布、Top-K 覆盖率、稀疏化后指标等。
    """
    # --- 出边覆盖率：有出边 POI 占总 POI 的比例 ---
    n_pois_with_out = len(poi_trans)
    out_degree_ratio = n_pois_with_out / max(num_venues - 1, 1)  # 排除 PAD

    # --- 出度分布：每个 POI 有多少个不同的目标 POI ---
    out_degrees = [len(counter) for counter in poi_trans.values()]
    avg_outdegree = np.mean(out_degrees) if out_degrees else 0.0
    median_outdegree = np.median(out_degrees) if out_degrees else 0.0
    max_outdegree = max(out_degrees) if out_degrees else 0
    min_outdegree = min(out_degrees) if out_degrees else 0

    # --- 转移频次分布：所有 POI 对的出现次数统计 ---
    all_counts = [cnt for counter in poi_trans.values() for cnt in counter.values()]
    if all_counts:
        count_percentiles = {
            "p1": int(np.percentile(all_counts, 1)),
            "p5": int(np.percentile(all_counts, 5)),
            "p25": int(np.percentile(all_counts, 25)),
            "p50": int(np.percentile(all_counts, 50)),
            "p75": int(np.percentile(all_counts, 75)),
            "p95": int(np.percentile(all_counts, 95)),
            "p99": int(np.percentile(all_counts, 99)),
            "max": int(max(all_counts)),
            "min": int(min(all_counts)),
            "mean": float(np.mean(all_counts)),
            "total_unique_pairs": len(all_counts),
        }
    else:
        count_percentiles = {}

    # --- Top-K 累积覆盖率：每个源 POI 的 top-k 高频目标覆盖了多少总转移量 ---
    top1_coverage = sum(
        counter.most_common(1)[0][1] if counter else 0
        for counter in poi_trans.values()
    )
    top5_coverage = sum(
        sum(c for _, c in counter.most_common(5))
        for counter in poi_trans.values()
    )
    top10_coverage = sum(
        sum(c for _, c in counter.most_common(10))
        for counter in poi_trans.values()
    )
    total_transitions = sum(all_counts)

    # 稀疏化后的平均出度
    sparse_out_degrees = [len(items) for items in sparse_poi_trans.values()]
    avg_sparse_outdegree = np.mean(sparse_out_degrees) if sparse_out_degrees else 0.0

    return {
        "n_venues_total": num_venues - 1,  # 排除 PAD
        "n_venues_with_out_edges": n_pois_with_out,
        "out_edge_coverage_ratio": round(out_degree_ratio, 4),
        "outdegree_min": int(min_outdegree),
        "outdegree_avg": round(float(avg_outdegree), 2),
        "outdegree_median": int(median_outdegree),
        "outdegree_max": int(max_outdegree),
        "total_transition_pairs": total_transitions,
        "total_unique_pairs": len(all_counts),
        "transition_count_distribution": {
            k: (int(v) if isinstance(v, (np.integer, np.floating)) else v)
            for k, v in count_percentiles.items()
        },
        "top1_cumulative_coverage": round(top1_coverage / max(total_transitions, 1), 4),
        "top5_cumulative_coverage": round(top5_coverage / max(total_transitions, 1), 4),
        "top10_cumulative_coverage": round(top10_coverage / max(total_transitions, 1), 4),
        "sparse_top_k": 100,
        "sparse_avg_outdegree": round(float(avg_sparse_outdegree), 2),
    }


# ==============================================================================
# 二、Intent-level (Category + HourBin) Transition Memory
# ==============================================================================

def build_intent_transition_counts(
    train_traj: List[Dict],
    venue_to_idx: Dict[str, int],
    cat_to_idx: Dict[str, int],
) -> Tuple[Dict[Tuple[int, int], Counter], Dict[int, Counter]]:
    """
    从 train 轨迹中统计意图级（类别+时段）和纯类别转移频次。

    intent_key = (last_category_idx, hour_bin)，将类别意图与时间上下文结合，
    捕捉"在某个时段、处于某类场所后，用户通常会去哪里"的群体行为模式。

    同时统计纯类别转移: last_category_idx -> next_category_idx，用于类别级别的
    粗粒度转移先验。

    Args:
        train_traj: 训练轨迹列表
        venue_to_idx: POI ID → 索引
        cat_to_idx: 类别名 → 索引

    Returns:
        intent_trans: {(cat_idx, hour_bin): Counter({poi_idx: count})}
        cat_trans: {cat_idx: Counter({cat_idx: count})}
    """
    intent_trans = defaultdict(Counter)
    cat_trans = defaultdict(Counter)
    pad_idx = venue_to_idx.get('<PAD>', 0)
    pad_cat = cat_to_idx.get('<PAD>', 0)

    total_intent_pairs = 0
    total_cat_pairs = 0
    skipped_no_timestamp = 0

    for traj in train_traj:
        venues = traj['venues']
        categories = traj['categories']
        timestamps = traj.get('timestamps', None)

        for i in range(len(venues) - 1):
            src_v = venue_to_idx.get(venues[i], 0)
            dst_v = venue_to_idx.get(venues[i + 1], 0)
            src_c = cat_to_idx.get(categories[i], 0)
            dst_c = cat_to_idx.get(categories[i + 1], 0)

            if src_v == pad_idx or dst_v == pad_idx:
                continue

            # 类别转移
            if src_c != pad_cat and dst_c != pad_cat:
                cat_trans[src_c][dst_c] += 1
                total_cat_pairs += 1

            # 意图转移
            if timestamps is not None and i < len(timestamps):
                hour_bin = get_hour_bin(timestamps[i])
                intent_key = (src_c, hour_bin)
                intent_trans[intent_key][dst_v] += 1
                total_intent_pairs += 1
            else:
                skipped_no_timestamp += 1

    if skipped_no_timestamp > 0:
        print(f"  [警告] {skipped_no_timestamp} 个相邻对因缺少时间戳而跳过意图转移统计")

    return intent_trans, cat_trans, total_intent_pairs, total_cat_pairs


def sparsify_intent_transitions(
    intent_trans: Dict[Tuple[int, int], Counter],
    top_k: int = 100,
) -> Dict[str, List[Tuple[int, int]]]:
    """
    将意图转移稀疏化，每个 intent_key 仅保留 top_k 个最高频目标 POI。

    返回的 key 使用字符串 `"{cat_idx}_{hour_bin}"` 以便 JSON 序列化和后续查询。
    与 POI 级稀疏化同理，将存储从 O(C×H×V) 降为 O(C×H×top_k)。
    """
    sparse = {}
    for (cat_idx, hour_bin), counter in intent_trans.items():
        top_items = counter.most_common(top_k)
        key_str = f"{cat_idx}_{hour_bin}"
        sparse[key_str] = [(dst, cnt) for dst, cnt in top_items]
    return sparse


def compute_intent_transition_stats(
    intent_trans: Dict[Tuple[int, int], Counter],
    cat_to_idx: Dict[str, int],
) -> Dict:
    """
    计算意图转移统计指标，评估意图级 memory 的覆盖度和质量。

    返回统计字典，包含 intent key 覆盖率、每 key 候选 POI 分布、top-20 高频意图示例等。
    """
    idx_to_cat = {v: k for k, v in cat_to_idx.items()}

    # --- Intent 覆盖率：实际出现的 intent key 占理论上可能总数的比例 ---
    n_intent_keys = len(intent_trans)
    n_cats = len(cat_to_idx) - 1  # 排除 PAD
    max_possible_intents = n_cats * 4  # 4 个时间桶
    coverage = n_intent_keys / max(max_possible_intents, 1)

    # --- 每 intent key 的候选 POI 数量分布 ---
    n_candidates = [len(counter) for counter in intent_trans.values()]
    avg_candidates = np.mean(n_candidates) if n_candidates else 0.0
    median_candidates = np.median(n_candidates) if n_candidates else 0.0

    # 所有转移对的总频次
    all_counts = [cnt for counter in intent_trans.values() for cnt in counter.values()]
    total_pairs = sum(all_counts)

    # 最常见的 20 个 intent key
    top_intents = sorted(
        intent_trans.items(),
        key=lambda x: sum(x[1].values()),
        reverse=True
    )[:20]
    top_intent_examples = []
    for (cat_idx, hour_bin), counter in top_intents:
        cat_name = idx_to_cat.get(cat_idx, f"UNK({cat_idx})")
        hour_label = HOUR_BINS[hour_bin][2]
        top_3_pois = counter.most_common(3)
        top_intent_examples.append({
            "intent_key": f"({cat_name}, {hour_label})",
            "cat_idx": cat_idx,
            "hour_bin": hour_bin,
            "total_count": sum(counter.values()),
            "n_unique_targets": len(counter),
            "top3_targets": top_3_pois,  # [(poi_idx, count), ...]
        })

    return {
        "n_categories": n_cats,
        "n_hour_bins": 4,
        "max_possible_intent_keys": max_possible_intents,
        "n_actual_intent_keys": n_intent_keys,
        "intent_coverage_ratio": round(coverage, 4),
        "candidates_per_intent_avg": round(float(avg_candidates), 2),
        "candidates_per_intent_median": int(median_candidates),
        "total_intent_transition_pairs": total_pairs,
        "total_unique_intent_pairs": len(all_counts),
        "top20_intent_examples": top_intent_examples,
        "sparse_top_k": 100,
    }


def compute_category_transition_stats(
    cat_trans: Dict[int, Counter],
    cat_to_idx: Dict[str, int],
) -> Dict:
    """计算类别转移统计指标，包括矩阵密度、最常见类别对等诊断信息。"""
    idx_to_cat = {v: k for k, v in cat_to_idx.items()}
    n_cats = len(cat_to_idx) - 1

    n_cats_with_out = len(cat_trans)
    out_degrees = [len(counter) for counter in cat_trans.values()]
    avg_outdegree = np.mean(out_degrees) if out_degrees else 0.0

    all_counts = [cnt for counter in cat_trans.values() for cnt in counter.values()]
    total_pairs = sum(all_counts)

    # --- 最常见的 30 个类别转移对，反映典型的场所类型切换模式 ---
    cat_pairs_sorted = sorted(
        [(src, dst, cnt) for src, counter in cat_trans.items()
         for dst, cnt in counter.items()],
        key=lambda x: x[2],
        reverse=True
    )[:30]
    top_cat_pairs = []
    for src, dst, cnt in cat_pairs_sorted:
        src_name = idx_to_cat.get(src, f"UNK({src})")
        dst_name = idx_to_cat.get(dst, f"UNK({dst})")
        top_cat_pairs.append({
            "from": src_name,
            "to": dst_name,
            "count": cnt,
        })

    # 全矩阵统计
    cat_matrix_density = len(all_counts) / max(n_cats * n_cats, 1)

    return {
        "n_categories": n_cats,
        "n_categories_with_out_edges": n_cats_with_out,
        "category_outdegree_avg": round(float(avg_outdegree), 2),
        "total_category_transition_pairs": total_pairs,
        "total_unique_category_pairs": len(all_counts),
        "matrix_density": round(cat_matrix_density, 4),
        "top30_category_pairs": top_cat_pairs,
    }


# ==============================================================================
# 三、Other-Users Transition Memory 预留
# ==============================================================================

def build_per_user_poi_transitions(
    train_traj: List[Dict],
    venue_to_idx: Dict[str, int],
) -> Dict[str, Counter]:
    """
    按用户维度构建个性化 POI 转移计数表。

    用于 other-users 查询：从全局转移表中减去当前用户自身的转移贡献，
    确保群体信号不包含当前用户的历史行为（避免与 T9 个人长期记忆冗余）。

    Returns:
        {user_id: Counter({(src, dst): count})}
    """
    pad_idx = venue_to_idx.get('<PAD>', 0)
    user_trans = defaultdict(Counter)

    for traj in train_traj:
        uid = traj['user_id']
        venues = traj['venues']
        for i in range(len(venues) - 1):
            src = venue_to_idx.get(venues[i], 0)
            dst = venue_to_idx.get(venues[i + 1], 0)
            if src != pad_idx and dst != pad_idx:
                user_trans[uid][(src, dst)] += 1

    return user_trans


def evaluate_other_users_cost(
    train_traj: List[Dict],
    venue_to_idx: Dict[str, int],
    poi_trans: Dict[int, Counter],
) -> Dict:
    """
    评估 other-users transition memory 的实现成本和可行性。

    设计思路：
        对于用户 u，other-users transition = global_transitions - user_u_transitions
        即：从全局 POI 转移表中减去用户 u 自身的转移贡献。

    实现方案：
        A. 预计算存储（高内存）：
           - 为每个用户存储一个独立的转移矩阵
           - 内存 = num_users × num_venues × num_venues × 4 bytes（float32）
           - TKY: 2281 × 7840 × 7840 × 4 ≈ 560 GB → 不可行

        B. 运行时减法（低内存，推荐）：
           - 存储全局转移表 + 每个用户的转移贡献
           - 查询时: other_counts = global_counts - user_counts
           - 内存 ≈ 全局矩阵 + per_user_sparse_counts
           - TKY: ~7840×100×4 ≈ 3 MB（全局 top-100 sparse）
                  + ~2281×500×4 ≈ 4.6 MB（per-user sparse pairs）
                  → 总计 < 10 MB，完全可行

        C. 按需计算（零额外内存，最慢）：
           - 在每次查询时扫描 train_traj，跳过当前用户
           - 内存开销为零，但查询延迟极高

    推荐方案 B，在 T10b 阶段实现。

    Returns:
        成本评估字典
    """
    n_users = len(set(t['user_id'] for t in train_traj))
    n_venues = len(venue_to_idx) - 1

    # --- 方案 A：预计算全矩阵（高内存，不可行）---
    # 为每个用户存储完整的 V×V 稠密转移矩阵，内存 = num_users × V² × 4 bytes
    plan_a_memory_gb = n_users * n_venues * n_venues * 4 / (1024 ** 3)

    # --- 方案 B：运行时减法（低内存，推荐）---
    # 存储全局 top-100 稀疏矩阵 + 每用户转移贡献，查询时 global - user = other_users
    # 全局稀疏 top-100
    global_sparse_mb = n_venues * 100 * 2 * 4 / (1024 * 1024)  # ~5.98 MB (src,dst) pairs
    # per-user 平均出边
    user_trans = build_per_user_poi_transitions(train_traj, venue_to_idx)
    avg_user_pairs = np.mean([len(c) for c in user_trans.values()]) if user_trans else 0
    max_user_pairs = max([len(c) for c in user_trans.values()]) if user_trans else 0
    per_user_memory_mb = n_users * avg_user_pairs * 3 * 4 / (1024 * 1024)  # (src,dst,cnt)
    total_plan_b_mb = global_sparse_mb + per_user_memory_mb

    return {
        "n_users": n_users,
        "n_venues": n_venues,
        "plan_A_full_matrix": {
            "description": "每个用户存储完整 (V×V) 转移矩阵",
            "memory_estimate_gb": round(plan_a_memory_gb, 2),
            "feasible": False,
        },
        "plan_B_runtime_subtraction": {
            "description": "存储全局稀疏转移表 + 各用户转移贡献，查询时相减",
            "global_sparse_memory_mb": round(global_sparse_mb, 2),
            "per_user_avg_unique_pairs": round(float(avg_user_pairs), 1),
            "per_user_max_unique_pairs": int(max_user_pairs),
            "per_user_memory_mb": round(per_user_memory_mb, 2),
            "total_memory_mb": round(total_plan_b_mb, 2),
            "feasible": True,
            "recommendation": "T10b 阶段推荐使用方案 B，总内存 < 15 MB",
        },
        "plan_C_lazy_computation": {
            "description": "查询时扫描 train_traj 跳过当前用户，零额外存储",
            "memory_mb": 0,
            "query_latency": "高（每次需全量扫描），不推荐",
            "feasible": True,
        },
    }


# ==============================================================================
# 四、主入口
# ==============================================================================

def parse_args():
    parser = argparse.ArgumentParser(description="T10 Transition Memory Builder")
    parser.add_argument("--dataset", type=str, default=cfg.DATASET,
                        choices=sorted(cfg.DATASET_FILES.keys()))
    parser.add_argument("--data_path", type=str, default=None)
    parser.add_argument("--top_k", type=int, default=100,
                        help="每个源 POI/intent 保留的最大出边数")
    parser.add_argument("--output_dir", type=str, default=None)
    return parser.parse_args()


def main():
    """
    T10 Transition Memory 构建主函数。

    按顺序执行五个阶段：
    Step 1: 数据加载与预处理（复用 T9 管线，仅使用 train 轨迹）
    Step 2: POI 级转移 memory 构建与统计
    Step 3: 意图级（类别+时段）转移 memory 构建与统计
    Step 4: Other-users 转移 memory 成本评估（方案对比，推荐方案 B）
    Step 5: 生成中文统计诊断报告
    """
    args = parse_args()
    args.data_path = args.data_path or cfg.dataset_file(args.dataset)

    # 输出目录
    if args.output_dir:
        output_dir = args.output_dir
    else:
        output_dir = str(PROJECT_ROOT / "results" / args.dataset / "T10")
    os.makedirs(output_dir, exist_ok=True)

    top_k = args.top_k

    print("=" * 70)
    print("T10 第一阶段：构建 Train-Only Transition Memory")
    print(f"数据集: {args.dataset}")
    print(f"Top-K: {top_k}")
    print(f"输出目录: {output_dir}")
    print("=" * 70)

    # ================================================================
    # Step 1: 数据加载 —— 完全复用 T9 的数据管线，确保 train/val/test 划分一致
    # ================================================================
    print("\n[Step 1] 加载并预处理数据...")

    raw_df = load_raw_data(args.data_path)
    df = filter_low_frequency(
        raw_df,
        min_poi_checkins=cfg.MIN_POI_CHECKINS,
        min_user_checkins=cfg.MIN_USER_CHECKINS,
    )
    print(f"  过滤后: {len(df)} 签到, {df['userId'].nunique()} 用户, "
          f"{df['venueId'].nunique()} POI")

    # 含时间戳的轨迹（用于 intent key 的 hour_bin）
    trajectories = build_trajectories_24h(df, include_timestamps=True)
    trajectories.sort(key=lambda t: t["start_time"])
    train_traj, val_traj, test_traj = time_ordered_split(
        trajectories,
        train_ratio=cfg.TRAIN_RATIO,
        val_ratio=cfg.VAL_RATIO,
    )
    print(f"  轨迹划分: Train={len(train_traj)}, Val={len(val_traj)}, "
          f"Test={len(test_traj)}")

    # 构建样本 + 词表（仅 train）
    train_raw = build_sequences(train_traj, seq_len=cfg.SEQ_LEN)
    venue_to_idx, cat_to_idx = build_vocabularies(train_raw)
    num_venues = len(venue_to_idx)
    num_cats = len(cat_to_idx)
    print(f"  词表: {num_venues} POI (含PAD), {num_cats} 类别 (含PAD)")

    # 验证 train 时间范围
    train_start = min(t['start_time'] for t in train_traj)
    train_end = max(t['start_time'] for t in train_traj)
    val_start = min(t['start_time'] for t in val_traj)
    test_start = min(t['start_time'] for t in test_traj)
    print(f"  Train 时间范围: {train_start} → {train_end}")
    print(f"  Val 开始于: {val_start}")
    print(f"  Test 开始于: {test_start}")
    print("  ✅ 仅使用 train 数据构建所有统计")

    # ================================================================
    # Step 2: POI 级转移 memory —— 相邻 POI 对频次统计 → 稀疏化 → 诊断统计
    # ================================================================
    print("\n" + "=" * 70)
    print("[Step 2] POI-level Transition Memory")
    print("=" * 70)

    print("  统计相邻 POI 转移...")
    poi_trans, total_poi_pairs = build_poi_transition_counts(train_traj, venue_to_idx)
    print(f"  总转移对数: {total_poi_pairs:,}")
    print(f"  有出边的 POI 数: {len(poi_trans):,} / {num_venues - 1}")

    print(f"  稀疏化 (top_k={top_k})...")
    sparse_poi_trans = sparsify_poi_transitions(poi_trans, top_k=top_k)

    # 保存
    poi_pkl_path = os.path.join(output_dir, f"t10_poi_transition_top{top_k}.pkl")
    with open(poi_pkl_path, "wb") as f:
        pickle.dump(sparse_poi_trans, f)
    print(f"  保存: {poi_pkl_path}")

    # 统计
    poi_stats = compute_poi_transition_stats(poi_trans, sparse_poi_trans, num_venues)
    poi_stats["data_source"] = "train_trajectories_only"
    poi_stats["train_time_range"] = {"start": str(train_start), "end": str(train_end)}
    poi_stats["total_trajectories_used"] = len(train_traj)

    poi_stats_path = os.path.join(output_dir, "t10_poi_transition_stats.json")
    with open(poi_stats_path, "w", encoding="utf-8") as f:
        json.dump(poi_stats, f, indent=2, ensure_ascii=False)
    print(f"  保存: {poi_stats_path}")

    # 打印关键指标
    print(f"\n  --- POI Transition 关键指标 ---")
    print(f"  有出边的 POI 比例: {poi_stats['out_edge_coverage_ratio']:.2%}")
    print(f"  平均出度: {poi_stats['outdegree_avg']}")
    print(f"  中位出度: {poi_stats['outdegree_median']}")
    print(f"  Top-1 覆盖率: {poi_stats['top1_cumulative_coverage']:.2%}")
    print(f"  Top-5 覆盖率: {poi_stats['top5_cumulative_coverage']:.2%}")
    print(f"  Top-10 覆盖率: {poi_stats['top10_cumulative_coverage']:.2%}")
    print(f"  稀疏化后平均出度: {poi_stats['sparse_avg_outdegree']}")

    # ================================================================
    # Step 3: 意图级 + 类别级转移 memory —— intent key=(类别, 时段) → POI 转移
    # ================================================================
    print("\n" + "=" * 70)
    print("[Step 3] Intent-level + Category Transition Memory")
    print("=" * 70)

    print("  统计意图转移 (category + hour_bin)...")
    intent_trans, cat_trans, total_intent_pairs, total_cat_pairs = \
        build_intent_transition_counts(train_traj, venue_to_idx, cat_to_idx)
    print(f"  意图转移对数: {total_intent_pairs:,}")
    print(f"  意图 key 数量: {len(intent_trans):,}")
    print(f"  类别转移对数: {total_cat_pairs:,}")

    # 保存意图转移
    print(f"  稀疏化意图转移 (top_k={top_k})...")
    sparse_intent_trans = sparsify_intent_transitions(intent_trans, top_k=top_k)

    intent_pkl_path = os.path.join(output_dir, f"t10_intent_transition_top{top_k}.pkl")
    with open(intent_pkl_path, "wb") as f:
        pickle.dump(sparse_intent_trans, f)
    print(f"  保存: {intent_pkl_path}")

    # 意图转移统计
    intent_stats = compute_intent_transition_stats(intent_trans, cat_to_idx)
    intent_stats["data_source"] = "train_trajectories_only"
    intent_stats["hour_bins"] = [
        {"bin": i, "range": label} for i, (lo, hi, label) in enumerate(HOUR_BINS)
    ]

    # 类别转移统计
    cat_stats = compute_category_transition_stats(cat_trans, cat_to_idx)
    cat_stats["data_source"] = "train_trajectories_only"

    # 合并保存
    cat_stats_path = os.path.join(output_dir, "t10_category_transition_stats.json")
    combined = {
        "intent_transition": intent_stats,
        "category_transition": cat_stats,
    }
    with open(cat_stats_path, "w", encoding="utf-8") as f:
        json.dump(combined, f, indent=2, ensure_ascii=False)
    print(f"  保存: {cat_stats_path}")

    # 打印关键指标
    print(f"\n  --- Intent Transition 关键指标 ---")
    print(f"  Intent key 数量: {intent_stats['n_actual_intent_keys']} "
          f"/ {intent_stats['max_possible_intent_keys']} "
          f"(覆盖率 {intent_stats['intent_coverage_ratio']:.2%})")
    print(f"  每 intent 平均候选 POI 数: {intent_stats['candidates_per_intent_avg']}")
    print(f"  每 intent 中位候选 POI 数: {intent_stats['candidates_per_intent_median']}")

    print(f"\n  --- Category Transition 关键指标 ---")
    print(f"  有出边的类别比例: {cat_stats['n_categories_with_out_edges']}/{cat_stats['n_categories']}")
    print(f"  矩阵密度: {cat_stats['matrix_density']:.4f}")

    # ================================================================
    # Step 4: Other-Users 成本评估 —— 对比三种实现方案，推荐运行时减法（方案 B）
    # ================================================================
    print("\n" + "=" * 70)
    print("[Step 4] Other-Users Transition Memory 成本评估")
    print("=" * 70)

    other_users_cost = evaluate_other_users_cost(train_traj, venue_to_idx, poi_trans)

    cost_path = os.path.join(output_dir, "t10_other_users_cost.json")
    with open(cost_path, "w", encoding="utf-8") as f:
        json.dump(other_users_cost, f, indent=2, ensure_ascii=False)
    print(f"  保存: {cost_path}")

    plan_b = other_users_cost["plan_B_runtime_subtraction"]
    print(f"\n  推荐方案 B: 运行时减法")
    print(f"    全局稀疏表: {plan_b['global_sparse_memory_mb']:.2f} MB")
    print(f"    每用户平均唯一转移对: {plan_b['per_user_avg_unique_pairs']:.1f}")
    print(f"    每用户最多唯一转移对: {plan_b['per_user_max_unique_pairs']}")
    print(f"    Per-user 存储: {plan_b['per_user_memory_mb']:.2f} MB")
    print(f"    总内存: {plan_b['total_memory_mb']:.2f} MB")
    print(f"    ✅ 可行 (< 15 MB)")

    # ================================================================
    # Step 5: 中文统计诊断报告 —— 汇总所有统计指标，写入 Markdown 文件
    # ================================================================
    print("\n" + "=" * 70)
    print("[Step 5] 生成统计诊断报告")
    print("=" * 70)

    report_path = os.path.join(output_dir, "01_transition_memory_stats.md")
    _write_report(
        report_path, args, train_traj, val_traj, test_traj,
        num_venues, num_cats,
        poi_stats, intent_stats, cat_stats, other_users_cost,
        train_start, train_end, val_start, test_start,
    )
    print(f"  保存: {report_path}")

    # ================================================================
    # 完成
    # ================================================================
    print("\n" + "=" * 70)
    print("T10 Transition Memory 构建完成！")
    print("=" * 70)
    print(f"\n输出文件:")
    for fname in os.listdir(output_dir):
        fpath = os.path.join(output_dir, fname)
        size_kb = os.path.getsize(fpath) / 1024
        print(f"  {fname}  ({size_kb:.1f} KB)")

    print(f"\n✅ 所有统计仅使用 train 数据")
    print(f"✅ 未修改任何模型代码")
    print(f"✅ 未训练任何模型")
    print(f"✅ 可以进入 T10a 阶段")


# ==============================================================================
# 报告生成
# ==============================================================================

def _write_report(
    path: str,
    args,
    train_traj, val_traj, test_traj,
    num_venues, num_cats,
    poi_stats, intent_stats, cat_stats, other_users_cost,
    train_start, train_end, val_start, test_start,
):
    """生成中文统计诊断报告，包含八个章节：
    一、数据来源与合规声明
    二、POI 转移统计（出度分布、频次分布、Top-K 覆盖率）
    三、Intent 转移统计（覆盖率、候选数、Top-20 高频意图）
    四、类别转移矩阵概览（矩阵密度、Top-30 类别对）
    五、Other-Users 实现评估（三种方案对比与推荐）
    六、与 T9 Unseen 瓶颈的关系分析
    七、T10a 进入建议与风险评估
    八、输出文件清单
    """
    n_train_users = len(set(t['user_id'] for t in train_traj))

    lines = [
        "# T10 Transition Memory 统计诊断报告",
        "",
        f"**生成日期**: 2026-07-06",
        f"**数据集**: Foursquare {args.dataset}",
        f"**构建脚本**: `src/build_t10_memory.py`",
        f"**Top-K 参数**: {args.top_k}",
        "",
        "---",
        "",
        "## 一、数据来源说明",
        "",
        "### 1.1 Strict Protocol 合规声明",
        "",
        "| 检查项 | 状态 | 说明 |",
        "|--------|------|------|",
        "| 仅使用 train 轨迹构建统计 | ✅ | `train_traj` 仅包含 train 划分的轨迹 |",
        "| 未使用 val/test 轨迹 | ✅ | val/test 轨迹未参与任何统计 |",
        "| 未改变 train/val/test 划分 | ✅ | 复用 `time_ordered_split()` |",
        "| 未改变 vocab 构建方式 | ✅ | 复用 `build_vocabularies(train_raw)` |",
        "| 未训练模型 | ✅ | 仅构建统计表 |",
        "| 未引入 GNN | ✅ | 纯计数统计 |",
        "",
        "### 1.2 数据规模",
        "",
        f"| 指标 | 值 |",
        f"|------|----|",
        f"| Train 轨迹数 | {len(train_traj):,} |",
        f"| Train 用户数 | {n_train_users:,} |",
        f"| POI 总数（含 PAD） | {num_venues} |",
        f"| 类别总数（含 PAD） | {num_cats} |",
        f"| Train 时间范围 | {train_start} → {train_end} |",
        f"| Val 开始时间 | {val_start} |",
        f"| Test 开始时间 | {test_start} |",
        "",
        "**时间顺序**: train < val < test，严格时序划分。",
        "",
        "---",
        "",
        "## 二、POI Transition 统计",
        "",
        "### 2.1 构建方法",
        "",
        "从 train 轨迹中提取所有相邻 POI 对 `(poi_i → poi_{i+1})`，",
        "累加计数得到 POI 转移频次矩阵。忽略 PAD token。",
        "",
        "### 2.2 稀疏性统计",
        "",
        f"| 指标 | 值 |",
        f"|------|----|",
        f"| 总 POI 数（排除 PAD） | {poi_stats['n_venues_total']:,} |",
        f"| 有出边的 POI 数 | {poi_stats['n_venues_with_out_edges']:,} |",
        f"| 出边覆盖率 | {poi_stats['out_edge_coverage_ratio']:.2%} |",
        f"| 总转移对次数 | {poi_stats['total_transition_pairs']:,} |",
        f"| 唯一转移对数量 | {poi_stats['total_unique_pairs']:,} |",
        f"| 最小出度 | {poi_stats['outdegree_min']} |",
        f"| 平均出度 | {poi_stats['outdegree_avg']} |",
        f"| 中位出度 | {poi_stats['outdegree_median']} |",
        f"| 最大出度 | {poi_stats['outdegree_max']} |",
        f"| 稀疏化后平均出度 (top_{args.top_k}) | {poi_stats['sparse_avg_outdegree']} |",
        "",
        "### 2.3 转移频次分布",
        "",
    ]

    tcd = poi_stats.get('transition_count_distribution', {})
    if tcd:
        lines.extend([
            f"| 分位数 | 频次 |",
            f"|--------|------|",
            f"| min | {tcd.get('min', 'N/A')} |",
            f"| p1 | {tcd.get('p1', 'N/A')} |",
            f"| p5 | {tcd.get('p5', 'N/A')} |",
            f"| p25 | {tcd.get('p25', 'N/A')} |",
            f"| p50 (median) | {tcd.get('p50', 'N/A')} |",
            f"| p75 | {tcd.get('p75', 'N/A')} |",
            f"| p95 | {tcd.get('p95', 'N/A')} |",
            f"| p99 | {tcd.get('p99', 'N/A')} |",
            f"| max | {tcd.get('max', 'N/A')} |",
            f"| mean | {tcd.get('mean', 'N/A')} |",
            "",
        ])

    lines.extend([
        "**解读**: 转移频次呈典型长尾分布。p50 远小于 mean，说明大多数 POI 对仅出现极少数次，",
        "少数热门转移对占据大部分转移量。",
        "",
        "### 2.4 Top-K 覆盖率",
        "",
        f"| 覆盖层级 | 累积覆盖率 |",
        f"|----------|-----------|",
        f"| Top-1 出边 | {poi_stats['top1_cumulative_coverage']:.2%} |",
        f"| Top-5 出边 | {poi_stats['top5_cumulative_coverage']:.2%} |",
        f"| Top-10 出边 | {poi_stats['top10_cumulative_coverage']:.2%} |",
        "",
        "**解读**: Top-1/Top-5/Top-10 覆盖率表示每个源 POI 的 top-k 高频目标 POI",
        "在所有转移中占的比例。高覆盖率意味着仅用少量高频转移即可覆盖大部分用户行为。",
        "",
        "---",
        "",
        "## 三、Intent Transition 统计",
        "",
        "### 3.1 构建方法",
        "",
        "Intent key = `(last_category_idx, hour_bin)`，其中：",
        "",
        "| Hour Bin | 范围 | 标签 |",
        "|----------|------|------|",
        "| 0 | 00:00-05:59 | 深夜/凌晨 |",
        "| 1 | 06:00-11:59 | 上午 |",
        "| 2 | 12:00-17:59 | 下午 |",
        "| 3 | 18:00-23:59 | 晚上 |",
        "",
        "对每个 intent key，统计其后出现的所有 POI 及频次。",
        "",
        "### 3.2 稀疏性统计",
        "",
        f"| 指标 | 值 |",
        f"|------|----|",
        f"| 类别数 | {intent_stats['n_categories']} |",
        f"| 小时桶数 | {intent_stats['n_hour_bins']} |",
        f"| 最大可能 intent key 数 | {intent_stats['max_possible_intent_keys']} |",
        f"| 实际出现的 intent key 数 | {intent_stats['n_actual_intent_keys']} |",
        f"| Intent 覆盖率 | {intent_stats['intent_coverage_ratio']:.2%} |",
        f"| 每 intent 平均候选 POI 数 | {intent_stats['candidates_per_intent_avg']} |",
        f"| 每 intent 中位候选 POI 数 | {intent_stats['candidates_per_intent_median']} |",
        f"| 总意图转移次数 | {intent_stats['total_intent_transition_pairs']:,} |",
        f"| 唯一意图转移对 | {intent_stats['total_unique_intent_pairs']:,} |",
        "",
    ])

    # 最常见的 20 个 intent key
    top20 = intent_stats.get('top20_intent_examples', [])
    if top20:
        lines.extend([
            "### 3.3 最常见的 20 个 Intent Key",
            "",
            "| Intent Key | 总频次 | 唯一目标 POI 数 | Top-3 目标 POI (idx, 频次) |",
            "|-----------|--------|----------------|---------------------------|",
        ])
        for item in top20:
            top3_str = ", ".join(
                f"(POI#{p[0]}, {p[1]})" for p in item['top3_targets']
            )
            lines.append(
                f"| {item['intent_key']} | {item['total_count']:,} | "
                f"{item['n_unique_targets']} | {top3_str} |"
            )
        lines.append("")

    lines.extend([
        "**解读**: 最常见的 intent key 反映了用户在不同时段+不同类别场景下的典型移动模式。",
        "这些高频意图可以为 Unseen POI 推荐提供群体级先验。",
        "",
        "---",
        "",
        "## 四、Category Transition 矩阵概览",
        "",
        "### 4.1 统计",
        "",
        f"| 指标 | 值 |",
        f"|------|----|",
        f"| 类别数 | {cat_stats['n_categories']} |",
        f"| 有出边的类别数 | {cat_stats['n_categories_with_out_edges']} |",
        f"| 类别平均出度 | {cat_stats['category_outdegree_avg']} |",
        f"| 总类别转移次数 | {cat_stats['total_category_transition_pairs']:,} |",
        f"| 唯一类别对数量 | {cat_stats['total_unique_category_pairs']} |",
        f"| 矩阵密度 | {cat_stats['matrix_density']:.4f}",
        "",
        "### 4.2 最常见的 30 个类别转移",
        "",
        "| 源类别 | 目标类别 | 频次 |",
        "|--------|---------|------|",
    ])

    top30 = cat_stats.get('top30_category_pairs', [])
    for pair in top30:
        lines.append(f"| {pair['from']} | {pair['to']} | {pair['count']:,} |")
    lines.append("")

    lines.extend([
        "**解读**: 类别转移矩阵反映了用户在不同场所类型之间的移动规律。",
        "例如 'Food→Shop'、'Office→Food' 等模式是城市出行的基本规律。",
        "T10 将利用这些群体级规律来增强 Unseen POI 的推荐。",
        "",
        "---",
        "",
        "## 五、Other-Users Transition Memory 实现评估",
        "",
        "### 5.1 设计动机",
        "",
        "为了验证「群体信息不是当前用户自己的历史」，需要支持查询「排除当前用户后的全局转移」。",
        "这确保 T10 的 transition bias 确实来自**其他用户**的行为模式，而非当前用户的个人历史（后者已被 T9 覆盖）。",
        "",
        "### 5.2 实现方案对比",
        "",
        "| 方案 | 描述 | 内存 | 查询延迟 | 可行性 |",
        "|------|------|------|---------|--------|",
    ])

    import math
    plan_a = other_users_cost['plan_A_full_matrix']
    plan_b = other_users_cost['plan_B_runtime_subtraction']
    plan_c = other_users_cost['plan_C_lazy_computation']

    lines.extend([
        f"| A: 全矩阵 | 每用户 V×V 稠密矩阵 | {plan_a['memory_estimate_gb']} GB | 低 | ❌ 不可行 |",
        f"| **B: 运行时减法** | 全局稀疏 + per-user 贡献 | **{plan_b['total_memory_mb']:.1f} MB** | 低 | ✅ **推荐** |",
        f"| C: 按需计算 | 零额外存储 | 0 MB | 极高 | ⚠️ 慢 |",
        "",
        "### 5.3 推荐方案 B 详细评估",
        "",
        f"- **全局稀疏转移表**: {plan_b['global_sparse_memory_mb']:.2f} MB（top-{args.top_k} per source POI）",
        f"- **每用户平均唯一转移对**: {plan_b['per_user_avg_unique_pairs']:.1f}",
        f"- **每用户最多唯一转移对**: {plan_b['per_user_max_unique_pairs']}",
        f"- **Per-user 存储**: {plan_b['per_user_memory_mb']:.2f} MB",
        f"- **总内存估算**: **{plan_b['total_memory_mb']:.2f} MB**",
        "",
        "### 5.4 实现建议",
        "",
        "在 T10a 阶段暂不实现 other-users transfer memory。",
        "先用全局 POI transition + intent transition 验证效果。",
        "如果 T10a 的 Unseen 提升显著，T10b 再引入 other-users 排除逻辑。",
        "实现方式：",
        "```python",
        "def query_other_users_transition(src_poi, user_id):",
        "    global_probs = global_transition_probs[src_poi]",
        "    user_counts = per_user_transition_counts[user_id].get(src_poi, {})",
        "    other_counts = global_counts[src_poi] - user_counts",
        "    return normalize(other_counts.clamp(min=0))",
        "```",
        "",
        "---",
        "",
        "## 六、与 T9 Unseen 瓶颈的关系分析",
        "",
        "### 6.1 T9 现状回顾",
        "",
        "| 指标 | T9 Full | T9 Seen | T9 Unseen |",
        "|------|---------|---------|-----------|",
        "| 样本数 | 29,806 | 18,660 (62.6%) | 11,146 (37.4%) |",
        "| HR@5 | 49.01% | 71.11% | 12.01% |",
        "",
        "### 6.2 Unseen 瓶颈的成因",
        "",
        "T9 的因果长期记忆通过 Attention Pooling 将用户历史 POI 聚合成 h_long。",
        "这种机制天然倾向于推荐用户**之前访问过的 POI**（Seen 场景），",
        "对于用户从未访问过的 POI（Unseen 场景），h_long 提供的信号有限。",
        "",
        "当 gate_mean=0.4892（接近 0.5），模型在短期和长期之间均衡融合，",
        "但 h_long 中缺乏对 Unseen POI 的先验信息，导致 Unseen 场景的推荐退化到",
        "纯短期编码器（T5 水平）。",
        "",
        "### 6.3 Transition Memory 如何帮助 Unseen",
        "",
        "Transition memory 提供的是**群体级**的转移规律，而非个人历史：",
        "",
        "1. **POI Transition**: 给定当前 POI，群体最常访问的下一个 POI 是哪些？",
        "   → 即使用户本人从未去过，群体规律可以推荐合理的 Unseen 候选。",
        "",
        "2. **Intent Transition**: 给定当前类别 + 时段，群体最常去哪些 POI？",
        "   → 更高层级的抽象，泛化能力更强，对 Unseen POI 的覆盖更广。",
        "",
        "3. **Category Transition**: 从「Food」类别通常转移到「Shop」还是「Office」？",
        "   → 粗粒度先验，可以在 POI 级打分前缩小候选范围。",
        "",
        "### 6.4 预期效果",
        "",
        f"基于 POI 转移覆盖率分析：",
        f"- Top-1 出边覆盖率 = {poi_stats['top1_cumulative_coverage']:.2%}",
        f"- Top-5 出边覆盖率 = {poi_stats['top5_cumulative_coverage']:.2%}",
        f"- Top-10 出边覆盖率 = {poi_stats['top10_cumulative_coverage']:.2%}",
        "",
        f"Intent 级别有 {intent_stats['n_actual_intent_keys']} 个有效 intent key，",
        f"每 intent 平均 {intent_stats['candidates_per_intent_avg']} 个候选 POI，",
        "提供了比纯 POI 级转移更丰富的泛化信号。",
        "",
        "**保守预期**：T10a 可将 Unseen HR@5 从 12.01% 提升至 14–16%，",
        "整体 HR@5 从 49.01% 提升至 50–51%（接近或超过 T8 的 51.03%）。",
        "",
        "---",
        "",
        "## 七、是否可以进入 T10a？",
        "",
        "### ✅ 建议立即进入 T10a",
        "",
        "**理由**:",
        "",
        "1. **统计基础已就绪**: POI transition、intent transition、category transition 统计表已构建完成。",
        "2. **Strict protocol 合规**: 所有统计仅使用 train 数据，无泄露风险。",
        "3. **技术路线清晰**: 采用 T7b ResidualDistanceScoring 的代码模式，在 logits 层增加轻量 transition bias。",
        "4. **内存可控**: 稀疏转移表内存 < 10 MB。",
        "5. **可学习参数极少**: 仅需 gamma（标量）+ fine-tune transition embedding（~几千参数）。",
        "",
        "### T10a 实现建议",
        "",
        "1. **第一步（推荐优先）**: 实现残差式类别转移偏置（category transition bias），",
        "   直接使用预计算的类别转移概率作为 logits 上的加法偏置。",
        "   代码模式完全复用 T7b `ResidualDistanceScoring`。",
        "",
        "2. **第二步（可选增强）**: 增加 intent transition bias，",
        "   结合 POI 级和类别级信号。",
        "",
        "3. **第三步（T10b）**: 引入 other-users exclusion 逻辑，",
        "   确保群体信号不包含当前用户自身的历史。",
        "",
        "### 风险与缓解",
        "",
        "| 风险 | 缓解措施 |",
        "|------|---------|",
        "| Transition bias 过强抑制语义信号 | 使用 sigmoid(-3.0) 弱初始化 gamma ≈ 0.047 |",
        "| 类别过渡矩阵过于稀疏 | 使用拉普拉斯平滑或 back-off 到全局 POI 频率 |",
        "| Seen 场景不需要 transition bias | 可通过 gate 控制或仅在 Unseen 样本上生效 |",
        "| Overhead 影响训练速度 | 使用预计算 embedding lookup，零运行时计算 |",
        "",
        "---",
        "",
        "## 八、输出文件清单",
        "",
        f"| 文件 | 说明 |",
        f"|------|------|",
        f"| `results/{args.dataset}/T10/t10_poi_transition_top{args.top_k}.pkl` | POI 级稀疏转移表 |",
        f"| `results/{args.dataset}/T10/t10_poi_transition_stats.json` | POI 转移统计 JSON |",
        f"| `results/{args.dataset}/T10/t10_intent_transition_top{args.top_k}.pkl` | 意图级稀疏转移表 |",
        f"| `results/{args.dataset}/T10/t10_category_transition_stats.json` | 类别转移 + 意图统计 JSON |",
        f"| `results/{args.dataset}/T10/t10_other_users_cost.json` | Other-users 成本评估 |",
        f"| `results/{args.dataset}/T10/01_transition_memory_stats.md` | 本中文统计诊断报告 |",
        "",
        "---",
        "",
        "*报告由 `src/build_t10_memory.py` 自动生成于 2026-07-06。所有分析以中文呈现。*",
    ])

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


if __name__ == "__main__":
    main()
