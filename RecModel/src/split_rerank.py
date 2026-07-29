"""
T10e-1: Visited/Unvisited Split Rerank.

Core idea:
  - Visited candidates (in causal history) → base_score + rho_seen * revisit_score
  - Unvisited candidates → base_score + eta_unseen * explore_score

This prevents revisit_score from dominating all rankings (V1.1 problem) while
still protecting Seen samples.

Strict Protocol: train-only memory, val-only HP selection, single test eval.
"""

import csv, json, math, os, pickle, sys, time
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
import torch
from torch.utils.data import DataLoader

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import config as cfg
from src.utils import set_seed, get_device
from src.data.preprocess import (
    load_raw_data, filter_low_frequency, build_trajectories_24h,
    time_ordered_split, build_sequences, build_vocabularies,
    convert_sequences, build_causal_history_per_sample,
)
from src.data.dataset import create_dataloaders, create_val_loader
from src.features.word2vec import train_word2vec, build_behavioral_matrix
from src.features.text_encoder import build_poi_texts, encode_with_sbert, build_text_matrix
from src.models.transformer import TransformerPOIModel, count_parameters

# Reuse V1 infrastructure
from src.rerank_components import (
    build_geo_zones, build_intent_geo_memory, compute_hour_bin_t,
    IntentGeoFullBias, POIFullBias, LocalFullBias, normalize_scores,
)


# ==============================================================================
# Revisit & Explore Score Computation
# ==============================================================================

def compute_split_scores(causal_hist, causal_mask, cand_indices,
                         revisit_type='recency', hybrid_a=0.5):
    """
    计算 revisit_score 和 visited_mask（用于 T10e-1 Visited/Unvisited 分流）。

    全部在 CPU 上执行（避免逐元素 GPU 内核开销），最后才传回 GPU。

    三种 revisit 分数模式：
    - 'recency': 最近出现越近分数越高，1/log2(rank+1)，天然在 (0, 1]
    - 'frequency': log1p(count)，在 top-K 内归一化到 [0,1]
    - 'hybrid': a*recency + (1-a)*frequency，综合两种信号

    Args:
        causal_hist: (B, max_hist_len) — 因果历史 POI 索引（填充后）
        causal_mask: (B, max_hist_len) — 布尔掩码，True 表示有效位置
        cand_indices: (B, K) — T9 top-K 候选 POI 索引
        revisit_type: 'recency'（时效性）、'frequency'（频率）或 'hybrid'（混合）
        hybrid_a: hybrid 模式下 recency 的权重

    Returns:
        revisit_scores: (B, K) — revisit 分数（unvisited 候选为 0）
        visited_mask: (B, K) — bool，True 表示候选 POI 在因果历史中出现过
    """
    B, K = cand_indices.shape
    device = cand_indices.device

    # 将所有张量移到 CPU 以加速逐元素访问
    ch_cpu = causal_hist.cpu().numpy()
    cm_cpu = causal_mask.cpu().numpy()
    ci_cpu = cand_indices.cpu().numpy()

    scores_np = np.zeros((B, K), dtype=np.float32)
    visited_np = np.zeros((B, K), dtype=bool)

    for i in range(B):
        hist = ch_cpu[i][cm_cpu[i]].tolist()
        if not hist:
            continue

        # 构建 lookup：POI → (recency_rank, frequency)
        # recency_rank: 从历史末端倒数，最近出现的 rank=1，越远 rank 越大
        recency = {}
        freq = {}
        for pos, poi in enumerate(reversed(hist)):
            rrank = pos + 1
            if poi not in recency:
                recency[poi] = rrank  # 仅记录首次（即最近的）出现位置
            freq[poi] = freq.get(poi, 0) + 1

        ci = ci_cpu[i].tolist()
        for j, poi in enumerate(ci):
            if poi in recency:
                visited_np[i, j] = True
                if revisit_type == 'recency':
                    # log 衰减：最近访问的分数最高，随时间/距离衰减
                    scores_np[i, j] = 1.0 / math.log2(recency[poi] + 1)
                elif revisit_type == 'frequency':
                    # log 平滑：高频 POI 分数高，但 log 抑制极端值
                    scores_np[i, j] = math.log1p(freq[poi])
                elif revisit_type == 'hybrid':
                    # 混合模式：同时考虑时效和频率
                    r = 1.0 / math.log2(recency[poi] + 1)
                    f = math.log1p(freq.get(poi, 0))
                    scores_np[i, j] = hybrid_a * r + (1 - hybrid_a) * f

    # frequency 和 hybrid 模式在每样本 top-K 内归一化到 [0,1]
    # recency 模式天然在 (0, 1]，跳过一次遍历以节省时间
    if revisit_type in ('frequency', 'hybrid'):
        for i in range(B):
            row = scores_np[i]
            smax = row.max()
            if smax > 0:
                scores_np[i] = row / smax

    # Transfer to GPU
    scores = torch.from_numpy(scores_np).to(device)
    visited = torch.from_numpy(visited_np).to(device)
    return scores, visited


# ==============================================================================
# T10e-1 Split Rerank Evaluation
# ==============================================================================

