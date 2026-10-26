"""应用配置：统一从环境变量或 .env 读取，禁止硬编码密钥。"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """DeepSeek 相关配置。字段名会自动映射为大写环境变量。"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # 不要写默认密钥，缺失时由 llm.build_chat_model 明确报错
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-chat"
    request_timeout: float = 60.0


@lru_cache
def get_settings() -> Settings:
    """返回全局唯一的配置实例。"""
    return Settings()
