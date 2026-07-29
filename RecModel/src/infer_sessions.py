"""面向数据库 session 的 T10e-2 离线推理模块。

本模块负责三件事：按原训练协议重建 POI/类别词表、加载 T9 checkpoint、
执行 T10e-2 候选重排。checkpoint 中每一行 embedding 都对应固定的 POI，
因此绝不能按照数据库当前内容重新编号 venue_id，否则模型权重会整体错位。
"""

from __future__ import annotations

import pickle
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd
import torch

import config as cfg
from src.data.preprocess import (
    build_sequences,
    build_trajectories_24h,
    build_vocabularies,
    compute_time_features,
    filter_low_frequency,
    load_raw_data,
    time_ordered_split,
)
from src.models.transformer import TransformerPOIModel
from src.rerank_components import (
    IntentGeoFullBias,
    LocalFullBias,
    POIFullBias,
    build_geo_zones,
    build_intent_geo_memory,
    compute_hour_bin_t,
    normalize_scores,
)
from src.t10e2 import compute_frequency_revisit


@dataclass(slots=True)
class SessionInput:
    """一个待推理 session；最后的真实签到已从短期历史中剥离。"""
    session_id: str
    user_id: str
    venue_ids: list[str]
    categories: list[str]
    timestamps: list[object]
    target_poi_id: str
    causal_venue_ids: list[str]


@dataclass(slots=True)
class Recommendation:
    """一条可直接导出或写入 recommendation_results 的候选结果。"""
    session_id: str
    user_id: str
    target_poi_id: str
    poi_id: str
    rank: int
    score: float


