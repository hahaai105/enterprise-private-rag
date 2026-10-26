from app.graph import build_graph
from tests.conftest import FakeChatModel, make_client, make_settings


def test_chat_returns_answer_via_graph(fake_model):
    client = make_client(graph=build_graph(fake_model))

    response = client.post("/chat", json={"question": "  你好  "})

    assert response.status_code == 200
    assert response.json() == {"answer": "这是测试回答。"}
    # 证明请求确实经过 LangGraph 中的节点，且问题已去除首尾空白
    assert len(fake_model.calls) == 1
    messages = fake_model.calls[0]
    assert messages[0].type == "system"
    assert messages[-1].content == "你好"


def test_chat_rejects_blank_question(fake_model):
    client = make_client(graph=build_graph(fake_model))

    response = client.post("/chat", json={"question": "   "})

    assert response.status_code == 422
    assert fake_model.calls == []


def test_chat_returns_503_without_api_key():
    client = make_client(settings=make_settings(api_key=""))

    response = client.post("/chat", json={"question": "你好"})

    assert response.status_code == 503
    assert "DEEPSEEK_API_KEY" in response.json()["detail"]


def test_chat_returns_502_when_model_fails():
    model = FakeChatModel(exc=RuntimeError("upstream boom"))
    client = make_client(graph=build_graph(model))

    response = client.post("/chat", json={"question": "你好"})

    assert response.status_code == 502
    assert response.json()["detail"] == "模型调用失败，请稍后重试"
