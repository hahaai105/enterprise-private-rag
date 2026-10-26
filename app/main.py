"""FastAPI 入口：提供 /health 与 /chat。"""

import logging

from fastapi import FastAPI, HTTPException

from .config import Settings, get_settings
from .graph import build_graph, run_chat
from .llm import MissingApiKeyError, build_chat_model
from .rag import KnowledgeBase, KnowledgeBaseNotReadyError
from .schemas import ChatRequest, ChatResponse

logger = logging.getLogger(__name__)


def create_app(
    graph=None,
    settings: Settings | None = None,
    retriever=None,
) -> FastAPI:
    """创建应用。graph / retriever 可注入，用于测试时绕过真实模型与向量库。"""
    settings = settings or get_settings()
    app = FastAPI(title="Enterprise Private RAG", version="0.2.0")
    compiled_graph = graph

    def get_graph():
        """首次请求时才构建模型与检索器，保证缺少 Key 时 /health 仍可用。"""
        nonlocal compiled_graph
        if compiled_graph is None:
            active_retriever = retriever if retriever is not None else KnowledgeBase(settings)
            compiled_graph = build_graph(build_chat_model(settings), active_retriever)
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
            answer, sources = await run_chat(chat_graph, payload.question)
        except KnowledgeBaseNotReadyError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from None
        except Exception as exc:  # 不记录异常详情中的请求信息，避免泄露敏感内容
            logger.error("问答调用失败：%s", type(exc).__name__)
            raise HTTPException(
                status_code=502,
                detail="模型调用失败，请稍后重试",
            ) from None

        return ChatResponse(answer=answer, sources=sources)

    return app


app = create_app()
