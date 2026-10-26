"""飞书机器人：通过官方 SDK 的 WebSocket 长连接接收单聊消息，复用现有 RAG 工作流回复。

事件回调运行在 SDK 的 asyncio 事件循环中，因此这里只做解析、去重和投递，
把耗时的检索与模型调用交给线程池，避免阻塞事件接收。
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from collections import OrderedDict
from concurrent.futures import Executor, ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Callable

from .config import Settings, get_settings
from .graph import build_graph, run_chat
from .llm import MissingApiKeyError, build_chat_model
from .permissions import department_for_user
from .rag import KnowledgeBase, KnowledgeBaseNotReadyError

logger = logging.getLogger(__name__)

TEXT_ONLY_HINT = "目前只支持文本消息，请直接发送文字问题。"
EMPTY_TEXT_HINT = "没有识别到问题内容，请重新发送文字问题。"
KB_NOT_READY_HINT = "知识库尚未初始化，请联系管理员先执行知识库初始化。"
ERROR_HINT = "抱歉，回答失败，请稍后重试。"

SEEN_LIMIT = 1000
MAX_WORKERS = 2

AnswerFn = Callable[[str, str], tuple[str, list[dict[str, Any]]]]
ReplyFn = Callable[[str, str], None]
DepartmentFn = Callable[[str | None], str]


@dataclass(frozen=True)
class IncomingMessage:
    """从飞书事件中提取出的最小消息结构。"""

    event_id: str
    message_id: str
    chat_id: str
    chat_type: str
    message_type: str
    sender_type: str
    sender_id: str
    text: str


class _RecentKeys:
    """固定容量的内存去重表，避免重复事件造成重复回复。"""

    def __init__(self, limit: int = SEEN_LIMIT) -> None:
        self._limit = limit
        self._keys: OrderedDict[str, None] = OrderedDict()
        self._lock = threading.Lock()

    def add_if_new(self, keys: tuple[str, ...]) -> bool:
        with self._lock:
            if any(key in self._keys for key in keys):
                return False
            for key in keys:
                self._keys[key] = None
            while len(self._keys) > self._limit:
                self._keys.popitem(last=False)
            return True


def parse_text_content(content: str | None) -> str:
    """飞书文本消息的 content 是 JSON 字符串，例如 {"text": "你好"}。"""
    if not content:
        return ""
    try:
        payload = json.loads(content)
    except (TypeError, ValueError):
        return ""
    if not isinstance(payload, dict):
        return ""
    return str(payload.get("text", "")).strip()


def parse_message_event(event: Any) -> IncomingMessage | None:
    """解析 SDK 的 P2ImMessageReceiveV1 事件；缺少消息体时返回 None。"""
    body = getattr(event, "event", None)
    message = getattr(body, "message", None) if body is not None else None
    if message is None:
        return None

    header = getattr(event, "header", None)
    sender = getattr(body, "sender", None)
    sender_identity = getattr(sender, "sender_id", None)
    return IncomingMessage(
        event_id=str(getattr(header, "event_id", "") or ""),
        message_id=str(getattr(message, "message_id", "") or ""),
        chat_id=str(getattr(message, "chat_id", "") or ""),
        chat_type=str(getattr(message, "chat_type", "") or ""),
        message_type=str(getattr(message, "message_type", "") or ""),
        sender_type=str(getattr(sender, "sender_type", "") or ""),
        sender_id=str(
            getattr(sender_identity, "open_id", "")
            or getattr(sender_identity, "user_id", "")
            or ""
        ),
        text=parse_text_content(getattr(message, "content", "")),
    )


def build_reply_text(answer: str, sources: list[dict[str, Any]]) -> str:
    """把答案和文档来源拼成飞书文本消息。"""
    text = answer.strip() or "知识库中未找到相关依据。"
    if not sources:
        return text

    lines = [text, "", "参考来源："]
    for index, source in enumerate(sources, start=1):
        title = str(source.get("title") or "未知文档")
        doc_id = str(source.get("doc_id") or "")
        label = f"{index}. 【{title}】"
        if doc_id:
            label += f"（{doc_id}）"
        score = source.get("score")
        if isinstance(score, (int, float)):
            label += f" 相似度 {float(score):.2f}"
        lines.append(label)
    return "\n".join(lines)


class FeishuMessageHandler:
    """过滤单聊文本消息，异步执行 RAG 并回复。"""

    def __init__(
        self,
        answer: AnswerFn,
        reply: ReplyFn,
        executor: Executor | None = None,
        seen_limit: int = SEEN_LIMIT,
        department_for: DepartmentFn | None = None,
    ) -> None:
        self._answer = answer
        self._reply = reply
        self._executor = executor or ThreadPoolExecutor(
            max_workers=MAX_WORKERS,
            thread_name_prefix="feishu-rag",
        )
        self._seen = _RecentKeys(seen_limit)
        self._department_for = department_for or department_for_user

    def handle(self, event: Any) -> None:
        """SDK 回调入口：立即返回，耗时任务交给线程池。"""
        message = parse_message_event(event)
        if message is None or not message.message_id:
            return

        dedup_keys = tuple(key for key in (message.event_id, message.message_id) if key)
        if not self._seen.add_if_new(dedup_keys):
            logger.info("忽略重复飞书事件 message_id=%s", message.message_id)
            return

        try:
            self._executor.submit(self._process, message)
        except RuntimeError:
            logger.error("飞书消息线程池已关闭 message_id=%s", message.message_id)

    def _process(self, message: IncomingMessage) -> None:
        # 只处理用户发给机器人的单聊消息
        if message.sender_type != "user" or message.chat_type != "p2p":
            return

        if message.message_type != "text":
            self._safe_reply(message.message_id, TEXT_ONLY_HINT)
            return
        if not message.text:
            self._safe_reply(message.message_id, EMPTY_TEXT_HINT)
            return

        try:
            department = self._department_for(message.sender_id or None)
            answer, sources = self._answer(message.text, department)
        except KnowledgeBaseNotReadyError:
            logger.warning("飞书问答失败：知识库未初始化 message_id=%s", message.message_id)
            self._safe_reply(message.message_id, KB_NOT_READY_HINT)
            return
        except Exception as exc:  # 不记录问题内容，避免泄露业务信息
            logger.error(
                "飞书问答失败 message_id=%s error=%s",
                message.message_id,
                type(exc).__name__,
            )
            self._safe_reply(message.message_id, ERROR_HINT)
            return

        self._safe_reply(message.message_id, build_reply_text(answer, sources))

    def _safe_reply(self, message_id: str, text: str) -> None:
        try:
            self._reply(message_id, text)
        except Exception as exc:
            logger.error(
                "飞书回复失败 message_id=%s error=%s",
                message_id,
                type(exc).__name__,
            )

    def close(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)


def make_answer_fn(graph: Any) -> AnswerFn:
    """把 LangGraph 工作流包装为同步函数，供线程池调用。"""

    def answer(question: str, department: str) -> tuple[str, list[dict[str, Any]]]:
        return asyncio.run(run_chat(graph, question, department))

    return answer


def build_reply_fn(client: Any) -> ReplyFn:
    """基于飞书 SDK 的回复函数：回复到消息所在会话。"""
    import lark_oapi as lark

    def reply(message_id: str, text: str) -> None:
        request = (
            lark.im.v1.ReplyMessageRequest.builder()
            .message_id(message_id)
            .request_body(
                lark.im.v1.ReplyMessageRequestBody.builder()
                .content(json.dumps({"text": text}, ensure_ascii=False))
                .msg_type("text")
                .build()
            )
            .build()
        )
        response = client.im.v1.message.reply(request)
        if not response.success():
            logger.error("飞书回复失败 code=%s msg=%s", response.code, response.msg)

    return reply


def build_feishu_client(settings: Settings) -> Any:
    import lark_oapi as lark

    return (
        lark.Client.builder()
        .app_id(settings.feishu_app_id)
        .app_secret(settings.feishu_app_secret)
        .build()
    )


def build_ws_client(settings: Settings, handler: FeishuMessageHandler) -> Any:
    import lark_oapi as lark

    dispatcher = (
        lark.EventDispatcherHandler.builder("", "")
        .register_p2_im_message_receive_v1(handler.handle)
        .build()
    )
    return lark.ws.Client(
        settings.feishu_app_id,
        settings.feishu_app_secret,
        event_handler=dispatcher,
        log_level=lark.LogLevel.INFO,
    )


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    settings = get_settings()

    missing = [
        name
        for name, value in (
            ("FEISHU_APP_ID", settings.feishu_app_id),
            ("FEISHU_APP_SECRET", settings.feishu_app_secret),
        )
        if not value.strip()
    ]
    if missing:
        logger.error("缺少飞书配置：%s，请在 .env 中填写", "、".join(missing))
        return 1

    try:
        model = build_chat_model(settings)
    except MissingApiKeyError:
        logger.error("未配置 DEEPSEEK_API_KEY，请在 .env 中填写")
        return 1

    knowledge_base = KnowledgeBase(settings)
    if not knowledge_base.is_ready():
        logger.error("知识库尚未初始化，请先运行：uv run python -m app.ingest")
        return 1

    graph = build_graph(model, knowledge_base)
    client = build_feishu_client(settings)
    user_departments = settings.test_user_departments
    handler = FeishuMessageHandler(
        answer=make_answer_fn(graph),
        reply=build_reply_fn(client),
        department_for=lambda user_id: department_for_user(user_id, user_departments),
    )
    ws_client = build_ws_client(settings, handler)

    logger.info("飞书机器人已启动，等待单聊文本消息（Ctrl+C 退出）")
    try:
        ws_client.start()
    except KeyboardInterrupt:
        logger.info("收到退出信号，飞书机器人已停止")
    except Exception as exc:
        logger.error("飞书机器人运行失败：%s", type(exc).__name__)
        return 1
    finally:
        handler.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
