"""
Dynamic Fusion Gate：对多源特征做逐 token 的动态加权融合。

与 Static Fusion (concat + Linear) 不同，Dynamic Fusion 为每个
时间步、每个样本学习独立的特征源权重，使模型能够根据上下文
自适应地决定"此时该相信 ID、类别、行为语义还是文本语义"。

使用方式：
    gate = DynamicFusionGate(
        feature_dims=[64, 16, 64, 64],          # 各特征的原始维度
        feature_names=["id", "cat", "beh", "text"],  # 可读名称（可选）
        fusion_dim=128,                          # 融合后的统一维度
        gate_hidden=64,                          # Gate MLP 隐藏层大小
    )
    features = [id_emb, cat_emb, beh_emb, text_emb]  # 每个 (B, L, D_i)
    fused, gate_weights = gate(features, return_gate=True)
    # fused:       (B, L, 128)
    # gate_weights: (B, L, 4) — 每个特征源的 softmax 权重
"""

import torch
import torch.nn as nn
import torch.nn.functional as F
from typing import List, Optional, Tuple, Dict


class DynamicFusionGate(nn.Module):
    """
    逐 token 的动态多源特征加权融合模块。

    计算流程：
        1. 对每个特征源做独立线性投影 → 统一到 fusion_dim
        2. 将投影后的特征拼接作为 Gate MLP 的输入
        3. Gate MLP 输出 M 个 logits → softmax 得到权重
        4. 加权求和得到最终融合表示

    Args:
        feature_dims: 每个特征源的原始维度列表，例如 [64, 16, 64, 64]
        feature_names: 可读的特征名称列表，长度与 feature_dims 一致（可选）
        fusion_dim: 投影后的统一维度（默认 128，与 d_model 一致）
        gate_hidden: Gate MLP 的隐藏层大小（默认 64）
        dropout: Gate MLP 的 Dropout 比率（默认 0.1）
    """

    def __init__(
        self,
        feature_dims: List[int],
        feature_names: Optional[List[str]] = None,
        fusion_dim: int = 128,
        gate_hidden: int = 64,
        dropout: float = 0.1,
    ):
        super().__init__()

        self.num_features = len(feature_dims)
        self.fusion_dim = fusion_dim
        self.feature_names = (
            feature_names
            if feature_names is not None
            else [f"feat_{i}" for i in range(self.num_features)]
        )

        # ---- 各特征的独立投影层 ----
        # 每个特征源有独立的语义空间，需要单独的投影矩阵映射到统一的 fusion_dim，
        # 这样 Gate MLP 才能在统一的语义空间里比较各特征源的重要性。
        # 将每个特征从原始维度投影到统一的 fusion_dim
        self.projections = nn.ModuleList([
            nn.Linear(dim, fusion_dim)
            for dim in feature_dims
        ])

        # ---- Gate MLP ----
        # 核心设计：将所有投影后的特征拼接起来，通过一个轻量 MLP 为每个 token 位置
        # 输出 M 个 logit（M = 特征源数量），经 softmax 得到自适应融合权重。
        # 这样模型可以根据当前上下文决定"此处应该相信 ID 匹配还是行为语义相似"。
        # 输入：拼接所有投影特征 → (B, L, num_features * fusion_dim)
        # 输出：每个特征源的 logit → (B, L, num_features)
        gate_input_dim = self.num_features * fusion_dim
        self.gate_mlp = nn.Sequential(
            nn.Linear(gate_input_dim, gate_hidden),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(gate_hidden, self.num_features),
        )

        # 初始化策略：让 gate 初始时接近均匀权重，避免训练早期某个特征源被过度信任，
        # 确保模型从"平等对待所有特征"的起点开始学习
        self._init_gate_weights()

    def _init_gate_weights(self):
        """
        将 Gate MLP 的最后一层初始化为接近零，使初始权重接近均匀分布。

        设计理由：若 gate 随机初始化，训练初期某个特征源可能获得过高的 softmax 权重，
        导致模型过早就偏向单一特征，抑制其他特征的梯度回流。零初始化让 softmax 输出
        接近 uniform（各特征权重 ≈ 1/M），保证所有特征在训练早期都有平等的学习机会。

        投影层则使用标准 Xavier 初始化，确保前向传播时各特征投影方差稳定。
        """
        last_layer = self.gate_mlp[-1]  # nn.Linear(gate_hidden, num_features)
        nn.init.zeros_(last_layer.weight)
        nn.init.zeros_(last_layer.bias)

        # 投影层使用标准 Xavier 初始化，保证前向方差稳定
        for proj in self.projections:
            nn.init.xavier_uniform_(proj.weight)
            nn.init.zeros_(proj.bias)

    def forward(
        self,
        feature_list: List[torch.Tensor],
        return_gate: bool = False,
    ) -> Tuple[torch.Tensor, Optional[torch.Tensor]]:
        """
        Args:
            feature_list: 特征张量列表，每个张量形状为 (B, L, D_i)，
                          D_i 可以不同。
            return_gate: 若为 True，同时返回门控权重。

        Returns:
            fused: (B, L, fusion_dim) 融合后的表示
            gate_weights: (B, L, num_features) 门控权重（若 return_gate=True）
        """
        if len(feature_list) != self.num_features:
            raise ValueError(
                f"DynamicFusionGate 期望 {self.num_features} 个特征，"
                f"但收到 {len(feature_list)} 个。"
            )

        B, L = feature_list[0].shape[:2]

        # ---- Step 1: 各自投影到统一维度 ----
        # 每个特征源通过独立的投影矩阵映射到 fusion_dim，
        # 使不同语义空间的特征可以在同一维度下进行加权融合
        projected = []
        for i, feat in enumerate(feature_list):
            proj = self.projections[i](feat)  # (B, L, fusion_dim)
            projected.append(proj)

        # ---- Step 2: 计算自适应 Gate 权重 ----
        # 将所有投影后的特征拼接，通过 Gate MLP 为每个 token 位置
        # 输出 M 个 logit，经 softmax 得到归一化权重。
        # 关键：gate 是 position-wise 的，即序列中不同位置的 token
        # 可以有不同的特征源偏好（例如：POI 名称匹配靠 ID，语义相关靠 text）
        gate_input = torch.cat(projected, dim=-1)  # (B, L, M * fusion_dim)
        gate_logits = self.gate_mlp(gate_input)     # (B, L, M)
        gate_weights = F.softmax(gate_logits, dim=-1)  # (B, L, M)

        # ---- Step 3: 加权融合 ----
        # 将 M 个投影特征堆叠为 (B, L, M, fusion_dim)，
        # 与扩展后的 gate 权重逐元素相乘，沿特征源维度求和，
        # 得到最终的融合表示。每个 token 的融合结果 = Σ(gate_i * proj_i)
        stacked = torch.stack(projected, dim=2)
        gate_expanded = gate_weights.unsqueeze(-1)  # (B, L, M, 1)
        fused = (stacked * gate_expanded).sum(dim=2)  # (B, L, fusion_dim)

        if return_gate:
            return fused, gate_weights
        return fused

    def extra_repr(self) -> str:
        return (
            f"num_features={self.num_features}, "
            f"fusion_dim={self.fusion_dim}, "
            f"feature_names={self.feature_names}"
        )


