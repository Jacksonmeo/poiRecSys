"""从数据库 session 批量生成 T10e-2 推荐结果。

离线评估约定：每个 session 的最后一个签到作为真实目标，此前的签到作为
短期输入；同一用户在目标时间前的签到构成因果长期历史。脚本始终导出 CSV，
传入 ``--write-db`` 时再以事务方式替换 PostgreSQL 中对应模型的旧结果。

从仓库根目录运行：
    python backend/scripts/generate_recommendations.py --dataset TKY --top-k 10
    python backend/scripts/generate_recommendations.py --dataset TKY --top-k 10 --write-db
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
from collections import defaultdict
from dataclasses import asdict
from pathlib import Path

from sqlalchemy import delete, select

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
RECMODEL_ROOT = REPO_ROOT / "RecModel"
# 将 backend 和 RecModel 目录加入 Python 路径，以便导入应用和模型模块
for path in (BACKEND_ROOT, RECMODEL_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))


def load_backend_env() -> None:
    """确保从仓库根目录运行时也能读取 backend/.env。

    手动解析 .env 文件并注入 os.environ，使 pydantic-settings 能正确加载
    数据库连接 URL 等配置项。
    """
    env_file = BACKEND_ROOT / ".env"
    if not env_file.exists():
        return
    for raw_line in env_file.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


# 在导入数据库模块前加载环境变量
load_backend_env()

from app.db.database import SessionLocal  # noqa: E402
from app.models.checkin import Checkin  # noqa: E402
from app.models.poi import Poi  # noqa: E402
from app.models.recommendation_result import RecommendationResult  # noqa: E402
from app.models.session import UserSession  # noqa: E402
from src.infer_sessions import SessionInput, T10e2SessionRecommender  # noqa: E402


def parse_args() -> argparse.Namespace:
    """解析命令行参数。

    支持配置数据集、Top-K 数量、批大小、设备、试运行限制和数据库写入等选项。
    """
    parser = argparse.ArgumentParser(description="Generate Top-K recommendations from database sessions.")
    parser.add_argument("--dataset", default="TKY")
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--batch-size", type=int, default=256)
    parser.add_argument("--limit", type=int, default=None, help="Limit sessions for a smoke run.")
    parser.add_argument("--session-id", action="append", help="Only infer selected session ID(s).")
    parser.add_argument("--device", choices=("cpu", "cuda"), default=None)
    parser.add_argument("--write-db", action="store_true", help="Replace this model's rows in PostgreSQL.")
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="CSV path (default: backend/exports/recommendation_results_<dataset>.csv).",
    )
    return parser.parse_args()


def load_session_rows(db, dataset: str, session_ids: list[str] | None, limit: int | None):
    """读取待推理 session、其有序签到点以及涉及用户的完整时间线。

    查询分为三步：
    1. 从 sessions 表筛选符合条件的 session（按数据集、签到数 >= 2）
    2. 通过子查询 JOIN 方式获取选中 session 的所有签到点（含 POI 类别）
    3. 加载所有涉及用户的完整签到时间线（用于构建因果长期历史）

    使用子查询 JOIN 而非 IN 展开的原因是避免超过 PostgreSQL 单语句
    65535 个参数的上限（全量数据有数万个 session）。

    Args:
        db: 数据库会话。
        dataset: 数据集标签。
        session_ids: 可选，仅推理指定的 session ID 列表。
        limit: 可选，限制处理的 session 数量（用于冒烟测试）。

    Returns:
        (selected 列表, data 字典) 元组。data 包含 "points"（按 session 分组的签到点）
        和 "timelines"（按 user 分组的完整签到时间线）。
    """
    # 第一步：筛选符合条件的 session
    session_stmt = (
        select(UserSession.session_id, UserSession.user_id)
        .where(UserSession.dataset == dataset)
        .where(UserSession.checkin_count >= 2)
        .order_by(UserSession.start_time, UserSession.session_id)
    )
    if session_ids:
        session_stmt = session_stmt.where(UserSession.session_id.in_(session_ids))
    if limit is not None:
        session_stmt = session_stmt.limit(limit)
    selected = list(db.execute(session_stmt).all())
    if not selected:
        return [], {}

    # 全量数据约有数万个 session，不能把所有 ID 展开成 IN 参数，否则会超过
    # PostgreSQL 单语句 65535 个参数的上限。这里复用同一筛选条件构造子查询 JOIN。
    selected_session_subquery = session_stmt.with_only_columns(
        UserSession.session_id
    ).subquery("selected_sessions")
    # 第二步：通过子查询 JOIN 获取选中 session 的所有签到点
    point_stmt = (
        select(
            Checkin.session_id,
            Checkin.user_id,
            Checkin.venue_id,
            Checkin.utc_timestamp,
            Checkin.id,
            Poi.venue_category,
        )
        .join(Poi, Poi.venue_id == Checkin.venue_id)
        .join(
            selected_session_subquery,
            selected_session_subquery.c.session_id == Checkin.session_id,
        )
        .order_by(
            Checkin.session_id,
            Checkin.sequence_no.asc().nullslast(),
            Checkin.utc_timestamp,
            Checkin.id,
        )
    )
    points_by_session = defaultdict(list)
    for row in db.execute(point_stmt):
        points_by_session[row.session_id].append(row)

    # 长期因果记忆允许包含更早 session 的访问，因此一次读出用户完整时间线，
    # 后续再严格按照 target 时间切片，避免使用未来签到。
    user_ids = sorted({row.user_id for row in selected})
    timeline_stmt = (
        select(Checkin.user_id, Checkin.venue_id, Checkin.utc_timestamp, Checkin.id)
        .where(Checkin.user_id.in_(user_ids))
        .order_by(Checkin.user_id, Checkin.utc_timestamp, Checkin.id)
    )
    timelines = defaultdict(list)
    for row in db.execute(timeline_stmt):
        timelines[row.user_id].append(row)
    return selected, {"points": points_by_session, "timelines": timelines}


def make_inputs(selected, data, recommender: T10e2SessionRecommender):
    """将数据库记录转换为模型输入，并分类统计不能推理的 OOV session。

    对每个 session：
    1. 将签到点分为历史（前 N-1 个）和目标（最后一个）
    2. 检查目标和最后历史 POI 是否在模型词表中（OOV 检查）
    3. 构建因果长期历史：从用户时间线中筛选目标时间之前的签到
    4. 组装 SessionInput 对象供模型推理

    Args:
        selected: 选中的 session 列表。
        data: 包含 "points" 和 "timelines" 的字典。
        recommender: T10e2 推荐器实例。

    Returns:
        (inputs 列表, skipped 统计字典) 元组。
    """
    inputs, skipped = [], defaultdict(int)
    for session in selected:
        points = data["points"].get(session.session_id, [])
        # 签到点不足 2 个的 session 无法形成历史-目标对
        if len(points) < 2:
            skipped["fewer_than_2_joined_points"] += 1
            continue
        # 最后一个点为真实目标，之前的为历史
        history, target = points[:-1], points[-1]
        # 目标 POI 不在模型词表中则跳过
        if not recommender.supports_target(target.venue_id):
            skipped["target_out_of_vocabulary"] += 1
            continue
        # 最后一个历史 POI 不在词表中则跳过（模型需要它作为短期上下文锚点）
        if history[-1].venue_id not in recommender.venue_to_idx:
            skipped["last_history_poi_out_of_vocabulary"] += 1
            continue

        # 构建因果长期历史：仅包含目标时间之前的签到，避免数据泄漏
        prior = [
            row.venue_id
            for row in data["timelines"][session.user_id]
            if (row.utc_timestamp, row.id) < (target.utc_timestamp, target.id)
        ]
        inputs.append(
            SessionInput(
                session_id=session.session_id,
                user_id=session.user_id,
                venue_ids=[row.venue_id for row in history],
                categories=[row.venue_category or "Unknown" for row in history],
                timestamps=[row.utc_timestamp for row in history],
                target_poi_id=target.venue_id,
                causal_venue_ids=prior,
            )
        )
    return inputs, skipped


def write_csv(path: Path, rows) -> None:
    """输出便于审计和人工检查的扁平 recommendation_results CSV。

    每行对应一个候选 POI，包含用户、会话、目标、候选、排名和分数。

    Args:
        path: 输出 CSV 文件路径。
        rows: 推荐结果数据行列表。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["user_id", "session_id", "target_poi_id", "poi_id", "rank", "score", "model_name"]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            payload = asdict(row)
            payload["model_name"] = T10e2SessionRecommender.MODEL_NAME
            writer.writerow({key: payload[key] for key in fieldnames})


