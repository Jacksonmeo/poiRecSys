"""
Skip-Gram Word2Vec 行为语义嵌入。

在用户轨迹序列上训练 Word2Vec，学习能够捕捉功能性共现模式
（如 Office—Gym—Coffee Shop）的 POI 嵌入表示。
"""
import numpy as np
import torch
import torch.nn as nn
from collections import Counter
from typing import List, Tuple, Dict
import random
import time
import logging

logger = logging.getLogger(__name__)


def build_skipgram_pairs(sequences: List[List[int]], window_size: int = 3) -> List[Tuple[int, int]]:
    """
    使用滑动窗口从序列中构建 (中心词, 上下文词) 训练对。

    Args:
        sequences: 索引化轨迹列表，例如 [[1,2,3], [4,5,6,7]]
        window_size: 上下文窗口半径

    Returns:
        (center_token, context_token) 对的列表。
    """
    # 滑动窗口构建：以每个位置为中心词，将其窗口范围内的其他词作为上下文词，
    # 生成 (中心词, 上下文词) 训练对，窗口边界会自动裁剪防止越界
    pairs = []
    for seq in sequences:
        L = len(seq)
        for i, center in enumerate(seq):
            left = max(0, i - window_size)
            right = min(L, i + window_size + 1)
            for j in range(left, right):
                if j != i:
                    pairs.append((center, seq[j]))
    return pairs


class SkipGramNS(nn.Module):
    """
    带负采样的 Skip-Gram 模型。

    使用两个嵌入表：
        in_emb:  中心词嵌入（最终输出）—— 当 POI 作为被预测目标时的表示
        out_emb: 上下文词嵌入 —— 当 POI 作为上下文/共现 POI 时的表示
    这种双表设计让每个 POI 在充当不同角色时学习不同的向量，in_emb 最终被导出
    作为 POI 的行为语义嵌入，用于下游推荐任务。
    """

    def __init__(self, vocab_size: int, emb_dim: int):
        super().__init__()
        self.in_emb = nn.Embedding(vocab_size, emb_dim)
        self.out_emb = nn.Embedding(vocab_size, emb_dim)
        nn.init.xavier_uniform_(self.in_emb.weight)
        nn.init.xavier_uniform_(self.out_emb.weight)

    def forward(self, center: torch.Tensor, context: torch.Tensor,
                neg_samples: torch.Tensor) -> torch.Tensor:
        """
        Args:
            center: (batch,) 中心词索引
            context: (batch,) 正样本上下文词索引
            neg_samples: (batch, n_negs) 负样本索引

        Returns:
            标量损失 = -log(σ(v_c·u_o)) - Σ log(1-σ(v_c·u_k))

        损失函数核心思想：
            正样本（中心词与真实上下文词）内积越大越好 → -log(σ(·)) 惩罚低分
            负样本（中心词与随机采样的噪声词）内积越小越好 → -log(1-σ(·)) 惩罚高分
            两部分相加，迫使模型将语义上共现的 POI 拉近、无关的 POI 推远
        """
        v_c = self.in_emb(center)          # (batch, dim)  中心词向量
        u_o = self.out_emb(context)        # (batch, dim)  正样本上下文向量
        # 正样本得分：中心词与真实上下文词的内积 → sigmoid 转为概率
        pos_score = torch.sum(v_c * u_o, dim=-1).sigmoid()

        # 负样本得分：中心词与每个噪声词的内积，用批矩阵乘法 bmm 一次算出
        u_k = self.out_emb(neg_samples)    # (batch, n_negs, dim)
        neg_score = torch.bmm(u_k, v_c.unsqueeze(-1)).squeeze(-1).sigmoid()

        # 正损失：希望 σ(v_c·u_o) 接近 1，即正样本对被判定为共现
        pos_loss = -torch.log(pos_score + 1e-8).mean()
        # 负损失：希望 σ(v_c·u_k) 接近 0，即噪声样本对被判定为无关（对每个负样本求和再取均值）
        neg_loss = -torch.log(1 - neg_score + 1e-8).sum(dim=-1).mean()

        return pos_loss + neg_loss

    def get_embeddings(self) -> np.ndarray:
        """返回经 L2 归一化的中心词嵌入作为最终的词向量。

        L2 归一化将所有向量投影到单位超球面上，使得后续做余弦相似度时
        只需计算内积即可（避免了模长的干扰），这是推荐系统中嵌入的标准处理。
        """
        w = self.in_emb.weight.detach().cpu().numpy()
        return w / (np.linalg.norm(w, axis=1, keepdims=True) + 1e-8)


