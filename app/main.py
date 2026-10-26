"""FastAPI 入口：提供 /health 与 /chat。"""

import logging

from fastapi import FastAPI, HTTPException

from .config import Settings, get_settings
from .graph import build_graph, run_chat
from .llm import MissingApiKeyError, build_chat_model
from .schemas import ChatRequest, ChatResponse

logger = logging.getLogger(__name__)


def create_app(graph=None, settings: Settings | None = None) -> FastAPI:
    """创建应用。graph 可注入，用于测试时绕过真实模型。"""
    settings = settings or get_settings()
    app = FastAPI(title="Enterprise Private RAG", version="0.1.0")
    compiled_graph = graph

    def get_graph():
        """首次请求时才构建模型，保证缺少 Key 时 /health 仍可用。"""
        nonlocal compiled_graph
        if compiled_graph is None:
            compiled_graph = build_graph(build_chat_model(settings))
        return compiled_graph

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/chat", response_model=ChatResponse)
    async def chat(payload: ChatRequest) -> ChatResponse:
        try:
            chat_graph = get_graph()
        except MissingApiKeyError:
            raise HTTPException(
                status_code=503,
                detail="服务未配置 DEEPSEEK_API_KEY，请检查环境变量",
            ) from None

        try:
            answer = await run_chat(chat_graph, payload.question)
        except Exception as exc:  # 不记录异常详情中的请求信息，避免泄露敏感内容
            logger.error("模型调用失败：%s", type(exc).__name__)
            raise HTTPException(
                status_code=502,
                detail="模型调用失败，请稍后重试",
            ) from None

        return ChatResponse(answer=answer)

    return app


app = create_app()
