"""
T10e-2: High-confidence Unvisited Boost.

Builds on T10e-1's Visited/Unvisited split. For unvisited candidates, further
splits into high-confidence and low-confidence:
  - High-confidence (explore_score >= threshold): base + η_high * explore_score + τ
  - Low-confidence  (explore_score <  threshold): base + η_low  * explore_score

Goal: restore Unseen HR@5 closer to T9/V1 levels while keeping Seen gains from
T10e-1's revisit protection.

Strict Protocol: train-only memory, val-only HP selection, single test eval.
"""

import argparse, csv, json, math, os, pickle, sys, time
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

# Reuse T10e-1 split rerank eval for comparison
from src.split_rerank import eval_split_rerank


# ==============================================================================
# Revisit Score Computation (frequency-only, CPU for speed)
# ==============================================================================

def compute_frequency_revisit(causal_hist, causal_mask, cand_indices):
    """
    计算基于频率的 revisit 分数和 visited 掩码。

    在 CPU 上完成全部计算（避免逐元素 GPU 内核开销），最后再传回 GPU。
    对每个样本，统计 causal history 中每个 POI 的出现次数，
    候选 POI 若出现在 history 中则标记为 visited，并用 log1p(freq) 作为原始分数。
    最后在每个样本的 top-K 内做最大归一化到 [0,1]。

    Returns:
        revisit_scores: (B, K) — 频率分数，每个样本内归一化到 [0,1]
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

    # 逐样本计算：遍历因果历史，统计每个 POI 频率
    for i in range(B):
        hist = ch_cpu[i][cm_cpu[i]].tolist()
        if not hist:
            continue

        freq = {}
        for poi in hist:
            freq[poi] = freq.get(poi, 0) + 1

        ci = ci_cpu[i].tolist()
        for j, poi in enumerate(ci):
            if poi in freq:
                visited_np[i, j] = True
                scores_np[i, j] = math.log1p(freq[poi])  # log(1+count)，抑制极端高频值

    # 在每个样本的 top-K 内对频率分数做最大归一化到 [0,1]
    for i in range(B):
        row = scores_np[i]
        smax = row.max()
        if smax > 0:
            scores_np[i] = row / smax

    scores = torch.from_numpy(scores_np).to(device)
    visited = torch.from_numpy(visited_np).to(device)
    return scores, visited


# ==============================================================================
# Explore Threshold Pre-computation
# ==============================================================================

@torch.no_grad()
def compute_explore_thresholds(model, dataloader, device,
                                poi_bias_fn, geo_bias_fn, local_bias_fn,
                                K, beta, gamma, delta,
                                poi_zone_tensor, num_zones, quantiles):
    """
    在 Val 集的 Unvisited 候选上预计算 explore_score 的分位数阈值。

    遍历 Val 集：对每个样本的 T9 top-K 候选，找出那些不在 causal history 中的
    (即 unvisited)，收集它们的 explore_score = beta*poi + gamma*geo + delta*local。
    然后对所有 unvisited 候选的 explore_score 计算指定分位数，作为高/低置信度分割阈值。

    Returns dict: quantile → threshold_value
    """
    model.eval()
    uc_flag = getattr(model, 'use_causal_long_pref', False)
    all_scores = []

    for batch in dataloader:
        batch = [t.to(device) for t in batch]
        bv, bc, bt = batch[0], batch[1], batch[2]
        kw = {}
        if uc_flag:
            kw['causal_history'] = batch[3]
            kw['causal_mask'] = batch[4]

        # T9 前向：获取 top-K 候选
        base_l = model(bv, bc, t_seq=bt, **kw)
        t9_topk_vals, t9_topk_idx = torch.topk(base_l, k=K, dim=1)

        # 提取上下文特征：last POI、前一个/最后一个类别、时间 bin、地理区域
        lps = bv[:, -1]
        pcs = bc[:, -2]
        lcs = bc[:, -1]
        hbs = compute_hour_bin_t(bt)
        zones = poi_zone_tensor[lps].clamp(0, num_zones - 1)

        poi_s = poi_bias_fn(lps).gather(1, t9_topk_idx)
        geo_s = geo_bias_fn(pcs, lcs, hbs, zones).gather(1, t9_topk_idx)
        loc_s = local_bias_fn(zones, hbs).gather(1, t9_topk_idx)

        # explore_score 只包含三个 bias 分量（不含 T9 本身）
        explore_score = beta * poi_s + gamma * geo_s + delta * loc_s

        # 找出 Unvisited 候选并收集其 explore_score
        ch_np = batch[3].cpu().numpy()
        cm_np = batch[4].cpu().numpy()
        ci_np = t9_topk_idx.cpu().numpy()
        es_np = explore_score.cpu().numpy()

        for i in range(bv.size(0)):
            hist = set(ch_np[i][cm_np[i]].tolist())
            for j in range(K):
                if ci_np[i, j] not in hist:
                    all_scores.append(float(es_np[i, j]))

    if not all_scores:
        print("  WARNING: No unvisited candidates found, using 0.0 thresholds")
        return {q: 0.0 for q in quantiles}

    thresholds = {q: float(np.percentile(all_scores, q)) for q in quantiles}
    print(f"  Explore score distribution: min={min(all_scores):.4f}, "
          f"median={np.median(all_scores):.4f}, max={max(all_scores):.4f}")
    for q in sorted(quantiles):
        print(f"    Q{q}: {thresholds[q]:.6f}")

    return thresholds


# ==============================================================================
# T10e-2 Eval: High-confidence Unvisited Boost
# ==============================================================================

@torch.no_grad()
def eval_unvisited_boost(model, dataloader, device,
                          poi_bias_fn, geo_bias_fn, local_bias_fn,
                          K, norm, alpha, beta, gamma, delta,
                          rho_seen, eta_low, eta_high, tau_unvisited,
                          explore_threshold,
                          poi_zone_tensor, num_zones,
                          ks=(1, 5, 10), diag=False):
    """
    T10e-2: 高置信度 Unvisited Boost 评估。

    核心思路：在 T9 top-K 候选上执行三段式重排序——

    对于每个候选 i：
      if i in causal_history（已访问候选）：
        final_score = base_score + rho_seen * revisit_frequency_score(i)
        → 用频率 revisit 信号保护 Seen 样本，但仅对 visited 候选生效
      else（未访问候选）：
        if explore_score(i) >= explore_threshold（高置信度）：
          final_score = base_score + eta_high * explore_score(i) + tau_unvisited
          → 高置信度 unvisited 获得更强的探索 boost + 固定加分 τ
        else（低置信度）：
          final_score = base_score + eta_low  * explore_score(i)
          → 低置信度 unvisited 仅给予较弱的探索信号，降低噪声干扰

    这样做是为了：恢复 T10e-1 中受损的 Unseen HR@5，同时保住 Seen 和 NDCG。
    explore_score 只包含 bias 分量（β*poi + γ*geo + δ*local），不含 T9 自身分数。
    """
    model.eval()
    uc_flag = getattr(model, 'use_causal_long_pref', False)

    hits = {k: 0 for k in ks}
    ndcg = {k: 0.0 for k in ks}
    mrr = {k: 0.0 for k in ks}
    sh, suh = {k: 0 for k in ks}, {k: 0 for k in ks}
    sc, uc_cnt, tot = 0, 0, 0

    d = None
    if diag:
        d = {
            't9r': [], 'tr': [], 't9h5': 0, 'th5': 0, 'fg': 0, 'fl': 0,
            't9r_seen': [], 't9r_unseen': [], 'tr_seen': [], 'tr_unseen': [],
            'seen_t9h5': 0, 'unseen_t9h5': 0, 'seen_th5': 0, 'unseen_th5': 0,
            'top5_visited_ratio': [], 'top5_unvisited_ratio': [],
            'samples': [],
            'revisit_activated': 0,
            # New T10e-2 diagnostics
            'high_conf_triggered': 0,      # samples with >=1 high-conf candidate
            'high_conf_candidates': 0,      # total high-conf unvisited candidates
            'high_conf_target_present': 0,  # samples where target is high-conf unvisited
            'high_conf_target_hit': 0,      # high-conf target in top-5
            'low_conf_activated': 0,        # samples with >=1 low-conf candidate
            'high_conf_total': 0,           # total high-conf candidates across all samples
            'unseen_target_count': 0,       # count of unseen targets
            'unseen_target_top5': 0,        # unseen targets in top-5
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

        # Base score（与 V1 公式相同：T9 归一化 + 三个 bias）
        base_score = alpha * t9_norm + beta * poi_s + gamma * geo_s + delta * loc_s

        # Explore score（仅用于 unvisited 候选，与 V1 bias 公式相同但含义不同：
        # 它衡量"模型对该候选有多大的探索信心"——值越高越可能是合理的探索推荐）
        explore_score = beta * poi_s + gamma * geo_s + delta * loc_s

        # Revisit 分数 + visited 掩码（仅用频率模式，在 CPU 上计算）
        rev_s, visited_mask = compute_frequency_revisit(
            batch[3], batch[4], t9_topk_idx)

        # === T10e-2 三段式分流重排序 ===
        combined = base_score.clone()

        # 1. Visited（已访问候选）：加上 revisit 频率 boost，保护 Seen 样本
        combined[visited_mask] += rho_seen * rev_s[visited_mask]

        # 2-3. Unvisited 拆分为高/低置信度两段
        unvisited = ~visited_mask
        high_conf = unvisited & (explore_score >= explore_threshold)
        low_conf = unvisited & (explore_score < explore_threshold)

        # 高置信度 Unvisited：strong boost + 固定加分 τ（推动高质量探索候选上行）
        combined[high_conf] += eta_high * explore_score[high_conf] + tau_unvisited
        # 低置信度 Unvisited：仅给予较弱 boost，避免噪声干扰排名
        combined[low_conf] += eta_low * explore_score[low_conf]

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
                hist_pois = set(batch[3][i][batch[4][i].bool()].tolist())
                top5_visited = sum(1 for p in top5_pois if p in hist_pois)
                d['top5_visited_ratio'].append(top5_visited / 5.0)
                d['top5_unvisited_ratio'].append(1.0 - top5_visited / 5.0)

                # Track activation
                if visited_mask[i].any():
                    d['revisit_activated'] += 1

                # High/low confidence tracking
                hc_count = high_conf[i].sum().item()
                lc_count = low_conf[i].sum().item()
                d['high_conf_total'] += hc_count
                if hc_count > 0:
                    d['high_conf_triggered'] += 1
                    d['high_conf_candidates'] += hc_count
                if lc_count > 0:
                    d['low_conf_activated'] += 1

                # High-conf target tracking
                if not is_s:
                    d['unseen_target_count'] += 1
                    if h5:
                        d['unseen_target_top5'] += 1
                    # Check if target is a high-confidence unvisited candidate
                    t9p_idx_in_topk = t9p.index(tl) if tl in t9p else -1
                    if t9p_idx_in_topk >= 0 and high_conf[i, t9p_idx_in_topk]:
                        d['high_conf_target_present'] += 1
                        if h5:
                            d['high_conf_target_hit'] += 1

                # Store sample details for case studies (limit to avoid memory blowup)
                if len(d['samples']) < 5000:
                    d['samples'].append({
                        'batch': batch_idx, 'sample_i': i,
                        'target': tl, 'is_seen': is_s,
                        't9_rank': t9r, 't10e_rank': tr,
                        't9_top5': t9p[:5], 't10e_top5': rp[:5],
                        't9h5': t9h5, 't10eh5': h5,
                        'top5_visited_n': top5_visited,
                        'high_conf_count': hc_count,
                        'is_target_high_conf': (not is_s and t9p_idx_in_topk >= 0
                                                 and high_conf[i, t9p_idx_in_topk].item()),
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
            d['avg_top5_visited_ratio'] = float(np.mean(d['top5_visited_ratio']))
            d['avg_top5_unvisited_ratio'] = float(np.mean(d['top5_unvisited_ratio']))
        r['diag'] = d

    return r


# ==============================================================================
# Report Generation
# ==============================================================================

def gen_report(path, bc, test_r, t9_test, t10e1_test_r,
               stage_a_grid, stage_b_grid, stage_c_grid,
               n_params, oh_ms, diag_json_path, cases_csv_path,
               thresholds_dict, best_quantile):
    """生成 T10e-2 完整中文实验报告（Markdown 格式）。

    包含：方法说明、Strict Protocol、Val 网格搜索结果、Test 评估、
    Seen/Unseen 对比、Flip 分析（vs T9 / vs T10e-1）、Rank Change、
    高置信度 Boost 诊断、核心问题回答、案例研究、版本对比总结。
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
    t10e1 = {'HR@1': 21.31, 'HR@5': 50.54, 'HR@10': 60.30,
             'seen_HR@5': 73.62, 'unseen_HR@5': 11.91,
             'NDCG@5': 0.3693, 'NDCG@10': 0.4011,
             'MRR@5': 0.3239, 'MRR@10': 0.3372}

    diag = test_r.get('diag', {})
    t10e1_diag = t10e1_test_r.get('diag', {})
    fg = diag.get('fg', 0)
    fl = diag.get('fl', 0)
    t10e1_fg = t10e1_diag.get('fg', 0)
    t10e1_fl = t10e1_diag.get('fl', 0)

    # Compute T10e-1 vs T10e-2 flip counts from samples
    t10e2_samples = {f"{s['batch']}_{s['sample_i']}": s for s in diag.get('samples', [])}
    t10e1_samples = {f"{s['batch']}_{s['sample_i']}": s for s in t10e1_diag.get('samples', [])}

    t10e1_miss_t10e2_hit = 0
    t10e1_hit_t10e2_miss = 0
    t10e1_miss_t10e2_hit_examples = []
    t10e1_hit_t10e2_miss_examples = []

    for key, te2 in t10e2_samples.items():
        te1 = t10e1_samples.get(key)
        if te1 is None:
            continue
        if (not te1.get('t10eh5', False)) and te2.get('t10eh5', False):
            t10e1_miss_t10e2_hit += 1
            if len(t10e1_miss_t10e2_hit_examples) < 5:
                t10e1_miss_t10e2_hit_examples.append({'te1': te1, 'te2': te2})
        elif te1.get('t10eh5', False) and (not te2.get('t10eh5', False)):
            t10e1_hit_t10e2_miss += 1
            if len(t10e1_hit_t10e2_miss_examples) < 5:
                t10e1_hit_t10e2_miss_examples.append({'te1': te1, 'te2': te2})

    all_grid = stage_a_grid + stage_b_grid + stage_c_grid

    lines = [
        "# T10e-2: High-confidence Unvisited Boost — 实验报告", "",
        f"**日期**: 2026-07-07  **数据集**: Foursquare TKY",
        f"**T9 Baseline**: Test HR@5={t9.get('HR@5',0):.2f}%", "",
        "---", "",
        "## 一、方法说明", "",
        "### 1.1 核心思想", "",
        "在 T10e-1 Visited/Unvisited 分流基础上，对 Unvisited 候选进一步区分：",
        "- **高置信度 Unvisited**（explore_score ≥ 阈值）：给予更强 boost + 固定加分 τ",
        "- **低置信度 Unvisited**（explore_score < 阈值）：保留较弱探索信号",
        "",
        "目标是恢复 T10e-1 中受损的 Unseen HR@5，同时保住 Seen 和 NDCG 收益。", "",
        "### 1.2 分数公式", "",
        "```",
        "base_score(i) = α*norm_t9(i) + β*poi_transition(i) + γ*intent_geo(i) + δ*local_pop(i)",
        "explore_score(i) = β*poi_transition(i) + γ*intent_geo(i) + δ*local_pop(i)",
        "",
        "if candidate_i in user_causal_history:",
        "    final_score(i) = base_score(i) + ρ_seen * revisit_frequency_score(i)",
        "else:",
        "    if explore_score(i) >= explore_threshold:",
        "        final_score(i) = base_score(i) + η_high * explore_score(i) + τ_unvisited",
        "    else:",
        "        final_score(i) = base_score(i) + η_low  * explore_score(i)",
        "```", "",
        "### 1.3 核心参数", "",
        f"- **explore_threshold**: Val Unvisited 候选 explore_score 的 Q{int(best_quantile)} 分位数",
        f"  (阈值 = {bc.get('explore_threshold', 0):.6f})",
        f"- **η_high**: 高置信度 Unvisited 探索权重",
        f"- **η_low**: 低置信度 Unvisited 探索权重",
        f"- **τ_unvisited**: 高置信度 Unvisited 固定加分",
        f"- **ρ_seen**: Visited 候选 revisit 权重（frequency 归一化）", "",
        "### 1.4 分阶段搜索", "",
        "**Stage A**: 固定 ρ=0.15, η_low=0.10, τ=0.02，搜索 η_high × threshold_quantile",
        f"  - η_high ∈ [0.15, 0.20, 0.25, 0.30, 0.40]",
        f"  - threshold_quantile ∈ [50, 60, 70, 80, 90]",
        f"  - 组合数: 5×5=25", "",
        "**Stage B**: 固定 Stage A 最佳 η_high/threshold，搜索 ρ_seen × η_low × τ",
        f"  - ρ_seen ∈ [0.10, 0.12, 0.15, 0.18]",
        f"  - η_low ∈ [0.05, 0.08, 0.10]",
        f"  - τ_unvisited ∈ [0.00, 0.01, 0.02, 0.03, 0.05]",
        f"  - 组合数: 4×3×5=60", "",
        "**Stage C**: 在最佳配置附近微调", "",
        "固定参数：K=100, norm=zscore, α=1.0, β=0.062, γ=0.10, δ=0.05, revisit_type=frequency", "",
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
        "| 无 GNN / 无大参数 | ✅ |",
        "| 无训练，eval-only | ✅ |", "",
        "---", "",
        "## 三、Val 网格搜索", "",
        f"总组合数: {len(all_grid)} (Stage A: {len(stage_a_grid)}, Stage B: {len(stage_b_grid)}, Stage C: {len(stage_c_grid)})", "",
        "### 3.1 Explore Score 分布 (Val Unvisited Candidates)", "",
    ]

    for q in sorted(thresholds_dict.keys()):
        marker = " ← **选中**" if q == best_quantile else ""
        lines.append(f"- **Q{q}**: {thresholds_dict[q]:.6f}{marker}")

    lines += ["", "### 3.2 最佳配置", "",
              f"```json",
              f"{json.dumps(bc, indent=2, ensure_ascii=False)}",
              f"```", "",
              f"**最佳 Val HR@5**: {bc.get('best_val_hr5', 0):.2f}% "
              f"(T9 Val HR@5={t9_test.get('val_hr5', 44.18):.2f}%)",
              f"**最佳 Val Seen HR@5**: {bc.get('best_val_seen_hr5', 0):.2f}%",
              f"**最佳 Val Unseen HR@5**: {bc.get('best_val_unseen_hr5', 0):.2f}%",
              f"**最佳 Val NDCG@5**: {bc.get('best_val_ndcg5', 0):.4f}", ""]

    # Stage A top results
    if stage_a_grid:
        lines += ["### 3.3 Stage A Top-5 (η_high × threshold)", "",
                  "| # | η_high | Q | HR@5 | Seen HR@5 | Unseen HR@5 | NDCG@5 |",
                  "|---|--------|---|------|-----------|-------------|--------|"]
        sa = sorted(stage_a_grid, key=lambda x: x['HR@5'], reverse=True)[:5]
        for rank, g in enumerate(sa):
            lines.append(f"| {rank+1} | {g.get('eta_high',0):.3f} | "
                         f"{g.get('threshold_quantile',0)} | "
                         f"{g['HR@5']:.2f}% | {g.get('seen_HR@5',0):.2f}% | "
                         f"{g.get('unseen_HR@5',0):.2f}% | {g.get('NDCG@5',0):.4f} |")

    # Stage B top results
    if stage_b_grid:
        lines += ["", "### 3.4 Stage B Top-5 (ρ_seen × η_low × τ)", "",
                  "| # | ρ_seen | η_low | τ | HR@5 | Seen HR@5 | Unseen HR@5 | NDCG@5 |",
                  "|---|--------|-------|-----|------|-----------|-------------|--------|"]
        sb = sorted(stage_b_grid, key=lambda x: x['HR@5'], reverse=True)[:5]
        for rank, g in enumerate(sb):
            lines.append(f"| {rank+1} | {g.get('rho_seen',0):.3f} | "
                         f"{g.get('eta_low',0):.3f} | {g.get('tau',0):.3f} | "
                         f"{g['HR@5']:.2f}% | {g.get('seen_HR@5',0):.2f}% | "
                         f"{g.get('unseen_HR@5',0):.2f}% | {g.get('NDCG@5',0):.4f} |")

    # ========== Test Results ==========
    lines += ["", "---", "",
              "## 四、Test 评估结果", "",
              "### 4.1 主要指标", "",
              "| 指标 | T9 | V1 | V1.1 | V1.3 | T10e-1 | **T10e-2** | Δ vs T10e-1 |",
              "|------|-----|-----|------|------|--------|-----------|-------------|"]

    for m in ['HR@1', 'HR@5', 'HR@10']:
        t9v = t9.get(m, 0)
        v1v = v1.get(m, 0)
        v11v = v11.get(m, 0)
        v13v = v13.get(m, 0)
        e1v = t10e1.get(m, 0)
        tv = test_r.get(m, 0)
        lines.append(f"| {m} | {t9v:.2f}% | {v1v:.2f}% | {v11v:.2f}% | {v13v:.2f}% | "
                     f"{e1v:.2f}% | **{tv:.2f}%** | {tv-e1v:+.2f}% |")

    for m in ['NDCG@5', 'NDCG@10', 'MRR@5', 'MRR@10']:
        t9v = t9.get(m, 0)
        e1v = t10e1.get(m, 0)
        tv = test_r.get(m, 0)
        lines.append(f"| {m} | {t9v:.4f} | - | - | - | {e1v:.4f} | **{tv:.4f}** | {tv-e1v:+.4f} |")

    # Seen/Unseen comparison
    lines += ["", "### 4.2 Seen/Unseen 对比", "",
              "| 指标 | T9 | V1 | V1.1 | T10e-1 | **T10e-2** | Δ vs T10e-1 | Δ vs T9 |",
              "|------|-----|-----|------|--------|-----------|-------------|---------|"]
    for lbl, k, t9v in [('Seen HR@5', 'seen_HR@5', 71.11),
                          ('Unseen HR@5', 'unseen_HR@5', 12.01)]:
        v1v = v1.get(k, 0)
        v11v = v11.get(k, 0)
        e1v = t10e1.get(k, 0)
        tv = test_r.get(k, 0)
        lines.append(f"| {lbl} | {t9v:.2f}% | {v1v:.2f}% | {v11v:.2f}% | "
                     f"{e1v:.2f}% | **{tv:.2f}%** | {tv-e1v:+.2f}% | {tv-t9v:+.2f}% |")

    for k_val in [1, 10]:
        for prefix, label in [('seen', 'Seen'), ('unseen', 'Unseen')]:
            k_name = f'{prefix}_HR@{k_val}'
            e1v = t10e1_test_r.get(k_name, 0) if k_val == 5 else 0
            tv = test_r.get(k_name, 0)
            if tv:
                lines.append(f"| {label} HR@{k_val} | - | - | - | "
                             f"{e1v:.2f}% | **{tv:.2f}%** | - | - |")

    # Flip analysis
    lines += ["", "### 4.3 Flip 分析（vs T9）", "",
              f"- T9 miss@5 → T10e-2 hit@5: **{fg}**",
              f"- T9 hit@5 → T10e-2 miss@5: **{fl}**",
              f"- **Net Gain vs T9: {fg-fl:+d}**", "",
              "### 4.4 Flip 分析（vs T10e-1）", "",
              f"- T10e-1 miss@5 → T10e-2 hit@5: **{t10e1_miss_t10e2_hit}**",
              f"- T10e-1 hit@5 → T10e-2 miss@5: **{t10e1_hit_t10e2_miss}**",
              f"- **Net Gain vs T10e-1: {t10e1_miss_t10e2_hit-t10e1_hit_t10e2_miss:+d}**"]

    # Rank changes
    if diag.get('t9r'):
        t9r_all = np.mean(diag['t9r'])
        tr_all = np.mean(diag['tr'])
        lines += ["", "### 4.5 Rank Change", "",
                  f"- T9 mean rank: {t9r_all:.2f} → T10e-2: {tr_all:.2f} (Δ={tr_all-t9r_all:+.2f})"]
        if diag.get('t9r_seen'):
            lines.append(f"- Seen: T9={np.mean(diag['t9r_seen']):.2f} → T10e-2={np.mean(diag['tr_seen']):.2f}")
        if diag.get('t9r_unseen'):
            lines.append(f"- Unseen: T9={np.mean(diag['t9r_unseen']):.2f} → T10e-2={np.mean(diag['tr_unseen']):.2f}")

    # Top-5 composition
    if diag.get('avg_top5_visited_ratio') is not None:
        t10e1_visited = t10e1_diag.get('avg_top5_visited_ratio', 0)
        t10e2_visited = diag['avg_top5_visited_ratio']
        lines += ["", "### 4.6 Top-5 Visited/Unvisited 比例", "",
                  f"- T10e-1: visited={t10e1_visited*100:.1f}%, unvisited={(1-t10e1_visited)*100:.1f}%",
                  f"- T10e-2: visited={t10e2_visited*100:.1f}%, unvisited={(1-t10e2_visited)*100:.1f}%",
                  f"- Δ visited ratio: {(t10e2_visited-t10e1_visited)*100:+.1f}pp"]

    # High-confidence boost diagnostics
    lines += ["", "### 4.7 High-confidence Boost 诊断", "",
              f"- 触发 high-confidence boost 的样本数: {diag.get('high_conf_triggered',0)} / {diag.get('tot',1)} "
              f"({diag.get('high_conf_triggered',0)/max(diag.get('tot',1),1)*100:.1f}%)",
              f"- High-confidence unvisited 候选总数: {diag.get('high_conf_total',0)}",
              f"- 平均每样本 high-conf 候选数: {diag.get('high_conf_total',0)/max(diag.get('tot',1),1):.1f}",
              f"- Unseen target 命中 high-confidence: {diag.get('high_conf_target_present',0)} / "
              f"{diag.get('unseen_target_count',1)} ({diag.get('high_conf_target_present',0)/max(diag.get('unseen_target_count',1),1)*100:.1f}%)",
              f"- High-confidence target hit@5: {diag.get('high_conf_target_hit',0)} / "
              f"{max(diag.get('high_conf_target_present',1),1)} "
              f"({diag.get('high_conf_target_hit',0)/max(diag.get('high_conf_target_present',1),1)*100:.1f}%)",
              f"- Unseen target top-5 命中: {diag.get('unseen_target_top5',0)} / "
              f"{diag.get('unseen_target_count',1)} "
              f"({diag.get('unseen_target_top5',0)/max(diag.get('unseen_target_count',1),1)*100:.1f}%)"]

    # ========== Core Questions ==========
    lines += ["", "---", "",
              "## 五、核心问题回答", "",
              "| # | 问题 | 回答 |",
              "|---|------|------|"]

    def qa(q, a):
        lines.append(f"| {q} | {a} |")

    qa(1, f"Overall HR@5: **{test_r.get('HR@5',0):.2f}%** "
       f"(T9={t9.get('HR@5',0):.2f}%, T10e-1={t10e1['HR@5']:.2f}%)")
    qa(2, f"Seen HR@5: **{test_r.get('seen_HR@5',0):.2f}%** "
       f"(T10e-1={t10e1['seen_HR@5']:.2f}%)")
    qa(3, f"Unseen HR@5: **{test_r.get('unseen_HR@5',0):.2f}%** "
       f"(T9={71.11 if False else 12.01:.2f}%, T10e-1={t10e1['unseen_HR@5']:.2f}%)")

    # Fix: use proper T9 unseen value
    t9_unseen_hr5 = 12.01
    lines[-1] = (f"| 3 | Unseen HR@5: **{test_r.get('unseen_HR@5',0):.2f}%** "
                 f"(T9={t9_unseen_hr5:.2f}%, T10e-1={t10e1['unseen_HR@5']:.2f}%) |")

    qa(4, f"NDCG@5: **{test_r.get('NDCG@5',0):.4f}** "
       f"(T9={t9.get('NDCG@5',0.3687):.4f}, T10e-1={t10e1['NDCG@5']:.4f})")
    qa(5, f"MRR@10: **{test_r.get('MRR@10',0):.4f}** "
       f"(T10e-1={t10e1.get('MRR@10',0):.4f})")
    qa(6, f"T9 miss→T10e-2 hit: **{fg}**")
    qa(7, f"T9 hit→T10e-2 miss: **{fl}**")
    qa(8, f"Net gain vs T9: **{fg-fl:+d}**")
    qa(9, f"High-confidence boost 是否恢复 Unseen: "
       f"**{'是' if test_r.get('unseen_HR@5',0) > t10e1['unseen_HR@5'] else '否'}** "
       f"(T10e-2={test_r.get('unseen_HR@5',0):.2f}% vs T10e-1={t10e1['unseen_HR@5']:.2f}%)")
    qa(10, f"是否伤害 Seen: "
        f"**{'否' if test_r.get('seen_HR@5',0) >= t10e1['seen_HR@5'] - 1.0 else '是'}** "
        f"(T10e-2={test_r.get('seen_HR@5',0):.2f}% vs T10e-1={t10e1['seen_HR@5']:.2f}%)")
    qa(11, f"是否提升 NDCG/MRR: "
        f"NDCG@5 {'✅' if test_r.get('NDCG@5',0) > t10e1['NDCG@5'] else '持平' if abs(test_r.get('NDCG@5',0)-t10e1['NDCG@5'])<0.001 else '❌'}、"
        f"MRR@10 {'✅' if test_r.get('MRR@10',0) > t10e1.get('MRR@10',0) else '持平' if abs(test_r.get('MRR@10',0)-t10e1.get('MRR@10',0))<0.001 else '❌'}")
    qa(12, "新增参数量: **0** — 纯 rerank，无新增可学习参数")
    qa(13, f"推理开销: **{oh_ms:.1f}ms**",)

    # ========== Case Studies ==========
    lines += ["", "---", "",
              "## 六、案例研究", "",
              "### 6.1 T10e-1 miss → T10e-2 hit（5 例）", "",
              "| Target | Seen? | T10e-1 Rank | T10e-2 Rank | High-Conf? | 分析 |",
              "|--------|-------|-------------|-------------|------------|------|"]
    for ex in t10e1_miss_t10e2_hit_examples[:5]:
        te1 = ex['te1']; te2 = ex['te2']
        lines.append(f"| {te1.get('target','?')} | {te1.get('is_seen',False)} | "
                     f"{te1.get('t10e_rank','?')} | {te2.get('t10e_rank','?')} | "
                     f"{te2.get('is_target_high_conf',False)} | "
                     f"{'HC boost 推动' if te2.get('is_target_high_conf',False) else '综合效果'} |")

    lines += ["", "### 6.2 T10e-1 hit → T10e-2 miss（5 例）", "",
              "| Target | Seen? | T10e-1 Rank | T10e-2 Rank | 分析 |",
              "|--------|-------|-------------|-------------|------|"]
    for ex in t10e1_hit_t10e2_miss_examples[:5]:
        te1 = ex['te1']; te2 = ex['te2']
        reason = "revisit 保护减弱" if te1.get('is_seen', False) else "HC/Low 分割导致排序变化"
        lines.append(f"| {te1.get('target','?')} | {te1.get('is_seen',False)} | "
                     f"{te1.get('t10e_rank','?')} | {te2.get('t10e_rank','?')} | {reason} |")

    # ========== Summary Table ==========
    lines += ["", "---", "",
              "## 七、与各版本对比总结", "",
              "| 模型 | HR@5 | Seen HR@5 | Unseen HR@5 | NDCG@5 | MRR@10 | 特点 |",
              "|------|------|-----------|-------------|--------|--------|------|",
              f"| T9 | {t9.get('HR@5',0):.2f}% | 71.11% | 12.01% | {t9.get('NDCG@5',0.3687):.4f} | 0.3370 | 基线 |",
              f"| V1 | {v1['HR@5']:.2f}% | {v1['seen_HR@5']:.2f}% | {v1['unseen_HR@5']:.2f}% | {v1['NDCG@5']:.4f} | {v1['MRR@10']:.4f} | 轻量 rerank |",
              f"| V1.1 | {v11['HR@5']:.2f}% | {v11['seen_HR@5']:.2f}% | {v11['unseen_HR@5']:.2f}% | {v11['NDCG@5']:.4f} | {v11['MRR@10']:.4f} | revisit 统治 |",
              f"| V1.3 | {v13['HR@5']:.2f}% | {v13['seen_HR@5']:.2f}% | {v13['unseen_HR@5']:.2f}% | {v13['NDCG@5']:.4f} | - | 分段权重 |",
              f"| T10e-1 | {t10e1['HR@5']:.2f}% | {t10e1['seen_HR@5']:.2f}% | {t10e1['unseen_HR@5']:.2f}% | {t10e1['NDCG@5']:.4f} | {t10e1.get('MRR@10',0):.4f} | 分流 rerank |",
              f"| **T10e-2** | **{test_r.get('HR@5',0):.2f}%** | **{test_r.get('seen_HR@5',0):.2f}%** | **{test_r.get('unseen_HR@5',0):.2f}%** | **{test_r.get('NDCG@5',0):.4f}** | **{test_r.get('MRR@10',0):.4f}** | HC Unvisited Boost |",
              "", "---", "",
              "## 八、输出文件", "",
              f"- Val Grid CSV: `results/TKY/T10/t10e_2_unvisited_boost_val_grid.csv`",
              f"- Test CSV: `results/TKY/T10/t10e_2_unvisited_boost_test_result.csv`",
              f"- 诊断 JSON: `{os.path.basename(diag_json_path)}`",
              f"- 案例 CSV: `{os.path.basename(cases_csv_path)}`",
              f"- 报告: `results/TKY/T10/17_t10e_2_unvisited_boost_report.md`", "",
              "---", "",
              "*报告由 src/run_t10e_2_unvisited_boost.py 自动生成于 2026-07-07。所有分析以中文呈现。*"
    ]

    with open(path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
    print(f"Report: {path}")


# ==============================================================================
# Diagnostics
# ==============================================================================

def build_diagnostics(t10e2_r, t10e1_r, out_dir):
    """构建 T10e-2 诊断文件（JSON + CSV）。

    对比 T10e-1 和 T10e-2 的 per-sample 排序结果，统计：
    - Flip 变化（T10e-1 miss → T10e-2 hit，反之亦然）
    - Unseen target top-5 变化
    - High-confidence boost 的诊断指标
    输出到诊断 JSON（结构化汇总）和案例 CSV（Top-5 翻转案例）。
    """
    diag = t10e2_r.get('diag', {})
    t10e1_diag = t10e1_r.get('diag', {})

    # Build sample lookups
    t10e2_samples = {f"{s['batch']}_{s['sample_i']}": s for s in diag.get('samples', [])}
    t10e1_samples = {f"{s['batch']}_{s['sample_i']}": s for s in t10e1_diag.get('samples', [])}

    # Count flips
    t10e1_miss_t10e2_hit = []
    t10e1_hit_t10e2_miss = []

    for key, te2 in t10e2_samples.items():
        te1 = t10e1_samples.get(key)
        if te1 is None:
            continue
        te2_ok = te2.get('t10eh5', False)
        te1_ok = te1.get('t10eh5', False)

        if not te1_ok and te2_ok:
            t10e1_miss_t10e2_hit.append({
                'case_type': 'T10e1_miss_T10e2_hit',
                'target': te2['target'], 'is_seen': te2['is_seen'],
                't9_top5': str(te2['t9_top5']),
                't10e1_top5': str(te1['t10e_top5']),
                't10e2_top5': str(te2['t10e_top5']),
                't9_rank': te2['t9_rank'], 't10e1_rank': te1.get('t10e_rank', 0),
                't10e2_rank': te2['t10e_rank'],
                'is_target_high_conf': te2.get('is_target_high_conf', False),
            })
        elif te1_ok and not te2_ok:
            t10e1_hit_t10e2_miss.append({
                'case_type': 'T10e1_hit_T10e2_miss',
                'target': te2['target'], 'is_seen': te2['is_seen'],
                't9_top5': str(te2['t9_top5']),
                't10e1_top5': str(te1['t10e_top5']),
                't10e2_top5': str(te2['t10e_top5']),
                't9_rank': te2['t9_rank'], 't10e1_rank': te1.get('t10e_rank', 0),
                't10e2_rank': te2['t10e_rank'],
            })

    # Unseen target pushed out comparison
    unseen_t10e1_top5 = sum(1 for s in t10e1_samples.values()
                            if not s.get('is_seen', True) and s.get('t10eh5', False))
    unseen_t10e2_top5 = diag.get('unseen_target_top5', 0)
    # Net change in unseen targets making top-5
    unseen_delta = unseen_t10e2_top5 - unseen_t10e1_top5

    # Build diagnostics JSON
    diag_json = {
        'top5_visited_ratio_mean': float(np.mean(diag.get('top5_visited_ratio', [0]))),
        'top5_unvisited_ratio_mean': float(np.mean(diag.get('top5_unvisited_ratio', [0]))),
        'revisit_activated_samples': diag.get('revisit_activated', 0),
        'total_samples': diag.get('tot', 0),
        't9_miss_t10e2_hit': diag.get('fg', 0),
        't9_hit_t10e2_miss': diag.get('fl', 0),
        'net_gain': diag.get('fg', 0) - diag.get('fl', 0),
        'seen_unseen_balance': {
            'seen_hr5': t10e2_r.get('seen_HR@5', 0),
            'unseen_hr5': t10e2_r.get('unseen_HR@5', 0),
            'seen_unseen_gap': round(t10e2_r.get('seen_HR@5', 0) - t10e2_r.get('unseen_HR@5', 0), 2),
        },
        'high_confidence_diagnostics': {
            'triggered_samples': diag.get('high_conf_triggered', 0),
            'triggered_pct': round(diag.get('high_conf_triggered', 0) / max(diag.get('tot', 1), 1) * 100, 1),
            'total_candidates': diag.get('high_conf_total', 0),
            'avg_per_sample': round(diag.get('high_conf_total', 0) / max(diag.get('tot', 1), 1), 1),
            'target_in_high_conf': diag.get('high_conf_target_present', 0),
            'target_in_high_conf_hit5': diag.get('high_conf_target_hit', 0),
            'target_hit_rate_pct': round(
                diag.get('high_conf_target_hit', 0) / max(diag.get('high_conf_target_present', 1), 1) * 100, 1),
        },
        't10e1_vs_t10e2': {
            't10e1_miss_t10e2_hit': len(t10e1_miss_t10e2_hit),
            't10e1_hit_t10e2_miss': len(t10e1_hit_t10e2_miss),
            'net_vs_t10e1': len(t10e1_miss_t10e2_hit) - len(t10e1_hit_t10e2_miss),
            'unseen_top5_t10e1': unseen_t10e1_top5,
            'unseen_top5_t10e2': unseen_t10e2_top5,
            'unseen_top5_delta': unseen_delta,
        },
    }

    json_path = os.path.join(out_dir, "t10e_2_unvisited_boost_diagnostics.json")
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(diag_json, f, indent=2, ensure_ascii=False)
    print(f"Diagnostics: {json_path}")

    # Build cases CSV
    cases = []
    for ex in t10e1_miss_t10e2_hit[:5]:
        cases.append(ex)
    for ex in t10e1_hit_t10e2_miss[:5]:
        cases.append(ex)

    cases_path = os.path.join(out_dir, "t10e_2_unvisited_boost_cases.csv")
    if cases:
        fields = ['case_type', 'target', 'is_seen', 't9_rank', 't10e1_rank', 't10e2_rank',
                   't9_top5', 't10e1_top5', 't10e2_top5', 'is_target_high_conf']
        with open(cases_path, 'w', newline='', encoding='utf-8') as f:
            w = csv.DictWriter(f, fieldnames=fields, extrasaction='ignore')
            w.writeheader()
            for c in cases:
                w.writerow(c)
    else:
        with open(cases_path, 'w', newline='', encoding='utf-8') as f:
            f.write("case_type,target,is_seen\n")

    print(f"Cases CSV: {cases_path} ({len(cases)} cases)")
    return json_path, cases_path


# ==============================================================================
# Main
# ==============================================================================

def parse_args():
    parser = argparse.ArgumentParser(description="T10e-2 Unvisited Boost evaluation")
    parser.add_argument(
        "--fixed-config", action="store_true",
        help="Validate and test the published best config instead of repeating the exhaustive grid",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    fixed_config = args.fixed_config
    set_seed(cfg.SEED)
    device = get_device()
    print(f"Device: {device}")
    out_dir = os.path.join(cfg.SAVE_DIR, "T10")
    os.makedirs(out_dir, exist_ok=True)
    ckpt_path = os.path.join(cfg.CHECKPOINT_DIR, "T9_CausalMemoryFusion_best.pth")

    # --- Data pipeline (identical to T10e-1) ---
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
                             local_files_only=cfg.SBERT_LOCAL_FILES_ONLY)
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
    print(f"T9 Val HR@5={t9_val['HR@5']:.2f}% (Seen={t9_val.get('seen_HR@5',0):.2f}%, "
          f"Unseen={t9_val.get('unseen_HR@5',0):.2f}%)")
    print(f"T9 Test HR@5={t9_test['HR@5']:.2f}%")

    # Fixed params
    K = 100
    norm = 'zscore'
    alpha, beta, gamma, delta = 1.0, 0.062, 0.10, 0.05

    # Pre-compute explore thresholds
    print("\n=== Pre-compute Explore Score Thresholds (on Val) ===")
    quantile_opts = [90] if fixed_config else [50, 60, 70, 80, 90]
    thresholds = compute_explore_thresholds(
        model, val_ldr, device, poi_bias_fn, geo_bias_fn, local_bias_fn,
        K, beta, gamma, delta, pzt, nz, quantile_opts)

    # Val constraints
    t9_val_seen_hr5 = t9_val.get('seen_HR@5', 66.06)
    t9_val_unseen_hr5 = t9_val.get('unseen_HR@5', 9.0)

    # Also compute T10e-1 val baseline for constraints
    print("\n=== T10e-1 Val Baseline (for constraint) ===")
    t10e1_val = eval_split_rerank(
        model, val_ldr, device, poi_bias_fn, geo_bias_fn, local_bias_fn,
        K, norm, alpha, beta, gamma, delta,
        rho_seen=0.15, eta_unseen=0.10, revisit_type='frequency', hybrid_a=0.5,
        poi_zone_tensor=pzt, num_zones=nz)
    t10e1_val_seen_hr5 = t10e1_val.get('seen_HR@5', 66.79)
    print(f"T10e-1 Val Seen HR@5={t10e1_val_seen_hr5:.2f}% (constraint: >= {t10e1_val_seen_hr5-0.3:.2f}%)")
    print(f"T9 Val Unseen HR@5={t9_val_unseen_hr5:.2f}% (constraint: >= {t9_val_unseen_hr5:.2f}%)")

    # ========================================================================
    # STAGE A: 搜索 η_high × threshold_quantile
    # 固定 ρ_seen=0.15, η_low=0.10, τ=0.02
    # 目标：找到最优的高置信度探索权重和分位数阈值组合
    # 约束：Seen HR@5 >= T10e-1 Val Seen HR@5 - 0.3，Unseen HR@5 >= T9 Val Unseen HR@5
    # ========================================================================
    print("\n" + "=" * 70)
    print("STAGE A: Searching eta_high × threshold_quantile")
    print(f"  Fixed: ρ_seen=0.15, η_low=0.10, τ=0.02")
    print("=" * 70)

    eta_high_opts = [0.15] if fixed_config else [0.15, 0.20, 0.25, 0.30, 0.40]
    stage_a_grid = []

    for q in quantile_opts:
        for eh in eta_high_opts:
            r = eval_unvisited_boost(
                model, val_ldr, device,
                poi_bias_fn, geo_bias_fn, local_bias_fn,
                K, norm, alpha, beta, gamma, delta,
                rho_seen=0.15, eta_low=0.10, eta_high=eh,
                tau_unvisited=0.02, explore_threshold=thresholds[q],
                poi_zone_tensor=pzt, num_zones=nz)

            row = {
                'stage': 'A', 'eta_high': eh, 'threshold_quantile': q,
                'explore_threshold': thresholds[q],
                'rho_seen': 0.15, 'eta_low': 0.10, 'tau': 0.02,
                'HR@5': r['HR@5'], 'seen_HR@5': r.get('seen_HR@5', 0),
                'unseen_HR@5': r.get('unseen_HR@5', 0),
                'NDCG@5': r.get('NDCG@5', 0),
                'MRR@10': r.get('MRR@10', 0),
            }
            stage_a_grid.append(row)
            print(f"  Q={q} η_high={eh:.2f} → HR@5={r['HR@5']:.2f}% "
                  f"S={r.get('seen_HR@5',0):.2f}% U={r.get('unseen_HR@5',0):.2f}% "
                  f"NDCG@5={r.get('NDCG@5',0):.4f}")

    # ========================================================================
    # STAGE B: 搜索 ρ_seen × η_low × τ
    # 固定 Stage A 最优的 η_high 和 threshold_quantile
    # 目标：微调 visited boost 权重、低置信度 unvisited boost 权重和固定加分 τ
    # 约束同 Stage A（保护 Seen，不退化 Unseen）
    # ========================================================================
    print("\n" + "=" * 70)
    print("STAGE B: Searching ρ_seen × η_low × τ")
    print("=" * 70)

    # Find best from Stage A (with constraints)
    def meets_constraints(r):
        seen_ok = r.get('seen_HR@5', 0) >= t10e1_val_seen_hr5 - 0.3
        unseen_ok = r.get('unseen_HR@5', 0) >= t9_val_unseen_hr5
        return seen_ok and unseen_ok

    def select_best(grid):
        """Select best config: constraint-aware, then HR@5, tie-break NDCG, then Unseen."""
        # First try constraints
        valid = [g for g in grid if meets_constraints(g)]
        if not valid:
            print("  WARNING: No config met constraints, using overall best HR@5")
            valid = grid
        # Sort: HR@5 desc, tie-break NDCG@5 desc, then Unseen HR@5 desc
        valid.sort(key=lambda x: (x['HR@5'], x.get('NDCG@5', 0), x.get('unseen_HR@5', 0)), reverse=True)
        return valid[0]

    best_a = select_best(stage_a_grid)
    best_eta_high = best_a['eta_high']
    best_threshold_q = best_a['threshold_quantile']
    best_threshold = thresholds[best_threshold_q]
    print(f"Stage A Best: η_high={best_eta_high:.2f}, Q={best_threshold_q} "
          f"(threshold={best_threshold:.6f}), HR@5={best_a['HR@5']:.2f}%")

    rho_seen_opts = [0.20] if fixed_config else [0.10, 0.12, 0.15, 0.18]
    eta_low_opts = [0.10] if fixed_config else [0.05, 0.08, 0.10]
    tau_opts = [0.00] if fixed_config else [0.00, 0.01, 0.02, 0.03, 0.05]
    stage_b_grid = []

    for rho in rho_seen_opts:
        for el in eta_low_opts:
            for tau in tau_opts:
                r = eval_unvisited_boost(
                    model, val_ldr, device,
                    poi_bias_fn, geo_bias_fn, local_bias_fn,
                    K, norm, alpha, beta, gamma, delta,
                    rho_seen=rho, eta_low=el, eta_high=best_eta_high,
                    tau_unvisited=tau, explore_threshold=best_threshold,
                    poi_zone_tensor=pzt, num_zones=nz)

                row = {
                    'stage': 'B', 'rho_seen': rho, 'eta_low': el, 'tau': tau,
                    'eta_high': best_eta_high, 'threshold_quantile': best_threshold_q,
                    'explore_threshold': best_threshold,
                    'HR@5': r['HR@5'], 'seen_HR@5': r.get('seen_HR@5', 0),
                    'unseen_HR@5': r.get('unseen_HR@5', 0),
                    'NDCG@5': r.get('NDCG@5', 0),
                    'MRR@10': r.get('MRR@10', 0),
                }
                stage_b_grid.append(row)

    best_b = select_best(stage_b_grid)
    print(f"Stage B Best: ρ_seen={best_b['rho_seen']:.2f}, η_low={best_b['eta_low']:.2f}, "
          f"τ={best_b['tau']:.3f}, HR@5={best_b['HR@5']:.2f}%")

    # ========================================================================
    # STAGE C: 在 Stage B 最优配置附近微调
    # 对 ρ_seen、η_low、η_high、τ 做小范围 (±0.01~0.05) 邻域搜索
    # 同时用 select_best（约束优先 → HR@5 → NDCG → Unseen）选最优
    # ========================================================================
    print("\n" + "=" * 70)
    print("STAGE C: Fine-tuning around best config")
    print("=" * 70)

    # Create small neighborhood around best
    rho_fine = [best_b['rho_seen']] if fixed_config else sorted(set(
        [best_b['rho_seen']] +
        [best_b['rho_seen'] + d for d in [-0.02, 0.02] if 0.08 <= best_b['rho_seen'] + d <= 0.20]))
    el_fine = [best_b['eta_low']] if fixed_config else sorted(set(
        [best_b['eta_low']] +
        [best_b['eta_low'] + d for d in [-0.02, 0.02] if 0.03 <= best_b['eta_low'] + d <= 0.12]))
    eh_fine = [best_eta_high] if fixed_config else sorted(set(
        [best_eta_high] +
        [best_eta_high + d for d in [-0.05, 0.05] if 0.10 <= best_eta_high + d <= 0.45]))
    tau_fine = [best_b['tau']] if fixed_config else sorted(set(
        [best_b['tau']] +
        [best_b['tau'] + d for d in [-0.01, 0.01] if 0.00 <= best_b['tau'] + d <= 0.06]))

    stage_c_grid = []

    for rho in rho_fine:
        for el in el_fine:
            for eh in eh_fine:
                for tau in tau_fine:
                    r = eval_unvisited_boost(
                        model, val_ldr, device,
                        poi_bias_fn, geo_bias_fn, local_bias_fn,
                        K, norm, alpha, beta, gamma, delta,
                        rho_seen=rho, eta_low=el, eta_high=eh,
                        tau_unvisited=tau, explore_threshold=best_threshold,
                        poi_zone_tensor=pzt, num_zones=nz)

                    row = {
                        'stage': 'C', 'rho_seen': rho, 'eta_low': el,
                        'eta_high': eh, 'tau': tau,
                        'threshold_quantile': best_threshold_q,
                        'explore_threshold': best_threshold,
                        'HR@5': r['HR@5'], 'seen_HR@5': r.get('seen_HR@5', 0),
                        'unseen_HR@5': r.get('unseen_HR@5', 0),
                        'NDCG@5': r.get('NDCG@5', 0),
                        'MRR@10': r.get('MRR@10', 0),
                    }
                    stage_c_grid.append(row)

    best_c = select_best(stage_c_grid)
    if best_c['HR@5'] > best_b['HR@5']:
        print(f"Stage C improved: HR@5={best_c['HR@5']:.2f}% > Stage B {best_b['HR@5']:.2f}%")
        overall_best = best_c
    else:
        print(f"Stage C no improvement, using Stage B best: HR@5={best_b['HR@5']:.2f}%")
        overall_best = best_b

    # Build best config
    best_config = {
        'K': K, 'norm': norm,
        'alpha': alpha, 'beta': beta, 'gamma': gamma, 'delta': delta,
        'rho_seen': overall_best['rho_seen'],
        'eta_low': overall_best['eta_low'],
        'eta_high': overall_best['eta_high'],
        'tau_unvisited': overall_best['tau'],
        'explore_threshold': overall_best.get('explore_threshold', best_threshold),
        'explore_threshold_quantile': overall_best.get('threshold_quantile', best_threshold_q),
        'revisit_type': 'frequency',
        'best_val_hr5': overall_best['HR@5'],
        'best_val_seen_hr5': overall_best.get('seen_HR@5', 0),
        'best_val_unseen_hr5': overall_best.get('unseen_HR@5', 0),
        'best_val_ndcg5': overall_best.get('NDCG@5', 0),
    }

    print(f"\n=== BEST CONFIG: {json.dumps(best_config, indent=2)} ===")

    # Save val grid
    all_grid = stage_a_grid + stage_b_grid + stage_c_grid
    grid_csv = os.path.join(out_dir, "t10e_2_unvisited_boost_val_grid.csv")
    fields = ['stage', 'rho_seen', 'eta_low', 'eta_high', 'tau',
              'threshold_quantile', 'explore_threshold',
              'HR@5', 'seen_HR@5', 'unseen_HR@5', 'NDCG@5', 'MRR@10']
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
    test_r = eval_unvisited_boost(
        model, test_ldr, device,
        poi_bias_fn, geo_bias_fn, local_bias_fn,
        bc['K'], bc['norm'], bc['alpha'],
        bc['beta'], bc['gamma'], bc['delta'],
        bc['rho_seen'], bc['eta_low'], bc['eta_high'],
        bc['tau_unvisited'], bc['explore_threshold'],
        pzt, nz, diag=True)
    if torch.cuda.is_available():
        torch.cuda.synchronize()
    test_time = time.perf_counter() - t0

    print(f"\nTest HR@5={test_r['HR@5']:.2f}% HR@1={test_r['HR@1']:.2f}% HR@10={test_r['HR@10']:.2f}%")
    print(f"Seen HR@5={test_r.get('seen_HR@5',0):.2f}% Unseen HR@5={test_r.get('unseen_HR@5',0):.2f}%")
    print(f"NDCG@5={test_r.get('NDCG@5',0):.4f} MRR@5={test_r.get('MRR@5',0):.4f} MRR@10={test_r.get('MRR@10',0):.4f}")
    print(f"Test time: {test_time:.1f}s")

    # ========================================================================
    # T10e-1 Comparison (on test, with diag)
    # ========================================================================
    print("\n=== T10e-1 Comparison Eval (Test, diag) ===")
    t10e1_test_r = eval_split_rerank(
        model, test_ldr, device, poi_bias_fn, geo_bias_fn, local_bias_fn,
        K, norm, alpha, beta, gamma, delta,
        rho_seen=0.15, eta_unseen=0.10, revisit_type='frequency', hybrid_a=0.5,
        poi_zone_tensor=pzt, num_zones=nz, diag=True)
    print(f"T10e-1 Test HR@5={t10e1_test_r['HR@5']:.2f}% "
          f"Seen={t10e1_test_r.get('seen_HR@5',0):.2f}% "
          f"Unseen={t10e1_test_r.get('unseen_HR@5',0):.2f}%")

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
            _ = compute_frequency_revisit(batch[3], batch[4], t9_idx)
        if torch.cuda.is_available():
            torch.cuda.synchronize()
        rerank_times.append(time.perf_counter() - t0t)
    rr_mean = np.mean(rerank_times)
    oh_ms = (rr_mean - t9t_mean) * 1000
    oh_pct = (rr_mean - t9t_mean) / t9t_mean * 100
    print(f"T9: {t9t_mean:.3f}s, T10e-2: {rr_mean:.3f}s, Overhead: {oh_ms:.1f}ms ({oh_pct:.1f}%)")

    # ========================================================================
    # Diagnostics
    # ========================================================================
    print("\n=== Building Diagnostics ===")
    diag_json_path, cases_csv_path = build_diagnostics(test_r, t10e1_test_r, out_dir)

    # ========================================================================
    # Save Test Result
    # ========================================================================
    test_csv = os.path.join(out_dir, "t10e_2_unvisited_boost_test_result.csv")
    trow = {
        'model': 'T10e-2-UnvisitedBoost',
        'K': bc['K'], 'norm': bc['norm'],
        'alpha': bc['alpha'], 'beta': bc['beta'],
        'gamma': bc['gamma'], 'delta': bc['delta'],
        'rho_seen': bc['rho_seen'], 'eta_low': bc['eta_low'],
        'eta_high': bc['eta_high'], 'tau_unvisited': bc['tau_unvisited'],
        'explore_threshold_quantile': bc['explore_threshold_quantile'],
        'explore_threshold': bc['explore_threshold'],
        'revisit_type': 'frequency',
        'HR@1': test_r['HR@1'], 'HR@5': test_r['HR@5'], 'HR@10': test_r['HR@10'],
        'NDCG@5': test_r['NDCG@5'], 'NDCG@10': test_r['NDCG@10'],
        'MRR@5': test_r['MRR@5'], 'MRR@10': test_r['MRR@10'],
        'seen_HR@5': test_r.get('seen_HR@5', 0),
        'unseen_HR@5': test_r.get('unseen_HR@5', 0),
        'seen_HR@1': test_r.get('seen_HR@1', 0),
        'seen_HR@10': test_r.get('seen_HR@10', 0),
        'unseen_HR@1': test_r.get('unseen_HR@1', 0),
        'unseen_HR@10': test_r.get('unseen_HR@10', 0),
        'seen_ratio': test_r.get('seen_ratio', 0),
        'params': n_params, 'overhead_ms': round(oh_ms, 2),
        'overhead_pct': round(oh_pct, 2),
        'best_val_hr5': bc['best_val_hr5'],
        't9_test_hr5': t9_test['HR@5'],
        't10e1_test_hr5': t10e1_test_r['HR@5'],
    }
    with open(test_csv, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=list(trow.keys()))
        w.writeheader()
        w.writerow(trow)
    print(f"Test CSV: {test_csv}")

    # ========================================================================
    # Report
    # ========================================================================
    rpt_path = os.path.join(out_dir, "17_t10e_2_unvisited_boost_report.md")
    gen_report(rpt_path, best_config, test_r, t9_test, t10e1_test_r,
               stage_a_grid, stage_b_grid, stage_c_grid,
               n_params, oh_ms, diag_json_path, cases_csv_path,
               thresholds, best_threshold_q)

    # ========================================================================
    # Summary
    # ========================================================================
    print("\n" + "=" * 70)
    print("T10e-2 High-confidence Unvisited Boost Complete!")
    print(f"T9={t9_test['HR@5']:.2f}% → T10e-1={t10e1_test_r['HR@5']:.2f}% → T10e-2={test_r['HR@5']:.2f}%")
    print(f"  Δ vs T9: {test_r['HR@5']-t9_test['HR@5']:+.2f}%, Δ vs T10e-1: {test_r['HR@5']-t10e1_test_r['HR@5']:+.2f}%")
    print(f"Seen: {test_r.get('seen_HR@5',0):.2f}% (T10e-1: {t10e1_test_r.get('seen_HR@5',0):.2f}%)")
    print(f"Unseen: {test_r.get('unseen_HR@5',0):.2f}% (T10e-1: {t10e1_test_r.get('unseen_HR@5',0):.2f}%)")
    print(f"NDCG@5: {test_r.get('NDCG@5',0):.4f} (T10e-1: {t10e1_test_r.get('NDCG@5',0):.4f})")
    print(f"MRR@10: {test_r.get('MRR@10',0):.4f} (T10e-1: {t10e1_test_r.get('MRR@10',0):.4f})")
    diag = test_r.get('diag', {})
    print(f"Flip vs T9: gain={diag.get('fg',0)}, loss={diag.get('fl',0)}, "
          f"net={diag.get('fg',0)-diag.get('fl',0):+d}")
    print(f"Top-5 visited ratio: {diag.get('avg_top5_visited_ratio', 0)*100:.1f}%")
    print(f"High-conf triggered: {diag.get('high_conf_triggered', 0)} samples "
          f"({diag.get('high_conf_triggered', 0)/max(diag.get('tot',1),1)*100:.1f}%)")
    print(f"High-conf target hit rate: {diag.get('high_conf_target_hit', 0)}/"
          f"{max(diag.get('high_conf_target_present',1),1)} "
          f"({diag.get('high_conf_target_hit', 0)/max(diag.get('high_conf_target_present',1),1)*100:.1f}%)")
    print("=" * 70)


if __name__ == "__main__":
    main()
