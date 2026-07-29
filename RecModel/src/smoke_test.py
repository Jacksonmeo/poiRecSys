"""Fast, offline integrity test for data, model and reranking artifacts."""

from __future__ import annotations

import pickle
from pathlib import Path

import numpy as np
import torch

import config as cfg
from src.data.preprocess import (
    build_sequences,
    build_trajectories_24h,
    build_vocabularies,
    filter_low_frequency,
    load_raw_data,
    time_ordered_split,
)
from src.models.transformer import TransformerPOIModel
from src.t10e2 import compute_frequency_revisit


ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    """离线完整性测试：验证数据管线、模型 checkpoint 和前向传播、转移记忆文件。

    测试流程分为四个阶段：
    1. 数据加载与预处理：确保原始数据可读、低频过滤和轨迹构建正常
    2. Checkpoint 加载与词表校验：验证 checkpoint 和预处理产出的词表大小匹配
    3. 模型前向传播验证：用构造的样本输入跑一次 forward，检查输出形状和数值有效性
    4. 转移记忆验证：加载 POI transition memory，检查非空，运行 frequency_revisit 计算
    若任一步失败则抛出异常，所有通过则打印 PASS 和关键统计信息。
    """
    # === 阶段1: 数据加载与预处理 ===
    # 检查数据文件、checkpoint、memory 文件是否存在
    data_path = Path(cfg.dataset_file("TKY"))
    checkpoint_path = Path(cfg.CHECKPOINT_DIR) / "T9_CausalMemoryFusion_best.pth"
    memory_path = Path(cfg.SAVE_DIR) / "T10" / "t10_poi_transition_top100.pkl"
    for path in (data_path, checkpoint_path, memory_path):
        if not path.is_file():
            raise FileNotFoundError(path)

    # 完整数据管线：加载 → 低频过滤 → 24h轨迹构建 → 时间序划分 → 序列化 → 词表
    raw = load_raw_data(str(data_path))
    filtered = filter_low_frequency(raw, cfg.MIN_POI_CHECKINS, cfg.MIN_USER_CHECKINS)
    trajectories = build_trajectories_24h(filtered, include_timestamps=True)
    trajectories.sort(key=lambda item: item["start_time"])
    train_traj, val_traj, test_traj = time_ordered_split(
        trajectories, cfg.TRAIN_RATIO, cfg.VAL_RATIO
    )
    train_raw = build_sequences(train_traj, seq_len=cfg.SEQ_LEN)
    venue_to_idx, category_to_idx = build_vocabularies(train_raw)

    # === 阶段2: Checkpoint 加载与词表校验 ===
    # 从 checkpoint 中推断词表大小，与预处理产出的词表进行一致性校验
    state = torch.load(checkpoint_path, map_location="cpu", weights_only=True)
    num_venues = state["venue_emb.weight"].shape[0]
    num_categories = state["cat_emb.weight"].shape[0]
    if (len(venue_to_idx), len(category_to_idx)) != (num_venues, num_categories):
        raise AssertionError("Preprocessing vocabulary does not match the bundled checkpoint")

    # === 阶段3: 模型前向传播验证 ===
    # 用最小配置实例化模型并加载权重，构造伪造样本序列进行前向传播
    model = TransformerPOIModel(
        num_venues=num_venues, num_cats=num_categories, use_category=True,
        venue_emb_dim=64, cat_emb_dim=16, behav_dim=128, behav_proj_dim=64,
        text_dim=384, text_proj_dim=64, d_model=128, n_heads=2, n_layers=2,
        ff_dim=256, dropout=0.1, fc_dropout=0.3,
        behav_matrix=np.zeros((num_venues, 128), dtype=np.float32),
        text_matrix=np.zeros((num_venues, 384), dtype=np.float32),
        fusion_type="dynamic", gate_hidden=64, use_causal_long_pref=True,
        causal_pref_type="attention",
    )
    model.load_state_dict(state, strict=True)
    model.eval()
    # 构造样本输入：10个 venue 序列 + causal_history + mask
    with torch.no_grad():
        sample_venues = torch.tensor([[1, 2, 3, 4, 5, 6, 7, 8, 9, 10]])
        sample_categories = torch.ones_like(sample_venues)
        sample_history = torch.tensor([[0, 0, 0, 0, 0, 1, 2, 3, 4, 5]])
        sample_mask = sample_history.ne(0)
        logits = model(
            sample_venues, sample_categories,
            causal_history=sample_history, causal_mask=sample_mask,
        )
    # 校验输出形状和数值有效性
    if logits.shape != (1, num_venues) or not torch.isfinite(logits).all():
        raise AssertionError("Checkpoint model forward pass failed")

    # === 阶段4: 转移记忆验证 ===
    # 加载 POI transition memory 并验证非空
    with memory_path.open("rb") as handle:
        transition_memory = pickle.load(handle)
    if not transition_memory:
        raise AssertionError("Transition memory is empty")

    # 验证 frequency_revisit 计算逻辑：给定历史序列和候选集，检查是否标记为 visited
    history = torch.tensor([[0, 0, 3, 3, 7], [0, 1, 2, 3, 4]])
    mask = history.ne(0)
    candidates = torch.tensor([[3, 7, 9], [4, 8, 1]])
    scores, visited = compute_frequency_revisit(history, mask, candidates)
    assert visited.tolist() == [[True, True, False], [True, False, True]]
    assert scores.shape == candidates.shape

    print("T10e-2 standalone smoke test: PASS")
    print(f"  raw rows={len(raw):,}, filtered rows={len(filtered):,}")
    print(f"  trajectories train/val/test={len(train_traj):,}/{len(val_traj):,}/{len(test_traj):,}")
    print(f"  vocab POI/categories={num_venues:,}/{num_categories:,}")
    print(f"  checkpoint tensors={len(state)}, transition sources={len(transition_memory):,}")
    print(f"  model forward logits={tuple(logits.shape)}")


if __name__ == "__main__":
    main()
