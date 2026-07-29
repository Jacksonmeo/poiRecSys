"""
Transformer Next POI 推荐的通用工具函数。

提供以下核心功能：
    - 随机种子固定（确保实验可复现）
    - 设备自动选择（GPU / CPU）
    - 日志系统配置（文件 + 控制台双输出）
    - 余弦相似度计算
"""
import random
import numpy as np
import torch
import logging
import sys
import os
from datetime import datetime


def set_seed(seed: int = 42):
    """
    固定所有随机种子，确保实验可复现。

    为什么需要：深度学习实验涉及多处随机性——数据 shuffle、权重初始化、
    dropout、cudnn 算法选择等。若不固定种子，每次运行结果可能不同，无法
    进行可靠的消融实验和模型对比。

    具体固定内容：
    1. Python 内置 random 模块
    2. NumPy 全局随机数生成器
    3. PyTorch CPU / GPU 随机数生成器
    4. cuDNN 后端设为确定性模式，关闭 benchmark 自动调优
       （关闭 benchmark 会略降性能，但换来可复现性）
    """
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed(seed)
        torch.cuda.manual_seed_all(seed)  # 多 GPU 场景下同步所有 GPU 种子
        # cuDNN 确定性模式：牺牲部分性能换取每次运行结果完全一致
        torch.backends.cudnn.deterministic = True
        torch.backends.cudnn.benchmark = False


def get_device() -> torch.device:
    """
    获取当前可用的最佳计算设备。

    优先级：CUDA GPU > CPU。
    自动检测 CUDA 是否可用，无需手动指定设备类型，使得同一份代码可在
    不同硬件环境（GPU 服务器 / 本地 CPU）之间无缝切换。
    """
    if torch.cuda.is_available():
        return torch.device('cuda')
    return torch.device('cpu')


def setup_logging(log_dir: str = "logs", name: str = "transformer") -> logging.Logger:
    """
    设置双通道日志系统（文件 + 控制台），返回配置好的 Logger。

    设计思路：
    1. 日志文件带时间戳命名（如 transformer_20260715_143022.log），
       每次运行独立保存，防止覆盖历史日志，方便回溯对比不同实验。
    2. 同时输出到 stdout，方便训练过程中实时观察进度。
    3. 文件日志使用 utf-8 编码，避免中文内容乱码。

    Returns:
        配置好的 logging.Logger 实例，调用方可直接 logger.info(...) 使用。
    """
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, f'{name}_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log')
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s | %(levelname)s | %(message)s',
        handlers=[
            logging.FileHandler(log_file, encoding='utf-8'),  # 写入文件
            logging.StreamHandler(sys.stdout)                  # 输出到控制台
        ]
    )
    return logging.getLogger(__name__)


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """
    计算两个向量之间的余弦相似度。

    公式：cos(a, b) = (a · b) / (||a|| * ||b||)

    分母加 1e-8 防止除零（当向量范数为零时，返回 0）。
    常用于衡量两个 embedding 或特征向量之间的语义相似程度，
    值域为 [-1, 1]，越接近 1 表示方向越一致。
    """
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-8))
