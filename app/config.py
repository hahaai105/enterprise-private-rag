"""应用配置：统一从环境变量或 .env 读取，禁止硬编码密钥。"""

from functools import lru_cache

from pydantic import Field
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

    # RAG 配置
    knowledge_base_dir: str = "knowledge_base"
    chroma_dir: str = "data/chroma"
    chroma_collection: str = "enterprise_knowledge_base"
    embedding_model: str = "BAAI/bge-small-zh-v1.5"
    embedding_device: str = "cpu"
    rag_top_k: int = Field(default=4, ge=1, le=20)
    rag_score_threshold: float = Field(default=0.4, ge=-1.0, le=1.0)
    chunk_size: int = Field(default=500, ge=100)
    chunk_overlap: int = Field(default=80, ge=0)


@lru_cache
def get_settings() -> Settings:
    """返回全局唯一的配置实例。"""
    return Settings()
