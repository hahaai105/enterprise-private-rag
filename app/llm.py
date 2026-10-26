"""构建 DeepSeek 聊天模型。

DeepSeek 兼容 OpenAI 协议，因此直接复用 langchain-openai 的 ChatOpenAI，
只需要把 base_url 指向 DeepSeek 即可。
"""

from langchain_openai import ChatOpenAI

from .config import Settings


class MissingApiKeyError(RuntimeError):
    """未配置 DEEPSEEK_API_KEY 时抛出。"""


def build_chat_model(settings: Settings) -> ChatOpenAI:
    if not settings.deepseek_api_key.strip():
        raise MissingApiKeyError("未配置 DEEPSEEK_API_KEY")

    return ChatOpenAI(
        model=settings.deepseek_model,
        api_key=settings.deepseek_api_key,
        base_url=settings.deepseek_base_url,
        timeout=settings.request_timeout,
        max_retries=1,
    )