def compute_gate_stats(
    gate_weights_list: List[torch.Tensor],
    feature_names: List[str],
) -> Dict[str, float]:
    """
    从多个 batch 的 gate 权重中计算平均统计，用于可解释性分析。

    在测试集全量数据上汇总 gate 权重的全局均值，回答以下问题：
    - 模型整体上最依赖哪个特征源？（如 ID 匹配 vs 行为语义 vs 文本语义）
    - 不同特征源的重要性比例如何？
    - 训练后 gate 是否从 uniform 收敛到了有意义的分布？

    这是 Dynamic Fusion Gate 模型最核心的可解释性工具：
    如果某个特征的 gate 权重接近 0，说明该特征对模型决策贡献极小；
    如果 ID 的 gate 权重远高于语义特征，说明模型主要靠"记住 POI 热度"做推荐，
    而非真正理解语义相似性。

    Args:
        gate_weights_list: 每个 batch 的 gate 权重列表，
                           每个形状为 (B, L, M) 的 torch.Tensor
        feature_names: 特征名称列表，长度为 M

    Returns:
        {feature_name: average_weight} 字典（已归一化确保和为 1）
    """
    if not gate_weights_list:
        return {}

    # 将所有 batch 的 gate 权重沿 token 维度拼接，计算全局平均
    # reshape(-1, M) 将 (B, L, M) 展平为 (B*L, M)，即所有 token 位置的门控权重
    all_gates = torch.cat(
        [gw.reshape(-1, gw.size(-1)) for gw in gate_weights_list],
        dim=0,
    )  # (total_tokens, M)

    # 注意：padding 位置的嵌入为零向量，gate 输入全零时 softmax 输出接近 uniform，
    # 因此保留所有 token 不会影响各特征源的相对排序，仅可能略微拉平分布。
    mean_weights = all_gates.mean(dim=0)  # (M,)

    # 确保归一化（理论上已 softmax，但取平均后可能偏离 1）
    mean_weights = mean_weights / (mean_weights.sum() + 1e-8)

    return {
        name: round(float(mean_weights[i]), 4)
        for i, name in enumerate(feature_names)
    }