def train_word2vec(
    sequences: List[List[int]],
    vocab_size: int,
    emb_dim: int = 128,
    window_size: int = 3,
    n_negs: int = 5,
    batch_size: int = 2048,
    epochs: int = 10,
    lr: float = 0.001,
    device: torch.device = None,
) -> np.ndarray:
    """
    在轨迹序列上训练 Skip-Gram Word2Vec。

    Args:
        sequences: 索引化轨迹列表
        vocab_size: 词表总大小
        emb_dim: 嵌入维度（默认 128）
        window_size: 上下文窗口半径（默认 3）
        n_negs: 每个正样本对的负样本数量
        batch_size: 训练批次大小
        epochs: 训练轮数
        lr: 学习率
        device: torch 设备

    Returns:
        (vocab_size, emb_dim) 形状的 L2 归一化嵌入矩阵
    """
    if device is None:
        device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')

    logger.info(f"Training Word2Vec: dim={emb_dim}, window={window_size}, "
                f"negs={n_negs}, epochs={epochs}")

    # 构建训练样本对
    pairs = build_skipgram_pairs(sequences, window_size)
    logger.info(f"  Skip-gram pairs: {len(pairs):,}")

    # 构建负采样分布：unigram 频率的 0.75 次方平滑
    # 这个 trick 来自原始 Word2Vec 论文，p(w)^0.75 在高低频词之间做了折中：
    # 高频词采样概率被适当压低，低频词采样概率被适当抬高，避免高频词主导负采样
    word_counts = Counter(w for seq in sequences for w in seq)
    total_count = sum(word_counts.values())
    word_freq = np.zeros(vocab_size, dtype=np.float32)
    for w, c in word_counts.items():
        word_freq[w] = (c / total_count) ** 0.75
    word_freq /= word_freq.sum()

    # 模型初始化
    model = SkipGramNS(vocab_size, emb_dim).to(device)
    optimizer = torch.optim.Adam(model.parameters(), lr=lr)

    # 批量训练循环：每轮随机打乱训练对，按 batch 切分进行梯度下降
    n_batches = len(pairs) // batch_size
    t_start = time.time()

    for epoch in range(epochs):
        random.shuffle(pairs)  # 每轮打乱顺序，防止模型记忆固定的样本顺序
        total_loss = 0.0
        n_b = 0

        for b in range(n_batches):
            batch_pairs = pairs[b * batch_size:(b + 1) * batch_size]
            if len(batch_pairs) < 32:  # 跳过过小的尾部 batch，确保统计稳定
                continue

            centers = torch.tensor([p[0] for p in batch_pairs], dtype=torch.long, device=device)
            contexts = torch.tensor([p[1] for p in batch_pairs], dtype=torch.long, device=device)

            # 从平滑后的 unigram 分布中为当前 batch 抽取负样本
            # torch.multinomial 按 word_freq 概率采样，每个正样本对配 n_negs 个噪声词
            negs = torch.multinomial(
                torch.tensor(word_freq, device=device),
                len(batch_pairs) * n_negs,
                replacement=True
            ).view(len(batch_pairs), n_negs)

            optimizer.zero_grad()
            loss = model(centers, contexts, negs)
            loss.backward()
            optimizer.step()

            total_loss += loss.item()
            n_b += 1

        avg_loss = total_loss / max(n_b, 1)
        if (epoch + 1) % 3 == 0 or epoch == 0:
            logger.info(f"  Epoch {epoch + 1}/{epochs}, Loss={avg_loss:.4f}")

    elapsed = time.time() - t_start
    logger.info(f"  Training completed in {elapsed:.0f}s")

    return model.get_embeddings()


def build_behavioral_matrix(
    w2v_embeddings: np.ndarray,
    venue_to_idx: Dict[str, int],
    poi_to_w2v: Dict[str, int],
) -> np.ndarray:
    """
    将 Word2Vec 嵌入对齐到模型的 POI 词表。

    背景：Word2Vec 在自己的小词表上训练，其索引体系与下游模型的 venue_to_idx
    映射不同。本函数做"词表对齐"——按 venue_to_idx 的顺序逐行填入对应的 w2v 向量，
    未出现在 w2v 词表中的 POI 保持为零向量。

    Args:
        w2v_embeddings: (n_w2v, dim) 形状的 L2 归一化嵌入
        venue_to_idx: 模型的 POI → 索引映射
        poi_to_w2v: POI ID → Word2Vec 索引映射

    Returns:
        (num_venues, dim) 形状的对齐嵌入矩阵（未见过的 POI 用零向量填充）
    """
    num_venues = len(venue_to_idx)
    emb_dim = w2v_embeddings.shape[1]
    matrix = np.zeros((num_venues, emb_dim), dtype=np.float32)
    count = 0

    for venue_id, idx in venue_to_idx.items():
        if venue_id != '<PAD>' and venue_id in poi_to_w2v:
            matrix[idx] = w2v_embeddings[poi_to_w2v[venue_id]]
            count += 1

    logger.info(f"  Behavioral matrix: {matrix.shape}, coverage={count}/{num_venues - 1}")
    return matrix