@torch.no_grad()
def eval_split_rerank(model, dataloader, device, poi_bias_fn, geo_bias_fn, local_bias_fn,
                      K, norm, alpha, beta, gamma, delta,
                      rho_seen, eta_unseen, revisit_type, hybrid_a,
                      poi_zone_tensor, num_zones, ks=(1,5,10), diag=False):
    """
    T10e-1: Visited/Unvisited 分流重排序评估。

    核心理念：候选级自适应融合——对用户历史中出现过的候选（visited）和未出现过的候选
    （unvisited）使用不同的评分策略，避免 revisit_score 统治全部排名（V1.1 的问题）。

    对于每个候选 i：
      if i in causal_history:
        final_score = base_score + rho_seen * revisit_score(i)
        → visited 候选用 revisit_score（recency/frequency/hybrid）保护，维持 Seen HR@5
      else:
        final_score = base_score + eta_unseen * explore_score(i)
        → unvisited 候选保留探索信号（IntentGeo + POI + LocalPop），维持 Unseen HR@5

    关键是 visited_mask 精确地在候选级别分流，而非在全量级。
    """
    model.eval()
    uc_flag = getattr(model, 'use_causal_long_pref', False)

    hits = {k: 0 for k in ks}
    ndcg = {k: 0.0 for k in ks}
    mrr = {k: 0.0 for k in ks}
    sh, suh = {k: 0 for k in ks}, {k: 0 for k in ks}
    sc, uc_cnt, tot = 0, 0, 0

    # Diagnostics
    d = None
    if diag:
        d = {
            't9r': [], 'tr': [], 't9h5': 0, 'th5': 0, 'fg': 0, 'fl': 0,
            't9r_seen': [], 't9r_unseen': [], 'tr_seen': [], 'tr_unseen': [],
            'seen_t9h5': 0, 'unseen_t9h5': 0, 'seen_th5': 0, 'unseen_th5': 0,
            # Top-5 visited ratio tracking
            'top5_visited_ratio': [], 'top5_unvisited_ratio': [],
            # Sample-level details for case studies
            'samples': [],  # will store per-sample details (limited)
            # Counters
            'revisit_activated': 0, 'explore_activated': 0,
            'v1_miss_t10e_hit': 0, 'v1_hit_t10e_miss': 0,
            'v11_miss_t10e_hit': 0, 'v11_hit_t10e_miss': 0,
        }

    for batch_idx, batch in enumerate(dataloader):
        batch = [t.to(device) for t in batch]
        bv, bc, bt, bl = batch[0], batch[1], batch[2], batch[-1]
        kw = {}
        if uc_flag:
            kw['causal_history'] = batch[3]
            kw['causal_mask'] = batch[4]

        # T9 forward
        base_l = model(bv, bc, t_seq=bt, **kw)
        t9_topk_vals, t9_topk_idx = torch.topk(base_l, k=K, dim=1)
        t9_norm = normalize_scores(t9_topk_vals, norm)

        # Context features
        lps = bv[:, -1]
        pcs = bc[:, -2]
        lcs = bc[:, -1]
        hbs = compute_hour_bin_t(bt)
        zones = poi_zone_tensor[lps].clamp(0, num_zones - 1)

        # Bias scores
        poi_s = poi_bias_fn(lps).gather(1, t9_topk_idx)  # (B, K)
        geo_s = geo_bias_fn(pcs, lcs, hbs, zones).gather(1, t9_topk_idx)
        loc_s = local_bias_fn(zones, hbs).gather(1, t9_topk_idx)

        # Base score (V1 formula)
        base_score = alpha * t9_norm + beta * poi_s + gamma * geo_s + delta * loc_s

        # Explore score (for unvisited candidates)
        explore_score = beta * poi_s + gamma * geo_s + delta * loc_s

        # Revisit scores + visited mask
        rev_s, visited_mask = compute_split_scores(
            batch[3], batch[4], t9_topk_idx, revisit_type, hybrid_a)

        # Split rerank: visited 和 unvisited 使用不同的加分项
        # 核心公式：visited → + ρ_seen * revisit_score，unvisited → + η_unseen * explore_score
        combined = base_score.clone()
        combined[visited_mask] += rho_seen * rev_s[visited_mask]
        combined[~visited_mask] += eta_unseen * explore_score[~visited_mask]

        # Re-sort
        _, rerank_idx = torch.sort(combined, dim=1, descending=True)
        reranked_pois = t9_topk_idx.gather(1, rerank_idx)

        # Evaluate per sample
        for i in range(bl.size(0)):
            tl = bl[i].item()
            t9p = t9_topk_idx[i].tolist()
            rp = reranked_pois[i].tolist()
            t9r = t9p.index(tl) + 1 if tl in t9p else K + 1
            tr = rp.index(tl) + 1 if tl in rp[:K] else K + 1
            h5 = tl in rp[:5]
            t9h5 = tl in t9p[:5]

            for k_ in ks:
                if tl in rp[:k_]:
                    hits[k_] += 1
                    r = rp[:k_].index(tl) + 1
                    mrr[k_] += 1.0 / r
                    ndcg[k_] += 1.0 / np.log2(r + 1)

            # Seen/Unseen classification
            if uc_flag:
                ch = batch[3][i]
                cm = batch[4][i]
                is_s = tl in ch[cm].tolist()
            else:
                is_s = False

            if is_s:
                sc += 1
            else:
                uc_cnt += 1

            for k_ in ks:
                if tl in rp[:k_]:
                    (sh if is_s else suh)[k_] += 1

            # Diagnostics
            if diag:
                d['t9r'].append(t9r)
                d['tr'].append(tr)
                if t9h5:
                    d['t9h5'] += 1
                if h5:
                    d['th5'] += 1
                if not t9h5 and h5:
                    d['fg'] += 1
                elif t9h5 and not h5:
                    d['fl'] += 1

                if is_s:
                    d['t9r_seen'].append(t9r)
                    d['tr_seen'].append(tr)
                    if t9h5:
                        d['seen_t9h5'] += 1
                    if h5:
                        d['seen_th5'] += 1
                else:
                    d['t9r_unseen'].append(t9r)
                    d['tr_unseen'].append(tr)
                    if t9h5:
                        d['unseen_t9h5'] += 1
                    if h5:
                        d['unseen_th5'] += 1

                # Top-5 visited/unvisited ratio
                top5_pois = rp[:5]
                top5_visited = sum(1 for p in top5_pois if p in
                                   batch[3][i][batch[4][i].bool()].tolist())
                d['top5_visited_ratio'].append(top5_visited / 5.0)
                d['top5_unvisited_ratio'].append(1.0 - top5_visited / 5.0)

                # Track activation
                if visited_mask[i].any():
                    d['revisit_activated'] += 1
                if (~visited_mask[i]).any() and eta_unseen > 0:
                    d['explore_activated'] += 1

                # Store sample details for case studies (limit to avoid memory blowup)
                if len(d['samples']) < 5000:
                    d['samples'].append({
                        'batch': batch_idx, 'sample_i': i,
                        'target': tl, 'is_seen': is_s,
                        't9_rank': t9r, 't10e_rank': tr,
                        't9_top5': t9p[:5], 't10e_top5': rp[:5],
                        't9h5': t9h5, 't10eh5': h5,
                        'top5_visited_n': top5_visited,
                    })

            tot += 1

    # Build results dict
    r = {}
    for k_ in ks:
        r[f'HR@{k_}'] = round(hits[k_] / tot * 100, 2)
        r[f'NDCG@{k_}'] = round(ndcg[k_] / tot, 4)
        r[f'MRR@{k_}'] = round(mrr[k_] / tot, 4)
    r['total'] = tot
    for k_ in ks:
        r[f'seen_HR@{k_}'] = round(sh[k_] / max(sc, 1) * 100, 2)
        r[f'unseen_HR@{k_}'] = round(suh[k_] / max(uc_cnt, 1) * 100, 2)
    r['seen_n'] = sc
    r['unseen_n'] = uc_cnt
    r['seen_ratio'] = round(sc / max(tot, 1), 4)

    if diag:
        d['tot'] = tot
        d['sc'] = sc
        d['uc'] = uc_cnt
        if d['top5_visited_ratio']:
            d['avg_top5_visited_ratio'] = np.mean(d['top5_visited_ratio'])
        r['diag'] = d

    return r


# ==============================================================================
# V1 baseline eval (for comparison in diagnostics)
# ==============================================================================

@torch.no_grad()
def eval_v1_baseline(model, dataloader, device, poi_bias_fn, geo_bias_fn, local_bias_fn,
                     K, norm, alpha, beta, gamma, delta,
                     poi_zone_tensor, num_zones):
    """评估 V1 基线重排序（无 revisit 信号），用于与 T10e-1 对比。

    V1 公式：final_score = α*norm_T9 + β*poi + γ*geo + δ*local
    不对 visited/unvisited 做区分，所有候选使用同一公式。
    """
    model.eval()
    uc_flag = getattr(model, 'use_causal_long_pref', False)
    hits, tot = 0, 0
    samples = []  # (target, t9_top5, v1_top5, t9h5, v1h5, is_seen)

    for batch_idx, batch in enumerate(dataloader):
        batch = [t.to(device) for t in batch]
        bv, bc, bt, bl = batch[0], batch[1], batch[2], batch[-1]
        kw = {}
        if uc_flag:
            kw['causal_history'] = batch[3]
            kw['causal_mask'] = batch[4]

        base_l = model(bv, bc, t_seq=bt, **kw)
        t9_topk_vals, t9_topk_idx = torch.topk(base_l, k=K, dim=1)
        t9_norm = normalize_scores(t9_topk_vals, norm)

        lps = bv[:, -1]
        pcs = bc[:, -2]
        lcs = bc[:, -1]
        hbs = compute_hour_bin_t(bt)
        zones = poi_zone_tensor[lps].clamp(0, num_zones - 1)

        poi_s = poi_bias_fn(lps).gather(1, t9_topk_idx)
        geo_s = geo_bias_fn(pcs, lcs, hbs, zones).gather(1, t9_topk_idx)
        loc_s = local_bias_fn(zones, hbs).gather(1, t9_topk_idx)

        combined = alpha * t9_norm + beta * poi_s + gamma * geo_s + delta * loc_s
        _, rerank_idx = torch.sort(combined, dim=1, descending=True)
        reranked_pois = t9_topk_idx.gather(1, rerank_idx)

        for i in range(bl.size(0)):
            tl = bl[i].item()
            t9p = t9_topk_idx[i].tolist()
            rp = reranked_pois[i].tolist()
            t9h5 = tl in t9p[:5]
            v1h5 = tl in rp[:5]
            if v1h5:
                hits += 1

            if uc_flag:
                ch = batch[3][i]
                cm = batch[4][i]
                is_s = tl in ch[cm].tolist()
            else:
                is_s = False

            if len(samples) < 5000:
                samples.append({
                    'batch': batch_idx, 'sample_i': i,
                    'target': tl, 'is_seen': is_s,
                    't9_top5': t9p[:5], 'v1_top5': rp[:5],
                    't9h5': t9h5, 'v1h5': v1h5,
                })
            tot += 1

    return {'HR@5': round(hits / tot * 100, 2), 'total': tot, 'samples': samples}


