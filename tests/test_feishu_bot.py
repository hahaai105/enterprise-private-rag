"""飞书机器人 Mock 测试：消息解析、单聊过滤、RAG 调用、回复与去重。"""

import json
from dataclasses import dataclass, field

from app.feishu_bot import (
    EMPTY_TEXT_HINT,
    ERROR_HINT,
    KB_NOT_READY_HINT,
    TEXT_ONLY_HINT,
    FeishuMessageHandler,
    IncomingMessage,
    build_reply_fn,
    build_reply_text,
    make_answer_fn,
    parse_message_event,
    parse_text_content,
)
from app.graph import build_graph
from app.rag import KnowledgeBaseNotReadyError
from tests.conftest import FakeChatModel, FakeRetriever, make_chunk

TEXT_CONTENT = '{"text":"员工年假有多少天？"}'


@dataclass
class FakeHeader:
    event_id: str = "evt-1"


@dataclass
class FakeUserId:
    open_id: str = "ou_finance_demo"


@dataclass
class FakeSender:
    sender_type: str = "user"
    sender_id: FakeUserId = field(default_factory=FakeUserId)


@dataclass
class FakeEventMessage:
    message_id: str = "om_1"
    chat_id: str = "oc_1"
    chat_type: str = "p2p"
    message_type: str = "text"
    content: str = TEXT_CONTENT


@dataclass
class FakeEventBody:
    sender: FakeSender = field(default_factory=FakeSender)
    message: FakeEventMessage = field(default_factory=FakeEventMessage)


@dataclass
class FakeEvent:
    header: FakeHeader = field(default_factory=FakeHeader)
    event: FakeEventBody | None = field(default_factory=FakeEventBody)


class ImmediateExecutor:
    """测试用同步执行器，提交后立即执行。"""

    def submit(self, fn, *args, **kwargs):
        fn(*args, **kwargs)

    def shutdown(self, wait=True, cancel_futures=False):
        return None


class DeferredExecutor:
    """记录任务但不执行，用于验证事件回调不会阻塞。"""

    def __init__(self):
        self.tasks = []

    def submit(self, fn, *args, **kwargs):
        self.tasks.append((fn, args, kwargs))

    def shutdown(self, wait=True, cancel_futures=False):
        return None


class ReplyRecorder:
    def __init__(self):
        self.calls: list[tuple[str, str]] = []

    def __call__(self, message_id: str, text: str) -> None:
        self.calls.append((message_id, text))


def make_handler(answer, executor=None, department_for=None):
    replies = ReplyRecorder()
    handler = FeishuMessageHandler(
        answer=answer,
        reply=replies,
        executor=executor or ImmediateExecutor(),
        department_for=department_for,
    )
    return handler, replies


def test_parse_message_event_extracts_text_and_metadata():
    event = FakeEvent(
        header=FakeHeader(event_id="evt-42"),
        event=FakeEventBody(
            message=FakeEventMessage(
                message_id="om_42",
                chat_id="oc_42",
                content='{"text":"  年假有几天？  "}',
            )
        ),
    )

    message = parse_message_event(event)

    assert message == IncomingMessage(
        event_id="evt-42",
        message_id="om_42",
        chat_id="oc_42",
        chat_type="p2p",
        message_type="text",
        sender_type="user",
        sender_id="ou_finance_demo",
        text="年假有几天？",
    )


def test_parse_message_event_handles_missing_body_and_invalid_content():
    assert parse_message_event(FakeEvent(event=None)) is None
    assert parse_text_content(None) == ""
    assert parse_text_content("不是 JSON") == ""
    assert parse_text_content('{"image_key":"img_1"}') == ""


def test_handler_uses_existing_rag_graph_and_replies_with_sources():
    model = FakeChatModel(answer="员工年假为 7 天。")
    retriever = FakeRetriever([make_chunk()])
    handler, replies = make_handler(make_answer_fn(build_graph(model, retriever)))

    handler.handle(FakeEvent())

    assert retriever.questions == ["员工年假有多少天？"]
    assert retriever.departments == ["finance"]
    assert len(model.calls) == 1
    assert len(replies.calls) == 1
    message_id, text = replies.calls[0]
    assert message_id == "om_1"
    assert "员工年假为 7 天。" in text
    assert "参考来源：" in text
    assert "【请假与考勤制度】" in text
    assert "XC-HR-002" in text
    assert "0.82" in text


def test_handler_maps_sender_open_id_to_department():
    departments = []

    def answer(question, department):
        departments.append(department)
        return "答案", []

    handler, replies = make_handler(answer)

    handler.handle(FakeEvent())  # 默认发送者 ou_finance_demo

    assert departments == ["finance"]
    assert replies.calls == [("om_1", "答案")]


def test_handler_uses_public_for_unknown_sender():
    departments = []

    def answer(question, department):
        departments.append(department)
        return "答案", []

    handler, _ = make_handler(answer)

    handler.handle(
        FakeEvent(
            event=FakeEventBody(
                sender=FakeSender(sender_id=FakeUserId(open_id="ou_stranger")),
            )
        )
    )

    assert departments == ["public"]


