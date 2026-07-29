"""应用配置：通过 pydantic-settings 从 .env / 环境变量加载配置。

数据库密码等敏感信息通过环境变量注入，绝不硬编码在代码中。
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """应用级配置，所有字段都可以通过环境变量或 .env 文件设置。

    例如：DATABASE_URL=postgresql+psycopg://user:pass@host:5432/dbname
    """

    # 数据库连接 URL，默认指向本地 PostgreSQL 的 poi_recommendation 库
    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/poi_recommendation"
    # 推荐模型名称，用于在 recommendation_results 表中筛选对应模型的推理结果
    recommendation_model_name: str = "T10e2_CausalMemoryFusion"

    # pydantic-settings 配置：自动从 .env 文件和环境变量中读取配置项
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


# 全局单例配置对象，在应用启动时完成加载
settings = Settings()
