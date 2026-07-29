"""
将原始 POI 签到数据集拆分为用户表、POI 表和签到记录表，并导入 PostgreSQL 数据库。

功能：
  1. 读取原始 CSV 数据集
  2. 提取并去重用户信息（users 表）
  3. 提取并去重 POI 信息（pois 表）
  4. 提取签到记录并转换时间戳格式（checkins 表）
  5. 将三张表写入 PostgreSQL 数据库
"""

import pandas as pd
from sqlalchemy import create_engine

# ---------- 1. 读取原始数据集 ----------
df = pd.read_csv("dataset_TSMC2014_TKY.csv", sep=",")   # 或 sep="\t"

# ---------- 2. 提取用户表：仅保留 userId，去重后作为用户维度表 ----------
users = (
    df[["userId"]]
    .drop_duplicates()
    .rename(columns={"userId": "user_id"})
)

# ---------- 3. 提取 POI 表：保留地点属性字段，按 venueId 去重 ----------
pois = (
    df[
        [
            "venueId",
            "venueCategoryId",
            "venueCategory",
            "latitude",
            "longitude",
        ]
    ]
    .drop_duplicates(subset=["venueId"])
    .rename(
        columns={
            "venueId": "venue_id",
            "venueCategoryId": "venue_category_id",
            "venueCategory": "venue_category",
        }
    )
)

# ---------- 4. 提取签到记录表：保留用户-POI 关联及时间信息 ----------
checkins = (
    df[
        [
            "userId",
            "venueId",
            "timezoneOffset",
            "utcTimestamp",
        ]
    ]
    .rename(
        columns={
            "userId": "user_id",
            "venueId": "venue_id",
            "timezoneOffset": "timezone_offset",
            "utcTimestamp": "utc_timestamp",
        }
    )
)

# 将 UTC 时间戳字符串转换为标准 datetime 类型，以便数据库存储
checkins["utc_timestamp"] = pd.to_datetime(
    checkins["utc_timestamp"],
    utc=True,
)

# ---------- 5. 导入 PostgreSQL ----------

# 配置数据库连接参数（请按实际情况修改）
DB_CONFIG = {
    "host": "localhost",        # 数据库主机
    "port": 5432,               # 默认端口
    "database": "postgres",     # 数据库名称
    "user": "postgres",         # 用户名
    "password": "postgre"       # 密码
}

# 创建 SQLAlchemy 数据库引擎，用于与 PostgreSQL 通信
engine = create_engine(
    f"postgresql://{DB_CONFIG['user']}:{DB_CONFIG['password']}@"
    f"{DB_CONFIG['host']}:{DB_CONFIG['port']}/{DB_CONFIG['database']}"
)

# 将三张 DataFrame 写入数据库对应的表中
# if_exists='append'：追加模式，保留旧数据并在其后追加新记录（首次运行前需确保表结构已存在）
# index=False：不将 DataFrame 的行索引写入数据库
users.to_sql('users', engine, if_exists='append', index=False)
pois.to_sql('pois', engine, if_exists='append', index=False)
checkins.to_sql('checkins', engine, if_exists='append', index=False)

print("✅ 所有数据导入成功！")