def test_handler_accepts_custom_department_mapping():
    departments = []
    handler, _ = make_handler(
        lambda question, department: departments.append(department) or ("答案", []),
        department_for=lambda user_id: "hr" if user_id == "ou_custom" else "public",
    )

    handler.handle(
        FakeEvent(
            event=FakeEventBody(
                sender=FakeSender(sender_id=FakeUserId(open_id="ou_custom")),
            )
        )
    )

    assert departments == ["hr"]


def test_handler_returns_no_context_answer_without_calling_model():
    model = FakeChatModel()
    retriever = FakeRetriever([])
    handler, replies = make_handler(make_answer_fn(build_graph(model, retriever)))

    handler.handle(FakeEvent())

    assert "知识库中未找到相关依据" in replies.calls[0][1]
    assert "参考来源" not in replies.calls[0][1]
    assert model.calls == []


def test_handler_ignores_duplicate_events_and_repeated_message():
    questions = []

    def answer(question, department):
        questions.append(question)
        return "答案", []

    handler, replies = make_handler(answer)

    handler.handle(FakeEvent())
    handler.handle(FakeEvent())  # 同一 event_id 重投
    handler.handle(FakeEvent(header=FakeHeader(event_id="evt-2")))  # 同一条消息换 event_id

    assert questions == ["员工年假有多少天？"]
    assert len(replies.calls) == 1


def test_handler_ignores_bot_messages_and_group_messages():
    questions = []

    def answer(question, department):
        questions.append(question)
        return "答案", []

    handler, replies = make_handler(answer)

    handler.handle(
        FakeEvent(
            header=FakeHeader(event_id="evt-bot"),
            event=FakeEventBody(
                sender=FakeSender(sender_type="app"),
                message=FakeEventMessage(message_id="om_bot"),
            ),
        )
    )
    handler.handle(
        FakeEvent(
            header=FakeHeader(event_id="evt-group"),
            event=FakeEventBody(
                message=FakeEventMessage(message_id="om_group", chat_type="group"),
            ),
        )
    )

    assert questions == []
    assert replies.calls == []


def test_handler_prompts_for_non_text_message():
    questions = []
    handler, replies = make_handler(
        lambda question, department: questions.append(question) or ("答案", [])
    )

    handler.handle(
        FakeEvent(
            event=FakeEventBody(
                message=FakeEventMessage(
                    message_type="image",
                    content='{"image_key":"img_1"}',
                )
            )
        )
    )

    assert questions == []
    assert replies.calls == [("om_1", TEXT_ONLY_HINT)]


def test_handler_prompts_for_empty_text():
    questions = []
    handler, replies = make_handler(
        lambda question, department: questions.append(question) or ("答案", [])
    )

    handler.handle(
        FakeEvent(
            event=FakeEventBody(
                message=FakeEventMessage(content='{"text":"   "}'),
            )
        )
    )

    assert questions == []
    assert replies.calls == [("om_1", EMPTY_TEXT_HINT)]


def test_handler_reports_knowledge_base_not_ready():
    def answer(question, department):
        raise KnowledgeBaseNotReadyError("未初始化")

    handler, replies = make_handler(answer)

    handler.handle(FakeEvent())

    assert replies.calls == [("om_1", KB_NOT_READY_HINT)]


def test_handler_reports_rag_failure_without_raising():
    def answer(question, department):
        raise RuntimeError("upstream boom")

    handler, replies = make_handler(answer)

    handler.handle(FakeEvent())

    assert replies.calls == [("om_1", ERROR_HINT)]


def test_handler_returns_before_rag_finishes():
    executor = DeferredExecutor()
    handler, replies = make_handler(
        lambda question, department: ("答案", []), executor=executor
    )

    handler.handle(FakeEvent())

    # 回调立即返回，任务已投递但尚未执行
    assert len(executor.tasks) == 1
    assert replies.calls == []

    fn, args, kwargs = executor.tasks[0]
    fn(*args, **kwargs)

    assert replies.calls == [("om_1", "答案")]


def test_build_reply_text_formats_sources_and_handles_empty():
    assert build_reply_text("答案", []) == "答案"

    text = build_reply_text(
        "答案",
        [
            {"title": "请假与考勤制度", "doc_id": "XC-HR-002", "score": 0.6224},
            {"title": "员工手册", "doc_id": "XC-HR-001", "score": 0.5653},
        ],
    )

    assert text.startswith("答案\n\n参考来源：")
    assert "1. 【请假与考勤制度】（XC-HR-002） 相似度 0.62" in text
    assert "2. 【员工手册】（XC-HR-001） 相似度 0.57" in text


def test_build_reply_fn_sends_text_reply_to_message():
    class FakeResponse:
        code = 0
        msg = "ok"

        def success(self):
            return True

    class FakeMessageResource:
        def __init__(self):
            self.requests = []

        def reply(self, request):
            self.requests.append(request)
            return FakeResponse()

    class FakeV1:
        def __init__(self):
            self.message = FakeMessageResource()

    class FakeIm:
        def __init__(self):
            self.v1 = FakeV1()

    class FakeClient:
        def __init__(self):
            self.im = FakeIm()

    client = FakeClient()
    reply = build_reply_fn(client)

    reply("om_123", "员工年假为 7 天。")

    request = client.im.v1.message.requests[0]
    assert request.message_id == "om_123"
    assert request.request_body.msg_type == "text"
    assert json.loads(request.request_body.content) == {"text": "员工年假为 7 天。"}
