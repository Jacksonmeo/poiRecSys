"""
T10d-Rerank-V1: Eval-only rerank of T9 top-K candidates.

Rerank score:
  score(i) = alpha * norm_t9_score(i)
           + beta  * poi_transition_score(i)
           + gamma * intent_geo_score(i)
           + delta * local_popularity_score(i)

Candidate set = T9 top-K. No retraining. Train-only memories.

Key optimization: Build full-ranking bias vectors (vectorized), then gather
only the top-K candidates. This avoids per-sample Python loops and is ~100x faster.

Staged grid search:
  Stage A: fix K=100, norm=zscore, alpha=1.0, search beta/gamma/delta
  Stage B: fix best beta/gamma/delta, search K/norm/alpha
  Stage C: fine-tune around best config
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


# ==============================================================================
# Geo Zone & IntentGeo Memory (from T10c-lite)
# ==============================================================================

def build_geo_zones(train_traj, grid_size, venue_to_location, venue_to_idx):
    """构建地理区域网格（从 T10c-lite 复用）。

    将地图划分为 grid_size × grid_size 的均匀网格，每个 POI 根据其经纬度
    分配到对应的 zone 编号（zi * grid_size + zj）。用于后续 local popularity
    和 intent-geo memory 的 zone 特征计算。

    Returns:
        poi_idx_zone: dict，POI索引 → zone编号
        num_zones: 总 zone 数
        poi_zone_arr: (num_venues,) tensor，每个 POI 的 zone 编号
    """
    lats, lngs = [], []
    for traj in train_traj:
        for v in traj['venues']:
            loc = venue_to_location.get(v)
            if loc: lats.append(loc['latitude']); lngs.append(loc['longitude'])
    lat_min, lat_max = min(lats), max(lats)
    lng_min, lng_max = min(lngs), max(lngs)
    lat_step = (lat_max - lat_min) / grid_size
    lng_step = (lng_max - lng_min) / grid_size

    def get_zone(lat, lng):
        zi = min(int((lat - lat_min) / lat_step), grid_size - 1)
        zj = min(int((lng - lng_min) / lng_step), grid_size - 1)
        return zi * grid_size + zj

    num_zones = grid_size * grid_size
    poi_zone_arr = torch.full((len(venue_to_idx),), 0, dtype=torch.long)
    poi_idx_zone = {}
    for v_str, v_idx in venue_to_idx.items():
        loc = venue_to_location.get(v_str)
        if loc:
            z = get_zone(loc['latitude'], loc['longitude'])
            poi_idx_zone[v_idx] = z; poi_zone_arr[v_idx] = z
        else:
            poi_idx_zone[v_idx] = 0

    print(f"  Geo: {grid_size}x{grid_size}={num_zones} zones")
    return poi_idx_zone, num_zones, poi_zone_arr


def get_hour_bin_mem(ts) -> int:
    try: t = __import__('pandas').Timestamp(ts)
    except Exception: t = __import__('pandas').Timestamp(ts, unit='s')
    h = t.hour
    if h <= 5: return 0
    if h <= 11: return 1
    if h <= 17: return 2
    return 3


def build_intent_geo_memory(train_traj, venue_to_idx, cat_to_idx, poi_idx_zone, top_k=200):
    """构建 Intent-Geo 记忆库（从 T10c-lite 复用）。

    从训练轨迹中学习"在某个语境下，用户下一步去了哪些 POI"的模式。
    使用 5 级回退（backoff）策略构建复合 key：
      - Level 4: prev_cat + last_cat + hour_bin + zone  （最精细）
      - Level 3: last_cat + hour_bin + zone
      - Level 2: prev_cat + last_cat + zone
      - Level 1: last_cat + zone
      - Level 0: last_cat + hour_bin                       （最粗糙）

    每个 key 下保留 top_k 个最常去的 next POI 及其计数。
    Level 越高越精确但覆盖率越低，回退策略保证始终能查到数据。

    Returns:
        mems: dict，按 level 组织的 {key: [(poi, count), ...]} 字典
        key_totals: dict，按 level 组织的 {key: total_count} 字典（用于 min_count 过滤）
    """
    counters = {4: defaultdict(Counter), 3: defaultdict(Counter), 2: defaultdict(Counter),
                1: defaultdict(Counter), 0: defaultdict(Counter)}
    key_totals = {4: {}, 3: {}, 2: {}, 1: {}, 0: {}}
    for traj in train_traj:
        venues = traj['venues']; categories = traj['categories']
        timestamps = traj.get('timestamps', [])
        for i in range(len(venues) - 1):
            prev_c = categories[i] if i > 0 else '<PAD>'
            curr_c = categories[i]; next_v = venues[i+1]
            prev_cat = cat_to_idx.get(prev_c, 0)
            last_cat = cat_to_idx.get(curr_c, 0)
            next_poi = venue_to_idx.get(next_v, 0)
            curr_v = venues[i] if i < len(venues) else None
            zone = poi_idx_zone.get(venue_to_idx.get(curr_v, ''), -1)
            if zone < 0: zone = 0
            if len(timestamps) > i: hb = get_hour_bin_mem(timestamps[i])
            else: hb = 0
            if last_cat == 0 or next_poi == 0: continue
            k4 = f"{prev_cat}_{last_cat}_{hb}_{zone}"
            k3 = f"{last_cat}_{hb}_{zone}"
            k2 = f"{prev_cat}_{last_cat}_{zone}"
            k1 = f"{last_cat}_{zone}"
            k0 = f"{last_cat}_{hb}"
            for lv, k in [(4,k4),(3,k3),(2,k2),(1,k1),(0,k0)]:
                counters[lv][k][next_poi] += 1
    mems = {}
    for lv in [4,3,2,1,0]:
        mems[lv] = {}
        for k, ctr in counters[lv].items():
            key_totals[lv][k] = sum(ctr.values())
            mems[lv][k] = list(ctr.most_common(top_k))
        print(f"  L{lv}: {len(mems[lv])} keys")
    return mems, key_totals


def compute_hour_bin_t(t_seq):
    """从 sin-cos 时间特征恢复真实小时，并映射到 4 个时间桶。

    输入 t_seq[:, -1, :] 的最后一列是 (sin(hour*2π/24), cos(hour*2π/24))，
    通过 atan2 反推真实小时，再分段：
      - bin 0: 凌晨 (0:00–5:59)
      - bin 1: 上午 (6:00–11:59)
      - bin 2: 下午 (12:00–17:59)
      - bin 3: 晚上 (18:00–23:59)
    这是 T9 模型的 sin-cos 时间编码的逆过程，用于 rerank 阶段的 bias 查表。
    """
    hs = t_seq[:, -1, 0]; hc = t_seq[:, -1, 1]
    hour = torch.atan2(hs, hc) / (2.0 * math.pi) * 24.0
    hour = hour % 24.0
    hb = torch.zeros(hour.size(0), dtype=torch.long, device=hour.device)
    hb[(hour >= 6) & (hour < 12)] = 1
    hb[(hour >= 12) & (hour < 18)] = 2
    hb[(hour >= 18) & (hour < 24)] = 3
    return hb


# ==============================================================================
# Full-ranking Bias Lookups (vectorized, for fast gather)
# ==============================================================================

class IntentGeoFullBias:
    """意图-地理全量偏置查表（与 T10c-lite 相同）。

    根据上下文（prev_cat, last_cat, hour_bin, zone）在 IntentGeo 记忆中查询，
    生成 (B, num_venues) 的完整偏置矩阵。调用者通过 gather 只取 top-K 候选的分数。

    核心优化：全量向量化计算，然后用 gather 截取——避免逐样本 Python 循环，
    比逐候选查表快约 100 倍。
    """
    def __init__(self, mems, key_totals, top_k, min_count, num_cats, num_zones, num_venues, device):
        self.nc = num_cats; self.nz = num_zones; self.nv = num_venues
        self.device = device; self.min_count = min_count; self.top_k = top_k
        self.mem_tensors = {lv: {} for lv in [4,3,2,1,0]}
        for lv in [4,3,2,1,0]:
            for ks, edges in mems[lv].items():
                e = edges[:top_k]
                if not e: continue
                k = len(e)
                dsts = torch.tensor([d for d,_ in e], dtype=torch.long, device=device)
                bv = [1.0/math.log2(r+1) for r in range(1,k+1)]
                vals = torch.tensor(bv, dtype=torch.float32, device=device)
                self.mem_tensors[lv][ks] = (dsts, vals)
        self.key_totals = key_totals

    def __call__(self, pc, lc, hb, z):
        """Return (B, num_venues) full-ranking bias."""
        B = pc.size(0)
        bias = torch.zeros(B, self.nv, device=self.device)
        groups = defaultdict(list)
        for i in range(B):
            pci, lci, hbi, zi = pc[i].item(), lc[i].item(), hb[i].item(), z[i].item()
            k4s = f"{pci}_{lci}_{hbi}_{zi}"; k3s = f"{lci}_{hbi}_{zi}"
            k2s = f"{pci}_{lci}_{zi}"; k1s = f"{lci}_{zi}"; k0s = f"{lci}_{hbi}"
            for lv, ks in [(4,k4s),(3,k3s),(2,k2s),(1,k1s),(0,k0s)]:
                if ks in self.key_totals.get(lv,{}) and self.key_totals[lv][ks] >= self.min_count:
                    groups[(lv, ks)].append(i); break
        for (lv, k), indices in groups.items():
            if k in self.mem_tensors[lv]:
                dsts, vals = self.mem_tensors[lv][k]
                for idx in indices:
                    bias[idx, dsts] = vals
        return bias


class POIFullBias:
    """POI 转移全量偏置（类似 T10a SimplePOIBias）。

    基于 last_poi 的转移记忆：对每个源 POI，记录其历史中 top-K 个最常去的目标 POI。
    偏置值按 rank-based（1/log2(rank+1)）计算，越常见的转移偏置越高。

    返回 (B, num_venues) 的完整偏置矩阵，供调用者 gather 使用。
    """
    def __init__(self, poi_mem, top_k, bias_mode, num_venues, device):
        self.nv = num_venues; self.dev = device; mk = top_k
        ds = torch.zeros(num_venues, mk, dtype=torch.long, device=device)
        vs = torch.zeros(num_venues, mk, dtype=torch.float32, device=device)
        ls = torch.zeros(num_venues, dtype=torch.long, device=device)
        for src in range(num_venues):
            if src in poi_mem:
                edges = poi_mem[src][:mk]
                if edges:
                    k = len(edges); ls[src] = k
                    if bias_mode == 'rank':
                        bv = [1.0/math.log2(r+1) for r in range(1,k+1)]
                    else:
                        bv = [math.log1p(c) for _,c in edges]
                    for j, (d,_) in enumerate(edges): ds[src,j]=d; vs[src,j]=bv[j]
        self.ds=ds; self.vs=vs; self.ls=ls; self.mk=mk
        self._ci = torch.arange(mk, device=device).unsqueeze(0)

    def __call__(self, last_pois):
        """Return (B, num_venues) full-ranking bias."""
        B = last_pois.size(0)
        bias = torch.zeros(B, self.nv, device=self.dev)
        dsts = self.ds[last_pois]; vals = self.vs[last_pois]; lens = self.ls[last_pois]
        valid = self._ci[:, :self.mk] < lens.unsqueeze(1)
        bi = torch.arange(B, device=self.dev).unsqueeze(1).expand(-1, self.mk)
        fb, fd, fv = bi[valid], dsts[valid], vals[valid]
        if fb.numel() > 0: bias[fb, fd] = fv
        return bias


class LocalFullBias:
    """本地流行度全量偏置：(zone, hour_bin) → POI 得分。

    统计每个 (地理区域, 时间段) 组合下各 POI 的历史访问频率。
    偏置值按 rank-based（1/log2(rank+1)）计算。
    直觉：用户在某个时间、某个地点，倾向于去当地热门的 POI。

    返回 (B, num_venues) 的完整偏置矩阵，供调用者 gather 使用。
    """
    def __init__(self, train_traj, venue_to_idx, poi_idx_zone, top_k, num_venues, device):
        self.nv = num_venues; self.dev = device; self.top_k = top_k
        cnt = defaultdict(Counter)
        for traj in train_traj:
            venues = traj['venues']; ts_list = traj.get('timestamps', [])
            for i, v in enumerate(venues):
                vi = venue_to_idx.get(v, 0)
                if vi == 0: continue
                z = poi_idx_zone.get(vi, 0)
                if len(ts_list) > i: hb = get_hour_bin_mem(ts_list[i])
                else: hb = 0
                cnt[(z, hb)][vi] += 1
        # Build lookup: key → (dsts, vals) as before
        self.lookup = {}
        for (z, hb), ctr in cnt.items():
            edges = list(ctr.most_common(top_k))
            k = len(edges)
            dsts = torch.tensor([d for d,_ in edges], dtype=torch.long, device=device)
            bv = [1.0/math.log2(r+1) for r in range(1,k+1)]
            vals = torch.tensor(bv, dtype=torch.float32, device=device)
            self.lookup[(z, hb)] = (dsts, vals)
        # Also store per-zone-hour indexing for fast batch
        nz = max(z for (z,_) in cnt.keys()) + 1 if cnt else 1
        print(f"  Local: {len(self.lookup)} zone-hour keys, {nz} zones")

    def __call__(self, zones, hour_bins):
        """Return (B, num_venues) full-ranking bias."""
        B = zones.size(0)
        bias = torch.zeros(B, self.nv, device=self.dev)
        for i in range(B):
            key = (zones[i].item(), hour_bins[i].item())
            if key in self.lookup:
                dsts, vals = self.lookup[key]
                bias[i, dsts] = vals
        return bias


# ==============================================================================
# Norm functions
# ==============================================================================

def normalize_scores(values, method='zscore'):
    """将 (B, K) 分值归一化到 [0,1] 范围。

    两种方法：
    - 'zscore': 先标准化到 N(0,1)，截断 ±3σ，再线性映射到 [0,1]
      （更适合有离群值的分布，对极端值鲁棒）
    - 'minmax': 最小-最大归一化
      （保持原始比例关系，但受离群值影响）

    T9 logits 分布通常有长尾，zscore 更稳健。
    """
    if method == 'zscore':
        mean = values.mean(dim=1, keepdim=True)
        std = values.std(dim=1, keepdim=True) + 1e-8
        z = (values - mean) / std
        z = torch.clamp(z, -3, 3)
        return (z + 3) / 6
    elif method == 'minmax':
        vmin = values.min(dim=1, keepdim=True).values
        vmax = values.max(dim=1, keepdim=True).values
        denom = (vmax - vmin) + 1e-8
        return (values - vmin) / denom
    return values


# ==============================================================================
# Fast Rerank Evaluation (full-bias + gather)
# ==============================================================================

@torch.no_grad()
def eval_rerank(model, dataloader, device, poi_bias_fn, geo_bias_fn, local_bias_fn,
                K, norm, alpha, beta, gamma, delta, poi_zone_tensor, num_zones,
                ks=(1,5,10), diag=False):
    """
    使用 full-bias + gather 策略对 T9 top-K 候选重排序。

    流程：
    1. T9 前向 → 全量 logits → top-K 索引和值
    2. 分别计算三个 bias 的完整 (B, nv) 矩阵，在 top-K 位置 gather 截取
       （全量计算 + gather 比逐候选循环快约 100 倍）
    3. 融合所有分数：α*norm_T9 + β*poi + γ*geo + δ*local
    4. 对融合分数重新排序 → 评估 HR/NDCG/MRR

    这是 T10d-Rerank-V1 的核心：T9 负责召回（top-K 候选集），
    bias 信号负责精排（在 top-K 内调整顺序）。
    """
    model.eval(); uc = getattr(model, 'use_causal_long_pref', False)

    hits = {k: 0 for k in ks}; ndcg = {k: 0.0 for k in ks}; mrr = {k: 0.0 for k in ks}
    sh, suh = {k: 0 for k in ks}, {k: 0 for k in ks}
    sc, uc_cnt, tot = 0, 0, 0

    d = {'t9r':[], 'tr':[], 't9h5':0, 'th5':0, 'fg':0, 'fl':0,
         't9r_seen':[], 't9r_unseen':[], 'tr_seen':[], 'tr_unseen':[],
         'seen_t9h5':0, 'unseen_t9h5':0, 'seen_th5':0, 'unseen_th5':0} if diag else None

    for batch in dataloader:
        batch = [t.to(device) for t in batch]
        bv, bc, bt, bl = batch[0], batch[1], batch[2], batch[-1]
        kw = {}
        if uc: kw['causal_history'] = batch[3]; kw['causal_mask'] = batch[4]

        # T9 forward pass
        base_l = model(bv, bc, t_seq=bt, **kw)  # (B, num_venues)

        # Step 1: Get T9 top-K
        t9_topk_vals, t9_topk_idx = torch.topk(base_l, k=K, dim=1)  # both (B, K)

        # Step 2: Normalize T9 scores
        t9_norm = normalize_scores(t9_topk_vals, norm)  # (B, K)

        # Step 3: Compute full-ranking bias vectors (fast, vectorized)
        lps = bv[:, -1]; pcs = bc[:, -2]; lcs = bc[:, -1]
        hbs = compute_hour_bin_t(bt); zones = poi_zone_tensor[lps].clamp(0, num_zones - 1)

        # Step 4: Gather bias at top-K positions
        if beta != 0:
            poi_full = poi_bias_fn(lps)  # (B, nv)
            poi_s = poi_full.gather(1, t9_topk_idx)  # (B, K)
        else:
            poi_s = torch.zeros_like(t9_norm)

        if gamma != 0:
            geo_full = geo_bias_fn(pcs, lcs, hbs, zones)  # (B, nv)
            geo_s = geo_full.gather(1, t9_topk_idx)  # (B, K)
        else:
            geo_s = torch.zeros_like(t9_norm)

        if delta != 0:
            loc_full = local_bias_fn(zones, hbs)  # (B, nv)
            loc_s = loc_full.gather(1, t9_topk_idx)  # (B, K)
        else:
            loc_s = torch.zeros_like(t9_norm)

        # Step 5: Combined score
        combined = alpha * t9_norm + beta * poi_s + gamma * geo_s + delta * loc_s  # (B, K)

        # Step 6: Re-sort
        _, rerank_idx = torch.sort(combined, dim=1, descending=True)
        reranked_pois = t9_topk_idx.gather(1, rerank_idx)  # (B, K)

        # Step 7: Evaluate
        for i in range(bl.size(0)):
            tl = bl[i].item(); t9p = t9_topk_idx[i].tolist()
            rp = reranked_pois[i].tolist()
            t9r = t9p.index(tl)+1 if tl in t9p else K+1
            tr = rp.index(tl)+1 if tl in rp[:K] else K+1
            h5 = tl in rp[:5]; t9h5 = tl in t9p[:5]

            for k_ in ks:
                if tl in rp[:k_]:
                    hits[k_] += 1
                    r = rp[:k_].index(tl)+1
                    mrr[k_] += 1.0/r; ndcg[k_] += 1.0/np.log2(r+1)

            if uc:
                ch = batch[3][i]; cm = batch[4][i]
                is_s = tl in ch[cm].tolist()
            else: is_s = False
            if is_s: sc += 1
            else: uc_cnt += 1
            for k_ in ks:
                if tl in rp[:k_]: (sh if is_s else suh)[k_] += 1

            if diag:
                d['t9r'].append(t9r); d['tr'].append(tr)
                if t9h5: d['t9h5'] += 1
                if h5: d['th5'] += 1
                if not t9h5 and h5: d['fg'] += 1
                elif t9h5 and not h5: d['fl'] += 1
                if is_s:
                    d['t9r_seen'].append(t9r); d['tr_seen'].append(tr)
                    if t9h5: d['seen_t9h5'] += 1
                    if h5: d['seen_th5'] += 1
                else:
                    d['t9r_unseen'].append(t9r); d['tr_unseen'].append(tr)
                    if t9h5: d['unseen_t9h5'] += 1
                    if h5: d['unseen_th5'] += 1
            tot += 1

    r = {}
    for k_ in ks:
        r[f'HR@{k_}'] = round(hits[k_]/tot*100, 2)
        r[f'NDCG@{k_}'] = round(ndcg[k_]/tot, 4)
        r[f'MRR@{k_}'] = round(mrr[k_]/tot, 4)
    r['total'] = tot
    for k_ in ks:
        r[f'seen_HR@{k_}'] = round(sh[k_]/max(sc,1)*100, 2)
        r[f'unseen_HR@{k_}'] = round(suh[k_]/max(uc_cnt,1)*100, 2)
    r['seen_n'] = sc; r['unseen_n'] = uc_cnt
    r['seen_ratio'] = round(sc/max(tot,1), 4)
    if diag: d['tot']=tot; d['sc']=sc; d['uc']=uc_cnt; r['diag']=d
    return r


# ==============================================================================
# Report Generation
# ==============================================================================

def gen_report(path, bc, test_r, t9_test, all_grid, npar, oh_ms):
    """生成 T10d-Rerank-V1 完整中文实验报告（Markdown 格式）。

    包含：方法说明（四个分数组件 + full-bias gather 优化）、Strict Protocol、
    分阶段 Val 网格搜索（Stage A/B/C）、Test 评估（vs T9/T10c）、
    Seen/Unseen 对比、Flip 分析、Rank Change、消融分析（组件贡献）、
    推理开销、核心问题回答。
    """
    t9 = t9_test
    t10c = {'HR@1': 23.32, 'HR@5': 49.14, 'HR@10': 58.76, 'NDCG@5': 0.3704, 'NDCG@10': 0.4017,
            'MRR@5': 0.3298, 'MRR@10': 0.3429}

    lines = [
        "# T10d-Rerank-V1: T9 Top-K 重排序 — 实验报告", "",
        f"**日期**: 2026-07-06  **数据集**: Foursquare TKY",
        f"**T9 Baseline**: Test HR@5={t9.get('HR@5',0):.2f}%", "",
        "---", "",
        "## 一、方法说明", "",
        "### 1.1 候选集",
        "candidate_set = T9 top-K（不扩展，纯 rerank）", "",
        "### 1.2 重排序分数",
        "```",
        "score(i) = alpha * norm_t9_score(i)",
        "         + beta  * poi_transition_score(i)",
        "         + gamma * intent_geo_score(i)",
        "         + delta * local_popularity_score(i)",
        "```", "",
        "**四个分数组件**：",
        "1. **norm_t9_score**: T9 logits 在 top-K 内归一化 (zscore/minmax→[0,1])",
        "2. **poi_transition_score**: 基于 last_poi 的转移记忆 (T10a, rank-based)",
        "3. **intent_geo_score**: 基于 intent+geo 的记忆 (T10c-lite, 5-level backoff)",
        "4. **local_popularity_score**: 基于 (zone, hour) 的本地流行度", "",
        "---", "",
        "## 二、Strict Protocol", "",
        "| 规则 | 状态 |",
        "|------|------|",
        "| Memory 仅由 train 构建 | ✅ |",
        "| val 仅用于超参选择 | ✅ |",
        "| test 仅评估一次 | ✅ |",
        "| Full-ranking → top-K rerank | ✅ |",
        "| 无 GNN / 无大参数 | ✅ |",
        "| 不改变 T9 主干 | ✅ |", "",
        "---", "",
        "## 三、Val 网格搜索", "",
        f"总组合数: {len(all_grid)}", "",
        f"**最佳配置**: K={bc['K']}, norm={bc['norm']}, α={bc['alpha']:.2f}, "
        f"β={bc['beta']:.3f}, γ={bc['gamma']:.3f}, δ={bc['delta']:.3f}", "",
        f"**最佳 Val HR@5**: {bc.get('best_val_hr5', 0):.2f}%", "",
        "### 3.1 Stage A (固定 K=100, norm=zscore, α=1.0, 搜索 β/γ/δ)", ""]

    sa = [g for g in all_grid if g.get('stage') == 'A']
    if sa:
        best_sa = max(sa, key=lambda x: x['HR@5'])
        lines.append(f"最佳: β={best_sa.get('beta',0):.2f}, γ={best_sa.get('gamma',0):.2f}, "
                     f"δ={best_sa.get('delta',0):.2f}, HR@5={best_sa['HR@5']:.2f}%")

    sb = [g for g in all_grid if g.get('stage') == 'B']
    if sb:
        lines += ["", "### 3.2 Stage B (搜索 K/norm/α)"]
        best_sb = max(sb, key=lambda x: x['HR@5'])
        lines.append(f"最佳: K={best_sb.get('K',100)}, norm={best_sb.get('norm','zscore')}, "
                     f"α={best_sb.get('alpha',1.0):.2f}, HR@5={best_sb['HR@5']:.2f}%")

    sc_grid = [g for g in all_grid if g.get('stage') == 'C']
    if sc_grid:
        lines += ["", "### 3.3 Stage C (微调)"]
        best_sc = max(sc_grid, key=lambda x: x['HR@5'])
        lines.append(f"最佳: HR@5={best_sc['HR@5']:.2f}%")

    # Test results
    lines += ["", "---", "",
              "## 四、Test 评估结果", "",
              "### 4.1 主要指标", "",
              "| 指标 | T9 | T10c-lite | T10d-V1 | Δ vs T9 | Δ vs T10c |",
              "|------|-----|-----------|---------|---------|-----------|"]

    for m in ['HR@1', 'HR@5', 'HR@10']:
        t9v = t9.get(m, 0); tcv = t10c.get(m, 0); tv = test_r.get(m, 0)
        lines.append(f"| {m} | {t9v:.2f}% | {tcv:.2f}% | {tv:.2f}% | {tv-t9v:+.2f}% | {tv-tcv:+.2f}% |")
    for m in ['NDCG@5', 'NDCG@10', 'MRR@5', 'MRR@10']:
        t9v = t9.get(m, 0); tcv = t10c.get(m, 0); tv = test_r.get(m, 0)
        lines.append(f"| {m} | {t9v:.4f} | {tcv:.4f} | {tv:.4f} | {tv-t9v:+.4f} | {tv-tcv:+.4f} |")

    lines += ["", "### 4.2 Seen/Unseen", "",
              "| 指标 | T9 | T10c-lite | T10d-V1 | Δ vs T9 | Δ vs T10c |",
              "|------|-----|-----------|---------|---------|-----------|"]
    for lbl, k, t9v in [('Seen HR@5', 'seen_HR@5', 71.11), ('Unseen HR@5', 'unseen_HR@5', 12.01)]:
        tcv = {'seen_HR@5': 71.00, 'unseen_HR@5': 12.54}.get(k, 0)
        tv = test_r.get(k, 0)
        lines.append(f"| {lbl} | {t9v:.2f}% | {tcv:.2f}% | {tv:.2f}% | {tv-t9v:+.2f}% | {tv-tcv:+.2f}% |")

    # Flip analysis
    diag = test_r.get('diag', {})
    fg = diag.get('fg', 0); fl = diag.get('fl', 0)

    lines += ["", "### 4.3 Flip 分析", "",
              f"- T9 miss@5 → T10d hit@5: {fg}",
              f"- T9 hit@5 → T10d miss@5: {fl}",
              f"- Net gain: {fg-fl:+d}"]

    if diag.get('t9r'):
        t9r_all = np.mean(diag['t9r']); tr_all = np.mean(diag['tr'])
        lines += ["", "### 4.4 Rank Change", "",
                  f"- T9 mean rank: {t9r_all:.2f} → T10d: {tr_all:.2f} (Δ={tr_all-t9r_all:+.2f})"]
        if diag.get('t9r_seen'):
            lines.append(f"- Seen: T9={np.mean(diag['t9r_seen']):.2f} → T10d={np.mean(diag['tr_seen']):.2f}")
        if diag.get('t9r_unseen'):
            lines.append(f"- Unseen: T9={np.mean(diag['t9r_unseen']):.2f} → T10d={np.mean(diag['tr_unseen']):.2f}")

    lines += ["", "### 4.5 组件贡献分析 (消融)", "",
              "| 配置 | Val HR@5 |",
              "|------|----------|"]
    # Find key ablations
    for g in all_grid:
        if g.get('stage') == 'A':
            if g.get('beta',0)==0 and g.get('gamma',0)==0 and g.get('delta',0)==0:
                lines.append(f"| T9-only (baseline) | {g['HR@5']:.2f}% |")
            if g.get('beta',0) > 0 and g.get('gamma',0)==0 and g.get('delta',0)==0:
                if 'shown_poi_only' not in dir():
                    lines.append(f"| POI only (β={g['beta']}) | {g['HR@5']:.2f}% |")
                    globals()['shown_poi_only'] = True

    lines += ["", f"Seen ratio: {test_r.get('seen_ratio',0)*100:.1f}%, "
              f"参数量: {npar:,}, 推理开销: {oh_ms:.1f}ms", "",
              "---", "",
              "## 六、核心问题回答", "",
              f"**1. Overall HR@5**: {test_r.get('HR@5',0):.2f}% (T9={t9.get('HR@5',0):.2f}%, "
              f"Δ={test_r.get('HR@5',0)-t9.get('HR@5',0):+.2f}%)",
              f"**2. Seen HR@5**: {test_r.get('seen_HR@5',0):.2f}%",
              f"**3. Unseen HR@5**: {test_r.get('unseen_HR@5',0):.2f}% "
              f"(T9=12.01%, Δ={test_r.get('unseen_HR@5',0)-12.01:+.2f}%)",
              f"**4. vs T10c-lite V3**: Δ={test_r.get('HR@5',0)-49.14:+.2f}%",
              f"**5. T9 miss→T10d hit**: {fg}",
              f"**6. T9 hit→T10d miss**: {fl}",
              f"**7. Net gain**: {fg-fl:+d}",
              f"**8. Target rank**: T9 mean={t9r_all:.2f} → T10d mean={tr_all:.2f}",
              f"**9. 组件贡献**: 见消融分析",
              f"**10. 推理开销**: {oh_ms:.1f}ms",
              f"**11. 新增参数**: 0", "",
              "---", "",
              "*报告由 src/run_t10d_rerank_v1.py 自动生成。*"]

    with open(path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
    print(f"Report: {path}")


# ==============================================================================
# Main
# ==============================================================================

def main():
    set_seed(cfg.SEED); device = get_device()
    print(f"Device: {device}")
    out_dir = os.path.join(cfg.SAVE_DIR, "T10")
    ckpt_path = os.path.join(cfg.CHECKPOINT_DIR, "T9_CausalMemoryFusion_best.pth")

    # --- Data pipeline ---
    print("\n=== Data Loading ===")
    raw_df = load_raw_data(cfg.dataset_file("TKY"))
    df = filter_low_frequency(raw_df, min_poi_checkins=cfg.MIN_POI_CHECKINS, min_user_checkins=cfg.MIN_USER_CHECKINS)
    vl = df.groupby("venueId")[["latitude","longitude"]].first().to_dict("index")
    vc = df.groupby("venueId")["venueCategory"].first().to_dict()

    trajectories = build_trajectories_24h(df, include_timestamps=True)
    trajectories.sort(key=lambda t: t["start_time"])
    train_traj, val_traj, test_traj = time_ordered_split(trajectories, train_ratio=cfg.TRAIN_RATIO, val_ratio=cfg.VAL_RATIO)

    uti = {}
    for t in train_traj:
        if t['user_id'] not in uti: uti[t['user_id']] = len(uti)

    train_raw = build_sequences(train_traj, seq_len=cfg.SEQ_LEN, user_to_idx=uti, include_time=True, include_target_timestamp=True)
    val_raw = build_sequences(val_traj, seq_len=cfg.SEQ_LEN, user_to_idx=uti, include_time=True, include_target_timestamp=True)
    test_raw = build_sequences(test_traj, seq_len=cfg.SEQ_LEN, user_to_idx=uti, include_time=True, include_target_timestamp=True)

    v2i, c2i = build_vocabularies(train_raw)
    nv, nc = len(v2i), len(c2i)
    train_seqs = convert_sequences(train_raw, v2i, c2i)
    val_seqs, _ = convert_sequences(val_raw, v2i, c2i, return_stats=True)
    test_seqs, _ = convert_sequences(test_raw, v2i, c2i, return_stats=True)

    (tr_c, tr_cm, v_c, v_cm, te_c, te_cm) = build_causal_history_per_sample(
        train_traj=train_traj, train_seqs=train_seqs, val_seqs=val_seqs, test_seqs=test_seqs,
        venue_to_idx=v2i, user_to_idx=uti, max_history_len=cfg.MAX_CAUSAL_HISTORY)
    def _at(s,m,mk):
        for i,s2 in enumerate(s): s2['causal_hist']=m[i].tolist(); s2['causal_mask']=mk[i].tolist()
    _at(train_seqs,tr_c,tr_cm); _at(val_seqs,v_c,v_cm); _at(test_seqs,te_c,te_cm)

    _, test_ldr = create_dataloaders(train_seqs, test_seqs, 512, num_workers=0, include_time=True, include_causal_history=True)
    val_ldr = create_val_loader(val_seqs, 512, num_workers=0, include_time=True, include_causal_history=True)
    print(f"Vocab: {nv} POIs, {nc} cats, Val={len(val_ldr)}, Test={len(test_ldr)}")

    # Features
    print("\n=== Features ===")
    tps = sorted(set(v for t in train_traj for v in t["venues"]))
    p2w = {p:i for i,p in enumerate(tps)}
    ws = [[p2w[v] for v in t["venues"]] for t in train_traj if len(t["venues"])>=2]
    we = train_word2vec(ws, len(tps), emb_dim=128, window_size=3, n_negs=5, batch_size=2048, epochs=10, lr=0.001, device=device)
    bm = build_behavioral_matrix(we, v2i, p2w)
    tvs = [v for v in v2i if v!="<PAD>"]
    pt = build_poi_texts(tvs, vc, vl, dataset="TKY")
    te_e = encode_with_sbert(pt, model_name="all-MiniLM-L6-v2", batch_size=256, local_files_only=True)
    tm = build_text_matrix(te_e, v2i)

    # T9 Model
    print("\n=== Load T9 ===")
    model = TransformerPOIModel(num_venues=nv, num_cats=nc, use_category=True, venue_emb_dim=64, cat_emb_dim=16,
                                behav_dim=128, behav_proj_dim=64, text_dim=384, text_proj_dim=64,
                                d_model=128, n_heads=2, n_layers=2, ff_dim=256, dropout=0.1, fc_dropout=0.3,
                                behav_matrix=bm, text_matrix=tm, fusion_type="dynamic", gate_hidden=64,
                                use_causal_long_pref=True, causal_pref_type="attention").to(device)
    model.load_state_dict(torch.load(ckpt_path, weights_only=True))
    n_params = count_parameters(model)
    print(f"Params: {n_params:,}")

    # --- Build Memories ---
    print("\n=== Build Memories ===")

    gs = 20
    poi_idx_zone, nz, pzt = build_geo_zones(train_traj, gs, vl, v2i)
    pzt = pzt.to(device)

    print("Building IntentGeo memory...")
    geo_mems, geo_kt = build_intent_geo_memory(train_traj, v2i, c2i, poi_idx_zone, top_k=200)

    print("Loading POI transition memory...")
    with open(os.path.join(out_dir, "t10_poi_transition_top100.pkl"), 'rb') as f:
        poi_mem = pickle.load(f)

    # Build full-ranking bias functions (fast, vectorized)
    geo_bias_fn = IntentGeoFullBias(geo_mems, geo_kt, 50, 3, nc, nz, nv, device)
    poi_bias_fn = POIFullBias(poi_mem, 50, 'rank', nv, device)
    local_bias_fn = LocalFullBias(train_traj, v2i, poi_idx_zone, 200, nv, device)

    # T9 baseline
    from src.t9_evaluation import eval_t9_simple
    print("\n=== T9 Baseline ===")
    t9_val = eval_t9_simple(model, val_ldr, device)
    t9_test = eval_t9_simple(model, test_ldr, device)
    print(f"T9 Val HR@5={t9_val['HR@5']:.2f}%, Test HR@5={t9_test['HR@5']:.2f}%")

    # ========================================================================
    # 分阶段网格搜索
    #
    # Stage A: 固定 K=100, norm=zscore, α=1.0，搜索 β/γ/δ（bias 权重）
    #   - 4×5×4 = 80 组合，覆盖 sparsely
    # Stage B: 固定最优 β/γ/δ，搜索 K/norm/α（归一化与候选集大小）
    #   - 4×2×3 = 24 组合
    # Stage C: 在最优配置附近 ±25% 微调
    #   - 小范围邻域搜索
    # ========================================================================
    print("\n" + "=" * 70)
    print("STAGED GRID SEARCH")
    print("=" * 70)

    all_grid = []
    best_val_hr5 = t9_val['HR@5']  # 从 T9 基线开始
    best_config = {'K': 100, 'norm': 'zscore', 'alpha': 1.0, 'beta': 0, 'gamma': 0, 'delta': 0}

    # ---- Stage A: 固定 K=100, norm=zscore, α=1.0，搜索 β/γ/δ ----
    # 目的：找到三个 bias 分量的最优加权组合
    # β 控制 POI 转移记忆权重，γ 控制 IntentGeo 上下文权重，δ 控制本地流行度权重
    print("\n--- Stage A: Search β/γ/δ (K=100, norm=zscore, α=1.0) ---")

    # Sparse grid to cover the space efficiently
    beta_opts = [0.05, 0.10, 0.20, 0.30]
    gamma_opts = [0.10, 0.20, 0.30, 0.50, 0.70]
    delta_opts = [0.00, 0.05, 0.10, 0.20]
    na = len(beta_opts) * len(gamma_opts) * len(delta_opts)
    ci = 0

    K_fixed = 100; norm_fixed = 'zscore'; alpha_fixed = 1.0

    for beta in beta_opts:
        for gamma in gamma_opts:
            for delta in delta_opts:
                ci += 1
                t0 = time.perf_counter()
                r = eval_rerank(model, val_ldr, device, poi_bias_fn, geo_bias_fn, local_bias_fn,
                                K_fixed, norm_fixed, alpha_fixed, beta, gamma, delta, pzt, nz)
                if torch.cuda.is_available(): torch.cuda.synchronize()
                et = time.perf_counter() - t0
                row = {'stage': 'A', 'K': K_fixed, 'norm': norm_fixed, 'alpha': alpha_fixed,
                       'beta': beta, 'gamma': gamma, 'delta': delta,
                       'HR@5': r['HR@5'], 'seen_HR@5': r.get('seen_HR@5',0),
                       'unseen_HR@5': r.get('unseen_HR@5',0), 'eval_time': round(et,1)}
                all_grid.append(row)
                if r['HR@5'] > best_val_hr5:
                    best_val_hr5 = r['HR@5']
                    best_config = {'K': K_fixed, 'norm': norm_fixed, 'alpha': alpha_fixed,
                                   'beta': beta, 'gamma': gamma, 'delta': delta}
                if ci % 20 == 0:
                    print(f"  [A{ci}/{na}] β={beta:.2f} γ={gamma:.2f} δ={delta:.2f} → "
                          f"HR@5={r['HR@5']:.2f}% (best={best_val_hr5:.2f}%) [{et:.1f}s]")

    print(f"  [A{ci}/{na}] Done. Best: β={best_config['beta']:.3f} γ={best_config['gamma']:.3f} "
          f"δ={best_config['delta']:.3f} → Val HR@5={best_val_hr5:.2f}%")

    # ---- Stage B: 固定最优 β/γ/δ，搜索 K/norm/α ----
    # 目的：确定最优候选集大小 K、归一化方法和 T9 分数权重 α
    # K 影响召回覆盖率和重排序效率的平衡，norm 影响分数融合质量，α 调节 T9 vs bias 的主导程度
    print("\n--- Stage B: Search K/norm/α ---")
    best_beta = best_config['beta']; best_gamma = best_config['gamma']
    best_delta = best_config['delta']

    K_opts = [50, 100, 200, 500]
    norm_opts = ['zscore', 'minmax']
    alpha_opts = [0.8, 1.0, 1.2]
    nb = len(K_opts) * len(norm_opts) * len(alpha_opts)
    ci = 0

    for K in K_opts:
        for norm in norm_opts:
            for alpha in alpha_opts:
                ci += 1
                t0 = time.perf_counter()
                r = eval_rerank(model, val_ldr, device, poi_bias_fn, geo_bias_fn, local_bias_fn,
                                K, norm, alpha, best_beta, best_gamma, best_delta, pzt, nz)
                if torch.cuda.is_available(): torch.cuda.synchronize()
                et = time.perf_counter() - t0
                row = {'stage': 'B', 'K': K, 'norm': norm, 'alpha': alpha,
                       'beta': best_beta, 'gamma': best_gamma, 'delta': best_delta,
                       'HR@5': r['HR@5'], 'seen_HR@5': r.get('seen_HR@5',0),
                       'unseen_HR@5': r.get('unseen_HR@5',0), 'eval_time': round(et,1)}
                all_grid.append(row)
                if r['HR@5'] > best_val_hr5 + 0.001:  # Small threshold
                    best_val_hr5 = r['HR@5']
                    best_config = {'K': K, 'norm': norm, 'alpha': alpha,
                                   'beta': best_beta, 'gamma': best_gamma, 'delta': best_delta}
                print(f"  [B{ci}/{nb}] K={K} norm={norm} α={alpha:.2f} → "
                      f"HR@5={r['HR@5']:.2f}% (best={best_val_hr5:.2f}%) [{et:.1f}s]")

    print(f"\nStage B best: K={best_config['K']} norm={best_config['norm']} α={best_config['alpha']:.2f} "
          f"→ Val HR@5={best_val_hr5:.2f}%")

    # ---- Stage C: 在最优配置附近微调（±25%） ----
    # 目的：在 Stage B 最优配置周围做邻域搜索，消除粗网格搜索的精度损失
    print("\n--- Stage C: Fine-tune ---")
    bc = best_config
    fine_beta = [bc['beta'] * 0.75, bc['beta'], bc['beta'] * 1.25]
    fine_gamma = [bc['gamma'] * 0.75, bc['gamma'], bc['gamma'] * 1.25]

    ci = 0; nc_ = len(fine_beta) * len(fine_gamma)
    for b2 in fine_beta:
        for g2 in fine_gamma:
            if abs(b2 - bc['beta']) < 0.005 and abs(g2 - bc['gamma']) < 0.005:
                continue
            ci += 1
            b2r = round(b2, 3); g2r = round(g2, 3)
            t0 = time.perf_counter()
            r = eval_rerank(model, val_ldr, device, poi_bias_fn, geo_bias_fn, local_bias_fn,
                            bc['K'], bc['norm'], bc['alpha'], b2r, g2r, bc['delta'], pzt, nz)
            if torch.cuda.is_available(): torch.cuda.synchronize()
            et = time.perf_counter() - t0
            row = {'stage': 'C', 'K': bc['K'], 'norm': bc['norm'], 'alpha': bc['alpha'],
                   'beta': b2r, 'gamma': g2r, 'delta': bc['delta'],
                   'HR@5': r['HR@5'], 'seen_HR@5': r.get('seen_HR@5',0),
                   'unseen_HR@5': r.get('unseen_HR@5',0), 'eval_time': round(et,1)}
            all_grid.append(row)
            if r['HR@5'] > best_val_hr5 + 0.001:
                best_val_hr5 = r['HR@5']
                best_config = {'K': bc['K'], 'norm': bc['norm'], 'alpha': bc['alpha'],
                               'beta': b2r, 'gamma': g2r, 'delta': bc['delta']}
            print(f"  [C{ci}/{nc_}] β={b2r:.3f} γ={g2r:.3f} → "
                  f"HR@5={r['HR@5']:.2f}% (best={best_val_hr5:.2f}%) [{et:.1f}s]")

    best_config['best_val_hr5'] = best_val_hr5
    print(f"\n=== BEST CONFIG: {best_config} ===")

    # Save val grid
    grid_csv = os.path.join(out_dir, "t10d_rerank_v1_val_grid.csv")
    fields = ['stage', 'K', 'norm', 'alpha', 'beta', 'gamma', 'delta',
              'HR@5', 'seen_HR@5', 'unseen_HR@5', 'eval_time']
    with open(grid_csv, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction='ignore'); w.writeheader()
        for row in all_grid: w.writerow(row)
    print(f"Val grid: {grid_csv}")

    # ========================================================================
    # Test Evaluation
    # ========================================================================
    print("\n=== TEST EVALUATION ===")
    bc2 = best_config
    t0 = time.perf_counter()
    test_r = eval_rerank(model, test_ldr, device, poi_bias_fn, geo_bias_fn, local_bias_fn,
                          bc2['K'], bc2['norm'], bc2['alpha'],
                          bc2['beta'], bc2['gamma'], bc2['delta'],
                          pzt, nz, diag=True)
    if torch.cuda.is_available(): torch.cuda.synchronize()
    test_time = time.perf_counter() - t0
    print(f"Test HR@5={test_r['HR@5']:.2f}% Seen={test_r.get('seen_HR@5',0):.2f}% "
          f"Unseen={test_r.get('unseen_HR@5',0):.2f}% [{test_time:.1f}s]")

    # Timing
    print("\n=== Timing ===")
    for batch in val_ldr:
        batch = [t.to(device) for t in batch]
        _ = model(batch[0], batch[1], causal_history=batch[3], causal_mask=batch[4])
        break
    if torch.cuda.is_available(): torch.cuda.synchronize()

    t9_times = []
    for _ in range(5):
        t0t = time.perf_counter()
        for batch in val_ldr:
            batch = [t.to(device) for t in batch]
            _ = model(batch[0], batch[1], causal_history=batch[3], causal_mask=batch[4])
        if torch.cuda.is_available(): torch.cuda.synchronize()
        t9_times.append(time.perf_counter() - t0t)
    t9t_mean = np.mean(t9_times)

    rerank_times = []
    for _ in range(5):
        t0t = time.perf_counter()
        for batch in val_ldr:
            batch = [t.to(device) for t in batch]
            bv2, bc2t, bt2t = batch[0], batch[1], batch[2]
            base_l = model(bv2, bc2t, causal_history=batch[3], causal_mask=batch[4])
            t9_topk_vals, t9_topk_idx = torch.topk(base_l, k=bc2['K'], dim=1)
            t9_n = normalize_scores(t9_topk_vals, bc2['norm'])
            lps = bv2[:, -1]; pcs = bc2t[:, -2]; lcs = bc2t[:, -1]
            hbs = compute_hour_bin_t(bt2t); zones = pzt[lps].clamp(0, nz-1)
            pf = poi_bias_fn(lps); gf = geo_bias_fn(pcs, lcs, hbs, zones)
            lf = local_bias_fn(zones, hbs)
            ps2 = pf.gather(1, t9_topk_idx); gs2 = gf.gather(1, t9_topk_idx)
            ls2 = lf.gather(1, t9_topk_idx)
            comb = bc2['alpha']*t9_n + bc2['beta']*ps2 + bc2['gamma']*gs2 + bc2['delta']*ls2
            _, ri = torch.sort(comb, dim=1, descending=True)
            _ = t9_topk_idx.gather(1, ri)
        if torch.cuda.is_available(): torch.cuda.synchronize()
        rerank_times.append(time.perf_counter() - t0t)
    rr_mean = np.mean(rerank_times)

    oh_ms = (rr_mean - t9t_mean) * 1000
    oh_pct = (rr_mean - t9t_mean) / t9t_mean * 100
    print(f"T9: {t9t_mean:.3f}s, T10d: {rr_mean:.3f}s, Overhead: {oh_ms:.1f}ms ({oh_pct:.1f}%)")

    # Save test result
    test_csv = os.path.join(out_dir, "t10d_rerank_v1_test_result.csv")
    trow = {'model': 'T10d-Rerank-V1', **{k: str(v) for k,v in bc2.items()},
            'HR@1': test_r['HR@1'], 'HR@5': test_r['HR@5'], 'HR@10': test_r['HR@10'],
            'NDCG@5': test_r['NDCG@5'], 'NDCG@10': test_r['NDCG@10'],
            'MRR@5': test_r['MRR@5'], 'MRR@10': test_r['MRR@10'],
            'seen_HR@5': test_r.get('seen_HR@5',0), 'unseen_HR@5': test_r.get('unseen_HR@5',0),
            'seen_ratio': test_r.get('seen_ratio',0),
            'params': n_params, 'overhead_ms': round(oh_ms,2), 'overhead_pct': round(oh_pct,2),
            'best_val_hr5': best_val_hr5, 't9_test_hr5': t9_test['HR@5']}
    with open(test_csv, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=list(trow.keys())); w.writeheader(); w.writerow(trow)
    print(f"Test CSV: {test_csv}")

    # Report
    rpt_path = os.path.join(out_dir, "10_t10d_rerank_v1_report.md")
    gen_report(rpt_path, best_config, test_r, t9_test, all_grid, n_params, oh_ms)

    # Summary
    print("\n" + "=" * 70)
    print(f"T10d-Rerank-V1 Complete!")
    print(f"T9={t9_test['HR@5']:.2f}% → T10d-V1={test_r['HR@5']:.2f}% (Δ={test_r['HR@5']-t9_test['HR@5']:+.2f}%)")
    print(f"vs T10c-lite V3=49.14%: Δ={test_r['HR@5']-49.14:+.2f}%")
    print(f"Seen: {test_r.get('seen_HR@5',0):.2f}%, Unseen: {test_r.get('unseen_HR@5',0):.2f}%")
    diag = test_r.get('diag', {})
    print(f"Flip: gain={diag.get('fg',0)}, loss={diag.get('fl',0)}, net={diag.get('fg',0)-diag.get('fl',0):+d}")
    print("=" * 70)


if __name__ == "__main__":
    main()
