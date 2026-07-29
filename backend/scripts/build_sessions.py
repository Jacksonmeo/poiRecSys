"""Build stable 24-hour sessions from database check-ins and export CSV files.

从数据库签到记录构建稳定的 24 小时会话并导出 CSV 文件。
此脚本只读取 checkins 表，不向 PostgreSQL 回写数据。

会话切分规则：
1. 按用户分组签到记录。
2. 按 utc_timestamp 升序、id 升序排列。
3. 相邻签到间隔超过 24 小时则切分为新会话。
4. 仅保留包含至少 2 次签到的会话段。
5. 单次签到段被统计为丢弃。

Usage:
    python backend/scripts/build_sessions.py --dataset TKY --dry-run
    python backend/scripts/build_sessions.py --dataset TKY
    python backend/scripts/build_sessions.py --dataset TKY --output-dir backend/exports
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def load_backend_env() -> None:
    """从仓库根目录运行时加载 backend/.env 环境变量。

    pydantic-settings 从当前工作目录解析相对路径的 env_file，
    因此 `python backend/scripts/build_sessions.py` 可能找不到 backend/.env。
    此函数手动解析 .env 文件并注入 os.environ，确保数据库连接配置正确加载。
    """
    env_file = ROOT / ".env"
    if not env_file.exists():
        return

    for raw_line in env_file.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        # 跳过空行、注释行和无效格式行
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        # setdefault 确保不覆盖已通过命令行设置的环境变量
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


# 在导入数据库模块之前加载环境变量，确保配置可用
load_backend_env()

from app.db.database import SessionLocal  # noqa: E402
from app.models.checkin import Checkin  # noqa: E402
from app.models.poi import Poi  # noqa: E402

# 会话切分的时间阈值：24 小时
SESSION_GAP = timedelta(hours=24)
# 有效会话的最少签到次数
MIN_SESSION_LENGTH = 2


@dataclass(slots=True)
class BuiltSession:
    """构建完成的会话数据结构。

    包含会话标识和所属签到列表，通过 property 提供派生时间属性。
    """

    session_id: str
    user_id: str
    checkins: list[Checkin]

    @property
    def start_time(self) -> datetime:
        """会话起始时间：第一次签到的 UTC 时间。"""
        return self.checkins[0].utc_timestamp

    @property
    def end_time(self) -> datetime:
        """会话结束时间：最后一次签到的 UTC 时间。"""
        return self.checkins[-1].utc_timestamp

    @property
    def checkin_count(self) -> int:
        """会话内的签到次数。"""
        return len(self.checkins)


@dataclass(slots=True)
class BuildResult:
    """会话构建结果统计。

    包含成功构建的会话列表和丢弃的段/签到数量，用于质量控制。
    """

    sessions: list[BuiltSession]
    # 因签到数不足 MIN_SESSION_LENGTH 而被丢弃的会话段数量
    discarded_single_segments: int
    # 被丢弃段中包含的签到总数
    discarded_checkins: int


def parse_args() -> argparse.Namespace:
    """解析命令行参数。

    支持指定数据集标签、输出目录和试运行模式。
    """
    parser = argparse.ArgumentParser(
        description="Build stable sessions from check-ins and export CSV files.",
    )
    parser.add_argument(
        "--dataset",
        default="TKY",
        help="Dataset label used in generated session IDs and CSV rows.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "exports",
        help="Directory for generated CSV files. Default: backend/exports.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute statistics without writing CSV files.",
    )
    return parser.parse_args()


def normalize_dataset(dataset: str) -> str:
    """规范化数据集标签：去空白并转为大写。

    空字符串会触发 ValueError，确保数据集标签始终有效。
    """
    normalized = dataset.strip().upper()
    if not normalized:
        raise ValueError("dataset must not be empty")
    return normalized


def build_session_id(
    dataset: str,
    user_id: str,
    session_index: int,
) -> str:
    """生成全局唯一的会话 ID。

    格式：{数据集}_{用户ID}_{5位序号}
    例如：TKY_user123_00001
    """
    return f"{dataset}_{user_id}_{session_index:05d}"


def build_sessions(
    checkins: list[Checkin],
    dataset: str,
) -> BuildResult:
    """核心会话构建算法：将签到列表按 24 小时间隔切分为会话。

    算法步骤：
    1. 按 user_id 分组签到记录。
    2. 每组内按时间排序后，遍历相邻签到的时间间隔。
    3. 间隔超过 SESSION_GAP（24小时）则在此处切分。
    4. 段长度 >= MIN_SESSION_LENGTH（2）的保留为有效会话。
    5. 更短的段被丢弃并统计。

    Args:
        checkins: 从数据库加载的签到 ORM 对象列表。
        dataset: 数据集标签。

    Returns:
        BuildResult 包含有效会话列表和丢弃统计。
    """
    # 按 user_id 分组签到记录
    grouped: dict[str, list[Checkin]] = defaultdict(list)

    for checkin in checkins:
        grouped[checkin.user_id].append(checkin)

    sessions: list[BuiltSession] = []
    discarded_single_segments = 0
    discarded_checkins = 0

    # 按用户排序以保证可复现性
    for user_id in sorted(grouped):
        # 用户内按时间和 ID 排序，确保确定性顺序
        user_checkins = sorted(
            grouped[user_id],
            key=lambda item: (
                item.utc_timestamp,
                item.id,
            ),
        )

        segment_start = 0
        valid_session_index = 1

        # 遍历签到序列，在相邻间隔 > 24h 处切分会话
        for index in range(1, len(user_checkins)):
            previous_checkin = user_checkins[index - 1]
            current_checkin = user_checkins[index]
            gap = current_checkin.utc_timestamp - previous_checkin.utc_timestamp

            if gap > SESSION_GAP:
                # 提取从 segment_start 到 index-1 的签到段
                segment = user_checkins[segment_start:index]
                if len(segment) >= MIN_SESSION_LENGTH:
                    sessions.append(
                        BuiltSession(
                            session_id=build_session_id(
                                dataset=dataset,
                                user_id=user_id,
                                session_index=valid_session_index,
                            ),
                            user_id=user_id,
                            checkins=segment,
                        ),
                    )
                    valid_session_index += 1
                else:
                    # 记录被丢弃的单签到段
                    discarded_single_segments += 1
                    discarded_checkins += len(segment)

                segment_start = index

        # 处理最后一段（从最后一个切分点到末尾）
        final_segment = user_checkins[segment_start:]
        if len(final_segment) >= MIN_SESSION_LENGTH:
            sessions.append(
                BuiltSession(
                    session_id=build_session_id(
                        dataset=dataset,
                        user_id=user_id,
                        session_index=valid_session_index,
                    ),
                    user_id=user_id,
                    checkins=final_segment,
                ),
            )
        elif final_segment:
            discarded_single_segments += 1
            discarded_checkins += len(final_segment)

    return BuildResult(
        sessions=sessions,
        discarded_single_segments=discarded_single_segments,
        discarded_checkins=discarded_checkins,
    )


def print_stats(
    user_count: int,
    checkin_count: int,
    build_result: BuildResult,
    missing_poi_count: int,
) -> None:
    """打印会话构建的统计摘要信息。

    输出包括用户数、签到数、有效会话数、平均会话长度、最大/最小长度等，
    用于快速评估数据质量和构建结果。
    """
    sessions = build_result.sessions
    lengths = [session.checkin_count for session in sessions]
    session_count = len(sessions)
    assigned_checkin_count = sum(lengths)
    average_length = assigned_checkin_count / session_count if session_count else 0

    print(f"users: {user_count}")
    print(f"checkins: {checkin_count}")
    print(f"valid_sessions: {session_count}")
    print(f"assigned_checkins: {assigned_checkin_count}")
    print(f"discarded_single_segments: {build_result.discarded_single_segments}")
    print(f"discarded_checkins: {build_result.discarded_checkins}")
    print(f"average_session_length: {average_length:.2f}")
    print(f"min_session_length: {min(lengths) if lengths else 0}")
    print(f"max_session_length: {max(lengths) if lengths else 0}")
    print(f"checkins_without_poi: {missing_poi_count}")


def isoformat(value: datetime) -> str:
    """将 datetime 对象转为 ISO 8601 格式字符串，用于 CSV 导出。"""
    return value.isoformat()


def write_csv_outputs(
    output_dir: Path,
    dataset: str,
    sessions: list[BuiltSession],
) -> tuple[Path, Path]:
    """将构建的会话写入 CSV 文件。

    生成两个 CSV 文件：
    1. sessions_{dataset}.csv: 会话摘要（ID、时间范围、签到数）
    2. session_points_{dataset}.csv: 每个会话的签到点序列

    Args:
        output_dir: 输出目录。
        dataset: 数据集标签。
        sessions: 构建完成的会话列表。

    Returns:
        (会话文件路径, 轨迹点文件路径) 元组。
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    session_file = output_dir / f"sessions_{dataset}.csv"
    point_file = output_dir / f"session_points_{dataset}.csv"

    # 写入会话摘要 CSV
    with session_file.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=[
                "dataset",
                "session_id",
                "user_id",
                "start_time",
                "end_time",
                "checkin_count",
            ],
        )
        writer.writeheader()
        for session in sessions:
            writer.writerow(
                {
                    "dataset": dataset,
                    "session_id": session.session_id,
                    "user_id": session.user_id,
                    "start_time": isoformat(session.start_time),
                    "end_time": isoformat(session.end_time),
                    "checkin_count": session.checkin_count,
                },
            )

    # 写入轨迹点 CSV
    with point_file.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=[
                "dataset",
                "session_id",
                "user_id",
                "sequence_no",
                "checkin_id",
                "venue_id",
                "timezone_offset",
                "utc_timestamp",
            ],
        )
        writer.writeheader()
        for session in sessions:
            for sequence_no, checkin in enumerate(session.checkins, start=1):
                writer.writerow(
                    {
                        "dataset": dataset,
                        "session_id": session.session_id,
                        "user_id": session.user_id,
                        "sequence_no": sequence_no,
                        "checkin_id": checkin.id,
                        "venue_id": checkin.venue_id,
                        "timezone_offset": checkin.timezone_offset,
                        "utc_timestamp": isoformat(checkin.utc_timestamp),
                    },
                )

    return session_file, point_file


