from app.graph import build_graph
from app.rag import KnowledgeBaseNotReadyError
from tests.conftest import (
    FakeChatModel,
    FakeRetriever,
    make_chunk,
    make_client,
    make_settings,
)


def test_chat_returns_answer_with_sources(fake_model):
    retriever = FakeRetriever([make_chunk()])
    client = make_client(graph=build_graph(fake_model, retriever))

    response = client.post("/chat", json={"question": "  年假有几天？  "})

    assert response.status_code == 200
    body = response.json()
    assert body["answer"] == "这是测试回答。"
    assert body["sources"] == [
        {
            "doc_id": "XC-HR-002",
            "title": "请假与考勤制度",
            "source": "02_leave_attendance.md",
            "department": "人力资源部",
            "access_scope": "全体员工",
            "snippet": "员工年假为 7 天。",
            "score": 0.82,
        }
    ]
    # 问题已去除首尾空白，并确实进入检索节点；未提供用户时只能访问 public
    assert retriever.questions == ["年假有几天？"]
    assert retriever.departments == ["public"]

    messages = fake_model.calls[0]
    assert messages[0].type == "system"
    assert "员工年假为 7 天。" in messages[-1].content
    assert "年假有几天？" in messages[-1].content


def test_chat_returns_no_context_answer_without_calling_model(fake_model):
    retriever = FakeRetriever([])
    client = make_client(graph=build_graph(fake_model, retriever))

    response = client.post("/chat", json={"question": "公司食堂今天有什么菜？"})

    assert response.status_code == 200
    body = response.json()
    assert "知识库中未找到相关依据" in body["answer"]
    assert body["sources"] == []
    assert retriever.questions == ["公司食堂今天有什么菜？"]
    assert fake_model.calls == []


def test_chat_rejects_blank_question(fake_model):
    retriever = FakeRetriever([make_chunk()])
    client = make_client(graph=build_graph(fake_model, retriever))

    response = client.post("/chat", json={"question": "   "})

    assert response.status_code == 422
    assert retriever.questions == []
    assert fake_model.calls == []


def test_chat_returns_503_without_api_key():
    client = make_client(
        settings=make_settings(api_key=""),
        retriever=FakeRetriever([make_chunk()]),
    )

    response = client.post("/chat", json={"question": "你好"})

    assert response.status_code == 503
    assert "DEEPSEEK_API_KEY" in response.json()["detail"]


def test_chat_returns_503_when_knowledge_base_not_ready(fake_model):
    class NotReadyRetriever:
        def search(self, question, department="public"):
            raise KnowledgeBaseNotReadyError(
                "知识库尚未初始化或为空，请先运行：uv run python -m app.ingest"
            )

    client = make_client(graph=build_graph(fake_model, NotReadyRetriever()))

    response = client.post("/chat", json={"question": "年假有几天？"})

    assert response.status_code == 503
    assert "知识库尚未初始化" in response.json()["detail"]
    assert fake_model.calls == []


def test_chat_returns_502_when_model_fails():
    model = FakeChatModel(exc=RuntimeError("upstream boom"))
    client = make_client(graph=build_graph(model, FakeRetriever([make_chunk()])))

    response = client.post("/chat", json={"question": "你好"})

    assert response.status_code == 502
    assert response.json()["detail"] == "模型调用失败，请稍后重试"


def test_chat_resolves_department_from_user_mapping(fake_model):
    retriever = FakeRetriever([make_chunk()])
    client = make_client(
        graph=build_graph(fake_model, retriever),
        settings=make_settings(
            test_user_departments={"ou_finance_demo": "finance"},
        ),
    )

    response = client.post(
        "/chat",
        json={"question": "2026 年总预算是多少？", "user_id": "ou_finance_demo"},
    )

    assert response.status_code == 200
    assert retriever.departments == ["finance"]


def test_chat_uses_public_for_unknown_user(fake_model):
    retriever = FakeRetriever([make_chunk()])
    client = make_client(graph=build_graph(fake_model, retriever))

    response = client.post(
        "/chat",
        json={"question": "2026 年总预算是多少？", "user_id": "ou_stranger"},
    )

    assert response.status_code == 200
    assert retriever.departments == ["public"]
