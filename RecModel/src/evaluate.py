"""
评估指标：Next POI 推荐的 HR@K、NDCG@K 和 MRR@K。

采用全量排序评估（所有候选 POI 参与排序）——不使用负采样。

指标定义（所有指标均基于同一个 top-K 排序结果）：

    HR@K  (Hit Rate@K):
        真实 POI 是否出现在 Top-K 预测中的 0/1 判定，对所有样本取平均。

    NDCG@K (Normalized Discounted Cumulative Gain@K):
        单标签场景下 IDCG=1.0，因此 NDCG@K = 1 / log₂(rank+1)。
        若真实 POI 不在 Top-K 中，则该样本 NDCG@K = 0。

    MRR@K  (Mean Reciprocal Rank@K):
        若真实 POI 在 Top-K 中的排名为 rank（rank 从 1 开始），
        则 MRR@K = 1 / rank。不在 Top-K 中则 MRR@K = 0。
        对所有样本取平均。
"""
import torch
import numpy as np
from torch.utils.data import DataLoader
from typing import Dict, Tuple


@torch.no_grad()
def evaluate(
    model: torch.nn.Module,
    dataloader: DataLoader,
    device: torch.device,
    ks: Tuple[int, ...] = (1, 5, 10),
) -> Dict[str, float]:
    """
    在完整测试集上评估模型。

    对每个样本，对所有 POI 进行全量排序，检查真实标签是否出现在
    预测结果的前 K 个候选中。

    Args:
        model: 已训练的模型（eval 模式）
        dataloader: 测试 DataLoader
        device: torch 设备
        ks: HR@K、NDCG@K 和 MRR@K 中的 K 值元组

    Returns:
        字典，包含以下字段：
            HR@{k}:   命中率，百分比形式
            NDCG@{k}: 归一化折损累积增益
            MRR@{k}:  平均倒数排名
            total:    评估的测试样本总数
    """
    model.eval()

    use_time = getattr(model, 'use_time', False)
    use_long = getattr(model, 'use_long_pref', False)
    use_causal = getattr(model, 'use_causal_long_pref', False)

    max_k = max(ks)
    hits = {k: 0 for k in ks}
    ndcg = {k: 0.0 for k in ks}
    mrr = {k: 0.0 for k in ks}
    total = 0

    for batch in dataloader:
        # batch: (venues, categories, [time], [user_idx], [causal_hist, causal_mask], labels)
        batch = [t.to(device) for t in batch]
        bv, bc = batch[0], batch[1]
        bl = batch[-1]  # label 始终在最后

        # 基于 model flags 构建 kwargs（支持任意组合：time, user_idx, causal_history）
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
        _, topk = torch.topk(logits, k=max_k, dim=1)

        # 逐样本计算 HR@K、NDCG@K、MRR@K：全量排序评估，每个样本在所有 POI 中检查真实标签是否出现在 Top-K
        for i in range(bl.size(0)):
            true_label = bl[i].item()
            preds = topk[i].tolist()

            for k in ks:
                # HR@K: 真实 POI 出现在 Top-K 中则计数+1（命中率）
                if true_label in preds[:k]:
                    hits[k] += 1
                    rank = preds[:k].index(true_label) + 1  # rank 从 1 开始
                    # MRR@K: 排名倒数 1/rank，rank 越高贡献越小
                    mrr[k] += 1.0 / rank
                    # NDCG@K：单标签场景下 IDCG = 1/log₂(2) = 1.0
                    # 折扣因子为 1/log₂(rank+1)，rank 越大折扣越大
                    ndcg[k] += 1.0 / np.log2(rank + 1)

            total += 1

    results = {}
    # HR@K（命中率，百分比）
    for k in ks:
        results[f'HR@{k}'] = round(hits[k] / total * 100, 2)
    # NDCG@K
    for k in ks:
        results[f'NDCG@{k}'] = round(ndcg[k] / total, 4)
    # MRR@K
    for k in ks:
        results[f'MRR@{k}'] = round(mrr[k] / total, 4)
    results['total'] = total

    return results


def print_metrics(results: Dict[str, float], prefix: str = ""):
    """以美观的格式打印评估指标。
    按 HR@K → NDCG@K → MRR@K 顺序输出，便于人工对比不同 K 值下的表现。
    """
    print(f"\n{'=' * 60}")
    print(f"  {prefix} Results")
    print(f"{'=' * 60}")
    # HR@K：百分比格式，直观反映命中比例
    for k in [1, 5, 10]:
        if f'HR@{k}' in results:
            print(f"  HR@{k}:     {results[f'HR@{k}']:.2f}%")
    # NDCG@K：精确到小数点后4位，反映排序质量
    for k in [1, 5, 10]:
        if f'NDCG@{k}' in results:
            print(f"  NDCG@{k}:   {results[f'NDCG@{k}']:.4f}")
    # MRR@K：精确到小数点后4位，反映真实 POI 的平均排名倒数
    for k in [1, 5, 10]:
        if f'MRR@{k}' in results:
            print(f"  MRR@{k}:    {results[f'MRR@{k}']:.4f}")
    print(f"  Samples:   {results['total']:,}")
    print(f"{'=' * 60}\n")


def format_results_table(results_list: Dict[str, Dict[str, float]]) -> str:
    """
    将多个模型的结果格式化为 Markdown 对比表格。

    Args:
        results_list: model_name → {metric: value}

    Returns:
        Markdown 表格字符串
    """
    # 表格列：模型名称 + 3个HR指标 + 2个NDCG指标 + 2个MRR指标
    headers = ['Model', 'HR@1', 'HR@5', 'HR@10', 'NDCG@5', 'NDCG@10', 'MRR@5', 'MRR@10']
    lines = ['| ' + ' | '.join(headers) + ' |']
    lines.append('|' + '|'.join(['-------'] * len(headers)) + '|')

    # 逐模型构建行：缺失指标填充默认值 0
    for model_name, metrics in results_list.items():
        row = [
            model_name,
            f"{metrics.get('HR@1', 0):.1f}%",
            f"{metrics.get('HR@5', 0):.1f}%",
            f"{metrics.get('HR@10', 0):.1f}%",
            f"{metrics.get('NDCG@5', 0):.4f}",
            f"{metrics.get('NDCG@10', 0):.4f}",
            f"{metrics.get('MRR@5', 0):.4f}",
            f"{metrics.get('MRR@10', 0):.4f}",
        ]
        lines.append('| ' + ' | '.join(row) + ' |')

    return '\n'.join(lines)