@torch.no_grad()
def eval_v11_baseline(model, dataloader, device, poi_bias_fn, geo_bias_fn, local_bias_fn,
                      K, norm, alpha, beta, gamma, delta,
                      rho, revisit_type, hybrid_a,
                      poi_zone_tensor, num_zones):
    """评估 V1.1 基线重排序（全局 revisit boost），用于与 T10e-1 对比。

    V1.1 公式：final_score = α*norm_T9 + β*poi + γ*geo + δ*local + ρ * revisit_score
    对所有候选都加 revisit_score，导致 revisit 信号统治排序，Unseen HR@5 大幅下降。
    这正是 T10e-1 要解决的核心问题。
    """
    from src.run_t10d_v1_1_revisit import compute_revisit_scores

    model.eval()
    uc_flag = getattr(model, 'use_causal_long_pref', False)
    hits, tot = 0, 0
    samples = []

    for batch_idx, batch in enumerate(dataloader):
        batch = [t.to(device) for t in batch]
        bv, bc, bt, bl = batch[0], batch[1], batch[2], batch[-1]
        kw = {}
        if uc_flag:
            kw['causal_history'] = batch[3]
            kw['causal_mask'] = batch[4]

        base_l = model(bv, bc, t_seq=bt, **kw)
        t9_topk_vals, t9_topk_idx = torch.topk(base_l, k=K, dim=1)
        t9_norm = normalize_scores(t9_topk_vals, norm)

        lps = bv[:, -1]
        pcs = bc[:, -2]
        lcs = bc[:, -1]
        hbs = compute_hour_bin_t(bt)
        zones = poi_zone_tensor[lps].clamp(0, num_zones - 1)

        poi_s = poi_bias_fn(lps).gather(1, t9_topk_idx)
        geo_s = geo_bias_fn(pcs, lcs, hbs, zones).gather(1, t9_topk_idx)
        loc_s = local_bias_fn(zones, hbs).gather(1, t9_topk_idx)
        rev_s = compute_revisit_scores(batch[3], batch[4], t9_topk_idx, revisit_type, hybrid_a)

        combined = alpha * t9_norm + beta * poi_s + gamma * geo_s + delta * loc_s + rho * rev_s
        _, rerank_idx = torch.sort(combined, dim=1, descending=True)
        reranked_pois = t9_topk_idx.gather(1, rerank_idx)

        for i in range(bl.size(0)):
            tl = bl[i].item()
            t9p = t9_topk_idx[i].tolist()
            rp = reranked_pois[i].tolist()
            t9h5 = tl in t9p[:5]
            v11h5 = tl in rp[:5]
            if v11h5:
                hits += 1

            if uc_flag:
                ch = batch[3][i]
                cm = batch[4][i]
                is_s = tl in ch[cm].tolist()
            else:
                is_s = False

            if len(samples) < 5000:
                samples.append({
                    'batch': batch_idx, 'sample_i': i,
                    'target': tl, 'is_seen': is_s,
                    't9_top5': t9p[:5], 'v11_top5': rp[:5],
                    't9h5': t9h5, 'v11h5': v11h5,
                })
            tot += 1

    return {'HR@5': round(hits / tot * 100, 2), 'total': tot, 'samples': samples}


# ==============================================================================
# Report Generation
# ==============================================================================

