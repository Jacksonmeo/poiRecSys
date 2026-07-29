"""模型指标路由：提供模型对比、消融实验和 seen/unseen 指标。

所有指标数据从预计算的 metrics.json 文件读取，不在请求期间现场计算。
"""

from fastapi import APIRouter

from app.services.metrics_service import get_ablation_metrics, get_model_metrics, get_seen_unseen_metrics

router = APIRouter()


@router.get("/models")
def list_model_metrics() -> dict:
    """返回主要模型的 HR@5、NDCG@5、MRR@10 等核心评估指标。

    用于模型对比页面的表格和图表展示，数据来源为离线评估结果。
    """
    return {"data": get_model_metrics()}


@router.get("/ablation")
def list_ablation_metrics() -> dict:
    """返回消融实验指标，用于分析各模块对模型性能的贡献。

    消融实验通过逐一移除模型组件（如因果记忆、时间编码等）来量化其影响。
    """
    return {"data": get_ablation_metrics()}


@router.get("/seen-unseen")
def list_seen_unseen_metrics() -> dict:
    """返回 seen / unseen POI 分组指标，评估模型对冷热 POI 的推荐能力。

    Seen POI 为训练集中出现过的兴趣点，Unseen POI 为仅出现于测试集的兴趣点。
    """
    return {"data": get_seen_unseen_metrics()}