def replace_database_rows(db, rows, dataset: str, selected_session_ids: list[str]) -> None:
    """在当前事务内替换所选 session 的同模型旧结果。

    先删除旧数据，再批量插入新结果，保证同一模型同 session 的数据原子替换。
    此操作在调用方的事务上下文中执行，需由调用方负责 commit。

    Args:
        db: 数据库会话。
        rows: 新的推荐结果行列表。
        dataset: 数据集标签。
        selected_session_ids: 被替换的 session ID 列表。
    """
    model_name = T10e2SessionRecommender.MODEL_NAME
    # 先删除所选 session 的该模型旧结果
    db.execute(
        delete(RecommendationResult).where(
            RecommendationResult.model_name == model_name,
            RecommendationResult.session_id.in_(selected_session_ids),
        )
    )
    # 批量插入新结果
    db.add_all(
        [
            RecommendationResult(
                **asdict(row),
                dataset=dataset,
                model_name=model_name,
            )
            for row in rows
        ]
    )


def main() -> None:
    """脚本主入口：加载模型、读取数据、批量推理、输出结果。

    完整流程：
    1. 解析命令行参数并校验
    2. 加载 T10e2 推荐模型（支持 CPU/CUDA）
    3. 从数据库读取待推理 session 和用户时间线
    4. 转换为模型输入格式，跳过 OOV session
    5. 按 batch 批量推理生成 Top-K 推荐
    6. 导出 CSV 文件
    7. 如果指定 --write-db，以事务方式写入 PostgreSQL
    """
    args = parse_args()
    dataset = args.dataset.strip().upper()
    if args.top_k < 1 or args.batch_size < 1:
        raise ValueError("top-k and batch-size must be positive")

    # 加载推荐模型
    print(f"Loading {T10e2SessionRecommender.MODEL_NAME} on {args.device or 'auto'} ...")
    recommender = T10e2SessionRecommender(device=args.device)
    with SessionLocal() as db:
        # 从数据库加载数据并转换为模型输入
        selected, data = load_session_rows(db, dataset, args.session_id, args.limit)
        inputs, skipped = make_inputs(selected, data, recommender)
        print(f"Selected sessions: {len(selected)}, inferable: {len(inputs)}, skipped: {dict(skipped)}")

        # 批量推理
        results = []
        for start in range(0, len(inputs), args.batch_size):
            results.extend(recommender.recommend(inputs[start : start + args.batch_size], args.top_k))
            print(f"Inferred {min(start + args.batch_size, len(inputs))}/{len(inputs)} sessions")

        # 导出 CSV 文件
        output = args.output or BACKEND_ROOT / "exports" / f"recommendation_results_{dataset}.csv"
        write_csv(output, results)
        print(f"CSV: {output} ({len(results)} rows)")

        # 可选：写入数据库
        if args.write_db:
            replace_database_rows(db, results, dataset, [item.session_id for item in inputs])
            db.commit()
            print(f"Database: replaced {len(results)} rows")


if __name__ == "__main__":
    main()