class T10e2SessionRecommender:
    """加载已发布的 T9 checkpoint，并应用固定参数的 T10e-2 重排。"""

    MODEL_NAME = "T10e2_CausalMemoryFusion"
    CANDIDATE_K = 100

    def __init__(self, device: str | None = None) -> None:
        self.device = torch.device(device or ("cuda" if torch.cuda.is_available() else "cpu"))
        self._prepare_reference_data()
        self._load_model()
        self._build_rerank_memories()

    def _prepare_reference_data(self) -> None:
        """按训练时完全相同的过滤和时间切分规则重建词表及训练轨迹。"""
        raw = load_raw_data(cfg.dataset_file("TKY"))
        filtered = filter_low_frequency(raw, cfg.MIN_POI_CHECKINS, cfg.MIN_USER_CHECKINS)
        trajectories = build_trajectories_24h(filtered, include_timestamps=True)
        trajectories.sort(key=lambda item: item["start_time"])
        train_traj, _, _ = time_ordered_split(trajectories, cfg.TRAIN_RATIO, cfg.VAL_RATIO)
        train_raw = build_sequences(train_traj, seq_len=cfg.SEQ_LEN)

        self.venue_to_idx, self.category_to_idx = build_vocabularies(train_raw)
        self.idx_to_venue = {idx: venue for venue, idx in self.venue_to_idx.items()}
        self.train_trajectories = train_traj
        self.venue_locations = filtered.groupby("venueId")[["latitude", "longitude"]].first().to_dict("index")

    def _load_model(self) -> None:
        """创建模型结构并恢复 checkpoint 中包含的全部特征矩阵和参数。"""
        checkpoint = Path(cfg.CHECKPOINT_DIR) / "T9_CausalMemoryFusion_best.pth"
        state = torch.load(checkpoint, map_location=self.device, weights_only=True)
        num_venues = len(self.venue_to_idx)
        num_categories = len(self.category_to_idx)
        expected = (state["venue_emb.weight"].shape[0], state["cat_emb.weight"].shape[0])
        if (num_venues, num_categories) != expected:
            raise RuntimeError(
                "Bundled dataset vocabulary does not match checkpoint: "
                f"rebuilt={(num_venues, num_categories)}, checkpoint={expected}"
            )

        self.model = TransformerPOIModel(
            num_venues=num_venues,
            num_cats=num_categories,
            use_category=True,
            venue_emb_dim=64,
            cat_emb_dim=16,
            behav_dim=128,
            behav_proj_dim=64,
            text_dim=384,
            text_proj_dim=64,
            d_model=128,
            n_heads=2,
            n_layers=2,
            ff_dim=256,
            dropout=0.1,
            fc_dropout=0.3,
            behav_matrix=np.zeros((num_venues, 128), dtype=np.float32),
            text_matrix=np.zeros((num_venues, 384), dtype=np.float32),
            fusion_type="dynamic",
            gate_hidden=64,
            use_causal_long_pref=True,
            causal_pref_type="attention",
        ).to(self.device)
        self.model.load_state_dict(state, strict=True)
        self.model.eval()

    def _build_rerank_memories(self) -> None:
        """从训练轨迹构造地理、局部和 POI 转移三个重排 memory。"""
        poi_idx_zone, num_zones, poi_zone_tensor = build_geo_zones(
            self.train_trajectories, 20, self.venue_locations, self.venue_to_idx
        )
        geo_memories, geo_keys = build_intent_geo_memory(
            self.train_trajectories,
            self.venue_to_idx,
            self.category_to_idx,
            poi_idx_zone,
            top_k=200,
        )
        memory_path = Path(cfg.SAVE_DIR) / "T10" / "t10_poi_transition_top100.pkl"
        with memory_path.open("rb") as handle:
            poi_memory = pickle.load(handle)

        num_venues = len(self.venue_to_idx)
        num_categories = len(self.category_to_idx)
        self.num_zones = num_zones
        self.poi_zone_tensor = poi_zone_tensor.to(self.device)
        self.poi_bias = POIFullBias(poi_memory, 50, "rank", num_venues, self.device)
        self.geo_bias = IntentGeoFullBias(
            geo_memories, geo_keys, 50, 3, num_categories, num_zones, num_venues, self.device
        )
        self.local_bias = LocalFullBias(
            self.train_trajectories, self.venue_to_idx, poi_idx_zone, 200, num_venues, self.device
        )

    def supports_target(self, venue_id: str) -> bool:
        """检查给定的 venue_id 是否在模型词表中，用于过滤数据库中存在但训练时未出现的 POI。"""
        return venue_id in self.venue_to_idx

    def _tensorize(self, samples: list[SessionInput]):
        """将数据库字符串 ID、时间和长期历史编码为模型需要的张量。"""
        venue_rows, category_rows, time_rows, causal_rows, causal_masks = [], [], [], [], []
        for sample in samples:
            # 截取最近 SEQ_LEN 个签到作为短期历史，不足时左侧补零（PAD）。
            venues = sample.venue_ids[-cfg.SEQ_LEN :]
            categories = sample.categories[-cfg.SEQ_LEN :]
            timestamps = sample.timestamps[-cfg.SEQ_LEN :]
            pad = cfg.SEQ_LEN - len(venues)
            venue_rows.append([0] * pad + [self.venue_to_idx.get(value, 0) for value in venues])
            category_rows.append([0] * pad + [self.category_to_idx.get(value or "Unknown", 0) for value in categories])
            # 数据库返回 Python datetime 对象，而原始预处理辅助函数期望 pandas Timestamp 的 ``dayofweek`` 属性，
            # 因此需要显式转换。
            time_rows.append(
                [[0.0] * 4 for _ in range(pad)]
                + [compute_time_features(pd.Timestamp(value)) for value in timestamps]
            )

            # 因果长期历史：截取最近 MAX_CAUSAL_HISTORY 个已访问 POI，左侧补零并生成对应的 mask。
            causal = [
                self.venue_to_idx[value]
                for value in sample.causal_venue_ids
                if value in self.venue_to_idx
            ][-cfg.MAX_CAUSAL_HISTORY :]
            causal_pad = cfg.MAX_CAUSAL_HISTORY - len(causal)
            causal_rows.append([0] * causal_pad + causal)
            causal_masks.append([False] * causal_pad + [True] * len(causal))

        return (
            torch.tensor(venue_rows, dtype=torch.long, device=self.device),
            torch.tensor(category_rows, dtype=torch.long, device=self.device),
            torch.tensor(time_rows, dtype=torch.float32, device=self.device),
            torch.tensor(causal_rows, dtype=torch.long, device=self.device),
            torch.tensor(causal_masks, dtype=torch.bool, device=self.device),
        )

    @torch.no_grad()
    def recommend(self, samples: Iterable[SessionInput], top_k: int = 10) -> list[Recommendation]:
        """批量执行 T9 全量打分、Top-100 截断和 T10e-2 重排。

        整体流水线：
        1. T9 全量排序：模型对词表中所有 POI 打分，屏蔽 PAD token。
        2. Top-K 截断：取分数最高的 CANDIDATE_K（默认 100）个候选，减少后续重排计算量。
        3. T10e-2 重排：在 Top-K 候选上叠加三种群体转移偏置和探索增强信号，重新排序。
        4. 输出 top_k（默认 10）个最终推荐。
        """
        batch = list(samples)
        if not batch:
            return []
        if top_k < 1:
            raise ValueError("top_k must be at least 1")

        # =========================================================================
        # 阶段一：T9 全量打分
        # 模型对词表中全部 num_venues 个 POI 输出 logits，代表语义层面的相关性分数。
        # =========================================================================
        venues, categories, times, causal, causal_mask = self._tensorize(batch)
        logits = self.model(
            venues,
            categories,
            t_seq=times,
            causal_history=causal,
            causal_mask=causal_mask,
        )
        # PAD（索引 0）仅用于补齐序列，不能作为真实 POI 推荐给用户，将其分数置为 -inf。
        logits[:, 0] = -torch.inf

        # =========================================================================
        # 阶段二：Top-K 截断
        # 从全量 logits 中取分数最高的 CANDIDATE_K 个候选，后续重排仅在此子集上进行，
        # 大幅降低计算开销。T9 分数经过 z-score 归一化后作为基础分数。
        # =========================================================================
        candidate_k = min(self.CANDIDATE_K, logits.shape[1] - 1)
        t9_values, candidates = torch.topk(logits, k=candidate_k, dim=1)
        t9_scores = normalize_scores(t9_values, "zscore")

        # =========================================================================
        # 阶段三：计算 T10e-2 重排所需的上下文特征
        # - last_poi: 用户当前所在的 POI
        # - previous_category / last_category: 前一个和当前 POI 的类别，用于意图级地理偏置
        # - hour_bins: 当前时间的小时桶（0-3），用于时间感知的偏置
        # - zones: 当前 POI 所在的地理区域，用于局部偏置
        # =========================================================================
        last_poi = venues[:, -1]
        previous_category = categories[:, -2]
        last_category = categories[:, -1]
        hour_bins = compute_hour_bin_t(times)
        zones = self.poi_zone_tensor[last_poi].clamp(0, self.num_zones - 1)

        # =========================================================================
        # 阶段四：三种群体转移偏置 + 探索分数
        #
        # poi_bias:    POI 级转移偏置 —— 给定当前 POI，群体最常去的下一个 POI 是哪些？
        #              基于训练轨迹中相邻 POI 对的频次统计，反映短期连续访问模式。
        # geo_bias:    意图-地理联合偏置 —— 给定 (前序类别, 当前类别, 小时桶, 地理区域)，
        #              群体常去的 POI 是哪些？融合了类别转移意图和空间邻近性。
        # local_bias:  局部地理偏置 —— 给定 (地理区域, 小时桶)，该区域在此时段的热门 POI。
        #              捕获"附近的人在这个时间通常去哪里"的局部流行度信号。
        #
        # explore:     探索分数 = 加权组合三种偏置，权重为手动设定的固定系数。
        #              目的是在 T9 语义分数之外，引入群体行为先验来引导探索。
        # =========================================================================
        poi_scores = self.poi_bias(last_poi).gather(1, candidates)
        geo_scores = self.geo_bias(previous_category, last_category, hour_bins, zones).gather(1, candidates)
        local_scores = self.local_bias(zones, hour_bins).gather(1, candidates)
        explore = 0.062 * poi_scores + 0.10 * geo_scores + 0.05 * local_scores
        combined = t9_scores + explore

        # =========================================================================
        # 阶段五：重访频率增强
        # 对于用户历史中已访问过的候选 POI，根据其历史访问频率给予额外加分。
        # 这利用了"用户倾向于重复访问熟悉的地点"的行为规律。
        # =========================================================================
        revisit, visited = compute_frequency_revisit(causal, causal_mask, candidates)
        combined[visited] += 0.20 * revisit[visited]

        # =========================================================================
        # 阶段六：未访问 POI 探索增强
        # 对于用户从未访问过的候选，按探索置信度分为两档分别增强：
        # - 高置信度（explore >= 阈值）：三种偏置信号一致且较强，给予更大的探索加分。
        # - 低置信度（explore < 阈值）：偏置信号较弱，给予较小的保守加分。
        # 阈值 0.03733944892883301 为训练集上 explore 分数的中位数，用于区分信号强弱。
        # =========================================================================
        unvisited = ~visited
        high_confidence = unvisited & (explore >= 0.03733944892883301)
        low_confidence = unvisited & ~high_confidence
        combined[high_confidence] += 0.15 * explore[high_confidence]
        combined[low_confidence] += 0.10 * explore[low_confidence]

        # =========================================================================
        # 阶段七：最终排序与输出
        # 按 combined 分数降序排列，取前 top_k 个候选，将索引映射回 venue_id 字符串。
        # =========================================================================
        order = torch.argsort(combined, dim=1, descending=True)
        ranked_pois = candidates.gather(1, order)[:, :top_k].cpu().tolist()
        ranked_scores = combined.gather(1, order)[:, :top_k].cpu().tolist()

        results: list[Recommendation] = []
        for sample, poi_indices, scores in zip(batch, ranked_pois, ranked_scores):
            for rank, (poi_idx, score) in enumerate(zip(poi_indices, scores), start=1):
                results.append(
                    Recommendation(
                        session_id=sample.session_id,
                        user_id=sample.user_id,
                        target_poi_id=sample.target_poi_id,
                        poi_id=self.idx_to_venue[poi_idx],
                        rank=rank,
                        score=float(score),
                    )
                )
        return results