def main() -> None:
    """脚本主入口：加载签到数据、构建会话、输出统计和 CSV。

    流程：
    1. 解析命令行参数
    2. 连接数据库加载所有签到记录
    3. 统计无 POI 对应的签到数量
    4. 按 24 小时规则构建会话
    5. 输出统计信息
    6. 除非 dry-run 模式，否则写入 CSV 文件
    """
    args = parse_args()
    dataset = normalize_dataset(args.dataset)

    try:
        with SessionLocal() as db:
            # 按用户和时间顺序加载所有签到记录
            checkins = list(
                db.scalars(
                    select(Checkin).order_by(
                        Checkin.user_id.asc(),
                        Checkin.utc_timestamp.asc(),
                        Checkin.id.asc(),
                    ),
                ).all(),
            )

            # 统计没有对应 POI 记录的签到（数据质量问题）
            missing_poi_count = (
                db.scalar(
                    select(func.count())
                    .select_from(Checkin)
                    .outerjoin(
                        Poi,
                        Checkin.venue_id == Poi.venue_id,
                    )
                    .where(Poi.venue_id.is_(None)),
                )
                or 0
            )
    except SQLAlchemyError as exc:
        print("database_error: failed to read checkins from PostgreSQL")
        print(f"detail: {exc.__class__.__name__}: {exc}")
        raise SystemExit(1) from exc

    # 执行会话构建核心算法
    build_result = build_sessions(
        checkins=checkins,
        dataset=dataset,
    )
    user_count = len({checkin.user_id for checkin in checkins})

    # 输出构建统计
    print_stats(
        user_count=user_count,
        checkin_count=len(checkins),
        build_result=build_result,
        missing_poi_count=missing_poi_count,
    )

    # dry-run 模式下只输出统计，不写入文件
    if args.dry_run:
        print("dry_run: true")
        print("csv_written: false")
        return

    # 写入 CSV 导出文件
    session_file, point_file = write_csv_outputs(
        output_dir=args.output_dir,
        dataset=dataset,
        sessions=build_result.sessions,
    )

    print("dry_run: false")
    print("csv_written: true")
    print(f"sessions_csv: {session_file}")
    print(f"session_points_csv: {point_file}")


if __name__ == "__main__":
    main()
