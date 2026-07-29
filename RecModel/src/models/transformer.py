"""
轻量级 Pre-LN Transformer 编码器，用于 Next POI 推荐。

架构流程：
    Input (POI + 类别 + 语义嵌入)
    → Static Fusion (concat + Linear) 或 Dynamic Fusion Gate (加权求和)
    → 位置编码（可学习）
    → Transformer Encoder（2 层, 2 头, Pre-LN）
    → 取最后一个 token 的隐藏状态
    → Dropout → FC → 对所有 POI 进行 softmax
    → (可选) GeoBias: logits -= gamma * log(1 + haversine_distance)

支持两种融合模式：
    - fusion_type="static": 原始 concat + Linear（默认，向后兼容）
    - fusion_type="dynamic": Dynamic Fusion Gate，逐 token 学习特征权重

支持 GeoBias（use_geobias=True）：
    - 基于 last_poi 到候选 POI 的 Haversine 距离施加偏置
    - gamma 为可学习参数（通过 softplus 保证为正）
"""
import torch
import torch.nn as nn
import torch.nn.functional as F
import numpy as np
from typing import Optional, Tuple, List, Dict

from src.models.fusion import DynamicFusionGate, compute_gate_stats


class PositionalEncoding(nn.Module):
    """
    可学习的位置编码。

    与 Transformer 原始的正弦位置编码不同，这里使用可学习的 Embedding 参数，
    让模型在训练过程中自动发现最适合 Next POI 推荐任务的位置模式。

    初始化使用 N(0, 0.02^2) 的小方差高斯分布，避免位置信号在训练初期
    盖过 token 嵌入的语义信息，同时保留了位置信息的可学习性。
    """

    def __init__(self, d_model: int, max_len: int = 100):
        super().__init__()
        # 小方差初始化：保证位置编码初始时接近零，让语义嵌入主导早期训练
        self.pe = nn.Parameter(torch.randn(1, max_len, d_model) * 0.02)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return x + self.pe[:, :x.size(1), :]


class TransformerEncoder(nn.Module):
    """
    Pre-LN Transformer 编码器，支持可选的注意力权重提取。

    Args:
        d_model: 模型维度（默认 128）
        n_heads: 注意力头数（默认 2）
        n_layers: 编码器层数（默认 2）
        ff_dim: 前馈网络隐藏层维度（默认 256）
        dropout: Dropout 比率（默认 0.1）
    """

    def __init__(
        self,
        d_model: int = 128,
        n_heads: int = 2,
        n_layers: int = 2,
        ff_dim: int = 256,
        dropout: float = 0.1,
    ):
        super().__init__()
        self.pos_enc = PositionalEncoding(d_model)
        self.layers = nn.ModuleList([
            nn.TransformerEncoderLayer(
                d_model=d_model,
                nhead=n_heads,
                dim_feedforward=ff_dim,
                dropout=dropout,
                activation='gelu',
                batch_first=True,
                norm_first=True,  # Pre-LN 提高训练稳定性
            )
            for _ in range(n_layers)
        ])
        self.norm = nn.LayerNorm(d_model)

    def forward(
        self, x: torch.Tensor, return_attention: bool = False
    ) -> Tuple[torch.Tensor, Optional[List[torch.Tensor]]]:
        """
        Args:
            x: (batch, seq_len, d_model)
            return_attention: 如果为 True，同时返回注意力权重

        Returns:
            output: (batch, seq_len, d_model)
            attentions: 每层的注意力张量列表 (batch, n_heads, seq_len, seq_len)，或 None
        """
        # 先加位置编码，再进入 Transformer 层
        x = self.pos_enc(x)
        attentions = []

        for layer in self.layers:
            if return_attention:
                # 需要提取注意力权重时，手动拆解 TransformerEncoderLayer 的计算步骤：
                # Pre-LN 架构：先做 LayerNorm，再做 Self-Attention/FNN，最后残差连接。
                # 这与 PyTorch 内置的 TransformerEncoderLayer(batch_first=True, norm_first=True) 完全等价，
                # 但让我们可以拿到 self_attn 的注意力权重矩阵。
                x2 = layer.self_attn(
                    x, x, x, need_weights=True, average_attn_weights=False
                )
                attn_weights = x2[1]  # (batch, n_heads, seq, seq)
                attentions.append(attn_weights)
                # Pre-LN: LN → Attention → Dropout → 残差连接
                x = layer.norm1(x + layer.dropout1(x2[0]))
                # Pre-LN: LN → FFN(GELU) → Dropout → 残差连接
                x = layer.norm2(
                    x + layer.dropout2(
                        layer.linear2(
                            layer.dropout(layer.activation(layer.linear1(x)))
                        )
                    )
                )
            else:
                # 不需要注意力权重时，直接用 PyTorch 内置实现，性能更高
                x = layer(x)

        # 最终 LayerNorm：Pre-LN 架构在编码器出口加一层额外归一化，稳定输出分布
        x = self.norm(x)
        if return_attention:
            return x, attentions
        return x, None


