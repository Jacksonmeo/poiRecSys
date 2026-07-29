"""
Transformer Next POI 推荐的训练循环。

核心设计原则：
    - Early stopping 和 learning rate scheduler 基于验证集 HR@5
    - 测试集仅在训练结束后用于最终评估（严格避免数据泄露）
    - 训练过程中不接触测试集，确保评估结果客观可信
"""
import torch
import torch.nn as nn
from torch.utils.data import DataLoader
from typing import Dict, Optional
import time
import os
import logging
import json

from src.evaluate import evaluate

logger = logging.getLogger(__name__)


def train_epoch(
    model: nn.Module,
    dataloader: DataLoader,
    optimizer: torch.optim.Optimizer,
    criterion: nn.Module,
    device: torch.device,
    grad_clip: float = 1.0,
) -> float:
    """
    训练一个 epoch，返回该 epoch 的平均损失值。

    关键设计：通过 model flags 动态构建 kwargs，支持模型在不同配置下
    （是否使用时间特征、长期偏好、因果历史）复用同一个训练循环。

    步骤：
    1. 将模型设为训练模式（启用 dropout / batch norm）
    2. 遍历每个 batch，将数据移到目标设备
    3. 根据 model 的属性标记（use_time, use_long_pref, use_causal_long_pref）
       动态组装前向传播参数，避免为每种模型变体维护不同的训练循环
    4. 计算交叉熵损失、反向传播、梯度裁剪、参数更新
    """
    model.train()
    total_loss = 0.0
    n_batches = 0

    # 通过 getattr 探测模型支持的额外输入维度，
    # 若无该属性则默认 False，保证与基础模型向后兼容
    use_time = getattr(model, 'use_time', False)
    use_long = getattr(model, 'use_long_pref', False)
    use_causal = getattr(model, 'use_causal_long_pref', False)

    for batch in dataloader:
        batch = [t.to(device) for t in batch]
        bv, bc = batch[0], batch[1]   # 固定位置：POI 序列、类别序列
        bl = batch[-1]                 # label 始终是最后一个元素

        optimizer.zero_grad()

        # ---- 基于 model flags 动态构建 kwargs ----
        # batch 结构: [bv, bc, (t_seq), (u_seq), (causal_history, causal_mask), label]
        # 通过 idx 指针按顺序读取可选字段，每个 flag 决定是否读取并消耗对应位置
        idx = 2
        kwargs = {}
        if use_time:
            kwargs['t_seq'] = batch[idx]
            idx += 1
        if use_long:
            kwargs['u_seq'] = batch[idx]
            idx += 1
        if use_causal:
            kwargs['causal_history'] = batch[idx]
            kwargs['causal_mask'] = batch[idx + 1]
            idx += 2

        logits = model(bv, bc, **kwargs)
        loss = criterion(logits, bl)
        loss.backward()

        # 梯度裁剪：防止 RNN/Transformer 训练中的梯度爆炸问题
        nn.utils.clip_grad_norm_(model.parameters(), grad_clip)
        optimizer.step()

        total_loss += loss.item()
        n_batches += 1

    return total_loss / max(n_batches, 1)


