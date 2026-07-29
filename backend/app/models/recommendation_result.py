"""离线模型推荐结果 ORM。

每行表示一个 session 的一个候选 POI；同一 session 和模型下通过 rank 排序，
目标 POI 单独保存，用于离线命中率分析和前端地图对照。
"""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Float, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class RecommendationResult(Base):
    """推荐结果表，存储离线模型对每个 session 的 Top-K 推荐候选。

    每个 session 有 K 行记录（K 为 top-k 参数），每行对应一个候选 POI。
    通过 target_poi_id 和 poi_id 的匹配可计算 HR@K 等离线指标。
    """

    __tablename__ = "recommendation_results"

    # 自增主键
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    # 会话 ID
    session_id: Mapped[str] = mapped_column(String(150), nullable=False, index=True)
    # 用户 ID
    user_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    # 数据集标签
    dataset: Mapped[str] = mapped_column(String(20), nullable=False, default="TKY")
    # 模型名称，用于区分不同模型的推理结果
    model_name: Mapped[str] = mapped_column(String(100), nullable=False)
    # 真实目标 POI（即会话最后一个签到点），用于计算命中率
    target_poi_id: Mapped[str] = mapped_column(String(100), nullable=False)
    # 候选 POI ID
    poi_id: Mapped[str] = mapped_column(String(100), nullable=False)
    # 推荐排名（1-based），排名越靠前表示模型越推荐该 POI
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    # 推荐分数，模型输出的原始置信度
    score: Mapped[float] = mapped_column(Float, nullable=False)
    # 生成时间，由数据库自动填充当前时间
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
