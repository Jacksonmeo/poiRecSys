"""PyTorch Dataset 和 DataLoader 工具函数。"""
import torch
from torch.utils.data import Dataset, DataLoader
from typing import List, Dict, Tuple, Optional
import numpy as np


class NextPOIDataset(Dataset):
    """
    用于 Next POI 推荐的数据集类。

    每个样本包含：
        inp_v: (seq_len,)  — POI ID 索引
        inp_c: (seq_len,)  — 类别索引
        inp_t: (seq_len, 4) — 时间特征 [hour_sin, hour_cos, weekday_sin, weekday_cos]（可选）
        user_idx: int       — 用户索引（可选，用于 T8 长期偏好）
        lbl_v: int          — 目标 POI ID 索引
        causal_hist: (max_hist,)  — 因果长期历史 POI 索引（可选，用于 T9）
        causal_mask: (max_hist,)  — 因果长期历史掩码（可选）

    返回顺序：v, c, [t], [u], [causal_hist, causal_mask], lbl

    设计思路：通过布尔标志位灵活控制返回哪些特征，避免为不同模型变体
    创建多个Dataset子类。所有可选特征通过preprocess.py统一预计算后传入。
    """

    def __init__(self, data: List[Dict], include_time: bool = False,
                 include_user: bool = False, include_causal_history: bool = False):
        # 保存样本列表和特征开关，供__getitem__按需构造张量
        self.data = data
        self.include_time = include_time
        self.include_user = include_user
        self.include_causal_history = include_causal_history

    def __len__(self) -> int:
        """返回数据集中的样本总数，供DataLoader计算epoch和batch数。"""
        return len(self.data)

    def __getitem__(self, idx: int):
        """按索引获取单个样本，将所有字段转换为PyTorch张量。

        返回元组遵循固定顺序：[v, c, (t), (u), (causal_hist, causal_mask), lbl]
        其中括号内的元素根据初始化标志位决定是否包含。
        这个顺序必须与模型forward方法的参数顺序一致。
        """
        s = self.data[idx]
        v = torch.tensor(s['inp_v'], dtype=torch.long)
        c = torch.tensor(s['inp_c'], dtype=torch.long)
        lbl = torch.tensor(s['lbl_v'], dtype=torch.long)

        result = [v, c]
        if self.include_time:
            t = torch.tensor(s['inp_t'], dtype=torch.float32)  # (seq_len, 4)
            result.append(t)
        if self.include_user:
            u = torch.tensor(s['user_idx'], dtype=torch.long)
            result.append(u)
        if self.include_causal_history:
            ch = torch.tensor(s['causal_hist'], dtype=torch.long)    # (max_hist,)
            cm = torch.tensor(s['causal_mask'], dtype=torch.bool)    # (max_hist,)
            result.append(ch)
            result.append(cm)
        result.append(lbl)
        return tuple(result)


def create_dataloaders(train_data: List[Dict],
                       test_data: List[Dict],
                       batch_size: int = 512,
                       num_workers: int = 0,
                       include_time: bool = False,
                       include_user: bool = False,
                       include_causal_history: bool = False) -> Tuple[DataLoader, DataLoader]:
    """创建训练和测试 DataLoader。

    训练集 shuffle=True（打乱顺序，避免模型学习到样本排列偏差），
    测试集 shuffle=False（保持固定顺序，确保评估结果可复现）。
    pin_memory=True 将数据固定在GPU内存中，加速CPU→GPU数据传输。

    Args:
        train_data: 训练样本列表。
        test_data: 测试样本列表。
        batch_size: 批次大小。
        num_workers: DataLoader 的工作进程数。
        include_time: 数据集是否应输出时间特征。
        include_user: 数据集是否应输出用户索引。
        include_causal_history: 数据集是否应输出因果长期历史。

    Returns:
        (train_loader, test_loader) 元组。
    """
    train_dataset = NextPOIDataset(train_data, include_time=include_time,
                                   include_user=include_user,
                                   include_causal_history=include_causal_history)
    test_dataset = NextPOIDataset(test_data, include_time=include_time,
                                  include_user=include_user,
                                  include_causal_history=include_causal_history)

    train_loader = DataLoader(
        train_dataset,
        batch_size=batch_size,
        shuffle=True,
        num_workers=num_workers,
        pin_memory=True,
    )
    test_loader = DataLoader(
        test_dataset,
        batch_size=batch_size,
        shuffle=False,
        num_workers=num_workers,
        pin_memory=True,
    )

    return train_loader, test_loader


def create_val_loader(val_data: List[Dict],
                      batch_size: int = 512,
                      num_workers: int = 0,
                      include_time: bool = False,
                      include_user: bool = False,
                      include_causal_history: bool = False) -> DataLoader:
    """创建验证集 DataLoader（shuffle=False，不参与训练）。

    验证集不shuffle的原因：
    1. 保证每次评估时的样本顺序一致，使验证指标可精确复现；
    2. 验证集仅用于评估，不需要打乱来增强泛化性；
    3. 如果需要按时间评估（如随时间变化的性能），保持原始顺序至关重要。

    Args:
        val_data: 验证样本列表。
        batch_size: 批次大小。
        num_workers: DataLoader 的工作进程数。
        include_time: 数据集是否应输出时间特征。
        include_user: 数据集是否应输出用户索引。
        include_causal_history: 数据集是否应输出因果长期历史。

    Returns:
        val_loader: 验证 DataLoader。
    """
    val_dataset = NextPOIDataset(val_data, include_time=include_time,
                                 include_user=include_user,
                                 include_causal_history=include_causal_history)
    return DataLoader(
        val_dataset,
        batch_size=batch_size,
        shuffle=False,
        num_workers=num_workers,
        pin_memory=True,
    )
