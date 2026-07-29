"""指标服务：读取 metrics.json 并按接口主题返回不同指标集合。

所有指标数据来自离线评估后导出的 JSON 文件，API 请求期间不做实时计算。
"""

import json
from pathlib import Path

import pandas as pd

# 指标 mock 数据使用 JSON 保存，便于维护多组实验结果。
DATA_DIR = Path(__file__).resolve().parents[1] / "data"


def _load_metrics() -> dict:
    """读取模型指标 JSON 文件，返回原始字典结构。

    metrics.json 包含 models（主模型对比）、ablation（消融实验）、
    seen_unseen（冷热 POI 分组）三组指标数据。
    """
    with (DATA_DIR / "metrics.json").open(encoding="utf-8") as metrics_file:
        return json.load(metrics_file)


def get_model_metrics() -> list[dict]:
    """返回主模型对比指标。

    包含各模型的 HR@5、NDCG@5、MRR@10 等核心评估指标，
    用于前端模型对比表格和柱状图展示。
    """
    return pd.DataFrame(_load_metrics()["models"]).to_dict(orient="records")


def get_ablation_metrics() -> list[dict]:
    """返回消融实验指标。

    通过逐一移除模型组件来量化各模块的贡献度，
    包含完整模型和各消融变体的指标对比。
    """
    return pd.DataFrame(_load_metrics()["ablation"]).to_dict(orient="records")


def get_seen_unseen_metrics() -> list[dict]:
    """返回 seen / unseen 分组指标。

    Seen POI 为训练集中出现过的兴趣点，Unseen 为仅测试集出现的兴趣点，
    分组评估可揭示模型对冷启动 POI 的推荐能力。
    """
    return pd.DataFrame(_load_metrics()["seen_unseen"]).to_dict(orient="records")