class GatedGeoBias(nn.Module):
    """
    门控空间距离偏置模块（T6a）。

    与 Naive GeoBias（无条件惩罚所有样本）不同，GatedGeoBias 通过
    MLP Gate 从用户当前隐藏状态 h_user 学习一个标量 gate ∈ (0, 1)，
    动态决定当前样本是否需要空间距离约束。

    公式：
        geo_penalty  = log(1 + distance_km)                  # (B, V)
        gamma        = softplus(raw_gamma)                    # 标量
        geo_gate     = sigmoid(MLP(h_user))                   # (B, 1)
        scaled_penalty = clamp(geo_gate * gamma * geo_penalty, max=max_geo_penalty)
        final_logits = logits - scaled_penalty

    Args:
        d_model: 用户隐藏状态维度
        venue_coords: (num_venues, 2) POI 经纬度矩阵 [lat, lon]
        max_geo_penalty: scaled_penalty 的上限（默认 1.0）
    """

    def __init__(
        self,
        d_model: int,
        venue_coords: np.ndarray,
        max_geo_penalty: float = 1.0,
    ):
        super().__init__()

        # 注册 venue_coords 为 buffer（不参与训练，随模型移动）
        self.register_buffer(
            'venue_coords',
            torch.tensor(venue_coords, dtype=torch.float32),
        )

        # 可学习的 gamma（弱初始化：softplus(-3.0) ≈ 0.0486）
        self.raw_gamma = nn.Parameter(torch.tensor(-3.0, dtype=torch.float32))

        # Gate MLP: h_user → gate ∈ (0, 1)
        self.gate_mlp = nn.Sequential(
            nn.Linear(d_model, d_model // 2),
            nn.ReLU(),
            nn.Linear(d_model // 2, 1),
            nn.Sigmoid(),
        )

        self.max_geo_penalty = max_geo_penalty

        # 存储最近一次 forward 的信息，供 collect_geo_stats 使用
        self.last_info: Dict = {}

    def forward(
        self,
        logits: torch.Tensor,
        h_user: torch.Tensor,
        v_seq: torch.Tensor,
    ) -> torch.Tensor:
        """
        Args:
            logits: (B, num_venues) 原始模型输出
            h_user: (B, d_model) 用户当前隐藏状态（Transformer 最后 token）
            v_seq: (B, seq_len) 输入 POI 序列（左填充，末尾为最后有效 POI）

        Returns:
            adjusted_logits: (B, num_venues)
        """
        B, V = logits.shape

        # ---- Step 1: 获取序列中最后一个有效 POI ----
        # 左填充策略保证 v_seq[:, -1] 始终是最后一个有效的签到 POI，
        # 作为空间距离计算的"起点"
        last_venues = v_seq[:, -1]  # (B,)

        # ---- Step 2: Haversine 距离计算 ----
        # 计算 last_poi 到所有候选 POI 的球面距离矩阵 (B, V)
        last_coords = self.venue_coords[last_venues]  # (B, 2)
        last_lat_rad = torch.deg2rad(last_coords[:, 0]).unsqueeze(1)  # (B, 1)
        last_lon_rad = torch.deg2rad(last_coords[:, 1]).unsqueeze(1)

        cand_lat_rad = torch.deg2rad(self.venue_coords[:, 0]).unsqueeze(0)  # (1, V)
        cand_lon_rad = torch.deg2rad(self.venue_coords[:, 1]).unsqueeze(0)

        dlat = cand_lat_rad - last_lat_rad
        dlon = cand_lon_rad - last_lon_rad

        a = (
            torch.sin(dlat / 2.0) ** 2
            + torch.cos(last_lat_rad)
            * torch.cos(cand_lat_rad)
            * torch.sin(dlon / 2.0) ** 2
        )
        a = a.clamp(min=0.0, max=1.0 - 1e-7)
        c = 2.0 * torch.atan2(torch.sqrt(a), torch.sqrt(1.0 - a))
        distance_km = 6371.0 * c  # (B, V)

        # ---- Step 3: 基础距离惩罚 ----
        # log(1+d) 做对数压缩，避免远距离 POI 的惩罚项过大导致数值不稳定
        geo_penalty = torch.log1p(distance_km)  # log(1 + d), (B, V)
        gamma = F.softplus(self.raw_gamma)       # softplus 保证 gamma > 0，使惩罚始终为正值

        # ---- Step 4: 上下文自适应门控 ----
        # 核心创新点：不是所有样本都需要空间距离约束。
        # 例如，用户可能愿意驱车 30 公里去一家知名餐厅，但只愿意步行 500 米买咖啡。
        # Gate MLP 从 h_user 中学习当前上下文的"空间敏感度"：gate 越接近 1，
        # 空间惩罚越强（用户当前更关注距离）；gate 越接近 0，距离对推荐影响越小。
        geo_gate = self.gate_mlp(h_user)  # (B, 1)

        # ---- Step 5: 缩放并限制上限 ----
        # clamp 防止极端距离样本的惩罚项主导梯度更新
        scaled_penalty = geo_gate * gamma * geo_penalty  # (B, V)
        scaled_penalty = torch.clamp(scaled_penalty, max=self.max_geo_penalty)

        # ---- Step 6: 应用偏置到 logits ----
        # 减去惩罚而非乘以因子：logits 是 log-probability 空间的值，
        # 减法等价于在概率空间中除以 exp(penalty)，比乘法更稳定
        final_logits = logits - scaled_penalty

        # ---- 存储信息供 collect_geo_stats 使用 ----
        self.last_info = {
            "gamma": gamma.item(),
            "geo_gate": geo_gate.detach().squeeze(-1),        # (B,)
            "scaled_penalty": scaled_penalty.detach(),         # (B, V)
            "distance_km": distance_km.detach(),               # (B, V)
        }

        return final_logits


def _bucketize_distance(
    distance_km: torch.Tensor,
    boundaries: Tuple[float, ...] = (1.0, 5.0, 10.0, 30.0, 80.0),
) -> torch.Tensor:
    """
    将距离 (km) 分桶为离散 bucket index。

    bucket 0: [0, 1) km
    bucket 1: [1, 5) km
    bucket 2: [5, 10) km
    bucket 3: [10, 30) km
    bucket 4: [30, 80) km
    bucket 5: [80, +inf) km

    Args:
        distance_km: 任意形状的距离张量
        boundaries: 桶边界列表（默认 (1, 5, 10, 30, 80)）

    Returns:
        bucket: 与输入同形状的 long 张量，值域 [0, num_boundaries]
    """
    bucket = torch.zeros_like(distance_km, dtype=torch.long)
    # 累加计数法：依次判断是否大于每个边界，大于则 bucket+1。
    # 例如 distance=7.3km → >=1 True (1), >=5 True (2), >=10 False (2) → bucket=2 ([5,10) km)
    for bound in boundaries:
        bucket = bucket + (distance_km >= bound).long()
    return bucket


class CandidateAwareDistanceScoring(nn.Module):
    """
    T7: 轻量加性距离感知打分模块。

    将空间距离作为低维加性特征参与打分，避免构造 [B, N, D] 级大张量。

    公式：
        base_logits    = h_user @ candidate_proj(venue_emb).T     # 语义匹配 (B, V)
        distance_score = distance_mlp(distance_features)           # 距离打分 (B, V)
        alpha          = sigmoid(distance_gate(distance_features)) # 门控 (B, V)
        logits         = base_logits + alpha * distance_score      # 最终分数 (B, V)

    其中 distance_features 仅包含低维距离衍生特征：
        - raw distance (km), log(1+d), 1/(1+d), d/100
        - distance_bucket_embedding (learnable, 6 buckets)
        - category_transition_embedding (learnable, num_cats^2)

    关键内存优势：
        - base_logits 通过 matmul 计算，不产生 [B, V, D] 中间张量
        - distance_features 维度仅 ~36（4 标量 + 16 距离桶 + 16 类别转移），
          分块后每块 [B, Vc, 36] ≈ 37 MB（相比旧方案 393 MB/chunk 降低 ~10×）
        - 无需 h_user_expand、cand_expand、interaction 等 [B, Vc, d_model] 张量

    Args:
        d_model: 模型隐藏维度
        venue_emb_dim: POI ID 嵌入原始维度（未投影前，如 64）
        num_venues: 候选 POI 数量
        num_cats: 类别数量
        venue_coords: (num_venues, 2) POI 经纬度 [lat, lon]
        venue_to_cat_idx: (num_venues,) POI → 类别索引映射
        distance_dim: 距离分桶嵌入维度（默认 16）
        transition_dim: 类别转移嵌入维度（默认 16）
        dropout: Scoring MLP 的 Dropout（默认 0.1）
        distance_boundaries: 距离分桶边界（默认 (1, 5, 10, 30, 80)）
    """

    def __init__(
        self,
        d_model: int,
        venue_emb_dim: int,
        num_venues: int,
        num_cats: int,
        venue_coords: np.ndarray,
        venue_to_cat_idx: np.ndarray,
        distance_dim: int = 16,
        transition_dim: int = 16,
        dropout: float = 0.1,
        distance_boundaries: Tuple[float, ...] = (1.0, 5.0, 10.0, 30.0, 80.0),
    ):
        super().__init__()

        self.d_model = d_model
        self.num_venues = num_venues
        self.num_cats = num_cats
        self.distance_boundaries = distance_boundaries
        self.num_distance_buckets = len(distance_boundaries) + 1  # 6

        # ---- 注册不可训练的查询表 ----
        self.register_buffer(
            'venue_coords',
            torch.tensor(venue_coords, dtype=torch.float32),
        )
        self.register_buffer(
            'venue_to_cat_idx',
            torch.tensor(venue_to_cat_idx, dtype=torch.long),
        )

        # ---- 候选 POI 投影层 ----
        # 将 venue_emb (venue_emb_dim → d_model)，用于 base_logits = h_user @ cand_repr.T
        self.candidate_proj = nn.Linear(venue_emb_dim, d_model)

        # ---- 距离分桶嵌入 ----
        self.distance_emb = nn.Embedding(self.num_distance_buckets, distance_dim)

        # ---- 类别转移嵌入 ----
        self.cat_transition_emb = nn.Embedding(num_cats * num_cats, transition_dim)

        # ---- Distance MLP: 低维距离特征 → 距离打分 ----
        # 输入: 4 标量特征 + distance_dim + transition_dim（典型值 ≈ 36）
        dist_feat_dim = 4 + distance_dim + transition_dim
        self.distance_mlp = nn.Sequential(
            nn.Linear(dist_feat_dim, d_model // 2),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(d_model // 2, 1),
        )

        # ---- 轻量 Distance Gate: 低维距离特征 → (0,1) 门控 ----
        self.distance_gate = nn.Sequential(
            nn.Linear(dist_feat_dim, d_model // 4),
            nn.ReLU(),
            nn.Linear(d_model // 4, 1),
            nn.Sigmoid(),
        )

        # 初始化
        self._init_weights()

        # 存储最近一次 forward 的信息，供 stats 收集使用
        self.last_info: Dict = {}

    def _init_weights(self):
        """初始化所有权重。

        distance_mlp 最后一层使用小权重初始化，使 distance_score 初始为小扰动，
        既保证梯度流通，又避免早期训练中距离特征主导语义匹配。
        """
        nn.init.xavier_uniform_(self.candidate_proj.weight)
        nn.init.zeros_(self.candidate_proj.bias)

        nn.init.xavier_uniform_(self.distance_emb.weight)
        nn.init.xavier_uniform_(self.cat_transition_emb.weight)

        # distance_mlp: 前层 Xavier，最后一层缩小 100× 以确保平稳启动
        mlp_layers = [m for m in self.distance_mlp if isinstance(m, nn.Linear)]
        for layer in mlp_layers[:-1]:
            nn.init.xavier_uniform_(layer.weight)
            nn.init.zeros_(layer.bias)
        # 最后一层: 小权重 + 零偏置 → distance_score ≈ 0
        nn.init.normal_(mlp_layers[-1].weight, std=0.001)
        nn.init.zeros_(mlp_layers[-1].bias)

        # distance_gate: 最后一层偏置 > 0，使初始 gate ≈ 0.73（距离信息充分参与）
        gate_linear_layers = [m for m in self.distance_gate if isinstance(m, nn.Linear)]
        for layer in gate_linear_layers[:-1]:
            nn.init.xavier_uniform_(layer.weight)
            nn.init.zeros_(layer.bias)
        nn.init.normal_(gate_linear_layers[-1].weight, std=0.001)
        nn.init.constant_(gate_linear_layers[-1].bias, 1.0)  # sigmoid(1.0) ≈ 0.73

    def forward(
        self,
        h_user: torch.Tensor,
        venue_emb_weight: torch.Tensor,
        v_seq: torch.Tensor,
        c_seq: torch.Tensor,
        chunk_size: int = 500,
    ) -> torch.Tensor:
        """
        Args:
            h_user: (B, d_model) Transformer 最后 token 的隐藏状态，代表用户短期兴趣
            venue_emb_weight: (V, venue_emb_dim) item_embedding.weight 矩阵
            v_seq: (B, seq_len) 输入 POI 序列（左填充，末尾为最后有效 POI）
            c_seq: (B, seq_len) 输入类别序列
            chunk_size: 候选分块大小，控制显存使用（默认 500）

        Returns:
            logits: (B, num_venues)

        算法流程：
            1. 语义匹配：h_user 与候选 POI 嵌入做点积 → base_logits (B, V)
            2. 距离打分：分块计算低维距离特征，通过 distance_mlp 打分
            3. 最终 logits = 语义匹配 + 门控 × 距离打分
        """
        B = h_user.size(0)
        V = self.num_venues

        # ================================================================
        # 阶段一：语义匹配分数（matmul，不产生 [B,V,D] 大张量）
        # 这是 O(B×d_model×V) 的矩阵乘法，PyTorch 内部高度优化，
        # 不会像 expand+cat 那样显式构造 [B,V,d_model] 中间张量，大幅节省显存
        # ================================================================
        candidate_repr = self.candidate_proj(venue_emb_weight)  # (V, d_model)
        base_logits = torch.matmul(h_user, candidate_repr.T)     # (B, V)

        # ================================================================
        # 阶段二：距离感知打分（分块计算低维特征 → MLP）
        # 将候选 POI 分成 chunk 逐块处理，每块只产生 (B, Vc, ~36) 的低维特征，
        # 避免一次性构造完整的 (B, V) 距离矩阵导致 OOM
        # ================================================================
        last_venues = v_seq[:, -1]           # (B,)
        last_coords = self.venue_coords[last_venues]  # (B, 2)
        last_categories = c_seq[:, -1]       # (B,)

        dist_score_chunks = []
        store_stats = not self.training
        if store_stats:
            all_distance_km_chunks = []

        for start in range(0, V, chunk_size):
            end = min(start + chunk_size, V)
            Vc = end - start

            # -- Step 2.1: Haversine 距离矩阵 (B, Vc) --
            cand_coords = self.venue_coords[start:end]  # (Vc, 2)
            distance_km_chunk = _compute_distance_matrix(last_coords, cand_coords)

            # -- Step 2.2: 构造距离标量特征 (B, Vc, 4) --
            # 四个互补的距离表示：原始距离 d、对数压缩 log(1+d)、反比 1/(1+d)、归一化 d/100
            # 不同表示对近/远距离有不同敏感度，组合使用让 MLP 能学习复杂的距离模式
            raw_feats = torch.stack([
                distance_km_chunk,
                torch.log1p(distance_km_chunk),
                1.0 / (1.0 + distance_km_chunk),
                distance_km_chunk / 100.0,
            ], dim=-1)  # (B, Vc, 4)

            # -- Step 2.3: 距离分桶嵌入 (B, Vc, distance_dim) --
            # 将连续距离离散化为 6 个桶，学习每个桶的可训练嵌入，
            # 捕捉非线性距离效应（如 "1km 内" 和 "1-5km" 的用户偏好可能有质的不同）
            distance_bucket_chunk = _bucketize_distance(
                distance_km_chunk, self.distance_boundaries
            )
            dist_emb = self.distance_emb(distance_bucket_chunk)

            # -- Step 2.4: 类别转移嵌入 (B, Vc, transition_dim) --
            # 捕捉 "从类别 A 签到后，接下来访问类别 B" 的转移模式，
            # 例如 "从咖啡馆 → 书店" 的转移概率高于 "从加油站 → 幼儿园"
            cand_cats = self.venue_to_cat_idx[start:end]  # (Vc,)
            transition_id = (
                last_categories.unsqueeze(1) * self.num_cats + cand_cats.unsqueeze(0)
            )  # (B, Vc)
            transition_id = transition_id.clamp(0, self.num_cats * self.num_cats - 1)
            cat_transition_emb = self.cat_transition_emb(transition_id)

            # -- Step 2.5: 拼接低维距离特征 (B, Vc, F) 其中 F ≈ 36 --
            # 总特征维度仅为 ~36（4 标量 + 16 距离桶 + 16 类别转移），
            # 远小于 d_model (128)，是关键的内存优化设计
            dist_feats = torch.cat(
                [raw_feats, dist_emb, cat_transition_emb], dim=-1
            )

            # -- Step 2.6: 距离 MLP 打分 + 门控 (B, Vc) --
            # distance_mlp 学习距离对偏好的非线性影响
            chunk_score = self.distance_mlp(dist_feats).squeeze(-1)
            # distance_gate 学习不同上下文中距离信息的重要性，
            # gate → 0 表示该样本几乎不需要距离约束（如用户探索新区域）
            alpha = self.distance_gate(dist_feats).squeeze(-1)
            chunk_score = alpha * chunk_score

            dist_score_chunks.append(chunk_score)

            if store_stats:
                all_distance_km_chunks.append(distance_km_chunk.detach())

        # ================================================================
        # 阶段三：最终 logits = 语义匹配 + 门控距离打分
        # 加法形式让距离打分作为"修正项"叠加在语义匹配上，
        # 而非取代语义匹配，保证基础推荐质量不受距离模块影响
        # ================================================================
        distance_score = torch.cat(dist_score_chunks, dim=1)  # (B, V)
        logits = base_logits + distance_score                  # (B, V)

        # ---- 存储信息供 stats 收集（仅评估模式） ----
        if store_stats:
            self.last_info = {
                "distance_km": torch.cat(all_distance_km_chunks, dim=1),  # (B, V)
            }
        else:
            self.last_info = {}

        return logits


class ResidualDistanceScoring(nn.Module):
    """
    T7b: 轻量残差距离 + 类别转移偏置打分模块。

    设计核心：保留 T5 的 Linear 输出头（base_logits），仅在此基础上
    增加轻量的 Embedding lookup bias，不构造任何 [B, V, d_model] 大张量。

    公式：
        base_logits      = Linear(h_user)                         # T5 输出 (B, V)
        bucket_id        = distance_bucket(last_poi, candidate)   # (B, V)
        distance_score   = distance_bias[bucket_id]                # (B, V) 标量
        transition_id    = last_cat * num_cats + cand_cat          # (B, V)
        transition_score = transition_bias[transition_id]          # (B, V) 标量
        final_logits     = base_logits + alpha*distance_score + beta*transition_score

    内存优势：
        - 仅产生 (B, V) float32 标量张量（B=512, V=7840 → ~16 MB）
        - 无 MLP、无 autograd 重计算、无 chunk 迭代
        - 训练速度接近 T5

    初始化：
        - distance_bias 和 transition_bias 初始化为零
        - alpha/beta 初始化为 sigmoid(-3.0) ≈ 0.047（弱残差，接近 T5）

    Args:
        num_venues: 候选 POI 数量
        num_cats: 类别数量
        venue_coords: (num_venues, 2) POI 经纬度 [lat, lon]
        venue_to_cat_idx: (num_venues,) POI → 类别索引映射
        num_distance_buckets: 距离分桶数量（默认 6）
        distance_boundaries: 距离分桶边界 km（默认 (1, 5, 10, 30, 80)）
    """

    def __init__(
        self,
        num_venues: int,
        num_cats: int,
        venue_coords: np.ndarray,
        venue_to_cat_idx: np.ndarray,
        num_distance_buckets: int = 6,
        distance_boundaries: Tuple[float, ...] = (1.0, 5.0, 10.0, 30.0, 80.0),
    ):
        super().__init__()

        self.num_venues = num_venues
        self.num_cats = num_cats
        self.distance_boundaries = distance_boundaries
        self.num_distance_buckets = num_distance_buckets

        # ---- 注册不可训练的查询表 ----
        self.register_buffer(
            'venue_coords',
            torch.tensor(venue_coords, dtype=torch.float32),
        )
        self.register_buffer(
            'venue_to_cat_idx',
            torch.tensor(venue_to_cat_idx, dtype=torch.long),
        )

        # ---- 距离分桶偏置：Embedding(num_buckets, 1)，初始化为零 ----
        self.distance_bias = nn.Embedding(num_distance_buckets, 1)
        nn.init.zeros_(self.distance_bias.weight)

        # ---- 类别转移偏置：Embedding(num_cats², 1)，初始化为零 ----
        self.transition_bias = nn.Embedding(num_cats * num_cats, 1)
        nn.init.zeros_(self.transition_bias.weight)

        # ---- 可学习残差强度：sigmoid(-3.0) ≈ 0.047 ----
        self.raw_alpha = nn.Parameter(torch.tensor(-3.0, dtype=torch.float32))
        self.raw_beta = nn.Parameter(torch.tensor(-3.0, dtype=torch.float32))

        # 存储最近一次 forward 的信息，供 stats 收集使用
        self.last_info: Dict = {}

    def forward(
        self,
        base_logits: torch.Tensor,
        v_seq: torch.Tensor,
        c_seq: torch.Tensor,
    ) -> torch.Tensor:
        """
        Args:
            base_logits: (B, num_venues) T5 Linear 输出层的原始 logits
            v_seq: (B, seq_len) 输入 POI 序列（左填充，末尾为最后有效 POI）
            c_seq: (B, seq_len) 输入类别序列

        Returns:
            final_logits: (B, num_venues)

        算法流程（极其轻量，仅 O(B×V) 的 Embedding 查表）：
            1. 从序列末尾提取 last_poi 和 last_cat
            2. 计算 last_poi → 所有候选 POI 的 Haversine 距离
            3. 距离分桶 + Embedding lookup → 距离偏置
            4. 类别转移索引 + Embedding lookup → 转移偏置
            5. 将偏置作为残差项叠加到 T5 原始 logits 上
        """
        B, V = base_logits.shape

        # ---- Step 1: 获取最后一个有效 POI 及其访问类别 ----
        last_venues = v_seq[:, -1]          # (B,)
        last_categories = c_seq[:, -1]      # (B,)

        # ---- Step 2: 计算 last_poi 到所有候选的 Haversine 距离矩阵 ----
        last_coords = self.venue_coords[last_venues]  # (B, 2)
        distance_km = _compute_distance_matrix(last_coords, self.venue_coords)

        # ---- Step 3: 距离分桶 → Embedding 查表获取偏置 ----
        # 每个距离桶对应一个可学习的偏置标量，训练后可解读为
        # "该距离范围内的 POI 有多大概率被用户选择"
        bucket_id = _bucketize_distance(distance_km, self.distance_boundaries)
        distance_score = self.distance_bias(bucket_id).squeeze(-1)  # (B, V)

        # ---- Step 4: 类别转移 → Embedding 查表获取偏置 ----
        # transition_id = last_cat * num_cats + cand_cat，
        # 将 (from_cat, to_cat) 对扁平化索引到 transition_bias 表中
        cand_cats = self.venue_to_cat_idx.unsqueeze(0).expand(B, -1)  # (B, V)
        transition_id = last_categories.unsqueeze(1) * self.num_cats + cand_cats
        transition_id = transition_id.clamp(0, self.num_cats * self.num_cats - 1)
        transition_score = self.transition_bias(transition_id).squeeze(-1)  # (B, V)

        # ---- Step 5: 残差强度由可学习参数 alpha/beta 控制 ----
        # sigmoid 保证 alpha, beta ∈ (0, 1)，初始时 sigmoid(-3) ≈ 0.047，
        # 让残差偏置以"小修正"的形式参与训练，不会破坏 T5 已学到的语义匹配
        alpha = torch.sigmoid(self.raw_alpha)
        beta = torch.sigmoid(self.raw_beta)

        # ---- Step 6: 最终 logits = T5 语义匹配 + 距离残差 + 类别转移残差 ----
        final_logits = base_logits + alpha * distance_score + beta * transition_score

        # ---- 存储信息供 stats 收集（仅评估模式） ----
        if not self.training:
            self.last_info = {
                "distance_km": distance_km.detach(),
                "distance_score": distance_score.detach(),
                "transition_score": transition_score.detach(),
                "alpha": alpha.item(),
                "beta": beta.item(),
            }
        else:
            self.last_info = {}

        return final_logits


def _compute_distance_matrix(
    last_coords: torch.Tensor,
    venue_coords: torch.Tensor,
) -> torch.Tensor:
    """
    批量计算 last_poi 与所有候选 POI 之间的 Haversine 距离矩阵。

    Haversine 公式计算球面上两点的大圆距离，相比欧氏距离能更准确地反映
    地球表面 POI 之间的实际地理距离，是位置推荐任务中空间偏置计算的基础。

    Args:
        last_coords: (B, 2) 每个样本最后一个 POI 的 [lat, lon]（度）
        venue_coords: (V, 2) 所有候选 POI 的 [lat, lon]（度）

    Returns:
        distance_km: (B, V) Haversine 距离矩阵（km）
    """
    last_lat_rad = torch.deg2rad(last_coords[:, 0]).unsqueeze(1)  # (B, 1)
    last_lon_rad = torch.deg2rad(last_coords[:, 1]).unsqueeze(1)  # (B, 1)

    cand_lat_rad = torch.deg2rad(venue_coords[:, 0]).unsqueeze(0)  # (1, V)
    cand_lon_rad = torch.deg2rad(venue_coords[:, 1]).unsqueeze(0)  # (1, V)

    dlat = cand_lat_rad - last_lat_rad
    dlon = cand_lon_rad - last_lon_rad

    a = (
        torch.sin(dlat / 2.0) ** 2
        + torch.cos(last_lat_rad)
        * torch.cos(cand_lat_rad)
        * torch.sin(dlon / 2.0) ** 2
    )
    a = a.clamp(min=0.0, max=1.0 - 1e-7)
    c = 2.0 * torch.atan2(torch.sqrt(a), torch.sqrt(1.0 - a))
    return 6371.0 * c


class TransformerPOIModel(nn.Module):
    """
    基于 Transformer 的 Next POI 推荐模型。

    支持可配置的多特征融合：
        - 基础:     POI ID + 类别
        - 行为语义: + Skip-Gram Word2Vec 嵌入
        - 文本语义: + Sentence-BERT 文本嵌入
        - 时间编码: + Sin-Cos 周期性时间编码（小时 + 星期几）
        - 融合:     + 行为语义和文本语义同时使用

    支持两种融合模式：
        - fusion_type="static":  concat + Linear projection（默认）
        - fusion_type="dynamic": Dynamic Fusion Gate（逐 token 加权）

    支持 GeoBias（use_geobias=True）：
        - geobias_type="naive": final_logits = logits - gamma * log(1 + distance_km)
        - geobias_type="gated": final_logits = logits - clamp(gate * gamma * log(1+d), max)
        - gamma: 可学习参数（通过 softplus 保证为正）

    支持两种 Scoring 模式：
        - scoring_type="linear": 传统 Linear(h_user) → logits（T5 及之前所有变体）
        - scoring_type="distance_feature": 候选感知距离特征打分（T7）

    Args:
        num_venues: 唯一 POI 数量
        num_cats: 唯一类别数量
        use_category: 是否包含 POI 类别嵌入（默认 True）
        venue_emb_dim: POI ID 嵌入维度（默认 64）
        cat_emb_dim: 类别嵌入维度（默认 16）
        use_time: 是否包含时间编码（默认 False）
        time_emb_dim: 时间编码投影维度（默认 16）
        behav_dim: 行为语义嵌入输入维度（默认 128）
        behav_proj_dim: 行为语义投影维度，0 表示禁用（默认 64）
        text_dim: 文本嵌入输入维度（默认 384）
        text_proj_dim: 文本投影维度，0 表示禁用（默认 0）
        d_model: Transformer 隐藏维度（默认 128）
        n_heads: 注意力头数（默认 2）
        n_layers: 编码器层数（默认 2）
        ff_dim: 前馈网络隐藏维度（默认 256）
        dropout: Transformer Dropout 比率（默认 0.1）
        fc_dropout: 最终分类器 Dropout 比率（默认 0.3）
        behav_matrix: 预计算的行为语义嵌入矩阵，可为 None
        text_matrix: 预计算的文本嵌入矩阵，可为 None
        fusion_type: 融合模式 — "static" 或 "dynamic"（默认 "static"）
        gate_hidden: Dynamic Fusion Gate 的隐藏层维度（默认 64）
        use_geobias: 是否启用 GeoBias 距离感知 logits（默认 False）
        venue_coords: POI 经纬度矩阵，shape=(num_venues, 2)，仅 use_geobias=True 或 scoring_type="distance_feature" 时需要
        geo_gamma_init: Naive GeoBias learnable gamma 的初始 raw 值（默认 0.1）
        geobias_type: GeoBias 类型 — "naive" 或 "gated"（默认 "naive"）
        max_geo_penalty: Gated GeoBias 的 scaled_penalty 上限（默认 1.0）
        scoring_type: 输出层模式 — "linear" 或 "distance_feature"（默认 "linear"）
        venue_to_cat_idx: (num_venues,) POI→类别索引数组，scoring_type="distance_feature" 时需要
        distance_dim: 距离分桶嵌入维度（默认 16），scoring_type="distance_feature" 时使用
        transition_dim: 类别转移嵌入维度（默认 16），scoring_type="distance_feature" 时使用
    """

    def __init__(
        self,
        num_venues: int,
        num_cats: int,
        use_category: bool = True,
        venue_emb_dim: int = 64,
        cat_emb_dim: int = 16,
        use_time: bool = False,
        time_emb_dim: int = 16,
        behav_dim: int = 128,
        behav_proj_dim: int = 64,
        text_dim: int = 384,
        text_proj_dim: int = 0,
        d_model: int = 128,
        n_heads: int = 2,
        n_layers: int = 2,
        ff_dim: int = 256,
        dropout: float = 0.1,
        fc_dropout: float = 0.3,
        behav_matrix: Optional[np.ndarray] = None,
        text_matrix: Optional[np.ndarray] = None,
        fusion_type: str = "static",
        gate_hidden: int = 64,
        use_geobias: bool = False,
        venue_coords: Optional[np.ndarray] = None,
        geo_gamma_init: float = 0.1,
        geobias_type: str = "naive",
        max_geo_penalty: float = 1.0,
        scoring_type: str = "linear",
        venue_to_cat_idx: Optional[np.ndarray] = None,
        distance_dim: int = 16,
        transition_dim: int = 16,
        use_long_pref: bool = False,
        long_pref_type: str = "attention",
        user_history_matrix: Optional[torch.Tensor] = None,
        user_history_lengths: Optional[torch.Tensor] = None,
        num_users: int = 0,
        use_causal_long_pref: bool = False,
        causal_pref_type: str = "attention",
    ):
        super().__init__()

        if fusion_type not in ("static", "dynamic"):
            raise ValueError(
                f"fusion_type 必须是 'static' 或 'dynamic'，收到 '{fusion_type}'"
            )
        if geobias_type not in ("naive", "gated"):
            raise ValueError(
                f"geobias_type 必须是 'naive' 或 'gated'，收到 '{geobias_type}'"
            )
        if scoring_type not in ("linear", "distance_feature", "residual_distance"):
            raise ValueError(
                f"scoring_type 必须是 'linear'、'distance_feature' 或 'residual_distance'，收到 '{scoring_type}'"
            )
        self.fusion_type = fusion_type
        self.use_geobias = use_geobias
        self.geobias_type = geobias_type
        self.scoring_type = scoring_type
        self.use_long_pref = use_long_pref
        self.use_causal_long_pref = use_causal_long_pref
        self.long_short_info: Dict = {}

        # ================================================================
        # 阶段一：嵌入层 — 将离散 ID 和连续特征映射到稠密向量空间
        # ================================================================
        # POI ID 嵌入是模型最核心的知识库，每个 POI 的向量编码了其语义和热度信息
        self.venue_emb = nn.Embedding(num_venues, venue_emb_dim)
        self.use_category = use_category
        if self.use_category:
            # 类别嵌入捕获 POI 的功能类型（餐厅/咖啡厅/商场等），提供归纳偏置
            self.cat_emb = nn.Embedding(num_cats, cat_emb_dim)

        self.use_time = use_time
        self.use_behav = behav_proj_dim > 0 and behav_matrix is not None
        self.use_text = text_proj_dim > 0 and text_matrix is not None

        # ================================================================
        # 阶段二：特征投影层（Static 和 Dynamic Fusion 共用）
        # 将不同来源、不同维度的特征投影到各自的统一子空间，
        # 为后续融合做好准备。行为语义和文本语义矩阵以 buffer 形式注册，
        # 不参与梯度更新但随模型移动到正确的设备。
        # ================================================================
        input_dim = venue_emb_dim
        if self.use_category:
            input_dim += cat_emb_dim
        if self.use_time:
            # 时间特征从 4 维（小时 sin/cos + 星期 sin/cos）投影到 time_emb_dim
            self.time_proj = nn.Linear(4, time_emb_dim)
            input_dim += time_emb_dim
        if self.use_behav:
            # 行为语义（Word2Vec）从高维投影到低维，减少噪声
            self.behav_proj = nn.Linear(behav_dim, behav_proj_dim)
            self.register_buffer('behav_matrix', torch.tensor(behav_matrix, dtype=torch.float32))
            input_dim += behav_proj_dim
        if self.use_text:
            # 文本语义（Sentence-BERT）从高维投影到低维，保留关键语义
            self.text_proj = nn.Linear(text_dim, text_proj_dim)
            self.register_buffer('text_matrix', torch.tensor(text_matrix, dtype=torch.float32))
            input_dim += text_proj_dim

        # ================================================================
        # 阶段三：Fusion 模块 — 多源特征融合
        # - static: 将所有特征拼接后通过一个 Linear 层投影到 d_model，
        #   参数少、速度快，但每个 token 使用相同的融合比例
        # - dynamic: 使用 Dynamic Fusion Gate 为每个 token 学习自适应的
        #   特征权重，更灵活但参数略多
        # ================================================================
        if self.fusion_type == "dynamic":
            # 构建 Dynamic Fusion Gate 所需的特征维度列表
            # 根据实际启用的特征动态构建，保证 Gate 输入维度与拼接后的总维度一致
            dyn_feature_dims = [venue_emb_dim]
            dyn_feature_names = ["id"]
            if self.use_category:
                dyn_feature_dims.append(cat_emb_dim)
                dyn_feature_names.append("category")
            if self.use_time:
                dyn_feature_dims.append(time_emb_dim)
                dyn_feature_names.append("time")
            if self.use_behav:
                dyn_feature_dims.append(behav_proj_dim)
                dyn_feature_names.append("behavioral")
            if self.use_text:
                dyn_feature_dims.append(text_proj_dim)
                dyn_feature_names.append("text")

            self.dynamic_fusion = DynamicFusionGate(
                feature_dims=dyn_feature_dims,
                feature_names=dyn_feature_names,
                fusion_dim=d_model,
                gate_hidden=gate_hidden,
                dropout=dropout,
            )

        # Static Fusion: concat → Linear 投影到 d_model
        self.input_proj = nn.Linear(input_dim, d_model) if input_dim != d_model else nn.Identity()

        # ================================================================
        # 阶段四：Transformer 编码器 — 序列建模核心
        # 2 层 Pre-LN Transformer，将融合后的特征序列编码为上下文感知的隐藏表示。
        # 轻量设计（2 层 2 头）避免了过拟合，适合中小规模的 POI 推荐数据集。
        # ================================================================
        self.encoder = TransformerEncoder(
            d_model=d_model,
            n_heads=n_heads,
            n_layers=n_layers,
            ff_dim=ff_dim,
            dropout=dropout,
        )

        # ================================================================
        # 阶段五：输出层 — 从用户隐藏状态映射到候选 POI 的推荐分数
        # 支持三种打分模式：
        #   - linear: T5 传统 Linear(h_user) → logits (B, V)
        #   - distance_feature: T7 候选感知距离特征打分（已弃用，显存开销大）
        #   - residual_distance: T7b T5 + 轻量残差距离/类别转移偏置（推荐）
        # ================================================================
        self.fc_dropout = nn.Dropout(fc_dropout)
        if self.scoring_type == "distance_feature":
            # T7 (deprecated heavy): 候选感知距离特征打分
            if venue_to_cat_idx is None:
                raise ValueError(
                    "scoring_type='distance_feature' 时必须提供 venue_to_cat_idx 数组。"
                )
            if venue_coords is None:
                raise ValueError(
                    "scoring_type='distance_feature' 时必须提供 venue_coords 矩阵。"
                )
            self.distance_scoring = CandidateAwareDistanceScoring(
                d_model=d_model,
                venue_emb_dim=venue_emb_dim,
                num_venues=num_venues,
                num_cats=num_cats,
                venue_coords=venue_coords,
                venue_to_cat_idx=venue_to_cat_idx,
                distance_dim=distance_dim,
                transition_dim=transition_dim,
                dropout=dropout,
            )
            self.register_buffer(
                'venue_coords',
                torch.tensor(venue_coords, dtype=torch.float32),
            )
        elif self.scoring_type == "residual_distance":
            # T7b: T5 Linear 输出 + 轻量残差距离/类别转移偏置
            # 保留 T5 的标准 Linear 分类头作为基础语义匹配
            if venue_to_cat_idx is None:
                raise ValueError(
                    "scoring_type='residual_distance' 时必须提供 venue_to_cat_idx 数组。"
                )
            if venue_coords is None:
                raise ValueError(
                    "scoring_type='residual_distance' 时必须提供 venue_coords 矩阵。"
                )
            self.fc = nn.Linear(d_model, num_venues)
            self.residual_scoring = ResidualDistanceScoring(
                num_venues=num_venues,
                num_cats=num_cats,
                venue_coords=venue_coords,
                venue_to_cat_idx=venue_to_cat_idx,
            )
            self.register_buffer(
                'venue_coords',
                torch.tensor(venue_coords, dtype=torch.float32),
            )
        else:
            # T5 及其他: 传统 Linear 分类器，h_user → logits
            self.fc = nn.Linear(d_model, num_venues)

        # ================================================================
        # 阶段六（可选）：T8 — 长期用户偏好融合（Long-Short Fusion）
        # 用户不仅受近期签到序列影响，还受长期历史偏好的影响。
        # 例如，一个用户最近 5 次签到都是快餐，但他过去半年常去高端餐厅。
        # Long-Short Fusion Gate 学习如何在短期兴趣 (h_short) 和长期偏好 (h_long)
        # 之间做自适应权衡。
        # ================================================================
        if self.use_long_pref:
            if user_history_matrix is None or user_history_lengths is None:
                raise ValueError(
                    "use_long_pref=True 时必须提供 user_history_matrix 和 user_history_lengths"
                )
            self.register_buffer(
                'user_history_matrix',
                user_history_matrix if isinstance(user_history_matrix, torch.Tensor)
                else torch.tensor(user_history_matrix, dtype=torch.long),
            )
            self.register_buffer(
                'user_history_lengths',
                user_history_lengths if isinstance(user_history_lengths, torch.Tensor)
                else torch.tensor(user_history_lengths, dtype=torch.long),
            )
            self.long_encoder = LongPreferenceEncoder(
                venue_emb_dim=venue_emb_dim,
                d_model=d_model,
                pool_type=long_pref_type,
                dropout=dropout,
            )
            self.long_short_gate = LongShortFusionGate(
                d_model=d_model,
                gate_hidden=gate_hidden,
                dropout=dropout,
            )

        # ================================================================
        # 阶段七（可选）：T9 — 因果长期记忆融合
        # 与 T8 使用全局用户历史不同，T9 使用每个样本独有的因果历史
        # （即该样本时间戳之前的所有签到，而非用户的全量历史），
        # 保证"不使用未来信息"的因果性约束。
        # 复用 LongPreferenceEncoder 和 LongShortFusionGate 的实现。
        # ================================================================
        if self.use_causal_long_pref:
            self.causal_long_encoder = LongPreferenceEncoder(
                venue_emb_dim=venue_emb_dim,
                d_model=d_model,
                pool_type=causal_pref_type,
                dropout=dropout,
            )
            self.causal_long_short_gate = LongShortFusionGate(
                d_model=d_model,
                gate_hidden=gate_hidden,
                dropout=dropout,
            )

        # ================================================================
        # 阶段八（可选）：GeoBias 模块 — 空间距离感知的 logit 偏置
        # 基于地理学第一定律（Tobler's Law）"近的事物比远的事物更相关"，
        # 对远距离候选 POI 施加惩罚，鼓励模型推荐距离用户当前位置较近的 POI。
        # - naive: 无条件对所有样本施加相同强度的距离惩罚
        # - gated: 通过 Gate MLP 学习样本级自适应惩罚强度
        # ================================================================
        if self.use_geobias:
            if venue_coords is None:
                raise ValueError(
                    "use_geobias=True 时必须提供 venue_coords 矩阵 (num_venues, 2)。"
                )
            if self.geobias_type == "gated":
                # T6a: 门控 GeoBias — 上下文自适应距离惩罚
                self.gated_geobias = GatedGeoBias(
                    d_model=d_model,
                    venue_coords=venue_coords,
                    max_geo_penalty=max_geo_penalty,
                )
                self.register_buffer(
                    'venue_coords',
                    torch.tensor(venue_coords, dtype=torch.float32),
                )
            else:
                # T6 Naive: 无条件距离惩罚，所有样本共享同一个 gamma 参数
                self.register_buffer(
                    'venue_coords',
                    torch.tensor(venue_coords, dtype=torch.float32),
                )
                self.geo_gamma_raw = nn.Parameter(
                    torch.tensor(geo_gamma_init, dtype=torch.float32)
                )

    def forward(
        self,
        v_seq: torch.Tensor,
        c_seq: torch.Tensor,
        t_seq: Optional[torch.Tensor] = None,
        u_seq: Optional[torch.Tensor] = None,
        causal_history: Optional[torch.Tensor] = None,
        causal_mask: Optional[torch.Tensor] = None,
        return_attention: bool = False,
        return_gate: bool = False,
    ):
        """
        整体算法流程（5 个阶段）：

        阶段一 — 特征嵌入：POI ID + 类别 + 时间 + 行为语义 + 文本语义 → 嵌入向量
        阶段二 — 特征融合：Static (concat+Linear) 或 Dynamic (Gate 加权) → d_model
        阶段三 — Transformer 编码：位置编码 + 2 层 Pre-LN Transformer → 隐藏状态序列
        阶段四 — 长期偏好融合（可选）：T8 全局用户历史 或 T9 因果历史 → h_final
        阶段五 — 输出打分：Linear / DistanceFeature / ResidualDistance → logits + GeoBias

        Args:
            v_seq: (batch, seq_len) POI ID 索引
            c_seq: (batch, seq_len) 类别索引
            t_seq: (batch, seq_len, 4) 时间特征 [h_sin, h_cos, w_sin, w_cos]
                   仅在 use_time=True 时生效，否则可为 None。
            u_seq: (batch,) 用户索引
                   仅在 use_long_pref=True 时生效，否则可为 None。
            causal_history: (batch, max_hist_len) 因果长期历史 POI 索引（左填充，0=PAD）
                   仅在 use_causal_long_pref=True 时生效，否则可为 None。
            causal_mask: (batch, max_hist_len) 因果长期历史有效位置掩码
                   仅在 use_causal_long_pref=True 时生效，否则可为 None。
            return_attention: 如果为 True，同时返回注意力权重
            return_gate: 如果为 True 且 fusion_type="dynamic"，同时返回门控权重
                若 use_long_pref=True 或 use_causal_long_pref=True，return_gate 返回 long-short gate

        Returns:
            若 return_gate=True 且 (use_long_pref=True 或 use_causal_long_pref=True):
                (logits, long_short_gate)
            若 return_gate=True 且 fusion_type="dynamic":
                (logits, gate_weights)
            若 return_attention=True:
                (logits, attentions)
            否则: logits
        """
        # ================================================================
        # 阶段一：特征嵌入 — 将各类输入映射到稠密向量空间
        # ================================================================
        v = self.venue_emb(v_seq)      # (B, S, venue_emb_dim)
        features = [v]

        if self.use_category:
            c = self.cat_emb(c_seq)    # (B, S, cat_emb_dim)
            features.append(c)

        if self.use_time:
            if t_seq is None:
                raise ValueError(
                    "需要时间特征但 t_seq 为 None。"
                    "请在 Dataset 中设置 include_time=True。"
                )
            t = self.time_proj(t_seq)  # (B, S, time_emb_dim)
            features.append(t)

        if self.use_behav:
            b = self.behav_proj(self.behav_matrix[v_seq])  # (B, S, behav_proj_dim)
            features.append(b)

        if self.use_text:
            t = self.text_proj(self.text_matrix[v_seq])    # (B, S, text_proj_dim)
            features.append(t)

        # ================================================================
        # 阶段二：特征融合 — Static 或 Dynamic
        # ================================================================
        gate_weights = None
        if self.fusion_type == "dynamic":
            x, gate_weights = self.dynamic_fusion(features, return_gate=True)
        else:
            x = torch.cat(features, dim=-1)  # (B, S, input_dim)
            x = self.input_proj(x)            # (B, S, d_model)

        # ================================================================
        # 阶段三：Transformer 序列编码
        # 2 层 Pre-LN Transformer 将融合后的嵌入序列编码为上下文感知的隐藏状态。
        # 每个位置的输出包含了该位置之前所有 token 的双向上下文信息。
        # ================================================================
        x, attentions = self.encoder(x, return_attention=return_attention)

        # 取序列最后一个 token 的隐藏状态作为用户的短期兴趣表示 h_short。
        # 在 Next POI 推荐中，最后一个位置对应的是"用户当前所处上下文"，
        # 其隐藏状态编码了整个签到序列的序列模式信息。
        h_user = x[:, -1, :]  # (B, d_model)

        # ================================================================
        # 阶段四（可选）：长期偏好融合
        # ================================================================
        # ---- T8: 基于全局用户历史的长期偏好 ----
        long_short_gate = None
        self.long_short_info = {}
        if self.use_long_pref:
            if u_seq is None:
                raise ValueError("use_long_pref=True 时必须提供 u_seq 参数")
            h_short = h_user
            # 从预存储的用户历史矩阵中查找该用户的完整签到历史
            user_hist = self.user_history_matrix[u_seq]         # (B, max_hist_len)
            hist_lens = self.user_history_lengths[u_seq]         # (B,)
            # 将长历史编码为固定维度的偏好向量 h_long
            h_long = self.long_encoder(
                self.venue_emb.weight, user_hist, hist_lens
            )                                                    # (B, d_model)
            # 自适应门控融合短期兴趣和长期偏好
            h_user, long_short_gate = self.long_short_gate(h_short, h_long)
            if not self.training:
                self.long_short_info = {
                    'h_short': h_short.detach(),
                    'h_long': h_long.detach(),
                }

        # ---- T9: 基于因果长期历史的长短期融合（per-sample causal history） ----
        # 与 T8 的区别：T9 使用每个样本的因果历史（该样本时间戳之前的所有签到），
        # 而非用户的全局历史。这保证了严格的因果性约束，适合在线推理场景。
        if self.use_causal_long_pref:
            if causal_history is None or causal_mask is None:
                raise ValueError(
                    "use_causal_long_pref=True 时必须提供 causal_history 和 causal_mask 参数"
                )
            h_short = h_user
            # causal_mask 中值为 1 的位置为有效 POI，sum 得到有效历史长度
            causal_lens = causal_mask.sum(dim=1)  # (B,)
            h_long = self.causal_long_encoder(
                self.venue_emb.weight, causal_history, causal_lens
            )  # (B, d_model)
            h_user, long_short_gate = self.causal_long_short_gate(h_short, h_long)
            if not self.training:
                self.long_short_info = {
                    'h_short': h_short.detach(),
                    'h_long': h_long.detach(),
                }

        # ================================================================
        # 阶段五：输出层 — 将用户表示映射为推荐分数
        # ================================================================
        # ---- 三种打分模式：linear (T5) / distance_feature (T7) / residual_distance (T7b) ----
        if self.scoring_type == "distance_feature":
            # T7 (deprecated heavy): 候选感知距离特征打分
            logits = self.distance_scoring(h_user, self.venue_emb.weight, v_seq, c_seq)
        elif self.scoring_type == "residual_distance":
            # T7b: T5 Linear 输出 + 轻量残差偏置
            base_logits = self.fc(self.fc_dropout(h_user))  # (B, num_venues)
            logits = self.residual_scoring(base_logits, v_seq, c_seq)
        else:
            # T5 / T8: 传统 Linear(h_user) 输出
            logits = self.fc(self.fc_dropout(h_user))  # (B, num_venues)

        # ---- GeoBias: 距离感知 logits 偏置（仅 linear scoring 模式）----
        if self.use_geobias:
            h_for_geo = h_user if self.geobias_type == "gated" else None
            logits = self._apply_geobias(logits, v_seq, h_user=h_for_geo)

        if return_gate and (self.use_long_pref or self.use_causal_long_pref) and long_short_gate is not None:
            return logits, long_short_gate
        if return_gate and self.fusion_type == "dynamic":
            return logits, gate_weights
        if return_attention:
            return logits, attentions
        return logits

    def _apply_geobias(
        self,
        logits: torch.Tensor,
        v_seq: torch.Tensor,
        h_user: Optional[torch.Tensor] = None,
    ) -> torch.Tensor:
        """
        对 logits 施加空间距离偏置。

        支持两种模式：
        - "naive": final_logits = logits - gamma * log(1 + distance_km)
        - "gated": final_logits = logits - clamp(gate(h_user) * gamma * log(1+d), max)

        Args:
            logits: (B, num_venues) 原始模型输出
            v_seq: (B, seq_len) 输入 POI 序列（左填充，末尾为最后有效 POI）
            h_user: (B, d_model) 用户隐藏状态（仅 gated 模式需要）

        Returns:
            adjusted_logits: (B, num_venues)
        """
        if self.geobias_type == "gated":
            if h_user is None:
                raise ValueError(
                    "geobias_type='gated' 需要 h_user 参数，但收到 None。"
                )
            return self.gated_geobias(logits, h_user, v_seq)

        # ---- Naive GeoBias（原有逻辑）----
        # 核心公式：final_logits = logits - gamma * log(1 + distance_km)
        # gamma 通过 softplus 保证为正，所有样本共享相同的惩罚强度
        B, V = logits.shape
        S = v_seq.size(1)

        # ---- Step 1: 提取最后有效 POI 作为距离计算的起点 ----
        # 左填充策略（PAD token 在左侧）保证 v_seq[:, -1] 始终为有效签到 POI
        last_venues = v_seq[:, -1]  # (B,)

        # ---- Step 2: Haversine 距离计算 (B, V) ----
        # 计算 last_poi（每个样本的最后一个签到位置）到所有 V 个候选 POI 的球面距离
        last_coords = self.venue_coords[last_venues]  # (B, 2)
        last_lat_rad = torch.deg2rad(last_coords[:, 0])  # (B,)
        last_lon_rad = torch.deg2rad(last_coords[:, 1])  # (B,)

        cand_lat_rad = torch.deg2rad(self.venue_coords[:, 0]).unsqueeze(0)  # (1, V)
        cand_lon_rad = torch.deg2rad(self.venue_coords[:, 1]).unsqueeze(0)  # (1, V)

        last_lat_rad = last_lat_rad.unsqueeze(1)  # (B, 1)
        last_lon_rad = last_lon_rad.unsqueeze(1)  # (B, 1)

        dlat = cand_lat_rad - last_lat_rad  # (B, V)
        dlon = cand_lon_rad - last_lon_rad  # (B, V)

        # Haversine 公式：计算球面两点间的大圆距离
        a = (
            torch.sin(dlat / 2.0) ** 2
            + torch.cos(last_lat_rad) * torch.cos(cand_lat_rad) * torch.sin(dlon / 2.0) ** 2
        )
        # 浮点精度保护：clamp 到 [0, 1) 避免 sqrt 传入负数
        a = a.clamp(min=0.0, max=1.0 - 1e-7)
        c = 2.0 * torch.atan2(torch.sqrt(a), torch.sqrt(1.0 - a))
        distance_km = 6371.0 * c  # (B, V)，地球平均半径 6371 km

        # ---- Step 3: 计算距离惩罚并应用到 logits ----
        # log(1+d) 对数压缩避免远距离惩罚过大，softplus 保证 gamma 为正
        geo_penalty = torch.log1p(distance_km)  # log(1 + d)，(B, V)
        gamma = F.softplus(self.geo_gamma_raw)  # 标量，保证为正

        bias = gamma * geo_penalty  # (B, V)

        return logits - bias


def count_parameters(model: nn.Module) -> int:
    """
    统计模型中可训练参数的总数量。

    用于快速比较不同模型变体的参数量级，辅助模型选型和资源配置决策。
    只统计 requires_grad=True 的参数，冻结的嵌入矩阵不计入。
    """
    return sum(p.numel() for p in model.parameters() if p.requires_grad)


@torch.no_grad()
def collect_gate_weights(
    model: TransformerPOIModel,
    dataloader,
    device: torch.device,
) -> Dict[str, float]:
    """
    在给定 DataLoader 上收集 Dynamic Fusion 的平均 gate 权重。

    仅在 fusion_type="dynamic" 时有效；若为 static fusion 则返回空字典。

    Args:
        model: 已训练的 TransformerPOIModel（eval 模式，fusion_type="dynamic"）
        dataloader: 评估用的 DataLoader
        device: torch 设备

    Returns:
        字典 {feature_name: average_weight}。
    """
    if model.fusion_type != "dynamic":
        return {}
    # 关键区分：T8/T9 模型启用 long_pref 时，return_gate 返回的是长短期融合门控值，
    # 而非 Dynamic Fusion Gate 的特征权重。此时无法收集特征级别的 gate 统计。
    if getattr(model, 'use_long_pref', False) or getattr(model, 'use_causal_long_pref', False):
        return {}

    model.eval()
    gate_weights_list = []

    for batch in dataloader:
        batch = [t.to(device) for t in batch]
        bv, bc = batch[0], batch[1]

        if len(batch) == 4:
            bt = batch[2]
            _, gw = model(bv, bc, bt, return_gate=True)
        else:
            _, gw = model(bv, bc, return_gate=True)

        gate_weights_list.append(gw.cpu())

    if not gate_weights_list:
        return {}

    feature_names = model.dynamic_fusion.feature_names
    return compute_gate_stats(gate_weights_list, feature_names)


@torch.no_grad()
def collect_geo_stats(
    model: TransformerPOIModel,
    dataloader,
    device: torch.device,
) -> Dict[str, float]:
    """
    在给定 DataLoader 上收集 GeoBias 相关的距离统计。

    支持 Naive GeoBias 和 Gated GeoBias 两种模式。

    Naive 模式统计项：
        - geo_gamma, avg_target_dist_km, avg_top1_dist_km, avg_top5_dist_km

    Gated 模式额外统计项：
        - geo_gamma, geo_gate_min/mean/max
        - scaled_penalty_min/mean/max
        - avg_target_dist_km, avg_top1_dist_km, avg_top5_dist_km
        - short_target_dist_geo_gate_mean（target ≤ 5km）
        - long_target_dist_geo_gate_mean（target > 5km）

    Args:
        model: 已训练的模型（eval 模式，use_geobias=True）
        dataloader: 评估用的 DataLoader
        device: torch 设备

    Returns:
        距离统计字典。
    """
    if not model.use_geobias:
        return {}

    model.eval()
    is_gated = (model.geobias_type == "gated")

    # Gamma
    if is_gated:
        gamma_val = float(F.softplus(model.gated_geobias.raw_gamma).item())
    else:
        gamma_val = float(F.softplus(model.geo_gamma_raw).item())

    target_dists = []
    top1_dists = []
    top5_dists = []

    # Gated 模式下额外收集：门控值和惩罚项分布
    all_geo_gates = []        # (total_samples,)
    all_scaled_penalty_means = []  # (total_samples,)
    all_scaled_penalty_maxs = []   # (total_samples,)
    all_scaled_penalty_mins = []   # (total_samples,)
    # 按 target 距离分组统计 gate 值，分析门控是否学会了对近/远距离做不同处理
    short_target_gates = []   # target 距离 ≤ 5km
    long_target_gates = []    # target 距离 > 5km
    DIST_THRESHOLD_KM = 5.0

    for batch in dataloader:
        batch = [t.to(device) for t in batch]
        bv, bc = batch[0], batch[1]
        bl = batch[-1]  # target labels

        if len(batch) == 4:
            bt = batch[2]
            logits = model(bv, bc, bt)
        else:
            logits = model(bv, bc)

        # ---- 计算 last_poi → target_poi 的 Haversine 距离 ----
        B = bv.size(0)
        last_venues = bv[:, -1]  # (B,)

        # gated 模式下 venue_coords 注册在 gated_geobias 子模块中，naive 模式下在顶层
        vc = model.gated_geobias.venue_coords if is_gated else model.venue_coords

        last_coords = vc[last_venues]  # (B, 2)
        target_coords = vc[bl]          # (B, 2)

        target_dist = _haversine_distance(
            last_coords[:, 0], last_coords[:, 1],
            target_coords[:, 0], target_coords[:, 1],
        )  # (B,)
        target_dists.append(target_dist.cpu())

        # ---- last_poi → Top-K 预测距离 ----
        _, topk = torch.topk(logits, k=5, dim=1)  # (B, 5)
        top1_venues = topk[:, 0]  # (B,)
        top5_venues = topk  # (B, 5)

        top1_coords = vc[top1_venues]  # (B, 2)
        top1_dist = _haversine_distance(
            last_coords[:, 0], last_coords[:, 1],
            top1_coords[:, 0], top1_coords[:, 1],
        )
        top1_dists.append(top1_dist.cpu())

        top5_coords = vc[top5_venues]  # (B, 5, 2)
        top5_dist_batch = _haversine_distance(
            last_coords[:, 0].unsqueeze(1), last_coords[:, 1].unsqueeze(1),
            top5_coords[:, :, 0], top5_coords[:, :, 1],
        )  # (B, 5)
        top5_dists.append(top5_dist_batch.mean(dim=1).cpu())  # (B,)

        # ---- Gated 模式: 收集 geo_gate 和 scaled_penalty 统计 ----
        if is_gated:
            info = model.gated_geobias.last_info
            if info:
                geo_gate_batch = info["geo_gate"].cpu()  # (B,)
                all_geo_gates.append(geo_gate_batch)

                sp = info["scaled_penalty"].cpu()  # (B, V)
                all_scaled_penalty_means.append(sp.mean(dim=1))  # (B,)
                all_scaled_penalty_maxs.append(sp.max(dim=1).values)  # (B,)
                all_scaled_penalty_mins.append(sp.min(dim=1).values)  # (B,)

                # 按 target 距离分组
                target_dist_cpu = target_dist.cpu()
                short_mask = target_dist_cpu <= DIST_THRESHOLD_KM
                long_mask = target_dist_cpu > DIST_THRESHOLD_KM

                if short_mask.any():
                    short_target_gates.append(geo_gate_batch[short_mask])
                if long_mask.any():
                    long_target_gates.append(geo_gate_batch[long_mask])

    # ---- 汇总统计 ----
    result = {
        "geo_gamma": round(gamma_val, 4),
        "avg_target_dist_km": round(float(torch.cat(target_dists).mean().item()), 2),
        "avg_top1_dist_km": round(float(torch.cat(top1_dists).mean().item()), 2),
        "avg_top5_dist_km": round(float(torch.cat(top5_dists).mean().item()), 2),
    }

    if is_gated and all_geo_gates:
        all_gates = torch.cat(all_geo_gates)  # (total_samples,)
        all_sp_mean = torch.cat(all_scaled_penalty_means)
        all_sp_max = torch.cat(all_scaled_penalty_maxs)
        all_sp_min = torch.cat(all_scaled_penalty_mins)

        result.update({
            "geo_gate_min": round(float(all_gates.min().item()), 4),
            "geo_gate_mean": round(float(all_gates.mean().item()), 4),
            "geo_gate_max": round(float(all_gates.max().item()), 4),
            "scaled_penalty_min": round(float(all_sp_min.min().item()), 4),
            "scaled_penalty_mean": round(float(all_sp_mean.mean().item()), 4),
            "scaled_penalty_max": round(float(all_sp_max.max().item()), 4),
        })

        if short_target_gates:
            short_all = torch.cat(short_target_gates)
            result["short_target_dist_geo_gate_mean"] = round(
                float(short_all.mean().item()), 4
            )
        if long_target_gates:
            long_all = torch.cat(long_target_gates)
            result["long_target_dist_geo_gate_mean"] = round(
                float(long_all.mean().item()), 4
            )

    return result


@torch.no_grad()
def collect_distance_scoring_stats(
    model,
    dataloader,
    device: torch.device,
) -> Dict[str, float]:
    """
    在给定 DataLoader 上收集 T7 DistanceFeatureScoring 的统计信息。

    统计项：
        - distance_emb_norm: 距离分桶嵌入的 L2 范数
        - distance_emb_mean: 距离分桶嵌入的均值
        - cat_transition_emb_norm: 类别转移嵌入的 L2 范数
        - cat_transition_emb_mean: 类别转移嵌入的均值
        - avg_target_dist_km: 平均目标距离
        - avg_top1_dist_km: 平均 Top-1 预测距离
        - avg_top5_dist_km: 平均 Top-5 预测距离

    Args:
        model: 已训练的模型（eval 模式，scoring_type="distance_feature"）
        dataloader: 评估用的 DataLoader
        device: torch 设备

    Returns:
        距离打分统计字典。
    """
    if model.scoring_type != "distance_feature":
        return {}

    model.eval()
    ds = model.distance_scoring

    # 嵌入统计（直接从权重计算）
    distance_emb_weight = ds.distance_emb.weight.data  # (num_buckets, distance_dim)
    cat_transition_emb_weight = ds.cat_transition_emb.weight.data  # (num_cats^2, transition_dim)

    # 距离统计
    target_dists = []
    top1_dists = []
    top5_dists = []

    for batch in dataloader:
        batch = [t.to(device) for t in batch]
        bv, bc = batch[0], batch[1]
        bl = batch[-1]

        if len(batch) == 4:
            bt = batch[2]
            logits = model(bv, bc, bt)
        else:
            logits = model(bv, bc)

        # last_poi → target_poi 距离
        B = bv.size(0)
        last_venues = bv[:, -1]
        vc = model.venue_coords

        last_coords = vc[last_venues]
        target_coords = vc[bl]

        target_dist = _haversine_distance(
            last_coords[:, 0], last_coords[:, 1],
            target_coords[:, 0], target_coords[:, 1],
        )
        target_dists.append(target_dist.cpu())

        # last_poi → Top-K 预测距离
        _, topk = torch.topk(logits, k=5, dim=1)
        top1_venues = topk[:, 0]
        top5_venues = topk

        top1_coords = vc[top1_venues]
        top1_dist = _haversine_distance(
            last_coords[:, 0], last_coords[:, 1],
            top1_coords[:, 0], top1_coords[:, 1],
        )
        top1_dists.append(top1_dist.cpu())

        top5_coords = vc[top5_venues]
        top5_dist_batch = _haversine_distance(
            last_coords[:, 0].unsqueeze(1), last_coords[:, 1].unsqueeze(1),
            top5_coords[:, :, 0], top5_coords[:, :, 1],
        )
        top5_dists.append(top5_dist_batch.mean(dim=1).cpu())

    return {
        "distance_emb_norm": round(float(distance_emb_weight.norm(p=2).item()), 4),
        "distance_emb_mean": round(float(distance_emb_weight.mean().item()), 4),
        "cat_transition_emb_norm": round(float(cat_transition_emb_weight.norm(p=2).item()), 4),
        "cat_transition_emb_mean": round(float(cat_transition_emb_weight.mean().item()), 4),
        "avg_target_dist_km": round(float(torch.cat(target_dists).mean().item()), 2),
        "avg_top1_dist_km": round(float(torch.cat(top1_dists).mean().item()), 2),
        "avg_top5_dist_km": round(float(torch.cat(top5_dists).mean().item()), 2),
    }


@torch.no_grad()
def collect_residual_distance_stats(
    model,
    dataloader,
    device: torch.device,
) -> Dict[str, object]:
    """
    在给定 DataLoader 上收集 T7b ResidualDistanceScoring 的统计信息。

    统计项：
        - alpha: 距离残差强度（sigmoid(raw_alpha)）
        - beta: 类别转移残差强度（sigmoid(raw_beta)）
        - distance_bucket_table: 各距离桶的 bias 值
        - transition_bias_mean/std/min/max: 类别转移偏置的统计
        - avg_target_dist_km / avg_top1_dist_km / avg_top5_dist_km: 距离统计

    Args:
        model: 已训练的模型（eval 模式，scoring_type="residual_distance"）
        dataloader: 评估用的 DataLoader
        device: torch 设备

    Returns:
        残差距离打分统计字典。
    """
    if model.scoring_type != "residual_distance":
        return {}

    model.eval()
    rs = model.residual_scoring

    # ---- 距离分桶偏置值（直接从权重读取） ----
    distance_bias_values = rs.distance_bias.weight.data.squeeze(-1).cpu()  # (num_buckets,)
    bucket_names = [
        "[0,1) km", "[1,5) km", "[5,10) km",
        "[10,30) km", "[30,80) km", "[80,+inf) km",
    ]
    distance_bucket_table = {
        bucket_names[i]: round(float(distance_bias_values[i]), 4)
        for i in range(len(bucket_names))
    }

    # ---- 类别转移偏置统计（直接从权重读取） ----
    transition_bias_weight = rs.transition_bias.weight.data.squeeze(-1).cpu()  # (num_cats²,)

    # ---- 距离统计（通过 forward 收集） ----
    target_dists = []
    top1_dists = []
    top5_dists = []

    for batch in dataloader:
        batch = [t.to(device) for t in batch]
        bv, bc = batch[0], batch[1]
        bl = batch[-1]

        if len(batch) == 4:
            bt = batch[2]
            logits = model(bv, bc, bt)
        else:
            logits = model(bv, bc)

        B = bv.size(0)
        last_venues = bv[:, -1]
        vc = model.venue_coords

        last_coords = vc[last_venues]
        target_coords = vc[bl]
        target_dist = _haversine_distance(
            last_coords[:, 0], last_coords[:, 1],
            target_coords[:, 0], target_coords[:, 1],
        )
        target_dists.append(target_dist.cpu())

        _, topk = torch.topk(logits, k=5, dim=1)
        top1_venues = topk[:, 0]
        top5_venues = topk

        top1_coords = vc[top1_venues]
        top1_dist = _haversine_distance(
            last_coords[:, 0], last_coords[:, 1],
            top1_coords[:, 0], top1_coords[:, 1],
        )
        top1_dists.append(top1_dist.cpu())

        top5_coords = vc[top5_venues]
        top5_dist_batch = _haversine_distance(
            last_coords[:, 0].unsqueeze(1), last_coords[:, 1].unsqueeze(1),
            top5_coords[:, :, 0], top5_coords[:, :, 1],
        )
        top5_dists.append(top5_dist_batch.mean(dim=1).cpu())

    # ---- Alpha/Beta: 从 last_info 获取 ----
    last_info = rs.last_info
    alpha_val = last_info.get("alpha", 0.0) if last_info else 0.0
    beta_val = last_info.get("beta", 0.0) if last_info else 0.0

    return {
        "alpha": round(float(alpha_val), 4),
        "beta": round(float(beta_val), 4),
        "distance_bucket_table": distance_bucket_table,
        "transition_bias_mean": round(float(transition_bias_weight.mean().item()), 4),
        "transition_bias_std": round(float(transition_bias_weight.std().item()), 4),
        "transition_bias_min": round(float(transition_bias_weight.min().item()), 4),
        "transition_bias_max": round(float(transition_bias_weight.max().item()), 4),
        "avg_target_dist_km": round(float(torch.cat(target_dists).mean().item()), 2),
        "avg_top1_dist_km": round(float(torch.cat(top1_dists).mean().item()), 2),
        "avg_top5_dist_km": round(float(torch.cat(top5_dists).mean().item()), 2),
    }


def _haversine_distance(
    lat1: torch.Tensor, lon1: torch.Tensor,
    lat2: torch.Tensor, lon2: torch.Tensor,
) -> torch.Tensor:
    """
    批量 Haversine 距离计算（km）。

    与 _compute_distance_matrix 不同，此函数接受任意广播形状的坐标张量，
    适用于 point-to-point 距离计算（如 last_poi → target_poi），
    而 _compute_distance_matrix 专门优化了 (B,2) vs (V,2) 的矩阵计算场景。

    Args:
        lat1, lon1: 第一组点的纬度/经度（度）
        lat2, lon2: 第二组点的纬度/经度（度）
        形状可广播。

    Returns:
        distance_km: 与输入广播后同形状的距离（km）
    """
    lat1_rad = torch.deg2rad(lat1)
    lon1_rad = torch.deg2rad(lon1)
    lat2_rad = torch.deg2rad(lat2)
    lon2_rad = torch.deg2rad(lon2)

    dlat = lat2_rad - lat1_rad
    dlon = lon2_rad - lon1_rad

    a = (
        torch.sin(dlat / 2.0) ** 2
        + torch.cos(lat1_rad) * torch.cos(lat2_rad) * torch.sin(dlon / 2.0) ** 2
    )
    a = a.clamp(min=0.0, max=1.0 - 1e-7)
    c = 2.0 * torch.atan2(torch.sqrt(a), torch.sqrt(1.0 - a))
    return 6371.0 * c


# ==============================================================================
# T8: Long-term Preference Encoder + Long-Short Fusion Gate
# ==============================================================================

class LongPreferenceEncoder(nn.Module):
    """
    将用户历史 POI 访问序列池化为长期偏好向量 h_long。

    支持两种池化模式：
        - "attention": 可学习注意力加权（默认）
        - "mean": 简单平均池化

    冷启动用户（零历史长度）输出零向量。

    Args:
        venue_emb_dim: POI ID 嵌入维度（来自 venue_emb 层）
        d_model: 输出维度（需与 Transformer d_model 一致）
        pool_type: "attention" 或 "mean"
        dropout: 注意力 MLP 的 dropout 比率
    """

    def __init__(self, venue_emb_dim: int = 64, d_model: int = 128,
                 pool_type: str = "attention", dropout: float = 0.1):
        super().__init__()
        if pool_type not in ("attention", "mean"):
            raise ValueError(f"pool_type 必须是 'attention' 或 'mean'，收到 '{pool_type}'")
        self.pool_type = pool_type

        # 投影 venue_emb (64-dim) → d_model (128-dim)
        self.proj = nn.Linear(venue_emb_dim, d_model)
        self.norm = nn.LayerNorm(d_model)

        if pool_type == "attention":
            self.attn = nn.Sequential(
                nn.Linear(d_model, d_model // 2),
                nn.Tanh(),
                nn.Linear(d_model // 2, 1),
            )

    def forward(self, venue_emb_weight: torch.Tensor,
                user_history_indices: torch.Tensor,
                user_history_lengths: torch.Tensor) -> torch.Tensor:
        """
        Args:
            venue_emb_weight: (num_venues, venue_emb_dim) — POI 嵌入表
            user_history_indices: (B, max_hist_len) — POI 索引，0=PAD
            user_history_lengths: (B,) — 每个用户的有效历史长度（可为 0）

        Returns:
            h_long: (B, d_model) — 冷用户为零向量
        """
        B, L = user_history_indices.shape
        device = user_history_indices.device

        # ---- Step 1: POI ID → 嵌入向量查表 ----
        # padding_idx=0 保证 PAD token (id=0) 的输出为零向量
        hist_emb = F.embedding(user_history_indices, venue_emb_weight, padding_idx=0)
        # (B, L, venue_emb_dim)

        # ---- Step 2: 投影到统一维度 d_model ----
        hist_emb = self.proj(hist_emb)  # (B, L, d_model)

        # ---- Step 3: 构造有效位置掩码 ----
        # 每个用户的实际历史长度可能不同（包括冷用户长度为 0），
        # 通过 mask 标记哪些位置是有效的签到记录
        has_history = user_history_lengths > 0  # (B,)
        positions = torch.arange(L, device=device).unsqueeze(0)  # (1, L)
        mask = positions < user_history_lengths.unsqueeze(1)  # (B, L)

        # ---- Step 4: 序列池化 → 固定维度向量 ----
        if self.pool_type == "mean":
            # 平均池化：对所有有效位置的嵌入取平均，简单高效
            hist_masked = hist_emb * mask.unsqueeze(-1).float()
            pooled = hist_masked.sum(dim=1) / user_history_lengths.unsqueeze(-1).float().clamp(min=1)
        else:  # attention
            # 注意力池化：通过可学习 MLP 计算每个历史 POI 的重要性权重，
            # 然后加权求和。较重要的历史 POI（如最近常去的店）获得更高权重。
            scores = self.attn(hist_emb).squeeze(-1)  # (B, L)
            scores = scores.masked_fill(~mask, float('-inf'))  # 屏蔽 PAD 位置
            attn_weights = F.softmax(scores, dim=-1)  # (B, L)
            # 处理冷用户：如果所有位置都被 masked，softmax 输入全为 -inf 会产生 NaN
            attn_weights = torch.nan_to_num(attn_weights, nan=0.0)
            pooled = torch.bmm(attn_weights.unsqueeze(1), hist_emb).squeeze(1)  # (B, d_model)

        # ---- Step 5: 处理冷启动用户（无历史记录） ----
        # has_history 为 False 的用户，其 pooled 输出强制置零，
        # 后续 LongShortFusionGate 检测到 h_long 为零向量时会主要依赖 h_short
        pooled = pooled * has_history.unsqueeze(-1).float()

        return self.norm(pooled)


class LongShortFusionGate(nn.Module):
    """
    可学习门控，自适应融合短期兴趣和长期偏好。

    核心公式：
        gate    = sigmoid(MLP([h_short || h_long]))
        h_final = gate * h_short + (1 - gate) * h_long

    设计理由：用户的最终推荐需求是短期兴趣和长期偏好的动态组合。
    - gate → 1：用户当前行为与历史模式一致，短期信号可靠，主要依赖 h_short
    - gate → 0：用户近期行为偏离长期偏好（如出差时访问不熟悉的区域），
      应更多依赖长期偏好提供稳健推荐
    - 对于冷用户（h_long ≈ 0），gate 会自然趋近 1，保证推荐不退化

    Args:
        d_model: h_short 和 h_long 的维度
        gate_hidden: Gate MLP 隐藏层大小
        dropout: dropout 比率
    """

    def __init__(self, d_model: int = 128, gate_hidden: int = 64, dropout: float = 0.1):
        super().__init__()
        self.mlp = nn.Sequential(
            nn.Linear(2 * d_model, gate_hidden),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(gate_hidden, 1),
            nn.Sigmoid(),
        )
        # 初始化策略：最后一层小权重 + 零偏置，使 gate 初始 ≈ 0.5，
        # 即训练初期平等对待短期和长期信息，避免过早偏向某一方
        last_linear = self.mlp[-2]  # nn.Linear(gate_hidden, 1) — Sequential 倒数第二个是最后的 Linear
        nn.init.normal_(last_linear.weight, std=0.001)
        nn.init.zeros_(last_linear.bias)

    def forward(self, h_short: torch.Tensor, h_long: torch.Tensor
                ) -> Tuple[torch.Tensor, torch.Tensor]:
        """
        Args:
            h_short: (B, d_model) — 短期兴趣表示（Transformer 编码的近期签到序列）
            h_long:  (B, d_model) — 长期偏好表示（用户全量历史的池化向量）

        Returns:
            h_final: (B, d_model) — 融合后的表示
            gate:    (B, 1) — 门控值（→1 = 依赖短期兴趣，→0 = 依赖长期偏好）
        """
        # 拼接短期和长期表示，让 MLP 感知两者的交互信息
        combined = torch.cat([h_short, h_long], dim=-1)  # (B, 2*d_model)
        gate = self.mlp(combined)                         # (B, 1)
        # 凸组合：保证 h_final 始终在 h_short 和 h_long 的凸包内
        h_final = gate * h_short + (1.0 - gate) * h_long
        return h_final, gate


@torch.no_grad()
def collect_long_short_stats(
    model,
    dataloader,
    device: torch.device,
) -> Dict[str, object]:
    """
    在 DataLoader 上收集 T8 long-short fusion 统计信息。

    统计项：
        gate_min/mean/max: 门控值统计
        h_short_norm_mean: 短期表示的平均 L2 范数
        h_long_norm_mean: 长期表示的平均 L2 范数
        h_long_norm_mean_warm: 非冷用户 h_long 的平均 L2 范数
        history_len_min/mean/median/max: 用户历史长度统计
        n_cold_users, n_total, cold_user_ratio: 冷用户计数
    """
    if not getattr(model, 'use_long_pref', False):
        return {}

    model.eval()
    use_time = getattr(model, 'use_time', False)

    all_gates = []
    h_short_norms = []
    h_long_norms = []
    history_lengths = []

    for batch in dataloader:
        batch = [t.to(device) for t in batch]
        bv, bc = batch[0], batch[1]

        # 根据模型配置从 batch 中动态解包字段
        # batch 结构: [v_seq, c_seq, (t_seq), u_seq, label]
        idx = 2
        kwargs = {}
        if use_time:
            kwargs['t_seq'] = batch[idx]
            idx += 1
        if model.use_long_pref:
            kwargs['u_seq'] = batch[idx]
            idx += 1

        _, gate = model(bv, bc, return_gate=True, **kwargs)
        all_gates.append(gate.cpu())

        info = model.long_short_info
        if info:
            h_short_norms.append(info['h_short'].norm(p=2, dim=-1).cpu())
            h_long_norms.append(info['h_long'].norm(p=2, dim=-1).cpu())

        # 用户索引在 batch 中的位置取决于是否包含时间特征
        bu_idx = 3 if use_time else 2
        hist_lens = model.user_history_lengths[batch[bu_idx]].cpu()
        history_lengths.append(hist_lens)

    all_gates = torch.cat(all_gates).squeeze(-1)
    h_short_norms = torch.cat(h_short_norms) if h_short_norms else None
    h_long_norms = torch.cat(h_long_norms) if h_long_norms else None
    history_lengths = torch.cat(history_lengths)

    # 区分冷用户（零历史长度）和温用户，分别统计
    cold = (history_lengths == 0)
    n_cold = cold.sum().item()
    n_total = len(history_lengths)

    result = {
        'gate_min': round(float(all_gates.min()), 4),
        'gate_mean': round(float(all_gates.mean()), 4),
        'gate_max': round(float(all_gates.max()), 4),
        'h_short_norm_mean': round(float(h_short_norms.mean()), 4) if h_short_norms is not None else None,
        'h_long_norm_mean': round(float(h_long_norms.mean()), 4) if h_long_norms is not None else None,
        'h_long_norm_mean_warm': round(float(h_long_norms[~cold].mean()), 4) if h_long_norms is not None and (~cold).any() else 0.0,
        'history_len_min': int(history_lengths.min().item()),
        'history_len_mean': round(float(history_lengths.float().mean().item()), 1),
        'history_len_median': round(float(history_lengths.float().median().item()), 1),
        'history_len_max': int(history_lengths.max().item()),
        'n_cold_users': n_cold,
        'n_total': n_total,
        'cold_user_ratio': round(n_cold / max(n_total, 1), 4),
    }
    return result


@torch.no_grad()
def collect_causal_long_short_stats(
    model,
    dataloader,
    device: torch.device,
) -> Dict[str, object]:
    """
    在 DataLoader 上收集 T9 Causal Long-Short fusion 统计信息。

    统计项：
        gate_min/mean/max: 门控值统计
        h_short_norm_mean: 短期表示的平均 L2 范数
        h_long_norm_mean: 长期表示的平均 L2 范数
        h_long_norm_mean_warm: 非冷用户 h_long 的平均 L2 范数
        history_len_min/mean/median/max: 因果历史长度统计
        n_zero_history, zero_history_ratio: 零历史样本比例
    """
    if not getattr(model, 'use_causal_long_pref', False):
        return {}

    model.eval()
    use_time = getattr(model, 'use_time', False)

    all_gates = []
    h_short_norms = []
    h_long_norms = []
    history_lengths = []

    for batch in dataloader:
        batch = [t.to(device) for t in batch]
        bv, bc = batch[0], batch[1]
        bl = batch[-1]

        # 根据模型配置从 batch 中动态解包字段
        # batch 结构: [v_seq, c_seq, (t_seq), causal_history, causal_mask, label]
        idx = 2
        kwargs = {}
        if use_time:
            kwargs['t_seq'] = batch[idx]
            idx += 1
        if model.use_causal_long_pref:
            kwargs['causal_history'] = batch[idx]
            kwargs['causal_mask'] = batch[idx + 1]
            idx += 2

        _, gate = model(bv, bc, return_gate=True, **kwargs)
        all_gates.append(gate.cpu())

        info = model.long_short_info
        if info:
            h_short_norms.append(info['h_short'].norm(p=2, dim=-1).cpu())
            h_long_norms.append(info['h_long'].norm(p=2, dim=-1).cpu())

        # causal_history 在 batch 中的索引位置取决于是否包含时间特征
        ch_idx = 3 if use_time else 2
        causal_mask_batch = batch[ch_idx + 1]  # causal_mask
        hist_lens = causal_mask_batch.sum(dim=1).cpu()  # (B,)
        history_lengths.append(hist_lens)

    all_gates = torch.cat(all_gates).squeeze(-1)
    h_short_norms = torch.cat(h_short_norms) if h_short_norms else None
    h_long_norms = torch.cat(h_long_norms) if h_long_norms else None
    history_lengths = torch.cat(history_lengths)

    zero_hist = (history_lengths == 0)
    n_zero = zero_hist.sum().item()
    n_total = len(history_lengths)

    result = {
        'gate_min': round(float(all_gates.min()), 4),
        'gate_mean': round(float(all_gates.mean()), 4),
        'gate_max': round(float(all_gates.max()), 4),
        'h_short_norm_mean': round(float(h_short_norms.mean()), 4) if h_short_norms is not None else None,
        'h_long_norm_mean': round(float(h_long_norms.mean()), 4) if h_long_norms is not None else None,
        'h_long_norm_mean_warm': round(float(h_long_norms[~zero_hist].mean()), 4) if h_long_norms is not None and (~zero_hist).any() else 0.0,
        'history_len_min': int(history_lengths.min().item()),
        'history_len_mean': round(float(history_lengths.float().mean().item()), 1),
        'history_len_median': round(float(history_lengths.float().median().item()), 1),
        'history_len_max': int(history_lengths.max().item()),
        'n_zero_history': n_zero,
        'n_total': n_total,
        'zero_history_ratio': round(n_zero / max(n_total, 1), 4),
    }
    return result
