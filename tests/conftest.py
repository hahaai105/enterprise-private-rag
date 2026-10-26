"""测试公共夹具：Mock 模型、Mock 检索器与测试客户端。"""

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage

from app.config import Settings
from app.main import create_app
from app.rag import RetrievedChunk


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


class FakeRetriever:
    """模拟向量检索器，记录收到的问题与部门。"""

    def __init__(self, chunks: list[RetrievedChunk] | None = None):
        self.chunks = chunks if chunks is not None else []
        self.questions: list[str] = []
        self.departments: list[str] = []

    def search(self, question: str, department: str = "public") -> list[RetrievedChunk]:
        self.questions.append(question)
        self.departments.append(department)
        return list(self.chunks)


def make_chunk(
    text: str = "员工年假为 7 天。",
    doc_id: str = "XC-HR-002",
    title: str = "请假与考勤制度",
    source: str = "02_leave_attendance.md",
    department: str = "人力资源部",
    access_scope: str = "全体员工",
    access_group: str = "public",
    score: float = 0.82,
) -> RetrievedChunk:
    return RetrievedChunk(
        text=text,
        metadata={
            "doc_id": doc_id,
            "title": title,
            "source": source,
            "department": department,
            "access_scope": access_scope,
            "access_group": access_group,
            "classification": "内部",
            "chunk_index": 0,
        },
        score=score,
    )


def make_settings(api_key: str = "test-key", **overrides) -> Settings:
    # _env_file=None：测试完全不读取本地 .env，保证结果可重复
    return Settings(deepseek_api_key=api_key, _env_file=None, **overrides)


def make_client(graph=None, settings: Settings | None = None, retriever=None) -> TestClient:
    return TestClient(
        create_app(
            graph=graph,
            settings=settings or make_settings(),
            retriever=retriever,
        )
    )


@pytest.fixture
def fake_model() -> FakeChatModel:
    return FakeChatModel()
