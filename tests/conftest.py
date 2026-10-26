"""测试公共夹具：Mock 模型 + 测试客户端。"""

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage

from app.config import Settings
from app.main import create_app


class FakeChatModel:
    """模拟聊天模型，记录收到的消息，可按需抛出异常。"""

    def __init__(self, answer: str = "这是测试回答。", exc: Exception | None = None):
        self.answer = answer
        self.exc = exc
        self.calls: list[list] = []

    async def ainvoke(self, messages):
        self.calls.append(messages)
        if self.exc is not None:
            raise self.exc
        return AIMessage(content=self.answer)


def make_settings(api_key: str = "test-key") -> Settings:
    # _env_file=None：测试完全不读取本地 .env，保证结果可重复
    return Settings(deepseek_api_key=api_key, _env_file=None)


def make_client(graph=None, settings: Settings | None = None) -> TestClient:
    return TestClient(create_app(graph=graph, settings=settings or make_settings()))


@pytest.fixture
def fake_model() -> FakeChatModel:
    return FakeChatModel()