def train(
    model: nn.Module,
    train_loader: DataLoader,
    val_loader: DataLoader,
    test_loader: DataLoader,
    device: torch.device,
    epochs: int = 25,
    lr: float = 0.001,
    grad_clip: float = 1.0,
    patience: int = 10,
    scheduler_factor: float = 0.5,
    scheduler_patience: int = 5,
    checkpoint_dir: str = "checkpoints",
    model_name: str = "transformer_model",
) -> Dict:
    """
    完整的训练循环，包含基于验证集的早停和学习率调度。

    训练协议：
    1. 每个 epoch 先在 train_loader 上训练，再在 val_loader 上评估
    2. 以 val HR@5 作为监控指标进行早停判断和学习率调整
    3. 当 val HR@5 连续 patience 轮未提升时触发早停
    4. 训练结束后加载最佳 checkpoint，在 test_loader 上做唯一一次最终评估

    为什么用验证集而非测试集做早停：
    早停决策如果接触测试集会导致信息泄露——测试集应当模拟"未来未知数据"，
    只能在所有超参数确定后使用一次，否则泛化性能评估会偏高。

    为什么用 HR@5 而非 loss 做早停监控：
    HR@5 是推荐系统的核心业务指标，直接优化业务目标比优化代理 loss 更有效。
    loss 下降不一定意味着推荐质量提升。

    学习率调度策略：
    使用 ReduceLROnPlateau，当 val HR@5 连续 scheduler_patience 轮不再提升时
    将学习率乘以 scheduler_factor（如 0.5 即减半）。这比固定衰减更智能——
    只在指标停滞时调低 lr，性能仍在提升时保持当前步长。

    Args:
        model: 待训练的模型。
        train_loader: 训练数据 DataLoader（shuffle=True）。
        val_loader: 验证数据 DataLoader（shuffle=False），用于 early stopping。
        test_loader: 测试数据 DataLoader（shuffle=False），仅用于最终评估。
        device: torch 设备。
        epochs: 最大训练轮数（默认 25）。
        lr: 初始学习率（默认 0.001）。
        grad_clip: 梯度裁剪阈值（默认 1.0）。
        patience: 早停耐心值（默认 10 轮）。
        scheduler_factor: ReduceLROnPlateau 的衰减因子（默认 0.5）。
        scheduler_patience: ReduceLROnPlateau 的耐心值（默认 5 轮）。
        checkpoint_dir: 模型检查点保存目录。
        model_name: 用于检查点文件命名的名称。

    Returns:
        字典，包含：
            test_metrics: 最佳 checkpoint 在测试集上的最终评估指标。
            best_val_metrics: 验证集上最佳 epoch 的指标。
            best_val_hr5: 最佳验证 HR@5 数值。
            best_epoch: 验证集上 HR@5 最佳的轮次。
            train_time_s: 总训练时间（秒）。
            history: 各轮训练/验证指标的历史列表。
            history_path: 历史记录 JSON 文件路径。
    """
    os.makedirs(checkpoint_dir, exist_ok=True)

    criterion = nn.CrossEntropyLoss()
    optimizer = torch.optim.Adam(model.parameters(), lr=lr)

    # ReduceLROnPlateau: 当 val HR@5 不再提升时自动降低学习率
    # mode='max' 因为 HR@5 是越大越好的指标
    scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(
        optimizer, mode='max', factor=scheduler_factor, patience=scheduler_patience
    )

    # ---- 早停状态变量 ----
    best_val_hr5 = 0.0        # 当前最佳验证 HR@5
    best_epoch = 0             # 最佳 epoch 编号
    best_val_metrics = None    # 最佳 epoch 的完整验证指标
    patience_counter = 0       # 连续未提升的 epoch 计数
    t_start = time.time()
    history = []

    best_ckpt_path = os.path.join(checkpoint_dir, f'{model_name}_best.pth')

    for epoch in range(epochs):
        # ---- 训练阶段 ----
        train_loss = train_epoch(model, train_loader, optimizer, criterion, device, grad_clip)

        # ---- 验证集评估：仅用于监控，不更新模型参数 ----
        val_metrics = evaluate(model, val_loader, device)

        # ---- 学习率调度：基于验证 HR@5 ----
        scheduler.step(val_metrics['HR@5'])

        # 记录 epoch 历史
        history.append({
            'epoch': epoch + 1,
            'train_loss': round(train_loss, 4),
            **{f'val_{k}': v for k, v in val_metrics.items() if k != 'total'},
        })

        # ---- 早停逻辑 ----
        if val_metrics['HR@5'] > best_val_hr5:
            # 验证 HR@5 提升：保存最佳模型，重置耐心计数器
            best_val_hr5 = val_metrics['HR@5']
            best_epoch = epoch + 1
            best_val_metrics = {k: v for k, v in val_metrics.items()}
            patience_counter = 0
            torch.save(model.state_dict(), best_ckpt_path)
        else:
            # 未提升：计数 +1，当达到 patience 阈值时停止训练
            patience_counter += 1

        # 每个 epoch 打印日志（前 2 个 epoch 和每 5 个 epoch 打印）
        if (epoch + 1) % 5 == 0 or epoch < 2:
            logger.info(
                f"Epoch {epoch + 1:2d}: Loss={train_loss:.4f}, "
                f"val_HR@1={val_metrics['HR@1']:.1f}%, val_HR@5={val_metrics['HR@5']:.1f}%, "
                f"val_HR@10={val_metrics['HR@10']:.1f}%, val_NDCG@5={val_metrics['NDCG@5']:.4f}, "
                f"val_MRR@5={val_metrics['MRR@5']:.4f}"
            )

        if patience_counter >= patience:
            logger.info(f"Early stopping at epoch {epoch + 1} "
                        f"(best val_HR@5={best_val_hr5:.1f}% at epoch {best_epoch})")
            break

    # ---- 最终评估协议 ----
    # 1. 加载训练过程中验证集上的最佳 checkpoint（而非最后一个 epoch 的模型）
    # 2. 在测试集上做唯一一次评估——此后不再调参，确保评估结果客观
    model.load_state_dict(torch.load(best_ckpt_path, weights_only=True))
    test_metrics = evaluate(model, test_loader, device)

    train_time = time.time() - t_start
    logger.info(
        f"\nTraining complete: best_epoch={best_epoch}, "
        f"best_val_HR@5={best_val_metrics['HR@5']:.1f}%, "
        f"test_HR@1={test_metrics['HR@1']:.1f}%, "
        f"test_HR@5={test_metrics['HR@5']:.1f}%, "
        f"test_HR@10={test_metrics['HR@10']:.1f}%, "
        f"test_NDCG@5={test_metrics['NDCG@5']:.4f}, "
        f"test_NDCG@10={test_metrics['NDCG@10']:.4f}, "
        f"test_MRR@5={test_metrics['MRR@5']:.4f}, "
        f"test_MRR@10={test_metrics['MRR@10']:.4f}, "
        f"Time={train_time:.0f}s"
    )

    # 保存最后一个 epoch 的模型（用于 debug / 对比最佳 vs 最终）
    final_path = os.path.join(checkpoint_dir, f'{model_name}_final.pth')
    torch.save(model.state_dict(), final_path)
    logger.info(f"Final model saved to: {final_path}")

    # 保存各 epoch 训练/验证指标历史为 JSON，方便后续画图和对比实验
    history_path = os.path.join(checkpoint_dir, f'{model_name}_history.json')
    with open(history_path, 'w', encoding='utf-8') as f:
        json.dump(history, f, indent=2)

    return {
        'test_metrics': test_metrics,            # 测试集指标（最终评估，仅一次）
        'best_val_metrics': best_val_metrics,    # 验证集指标（best epoch）
        'best_val_hr5': best_val_hr5,            # 最佳验证 HR@5 数值
        'best_epoch': best_epoch,                # 验证集上最优的 epoch
        'train_time_s': round(train_time, 1),
        'history': history,
        'history_path': history_path,
    }
