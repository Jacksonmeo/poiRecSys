"""Read-only Sprint 0 integrity audit for retail site-selection source data.

The script opens one PostgreSQL transaction, marks it READ ONLY before issuing
audit queries, and writes both JSON and Markdown reports. It never creates,
updates, or deletes database objects or rows.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import ValidationError
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import SQLAlchemyError

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = BACKEND_ROOT.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.site_selection_config_service import (  # noqa: E402
    CONFIG_DIRECTORY,
    SiteSelectionConfigError,
    load_site_selection_config,
)

try:  # Importing application settings validates the required DATABASE_URL.
    from app.core.config import settings  # noqa: E402
except ValidationError:
    settings = None

DEFAULT_REPORT_DIRECTORY = (
    REPOSITORY_ROOT / "docs" / "retail_site_selection_sprint0"
)
DEFAULT_JSON_OUTPUT = DEFAULT_REPORT_DIRECTORY / "data_integrity_report.json"
DEFAULT_MARKDOWN_OUTPUT = DEFAULT_REPORT_DIRECTORY / "data_integrity_report.md"

CRITICAL_BTREE_INDEX_REQUIREMENTS = (
    ("pois_venue_id", "pois", ("venue_id",)),
    ("pois_venue_category", "pois", ("venue_category",)),
    ("checkins_user_id", "checkins", ("user_id",)),
    ("checkins_venue_id", "checkins", ("venue_id",)),
    ("checkins_utc_timestamp", "checkins", ("utc_timestamp",)),
    ("checkins_session_id", "checkins", ("session_id",)),
    (
        "checkins_session_sequence",
        "checkins",
        ("session_id", "sequence_no"),
    ),
    ("sessions_session_id", "sessions", ("session_id",)),
    ("sessions_user_id", "sessions", ("user_id",)),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Audit site-selection source data without modifying PostgreSQL."
    )
    parser.add_argument(
        "--config-version",
        default="tokyo_coffee_v1",
        help="Exact version to audit. Unknown versions are rejected.",
    )
    parser.add_argument(
        "--json-output",
        type=Path,
        default=DEFAULT_JSON_OUTPUT,
        help="JSON report path.",
    )
    parser.add_argument(
        "--markdown-output",
        type=Path,
        default=DEFAULT_MARKDOWN_OUTPUT,
        help="Markdown report path.",
    )
    return parser.parse_args()


def scalar_count(connection: Connection, sql: str) -> int:
    return int(connection.execute(text(sql)).scalar_one())


def completeness(non_null_count: int, total_count: int) -> dict[str, int | float]:
    ratio = non_null_count / total_count if total_count else 0.0
    return {
        "non_null_count": non_null_count,
        "total_count": total_count,
        "ratio": round(ratio, 6),
    }


def load_indexes(connection: Connection) -> list[dict[str, Any]]:
    rows = connection.execute(
        text(
            """
            SELECT
                table_class.relname AS table_name,
                index_class.relname AS index_name,
                access_method.amname AS access_method,
                index_meta.indisunique AS is_unique,
                array_agg(attribute.attname ORDER BY key_part.ordinality)
                    FILTER (WHERE attribute.attname IS NOT NULL) AS columns
            FROM pg_index AS index_meta
            JOIN pg_class AS table_class
                ON table_class.oid = index_meta.indrelid
            JOIN pg_namespace AS namespace
                ON namespace.oid = table_class.relnamespace
            JOIN pg_class AS index_class
                ON index_class.oid = index_meta.indexrelid
            JOIN pg_am AS access_method
                ON access_method.oid = index_class.relam
            CROSS JOIN LATERAL unnest(index_meta.indkey)
                WITH ORDINALITY AS key_part(attnum, ordinality)
            LEFT JOIN pg_attribute AS attribute
                ON attribute.attrelid = table_class.oid
                AND attribute.attnum = key_part.attnum
            WHERE namespace.nspname = current_schema()
              AND table_class.relname IN ('pois', 'checkins', 'sessions')
            GROUP BY
                table_class.relname,
                index_class.relname,
                access_method.amname,
                index_meta.indisunique
            ORDER BY table_class.relname, index_class.relname
            """
        )
    ).mappings()
    return [
        {
            "table": row["table_name"],
            "name": row["index_name"],
            "access_method": row["access_method"],
            "is_unique": bool(row["is_unique"]),
            "columns": list(row["columns"] or []),
        }
        for row in rows
    ]


def audit_indexes(indexes: list[dict[str, Any]]) -> dict[str, Any]:
    gist_matches = [
        index["name"]
        for index in indexes
        if index["table"] == "pois"
        and index["access_method"] == "gist"
        and "geom" in index["columns"]
    ]

    critical_indexes = []
    for requirement_id, table_name, required_columns in (
        CRITICAL_BTREE_INDEX_REQUIREMENTS
    ):
        matching_indexes = [
            index["name"]
            for index in indexes
            if index["table"] == table_name
            and index["access_method"] == "btree"
            and tuple(index["columns"][: len(required_columns)]) == required_columns
        ]
        critical_indexes.append(
            {
                "requirement_id": requirement_id,
                "table": table_name,
                "columns": list(required_columns),
                "exists": bool(matching_indexes),
                "matching_indexes": matching_indexes,
            }
        )

    return {
        "pois_geom_gist": {
            "exists": bool(gist_matches),
            "matching_indexes": gist_matches,
        },
        "critical_btree": critical_indexes,
        "all_critical_btree_indexes_exist": all(
            item["exists"] for item in critical_indexes
        ),
    }


def audit_candidate_area(
    connection: Connection,
    area: Any,
    competitor_categories: list[str],
) -> dict[str, int]:
    polygon_geojson = json.dumps(
        area.polygon.model_dump(mode="json"), ensure_ascii=False
    )
    poi_row = connection.execute(
        text(
            """
            SELECT
                COUNT(p.id) AS poi_count,
                COUNT(p.id) FILTER (
                    WHERE p.venue_category = ANY(:competitor_categories)
                ) AS competitor_count
            FROM pois AS p
            WHERE ST_Covers(
                ST_SetSRID(ST_GeomFromGeoJSON(:polygon_geojson), 4326),
                p.geom
            )
            """
        ),
        {
            "polygon_geojson": polygon_geojson,
            "competitor_categories": competitor_categories,
        },
    ).mappings().one()
    historical_checkin_count = connection.execute(
        text(
            """
            SELECT COUNT(c.id)
            FROM checkins AS c
            JOIN pois AS p ON p.venue_id = c.venue_id
            WHERE ST_Covers(
                ST_SetSRID(ST_GeomFromGeoJSON(:polygon_geojson), 4326),
                p.geom
            )
            """
        ),
        {"polygon_geojson": polygon_geojson},
    ).scalar_one()
    return {
        "poi_count": int(poi_row["poi_count"]),
        "coffee_shop_and_cafe_count": int(poi_row["competitor_count"]),
        "historical_checkin_count": int(historical_checkin_count),
    }


def _database_context(connection: Connection) -> dict[str, Any]:
    """查询数据库名称/模式/版本/事务上下文。"""
    return dict(
        connection.execute(
            text(
                """
                SELECT
                    current_database() AS database_name,
                    current_schema() AS schema_name,
                    current_setting('server_version') AS server_version,
                    current_setting('transaction_isolation') AS transaction_isolation,
                    txid_current_snapshot()::text AS transaction_snapshot
                """
            )
        ).mappings().one()
    )


def _table_counts(connection: Connection) -> dict[str, int]:
    """统计三张核心表的行数。"""
    return {
        "pois": scalar_count(connection, "SELECT COUNT(1) FROM pois"),
        "checkins": scalar_count(connection, "SELECT COUNT(1) FROM checkins"),
        "sessions": scalar_count(connection, "SELECT COUNT(1) FROM sessions"),
    }


def _checkin_completeness(
    connection: Connection, checkins_count: int
) -> dict[str, Any]:
    """统计 checkins 关键字段非空率与 session 字段联合分布。"""
    session_id_non_null = scalar_count(
        connection, "SELECT COUNT(1) FROM checkins WHERE session_id IS NOT NULL"
    )
    sequence_no_non_null = scalar_count(
        connection, "SELECT COUNT(1) FROM checkins WHERE sequence_no IS NOT NULL"
    )
    assignment = connection.execute(
        text(
            """
            SELECT
                COUNT(1) FILTER (
                    WHERE session_id IS NOT NULL AND sequence_no IS NOT NULL
                ) AS both_non_null,
                COUNT(1) FILTER (
                    WHERE session_id IS NULL AND sequence_no IS NULL
                ) AS both_null,
                COUNT(1) FILTER (
                    WHERE session_id IS NOT NULL AND sequence_no IS NULL
                ) AS session_id_only,
                COUNT(1) FILTER (
                    WHERE session_id IS NULL AND sequence_no IS NOT NULL
                ) AS sequence_no_only
            FROM checkins
            """
        )
    ).mappings().one()
    return {
        "field_completeness": {
            "session_id": completeness(session_id_non_null, checkins_count),
            "sequence_no": completeness(sequence_no_non_null, checkins_count),
        },
        "assignment_distribution": {
            key: int(assignment[key])
            for key in (
                "both_non_null",
                "both_null",
                "session_id_only",
                "sequence_no_only",
            )
        },
    }


def _integrity_counts(connection: Connection) -> dict[str, int]:
    """统计 session 数量不一致与无法关联 POI 的孤儿 checkin。"""
    session_count_mismatch = scalar_count(
        connection,
        """
        SELECT COUNT(1)
        FROM (
            SELECT s.session_id
            FROM sessions AS s
            LEFT JOIN checkins AS c ON c.session_id = s.session_id
            GROUP BY s.session_id, s.checkin_count
            HAVING COUNT(c.id) <> s.checkin_count
        ) AS mismatches
        """,
    )
    orphan_checkins = scalar_count(
        connection,
        """
        SELECT COUNT(1)
        FROM checkins AS c
        LEFT JOIN pois AS p ON p.venue_id = c.venue_id
        WHERE p.venue_id IS NULL
        """,
    )
    return {
        "session_checkin_count_mismatch_count": session_count_mismatch,
        "checkins_without_poi_count": orphan_checkins,
    }


def run_audit(
    connection: Connection,
    config: Any,
    config_sha256: str,
    audit_script_sha256: str,
) -> dict[str, Any]:
    """执行只读数据完整性审计并汇总报告。"""
    counts = _table_counts(connection)
    completeness_report = _checkin_completeness(connection, counts["checkins"])
    integrity = _integrity_counts(connection)
    candidate_areas = {
        area.area_id: audit_candidate_area(
            connection, area, config.competitor_categories
        )
        for area in config.candidate_areas
    }
    indexes = audit_indexes(load_indexes(connection))

    return {
        "audit_version": "site_selection_data_audit_v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "database_status": "available",
        "read_only_transaction": True,
        "config_version": config.config_version,
        "config_sha256": config_sha256,
        "audit_script_sha256": audit_script_sha256,
        "dataset": config.dataset.sample_description,
        "database_context": _database_context(connection),
        "counts": counts,
        "checkin_field_completeness": completeness_report["field_completeness"],
        "checkin_assignment_field_distribution": completeness_report[
            "assignment_distribution"
        ],
        "session_checkin_count_mismatch_count": integrity[
            "session_checkin_count_mismatch_count"
        ],
        "checkins_without_poi_count": integrity["checkins_without_poi_count"],
        "candidate_areas": candidate_areas,
        "indexes": indexes,
    }


def _markdown_header(report: dict[str, Any]) -> list[str]:
    """生成报告头部：生成时间、版本、哈希与数据库上下文。"""
    database_context = report["database_context"]
    return [
        "# GeoAgent Sprint 0 数据完整性核验报告",
        "",
        f"- 生成时间（UTC）：`{report['generated_at']}`",
        f"- 配置版本：`{report['config_version']}`",
        f"- 配置 SHA-256：`{report['config_sha256']}`",
        f"- 审计脚本 SHA-256：`{report['audit_script_sha256']}`",
        f"- 数据口径：{report['dataset']}",
        "- 数据库状态：可用",
        (
            "- 数据库上下文："
            f"`{database_context['database_name']}` / "
            f"`{database_context['schema_name']}` / "
            f"PostgreSQL `{database_context['server_version']}`"
        ),
        (
            "- 事务上下文："
            f"`{database_context['transaction_isolation']}` / snapshot "
            f"`{database_context['transaction_snapshot']}`"
        ),
        "- 执行方式：单事务 `READ ONLY`；未修改数据库",
    ]


def _markdown_counts_section(report: dict[str, Any]) -> list[str]:
    """生成总量与完整性章节。"""
    counts = report["counts"]
    session_id = report["checkin_field_completeness"]["session_id"]
    sequence_no = report["checkin_field_completeness"]["sequence_no"]
    return [
        "## 总量与完整性",
        "",
        "| 核验项 | 结果 |",
        "|---|---:|",
        f"| POI 总数 | {counts['pois']:,} |",
        f"| checkin 总数 | {counts['checkins']:,} |",
        f"| session 总数 | {counts['sessions']:,} |",
        (
            "| `checkins.session_id` 非空 | "
            f"{session_id['non_null_count']:,} / {session_id['total_count']:,} "
            f"({session_id['ratio']:.2%}) |"
        ),
        (
            "| `checkins.sequence_no` 非空 | "
            f"{sequence_no['non_null_count']:,} / {sequence_no['total_count']:,} "
            f"({sequence_no['ratio']:.2%}) |"
        ),
        (
            "| session 实际 checkin 数与 `sessions.checkin_count` 不一致数量 | "
            f"{report['session_checkin_count_mismatch_count']:,} |"
        ),
        f"| 无法关联 POI 的 checkin 数量 | {report['checkins_without_poi_count']:,} |",
    ]


def _markdown_assignment_section(report: dict[str, Any]) -> list[str]:
    """生成 session 字段联合分布章节。"""
    assignment = report["checkin_assignment_field_distribution"]
    return [
        "### session 字段联合分布",
        "",
        "| `session_id` | `sequence_no` | checkin 数量 |",
        "|---|---|---:|",
        f"| 非空 | 非空 | {assignment['both_non_null']:,} |",
        f"| 空 | 空 | {assignment['both_null']:,} |",
        f"| 非空 | 空 | {assignment['session_id_only']:,} |",
        f"| 空 | 非空 | {assignment['sequence_no_only']:,} |",
    ]


def _markdown_areas_section(report: dict[str, Any]) -> list[str]:
    """生成候选分析区统计章节。"""
    lines = [
        "## 统一 1 km 候选分析区",
        "",
        "以下统计使用配置中由站点中心和统一 1,000 米半径生成的 Polygon。",
        "",
        "| area_id | POI | Coffee Shop + Café | 历史签到 |",
        "|---|---:|---:|---:|",
    ]
    for area_id, area_report in report["candidate_areas"].items():
        lines.append(
            f"| `{area_id}` | {area_report['poi_count']:,} | "
            f"{area_report['coffee_shop_and_cafe_count']:,} | "
            f"{area_report['historical_checkin_count']:,} |"
        )
    return lines


def _markdown_indexes_section(report: dict[str, Any]) -> list[str]:
    """生成索引核验章节。"""
    gist = report["indexes"]["pois_geom_gist"]
    lines = [
        "## 索引核验",
        "",
        f"- `pois.geom` GIST 索引：{'存在' if gist['exists'] else '缺失'}",
        (
            "- 全部关键 B-tree 索引："
            + (
                "存在"
                if report["indexes"]["all_critical_btree_indexes_exist"]
                else "存在缺口"
            )
        ),
        "",
        "| 关键索引需求 | 表 | 列前缀 | 状态 | 匹配索引 |",
        "|---|---|---|---|---|",
    ]
    for item in report["indexes"]["critical_btree"]:
        matches = ", ".join(f"`{name}`" for name in item["matching_indexes"])
        lines.append(
            f"| `{item['requirement_id']}` | `{item['table']}` | "
            f"`{', '.join(item['columns'])}` | "
            f"{'存在' if item['exists'] else '缺失'} | {matches or '—'} |"
        )
    return lines


def _markdown_semantics_section() -> list[str]:
    """生成查询语义与解释边界章节（静态文案）。"""
    return [
        "## 查询语义",
        "",
        "- POI 总量按 `pois` 行计数；候选区计数使用 `ST_Covers`，因此包含 Polygon 边界上的点。",
        "- Coffee Shop 与 Café 使用 `venue_category` 大小写敏感的精确匹配，不做模糊归类。",
        "- 历史签到按 `checkins.venue_id = pois.venue_id` 关联后逐条计数；无法关联 POI 的记录不进入候选区计数。",
        "- session 不一致数量按每个 `sessions.session_id` 的实际关联 checkin 行数与 `checkin_count` 比较。",
        "- 索引检查接受以所需列为最左前缀的 B-tree，并单独要求 `pois.geom` 的 GIST。",
        "",
        "## 解释边界",
        "",
        "本报告只核验历史开放空间数据与签到样本的完整性和候选区内样本计数。"
        "候选区是统一规则生成的站点周边 1 km 分析区，不是官方商圈边界；"
        "这些结果不构成当前经营表现或未来结果的承诺。",
        "",
    ]


def render_markdown(report: dict[str, Any]) -> str:
    """把审计报告渲染为 Markdown 文本。"""
    sections = [
        _markdown_header(report),
        _markdown_counts_section(report),
        _markdown_assignment_section(report),
        _markdown_areas_section(report),
        _markdown_indexes_section(report),
        _markdown_semantics_section(),
    ]
    return "\n".join(line for section in sections for line in section)


def write_reports(
    report: dict[str, Any], json_output: Path, markdown_output: Path
) -> None:
    json_output.parent.mkdir(parents=True, exist_ok=True)
    markdown_output.parent.mkdir(parents=True, exist_ok=True)
    json_output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    markdown_output.write_text(render_markdown(report), encoding="utf-8")


def main() -> int:
    args = parse_args()
    try:
        if settings is None:
            print(
                "config_error: DATABASE_URL is required for the read-only audit",
                file=sys.stderr,
            )
            return 1
        config = load_site_selection_config(args.config_version)
        config_path = CONFIG_DIRECTORY / f"{args.config_version}.json"
        config_sha256 = hashlib.sha256(config_path.read_bytes()).hexdigest()
        audit_script_sha256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
        engine = create_engine(settings.database_url, pool_pre_ping=True)
        try:
            with engine.connect() as connection, connection.begin():
                connection.execute(text("SET TRANSACTION READ ONLY"))
                report = run_audit(
                    connection,
                    config,
                    config_sha256=config_sha256,
                    audit_script_sha256=audit_script_sha256,
                )
        finally:
            engine.dispose()
    except SiteSelectionConfigError as exc:
        print(f"config_error: {exc}", file=sys.stderr)
        return 1
    except SQLAlchemyError as exc:
        print(
            "database_error: unable to complete the read-only site-selection "
            f"audit ({exc.__class__.__name__})",
            file=sys.stderr,
        )
        return 1

    write_reports(report, args.json_output, args.markdown_output)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"markdown_report: {args.markdown_output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