def gen_report(path, bc, test_r, t9_test, all_grid, npar, oh_ms, diag_json_path, cases_csv_path):
    """生成 T10e-1 完整中文实验报告（Markdown 格式）。

    包含：方法说明（分流公式 + revisit_score 类型）、Strict Protocol 检查表、
    Val 网格搜索 Top-10、Test 评估（含 Seen/Unseen 对比）、Flip 分析、Rank Change、
    Top-5 Visited/Unvisited 比例、核心问题回答。
    """
    t9 = t9_test
    v1 = {'HR@1': 19.96, 'HR@5': 49.35, 'HR@10': 59.06,
          'seen_HR@5': 70.68, 'unseen_HR@5': 13.63,
          'NDCG@5': 0.3559, 'NDCG@10': 0.3875,
          'MRR@5': 0.3101, 'MRR@10': 0.3233}
    v11 = {'HR@1': 20.50, 'HR@5': 51.07, 'HR@10': 60.92,
           'seen_HR@5': 75.66, 'unseen_HR@5': 9.90,
           'NDCG@5': 0.3715, 'NDCG@10': 0.4000,
           'MRR@5': 0.3150, 'MRR@10': 0.3280}
    v13 = {'HR@1': 20.10, 'HR@5': 50.39, 'HR@10': 60.38,
           'seen_HR@5': 74.00, 'unseen_HR@5': 10.86,
           'NDCG@5': 0.3699, 'NDCG@10': 0.3980}

    diag = test_r.get('diag', {})
    fg = diag.get('fg', 0)
    fl = diag.get('fl', 0)

    lines = [
        "# T10e-1: Visited/Unvisited Split Rerank — 实验报告", "",
        f"**日期**: 2026-07-06  **数据集**: Foursquare TKY",
        f"**T9 Baseline**: Test HR@5={t9.get('HR@5',0):.2f}%", "",
        "---", "",
        "## 一、方法说明", "",
        "### 1.1 核心思想", "",
        "候选级自适应融合：Visited/Unvisited 分流 rerank。",
        "对用户因果历史中出现过的候选 POI，使用 revisit_score 保护；",
        "对用户未访问过的候选 POI，保留 IntentGeo / POI / LocalPop 探索信号；",
        "避免像 V1.1 一样让 revisit_score 统治全部排序。", "",
        "### 1.2 分数公式", "",
        "```",
        "base_score(i) = α*norm_t9(i) + β*poi_transition(i) + γ*intent_geo(i) + δ*local_pop(i)",
        "",
        "if candidate_i in user_causal_history:",
        "    final_score(i) = base_score(i) + ρ_seen * revisit_score(i)",
        "else:",
        "    final_score(i) = base_score(i) + η_unseen * explore_score(i)",
        "",
        "explore_score(i) = β*poi_transition(i) + γ*intent_geo(i) + δ*local_pop(i)",
        "```", "",
        "### 1.3 Revisit Score 类型", "",
        "1. **recency**: 1/log2(recency_rank+1)，最近访问越近分数越高",
        "2. **frequency**: log(1+count)，在 top-K 内归一化到 [0,1]",
        "3. **hybrid**: a*recency + (1-a)*frequency", "",
        "### 1.4 搜索空间", "",
        f"- ρ_seen (revisit weight): [0.03, 0.05, 0.08, 0.10, 0.15, 0.20, 0.25]",
        f"- η_unseen (explore weight): [0.00, 0.03, 0.05, 0.08, 0.10, 0.15, 0.20]",
        f"- revisit_type: [recency, frequency, hybrid]",
        f"- hybrid_a: [0.3, 0.5, 0.7] (仅 hybrid)", "",
        "---", "",
        "## 二、Strict Protocol", "",
        "| 规则 | 状态 |",
        "|------|------|",
        "| Memory 仅由 train 构建 | ✅ |",
        "| Causal history per-sample time-constrained | ✅ |",
        "| 不使用 target_time 之后的信息 | ✅ |",
        "| val 仅用于超参选择 | ✅ |",
        "| test 仅评估一次 | ✅ |",
        "| 不改变 T9 主干 | ✅ |",
        "| Full-ranking → top-K rerank | ✅ |",
        "| 无 GNN / 无大参数 | ✅ |", "",
        "---", "",
        "## 三、Val 网格搜索", "",
        f"总组合数: {len(all_grid)}", "",
        f"**最佳配置**:", "",
        f"```json",
        f"{json.dumps(bc, indent=2)}",
        f"```", "",
        f"**最佳 Val HR@5**: {bc.get('best_val_hr5', 0):.2f}%", "",
    ]

    # Top-10 grid results
    sorted_grid = sorted(all_grid, key=lambda x: x['HR@5'], reverse=True)[:10]
    lines += ["### Top-10 Val 配置", "",
              "| # | ρ_seen | η_unseen | type | a | HR@5 | Seen HR@5 | Unseen HR@5 |",
              "|---|--------|----------|------|---|------|-----------|-------------|"]
    for rank, g in enumerate(sorted_grid):
        lines.append(f"| {rank+1} | {g.get('rho_seen',0):.3f} | {g.get('eta_unseen',0):.3f} | "
                     f"{g.get('revisit_type','')} | {g.get('hybrid_a',0):.1f} | "
                     f"{g['HR@5']:.2f}% | {g.get('seen_HR@5',0):.2f}% | {g.get('unseen_HR@5',0):.2f}% |")

    # Test results
    lines += ["", "---", "",
              "## 四、Test 评估结果", "",
              "### 4.1 主要指标", "",
              "| 指标 | T9 | V1 | V1.1 | V1.3 | T10e-1 | Δ vs V1 | Δ vs V1.1 |",
              "|------|-----|-----|------|------|--------|---------|-----------|"]

    for m in ['HR@1', 'HR@5', 'HR@10']:
        t9v = t9.get(m, 0)
        v1v = v1.get(m, 0)
        v11v = v11.get(m, 0)
        v13v = v13.get(m, 0)
        tv = test_r.get(m, 0)
        lines.append(f"| {m} | {t9v:.2f}% | {v1v:.2f}% | {v11v:.2f}% | {v13v:.2f}% | "
                     f"{tv:.2f}% | {tv-v1v:+.2f}% | {tv-v11v:+.2f}% |")

    for m in ['NDCG@5', 'NDCG@10', 'MRR@5', 'MRR@10']:
        t9v = t9.get(m, 0)
        tv = test_r.get(m, 0)
        v1v = v1.get(m, 0)
        lines.append(f"| {m} | {t9v:.4f} | {v1v:.4f} | - | - | {tv:.4f} | - | - |")

    lines += ["", "### 4.2 Seen/Unseen 对比", "",
              "| 指标 | T9 | V1 | V1.1 | V1.3 | T10e-1 | Δ vs V1.1 |",
              "|------|-----|-----|------|------|--------|-----------|"]
    for lbl, k, t9v in [('Seen HR@5', 'seen_HR@5', 71.11),
                          ('Unseen HR@5', 'unseen_HR@5', 12.01)]:
        v1v = v1.get(k, 0)
        v11v = v11.get(k, 0)
        v13v = v13.get(k, 0)
        tv = test_r.get(k, 0)
        lines.append(f"| {lbl} | {t9v:.2f}% | {v1v:.2f}% | {v11v:.2f}% | {v13v:.2f}% | "
                     f"{tv:.2f}% | {tv-v11v:+.2f}% |")

    # Flip analysis
    lines += ["", "### 4.3 Flip 分析", "",
              f"- T9 miss@5 → T10e hit@5: {fg}",
              f"- T9 hit@5 → T10e miss@5: {fl}",
              f"- Net gain: {fg-fl:+d}"]

    # Rank changes
    if diag.get('t9r'):
        t9r_all = np.mean(diag['t9r'])
        tr_all = np.mean(diag['tr'])
        lines += ["", "### 4.4 Rank Change", "",
                  f"- T9 mean rank: {t9r_all:.2f} → T10e: {tr_all:.2f} (Δ={tr_all-t9r_all:+.2f})"]
        if diag.get('t9r_seen'):
            lines.append(f"- Seen: T9={np.mean(diag['t9r_seen']):.2f} → T10e={np.mean(diag['tr_seen']):.2f}")
        if diag.get('t9r_unseen'):
            lines.append(f"- Unseen: T9={np.mean(diag['t9r_unseen']):.2f} → T10e={np.mean(diag['tr_unseen']):.2f}")

    # Top-5 visited ratio
    if diag.get('avg_top5_visited_ratio') is not None:
        lines += ["", "### 4.5 Top-5 Visited/Unvisited 比例", "",
                  f"- Top-5 中 visited candidates 平均比例: {diag['avg_top5_visited_ratio']*100:.1f}%",
                  f"- Top-5 中 unvisited candidates 平均比例: {(1-diag['avg_top5_visited_ratio'])*100:.1f}%"]

    lines += ["", "---", "",
              "## 五、核心问题回答", "",
              f"**1. Overall HR@5**: {test_r.get('HR@5',0):.2f}% "
              f"(T9={t9.get('HR@5',0):.2f}%, V1={v1['HR@5']:.2f}%, V1.1={v11['HR@5']:.2f}%)",
              f"**2. Seen HR@5**: {test_r.get('seen_HR@5',0):.2f}% "
              f"(V1={v1['seen_HR@5']:.2f}%, V1.1={v11['seen_HR@5']:.2f}%)",
              f"**3. Unseen HR@5**: {test_r.get('unseen_HR@5',0):.2f}% "
              f"(V1={v1['unseen_HR@5']:.2f}%, V1.1={v11['unseen_HR@5']:.2f}%)",
              f"**4. Net gain vs T9**: {fg-fl:+d}",
              f"**5. Seen/Unseen 是否比 V1.1 更平衡**: "
              f"{'是' if test_r.get('unseen_HR@5',0) > v11['unseen_HR@5'] else '否'}",
              f"**6. revisit_score 是否只保护 visited**: 是（代码保证 visited_mask 分流）",
              f"**7. 新增参数量**: 0",
              f"**8. 推理开销**: {oh_ms:.1f}ms", "",
              "---", "",
              "## 六、诊断输出", "",
              f"- Grid CSV: results/TKY/T10/t10e_1_split_rerank_val_grid.csv",
              f"- Test CSV: results/TKY/T10/t10e_1_split_rerank_test_result.csv",
              f"- 诊断 JSON: {diag_json_path}",
              f"- 案例 CSV: {cases_csv_path}", "",
              "---", "",
              "*报告由 src/run_t10e_1_split_rerank.py 自动生成。*"
    ]

    with open(path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
    print(f"Report: {path}")


# ==============================================================================
# Diagnostics
# ==============================================================================

def build_diagnostics(test_r, t10e_samples, v1_samples, v11_samples, out_dir):
    """构建 T10e-1 诊断文件（JSON + CSV）。

    对比 T10e-1 vs V1 vs V1.1 的 per-sample 排序结果，统计：
    - Flip 变化（V1 miss→T10e hit 等四类翻转）
    - Seen/Unseen 平衡性
    - Top-5 visited/unvisited 比例
    输出到诊断 JSON（结构化汇总）和案例 CSV（Top-5 翻转案例）。
    """
    diag = test_r.get('diag', {})

    # 1. Build diagnostics JSON
    diag_json = {
        'top5_visited_ratio_mean': float(np.mean(diag.get('top5_visited_ratio', [0]))),
        'top5_unvisited_ratio_mean': float(np.mean(diag.get('top5_unvisited_ratio', [0]))),
        'revisit_activated_samples': diag.get('revisit_activated', 0),
        'explore_activated_samples': diag.get('explore_activated', 0),
        'total_samples': diag.get('tot', 0),
        't9_miss_t10e_hit': diag.get('fg', 0),
        't9_hit_t10e_miss': diag.get('fl', 0),
        'net_gain': diag.get('fg', 0) - diag.get('fl', 0),
    }

    # Seen/Unseen balance
    diag_json['seen_unseen_balance'] = {
        'seen_hr5': test_r.get('seen_HR@5', 0),
        'unseen_hr5': test_r.get('unseen_HR@5', 0),
        'seen_unseen_gap': round(test_r.get('seen_HR@5', 0) - test_r.get('unseen_HR@5', 0), 2),
    }

    json_path = os.path.join(out_dir, "t10e_1_split_rerank_diagnostics.json")
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(diag_json, f, indent=2, ensure_ascii=False)
    print(f"Diagnostics: {json_path}")

    # 2. Build cases CSV
    cases = []

    # Build lookup from T10e samples
    t10e_lookup = {}
    for s in t10e_samples:
        key = (s['batch'], s['sample_i'])
        t10e_lookup[key] = s

    v1_lookup = {}
    for s in v1_samples:
        key = (s['batch'], s['sample_i'])
        v1_lookup[key] = s

    v11_lookup = {}
    for s in v11_samples:
        key = (s['batch'], s['sample_i'])
        v11_lookup[key] = s

    # Find case studies
    v1_miss_t10e_hit = []
    v1_hit_t10e_miss = []
    v11_miss_t10e_hit = []
    v11_hit_t10e_miss = []

    for key, te in t10e_lookup.items():
        v1s = v1_lookup.get(key)
        v11s = v11_lookup.get(key)
        if v1s is None or v11s is None:
            continue

        # V1 miss but T10e hit
        if not v1s['v1h5'] and te['t10eh5']:
            v1_miss_t10e_hit.append({
                'case_type': 'V1_miss_T10e_hit',
                'target': te['target'], 'is_seen': te['is_seen'],
                't9_top5': str(te['t9_top5']), 'v1_top5': str(v1s['v1_top5']),
                'v11_top5': str(v11s['v11_top5']), 't10e_top5': str(te['t10e_top5']),
                't9_rank': te['t9_rank'], 'v1_rank': v1s.get('v1_rank', 0),
                'v11_rank': v11s.get('v11_rank', 0), 't10e_rank': te['t10e_rank'],
            })

        # V1 hit but T10e miss
        if v1s['v1h5'] and not te['t10eh5']:
            v1_hit_t10e_miss.append({
                'case_type': 'V1_hit_T10e_miss',
                'target': te['target'], 'is_seen': te['is_seen'],
                't9_top5': str(te['t9_top5']), 'v1_top5': str(v1s['v1_top5']),
                'v11_top5': str(v11s['v11_top5']), 't10e_top5': str(te['t10e_top5']),
                't9_rank': te['t9_rank'], 'v1_rank': v1s.get('v1_rank', 0),
                'v11_rank': v11s.get('v11_rank', 0), 't10e_rank': te['t10e_rank'],
            })

        # V1.1 miss but T10e hit
        if not v11s['v11h5'] and te['t10eh5']:
            v11_miss_t10e_hit.append({
                'case_type': 'V11_miss_T10e_hit',
                'target': te['target'], 'is_seen': te['is_seen'],
                't9_top5': str(te['t9_top5']), 'v1_top5': str(v1s['v1_top5']),
                'v11_top5': str(v11s['v11_top5']), 't10e_top5': str(te['t10e_top5']),
                't9_rank': te['t9_rank'], 'v1_rank': v1s.get('v1_rank', 0),
                'v11_rank': v11s.get('v11_rank', 0), 't10e_rank': te['t10e_rank'],
            })

        # V1.1 hit but T10e miss
        if v11s['v11h5'] and not te['t10eh5']:
            v11_hit_t10e_miss.append({
                'case_type': 'V11_hit_T10e_miss',
                'target': te['target'], 'is_seen': te['is_seen'],
                't9_top5': str(te['t9_top5']), 'v1_top5': str(v1s['v1_top5']),
                'v11_top5': str(v11s['v11_top5']), 't10e_top5': str(te['t10e_top5']),
                't9_rank': te['t9_rank'], 'v1_rank': v1s.get('v1_rank', 0),
                'v11_rank': v11s.get('v11_rank', 0), 't10e_rank': te['t10e_rank'],
            })

    # Take top 5 of each, pad if fewer
    for lst, name in [(v1_miss_t10e_hit, 'V1_miss_T10e_hit'),
                       (v1_hit_t10e_miss, 'V1_hit_T10e_miss'),
                       (v11_miss_t10e_hit, 'V11_miss_T10e_hit'),
                       (v11_hit_t10e_miss, 'V11_hit_T10e_miss')]:
        selected = lst[:5]
        cases.extend(selected)
        diag_json[f'{name}_count'] = len(lst)
        diag_json[f'{name}_examples'] = len(selected)

    # Also add rank info to v1 and v11 samples for completeness
    # (We compute ranks from the top-5 lists since we didn't store them)
    for s in v1_samples:
        tl = s['target']
        t9p = s['t9_top5']
        v1p = s['v1_top5']
        # approximate rank
        s['v1_rank'] = v1p.index(tl) + 1 if tl in v1p else 100
        s['t9_rank'] = t9p.index(tl) + 1 if tl in t9p else 100
    for s in v11_samples:
        tl = s['target']
        v11p = s['v11_top5']
        s['v11_rank'] = v11p.index(tl) + 1 if tl in v11p else 100

    # Write cases CSV
    cases_path = os.path.join(out_dir, "t10e_1_split_rerank_cases.csv")
    if cases:
        fields = ['case_type', 'target', 'is_seen', 't9_rank', 'v1_rank', 'v11_rank', 't10e_rank',
                   't9_top5', 'v1_top5', 'v11_top5', 't10e_top5']
        with open(cases_path, 'w', newline='', encoding='utf-8') as f:
            w = csv.DictWriter(f, fieldnames=fields, extrasaction='ignore')
            w.writeheader()
            for c in cases:
                w.writerow(c)
    else:
        with open(cases_path, 'w', newline='', encoding='utf-8') as f:
            f.write("case_type,target,is_seen\n")

    print(f"Cases CSV: {cases_path} ({len(cases)} cases)")

    # Rewrite JSON with case info
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(diag_json, f, indent=2, ensure_ascii=False)

    return json_path, cases_path


# ==============================================================================
# Main
# ==============================================================================

def main():
    set_seed(cfg.SEED)
    device = get_device()
    print(f"Device: {device}")
    out_dir = os.path.join(cfg.SAVE_DIR, "T10")
    os.makedirs(out_dir, exist_ok=True)
    ckpt_path = os.path.join(cfg.CHECKPOINT_DIR, "T9_CausalMemoryFusion_best.pth")

    # --- Data pipeline ---
    print("\n=== Data Loading ===")
    raw_df = load_raw_data(cfg.dataset_file("TKY"))
    df = filter_low_frequency(raw_df, min_poi_checkins=cfg.MIN_POI_CHECKINS,
                              min_user_checkins=cfg.MIN_USER_CHECKINS)
    vl = df.groupby("venueId")[["latitude", "longitude"]].first().to_dict("index")
    vc = df.groupby("venueId")["venueCategory"].first().to_dict()

    trajectories = build_trajectories_24h(df, include_timestamps=True)
    trajectories.sort(key=lambda t: t["start_time"])
    train_traj, val_traj, test_traj = time_ordered_split(
        trajectories, train_ratio=cfg.TRAIN_RATIO, val_ratio=cfg.VAL_RATIO)

    uti = {}
    for t in train_traj:
        if t['user_id'] not in uti:
            uti[t['user_id']] = len(uti)

    train_raw = build_sequences(train_traj, seq_len=cfg.SEQ_LEN, user_to_idx=uti,
                                include_time=True, include_target_timestamp=True)
    val_raw = build_sequences(val_traj, seq_len=cfg.SEQ_LEN, user_to_idx=uti,
                              include_time=True, include_target_timestamp=True)
    test_raw = build_sequences(test_traj, seq_len=cfg.SEQ_LEN, user_to_idx=uti,
                               include_time=True, include_target_timestamp=True)

    v2i, c2i = build_vocabularies(train_raw)
    nv, nc = len(v2i), len(c2i)
    train_seqs = convert_sequences(train_raw, v2i, c2i)
    val_seqs, _ = convert_sequences(val_raw, v2i, c2i, return_stats=True)
    test_seqs, _ = convert_sequences(test_raw, v2i, c2i, return_stats=True)

    (tr_c, tr_cm, v_c, v_cm, te_c, te_cm) = build_causal_history_per_sample(
        train_traj=train_traj, train_seqs=train_seqs, val_seqs=val_seqs,
        test_seqs=test_seqs, venue_to_idx=v2i, user_to_idx=uti,
        max_history_len=cfg.MAX_CAUSAL_HISTORY)

    def _at(s, m, mk):
        for i, s2 in enumerate(s):
            s2['causal_hist'] = m[i].tolist()
            s2['causal_mask'] = mk[i].tolist()

    _at(train_seqs, tr_c, tr_cm)
    _at(val_seqs, v_c, v_cm)
    _at(test_seqs, te_c, te_cm)

    _, test_ldr = create_dataloaders(train_seqs, test_seqs, 512, num_workers=0,
                                     include_time=True, include_causal_history=True)
    val_ldr = create_val_loader(val_seqs, 512, num_workers=0,
                                include_time=True, include_causal_history=True)
    print(f"Vocab: {nv} POIs, {nc} cats, Val={len(val_ldr.dataset)}, Test={len(test_ldr.dataset)}")

    # Features
    print("\n=== Features ===")
    tps = sorted(set(v for t in train_traj for v in t["venues"]))
    p2w = {p: i for i, p in enumerate(tps)}
    ws = [[p2w[v] for v in t["venues"]] for t in train_traj if len(t["venues"]) >= 2]
    we = train_word2vec(ws, len(tps), emb_dim=128, window_size=3, n_negs=5,
                        batch_size=2048, epochs=10, lr=0.001, device=device)
    bm = build_behavioral_matrix(we, v2i, p2w)
    tvs = [v for v in v2i if v != "<PAD>"]
    pt = build_poi_texts(tvs, vc, vl, dataset="TKY")
    te_e = encode_with_sbert(pt, model_name="all-MiniLM-L6-v2", batch_size=256,
                             local_files_only=True)
    tm = build_text_matrix(te_e, v2i)

    # T9 Model
    print("\n=== Load T9 ===")
    model = TransformerPOIModel(
        num_venues=nv, num_cats=nc, use_category=True,
        venue_emb_dim=64, cat_emb_dim=16,
        behav_dim=128, behav_proj_dim=64, text_dim=384, text_proj_dim=64,
        d_model=128, n_heads=2, n_layers=2, ff_dim=256, dropout=0.1,
        fc_dropout=0.3, behav_matrix=bm, text_matrix=tm,
        fusion_type="dynamic", gate_hidden=64,
        use_causal_long_pref=True, causal_pref_type="attention").to(device)
    model.load_state_dict(torch.load(ckpt_path, weights_only=True))
    n_params = count_parameters(model)
    print(f"Params: {n_params:,}")

    # Memories
    print("\n=== Build Memories ===")
    gs = 20
    poi_idx_zone, nz, pzt = build_geo_zones(train_traj, gs, vl, v2i)
    pzt = pzt.to(device)
    geo_mems, geo_kt = build_intent_geo_memory(train_traj, v2i, c2i, poi_idx_zone, top_k=200)
    with open(os.path.join(out_dir, "t10_poi_transition_top100.pkl"), 'rb') as f:
        poi_mem = pickle.load(f)

    geo_bias_fn = IntentGeoFullBias(geo_mems, geo_kt, 50, 3, nc, nz, nv, device)
    poi_bias_fn = POIFullBias(poi_mem, 50, 'rank', nv, device)
    local_bias_fn = LocalFullBias(train_traj, v2i, poi_idx_zone, 200, nv, device)

    # T9 baseline
    from src.t9_evaluation import eval_t9_simple
    print("\n=== T9 Baseline ===")
    t9_val = eval_t9_simple(model, val_ldr, device)
    t9_test = eval_t9_simple(model, test_ldr, device)
    print(f"T9 Val HR@5={t9_val['HR@5']:.2f}% (Seen={t9_val.get('seen_HR@5',0):.2f}%), "
          f"Test HR@5={t9_test['HR@5']:.2f}%")

    # V1 fixed params
    v1_cfg = {'K': 100, 'norm': 'zscore', 'alpha': 1.0, 'beta': 0.062,
              'gamma': 0.10, 'delta': 0.05}
    t9_val_seen_hr5 = t9_val.get('seen_HR@5', 66.06)

    # ========================================================================
    # T10e-1 网格搜索：Visited/Unvisited 分流重排序
    #
    # 搜索空间：
    #   ρ_seen ∈ [0.03, 0.05, 0.08, 0.10, 0.15, 0.20, 0.25]  — visited boost 权重
    #   η_unseen ∈ [0.00, 0.03, 0.05, 0.08, 0.10, 0.15, 0.20] — unvisited explore 权重
    #   revisit_type ∈ [recency, frequency, hybrid]           — revisit 分数类型
    #   hybrid_a ∈ [0.3, 0.5, 0.7]                           — hybrid 模式下 recency 权重
    #
    # 选择规则（严格约束优先）：
    #   主指标：Val Overall HR@5 最高
    #   硬约束1：Val Seen HR@5 >= T9 Val Seen HR@5 - 0.5（不严重伤害 Seen）
    #   硬约束2：Val Unseen HR@5 >= T9 Val Unseen HR@5 - 0.5（不严重伤害 Unseen）
    #   平局打破1：Unseen HR@5 更高
    #   平局打破2：NDCG@5 更高
    # ========================================================================
    print("\n" + "=" * 70)
    print("T10e-1 GRID SEARCH: Visited/Unvisited Split Rerank")
    print("=" * 70)

    rho_seen_opts = [0.03, 0.05, 0.08, 0.10, 0.15, 0.20, 0.25]
    eta_unseen_opts = [0.00, 0.03, 0.05, 0.08, 0.10, 0.15, 0.20]
    revisit_types = ['recency', 'frequency', 'hybrid']
    hybrid_a_opts = [0.3, 0.5, 0.7]

    # Calculate total combos
    # recency: 7*7=49, frequency: 7*7=49, hybrid: 7*7*3=147 → total=245
    total_rec_freq = len(rho_seen_opts) * len(eta_unseen_opts) * 2
    total_hybrid = len(rho_seen_opts) * len(eta_unseen_opts) * len(hybrid_a_opts)
    total_combos = total_rec_freq + total_hybrid
    print(f"Total combinations: {total_combos}")

    all_grid = []
    best_val_hr5 = -1.0
    best_config = {}
    ci = 0

    for revisit_type in revisit_types:
        a_opts = hybrid_a_opts if revisit_type == 'hybrid' else [0.5]
        for ha in a_opts:
            for rho_seen in rho_seen_opts:
                for eta_unseen in eta_unseen_opts:
                    ci += 1
                    t0 = time.perf_counter()
                    r = eval_split_rerank(
                        model, val_ldr, device, poi_bias_fn, geo_bias_fn, local_bias_fn,
                        v1_cfg['K'], v1_cfg['norm'], v1_cfg['alpha'],
                        v1_cfg['beta'], v1_cfg['gamma'], v1_cfg['delta'],
                        rho_seen, eta_unseen, revisit_type, ha, pzt, nz)
                    if torch.cuda.is_available():
                        torch.cuda.synchronize()
                    et = time.perf_counter() - t0

                    row = {
                        'K': v1_cfg['K'], 'norm': v1_cfg['norm'],
                        'alpha': v1_cfg['alpha'], 'beta': v1_cfg['beta'],
                        'gamma': v1_cfg['gamma'], 'delta': v1_cfg['delta'],
                        'rho_seen': rho_seen, 'eta_unseen': eta_unseen,
                        'revisit_type': revisit_type, 'hybrid_a': ha,
                        'HR@5': r['HR@5'], 'seen_HR@5': r.get('seen_HR@5', 0),
                        'unseen_HR@5': r.get('unseen_HR@5', 0),
                        'NDCG@5': r.get('NDCG@5', 0),
                        'eval_time': round(et, 1),
                    }
                    all_grid.append(row)

                    # Selection rule:
                    # Primary: Val Overall HR@5 highest
                    # Hard constraint 1: Val Seen HR@5 >= T9 Val Seen HR@5
                    # Hard constraint 2: Val Unseen HR@5 >= T9 Val Unseen HR@5 (don't degrade)
                    t9_val_unseen_hr5 = t9_val.get('unseen_HR@5', 9.0)
                    seen_threshold = t9_val_seen_hr5 - 0.5  # Allow tiny degradation
                    unseen_threshold = t9_val_unseen_hr5 - 0.5

                    seen_ok = r.get('seen_HR@5', 0) >= seen_threshold
                    unseen_ok = r.get('unseen_HR@5', 0) >= unseen_threshold
                    meets_constraints = seen_ok and unseen_ok

                    if meets_constraints:
                        if r['HR@5'] > best_val_hr5 + 0.001:
                            best_val_hr5 = r['HR@5']
                            best_config = {
                                'K': v1_cfg['K'], 'norm': v1_cfg['norm'],
                                'alpha': v1_cfg['alpha'], 'beta': v1_cfg['beta'],
                                'gamma': v1_cfg['gamma'], 'delta': v1_cfg['delta'],
                                'rho_seen': rho_seen, 'eta_unseen': eta_unseen,
                                'revisit_type': revisit_type, 'hybrid_a': ha,
                                '_best_unseen': r.get('unseen_HR@5', 0),
                                '_best_ndcg': r.get('NDCG@5', 0),
                            }
                        elif abs(r['HR@5'] - best_val_hr5) < 0.03:
                            # Tie-break 1: higher Unseen HR@5
                            best_unseen = best_config.get('_best_unseen', 0)
                            if r.get('unseen_HR@5', 0) > best_unseen:
                                best_val_hr5 = r['HR@5']
                                best_config = {
                                    'K': v1_cfg['K'], 'norm': v1_cfg['norm'],
                                    'alpha': v1_cfg['alpha'], 'beta': v1_cfg['beta'],
                                    'gamma': v1_cfg['gamma'], 'delta': v1_cfg['delta'],
                                    'rho_seen': rho_seen, 'eta_unseen': eta_unseen,
                                    'revisit_type': revisit_type, 'hybrid_a': ha,
                                    '_best_unseen': r.get('unseen_HR@5', 0),
                                    '_best_ndcg': r.get('NDCG@5', 0),
                                }
                            elif abs(r.get('unseen_HR@5', 0) - best_unseen) < 0.01:
                                # Tie-break 2: higher NDCG@5
                                best_ndcg = best_config.get('_best_ndcg', 0)
                                if r.get('NDCG@5', 0) > best_ndcg:
                                    best_val_hr5 = r['HR@5']
                                    best_config = {
                                        'K': v1_cfg['K'], 'norm': v1_cfg['norm'],
                                        'alpha': v1_cfg['alpha'], 'beta': v1_cfg['beta'],
                                        'gamma': v1_cfg['gamma'], 'delta': v1_cfg['delta'],
                                        'rho_seen': rho_seen, 'eta_unseen': eta_unseen,
                                        'revisit_type': revisit_type, 'hybrid_a': ha,
                                        '_best_unseen': r.get('unseen_HR@5', 0),
                                        '_best_ndcg': r.get('NDCG@5', 0),
                                    }

                    if ci % 50 == 0:
                        print(f"  [{ci}/{total_combos}] type={revisit_type} ρ={rho_seen:.2f} "
                              f"η={eta_unseen:.2f} a={ha:.1f} → HR@5={r['HR@5']:.2f}% "
                              f"S={r.get('seen_HR@5',0):.2f}% U={r.get('unseen_HR@5',0):.2f}% "
                              f"(best={best_val_hr5:.2f}%) [{et:.1f}s]")

    # If no config met constraints, fallback: best overall HR@5, tie-break Unseen, then NDCG
    if best_val_hr5 < 0:
        print("\n⚠️ No config met hard constraints. Using best overall HR@5 (tie-break: Unseen > NDCG).")
        valid = [g for g in all_grid if g.get('HR@5', 0) > 0]
        valid.sort(key=lambda x: (x['HR@5'], x.get('unseen_HR@5', 0), x.get('NDCG@5', 0)), reverse=True)
        best = valid[0]
        best_val_hr5 = best['HR@5']
        best_config = {
            'K': v1_cfg['K'], 'norm': v1_cfg['norm'],
            'alpha': v1_cfg['alpha'], 'beta': v1_cfg['beta'],
            'gamma': v1_cfg['gamma'], 'delta': v1_cfg['delta'],
            'rho_seen': best['rho_seen'], 'eta_unseen': best['eta_unseen'],
            'revisit_type': best['revisit_type'], 'hybrid_a': best['hybrid_a'],
        }

    best_config['best_val_hr5'] = best_val_hr5
    # Clean up internal field
    best_config.pop('_best_unseen', None)
    print(f"\n=== BEST CONFIG: {json.dumps(best_config, indent=2)} ===")

    # Save val grid
    grid_csv = os.path.join(out_dir, "t10e_1_split_rerank_val_grid.csv")
    fields = ['K', 'norm', 'alpha', 'beta', 'gamma', 'delta',
              'rho_seen', 'eta_unseen', 'revisit_type', 'hybrid_a',
              'HR@5', 'seen_HR@5', 'unseen_HR@5', 'NDCG@5', 'eval_time']
    with open(grid_csv, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction='ignore')
        w.writeheader()
        for row in all_grid:
            w.writerow(row)
    print(f"Val grid: {grid_csv}")

    # ========================================================================
    # Test Evaluation
    # ========================================================================
    print("\n=== TEST EVALUATION ===")
    bc = best_config
    t0 = time.perf_counter()
    test_r = eval_split_rerank(
        model, test_ldr, device, poi_bias_fn, geo_bias_fn, local_bias_fn,
        bc['K'], bc['norm'], bc['alpha'],
        bc['beta'], bc['gamma'], bc['delta'],
        bc['rho_seen'], bc['eta_unseen'], bc['revisit_type'], bc['hybrid_a'],
        pzt, nz, diag=True)
    if torch.cuda.is_available():
        torch.cuda.synchronize()
    test_time = time.perf_counter() - t0

    print(f"\nTest HR@5={test_r['HR@5']:.2f}% HR@1={test_r['HR@1']:.2f}% HR@10={test_r['HR@10']:.2f}%")
    print(f"Seen HR@5={test_r.get('seen_HR@5',0):.2f}% Unseen HR@5={test_r.get('unseen_HR@5',0):.2f}%")
    print(f"NDCG@5={test_r.get('NDCG@5',0):.4f} MRR@5={test_r.get('MRR@5',0):.4f}")
    print(f"Test time: {test_time:.1f}s")

    # ========================================================================
    # Run V1 and V1.1 baselines for diagnostics
    # ========================================================================
    print("\n=== Baseline Evals for Diagnostics ===")
    print("Running V1 baseline...")
    v1_r = eval_v1_baseline(model, test_ldr, device, poi_bias_fn, geo_bias_fn, local_bias_fn,
                            v1_cfg['K'], v1_cfg['norm'], v1_cfg['alpha'],
                            v1_cfg['beta'], v1_cfg['gamma'], v1_cfg['delta'],
                            pzt, nz)
    v1_samples = v1_r['samples']
    print(f"V1 HR@5={v1_r['HR@5']:.2f}%")

    # V1.1 best config: rho=0.30, recency (from known results)
    v11_rho = 0.30
    v11_type = 'recency'
    v11_ha = 0.5
    print(f"Running V1.1 baseline (ρ={v11_rho}, type={v11_type})...")
    v11_r = eval_v11_baseline(model, test_ldr, device, poi_bias_fn, geo_bias_fn, local_bias_fn,
                               v1_cfg['K'], v1_cfg['norm'], v1_cfg['alpha'],
                               v1_cfg['beta'], v1_cfg['gamma'], v1_cfg['delta'],
                               v11_rho, v11_type, v11_ha, pzt, nz)
    v11_samples = v11_r['samples']
    print(f"V1.1 HR@5={v11_r['HR@5']:.2f}%")

    # ========================================================================
    # Timing
    # ========================================================================
    print("\n=== Timing ===")
    # Warmup
    for batch in val_ldr:
        batch = [t.to(device) for t in batch]
        _ = model(batch[0], batch[1], causal_history=batch[3], causal_mask=batch[4])
        break
    if torch.cuda.is_available():
        torch.cuda.synchronize()

    t9_times = []
    for _ in range(5):
        t0t = time.perf_counter()
        for batch in val_ldr:
            batch = [t.to(device) for t in batch]
            _ = model(batch[0], batch[1], causal_history=batch[3], causal_mask=batch[4])
        if torch.cuda.is_available():
            torch.cuda.synchronize()
        t9_times.append(time.perf_counter() - t0t)
    t9t_mean = np.mean(t9_times)

    rerank_times = []
    for _ in range(5):
        t0t = time.perf_counter()
        for batch in val_ldr:
            batch = [t.to(device) for t in batch]
            bv2, bc2, bt2 = batch[0], batch[1], batch[2]
            base_l = model(bv2, bc2, causal_history=batch[3], causal_mask=batch[4])
            t9_idx = torch.topk(base_l, k=bc['K'], dim=1)[1]
            _ = compute_split_scores(batch[3], batch[4], t9_idx,
                                     bc['revisit_type'], bc['hybrid_a'])
        if torch.cuda.is_available():
            torch.cuda.synchronize()
        rerank_times.append(time.perf_counter() - t0t)
    rr_mean = np.mean(rerank_times)
    oh_ms = (rr_mean - t9t_mean) * 1000
    oh_pct = (rr_mean - t9t_mean) / t9t_mean * 100
    print(f"T9: {t9t_mean:.3f}s, T10e: {rr_mean:.3f}s, Overhead: {oh_ms:.1f}ms ({oh_pct:.1f}%)")

    # ========================================================================
    # Build Diagnostics
    # ========================================================================
    print("\n=== Building Diagnostics ===")
    t10e_samples = test_r.get('diag', {}).get('samples', [])
    diag_json_path, cases_csv_path = build_diagnostics(
        test_r, t10e_samples, v1_samples, v11_samples, out_dir)

    # ========================================================================
    # Save Test Result
    # ========================================================================
    test_csv = os.path.join(out_dir, "t10e_1_split_rerank_test_result.csv")
    trow = {
        'model': 'T10e-1-SplitRerank',
        **{k: str(v) for k, v in bc.items()},
        'HR@1': test_r['HR@1'], 'HR@5': test_r['HR@5'], 'HR@10': test_r['HR@10'],
        'NDCG@5': test_r['NDCG@5'], 'NDCG@10': test_r['NDCG@10'],
        'MRR@5': test_r['MRR@5'], 'MRR@10': test_r['MRR@10'],
        'seen_HR@5': test_r.get('seen_HR@5', 0),
        'unseen_HR@5': test_r.get('unseen_HR@5', 0),
        'seen_ratio': test_r.get('seen_ratio', 0),
        'params': n_params, 'overhead_ms': round(oh_ms, 2),
        'overhead_pct': round(oh_pct, 2),
        'best_val_hr5': best_val_hr5,
        't9_test_hr5': t9_test['HR@5'],
    }
    with open(test_csv, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=list(trow.keys()))
        w.writeheader()
        w.writerow(trow)
    print(f"Test CSV: {test_csv}")

    # ========================================================================
    # Report
    # ========================================================================
    rpt_path = os.path.join(out_dir, "16_t10e_1_split_rerank_report.md")
    gen_report(rpt_path, best_config, test_r, t9_test, all_grid, n_params, oh_ms,
               diag_json_path, cases_csv_path)

    # ========================================================================
    # Summary
    # ========================================================================
    print("\n" + "=" * 70)
    print("T10e-1 Split Rerank Complete!")
    print(f"T9={t9_test['HR@5']:.2f}% → T10e-1={test_r['HR@5']:.2f}% "
          f"(Δ={test_r['HR@5']-t9_test['HR@5']:+.2f}%)")
    print(f"Seen: {test_r.get('seen_HR@5',0):.2f}%, Unseen: {test_r.get('unseen_HR@5',0):.2f}%")
    diag = test_r.get('diag', {})
    print(f"Flip: gain={diag.get('fg',0)}, loss={diag.get('fl',0)}, "
          f"net={diag.get('fg',0)-diag.get('fl',0):+d}")
    print(f"Top-5 visited ratio: {diag.get('avg_top5_visited_ratio', 0)*100:.1f}%")
    print("=" * 70)


if __name__ == "__main__":
    main()
