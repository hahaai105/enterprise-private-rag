"""LangGraph RAG 工作流：START -> retrieve -> answer -> END。

模型与检索器均通过参数注入，便于测试时替换为 Mock，不消耗真实 API 额度。
"""

import asyncio
from typing import Any, TypedDict

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph

from .rag import RetrievedChunk, format_context, sources_from_chunks

SYSTEM_PROMPT = (
    "你是一个企业知识库智能助手。只能依据提供的参考资料回答问题，"
    "并在回答中用【文档标题】标注依据。如果参考资料不足以回答，"
    "请明确说明“知识库中未找到相关依据”，不要编造。回答使用简洁、准确的中文。"
)

NO_CONTEXT_ANSWER = "知识库中未找到相关依据，暂时无法回答这个问题。"


class ChatState(TypedDict):
    question: str
    context: str
    sources: list[dict[str, Any]]
    answer: str


def build_graph(model: Any, retriever: Any):
    """编译 RAG 问答图；model 需提供 async ainvoke(messages)，retriever 需提供 search(question)。"""

    async def retrieve_node(state: ChatState) -> dict[str, Any]:
        chunks: list[RetrievedChunk] = await asyncio.to_thread(
            retriever.search,
            state["question"],
        )
        return {
            "context": format_context(chunks),
            "sources": sources_from_chunks(chunks),
        }

    async def answer_node(state: ChatState) -> dict[str, str]:
        if not state.get("context"):
            return {"answer": NO_CONTEXT_ANSWER}

        messages = [
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(
                content=(
                    "参考资料：\n"
                    f"{state['context']}\n\n"
                    f"用户问题：{state['question']}\n\n"
                    "请仅依据上述参考资料回答，并标注引用的文档标题。"
                )
            ),
        ]
        response = await model.ainvoke(messages)
        return {"answer": response.content}

    builder = StateGraph(ChatState)
    builder.add_node("retrieve", retrieve_node)
    builder.add_node("answer", answer_node)
    builder.add_edge(START, "retrieve")
    builder.add_edge("retrieve", "answer")
    builder.add_edge("answer", END)
    return builder.compile()


async def run_chat(graph, question: str) -> tuple[str, list[dict[str, Any]]]:
    """执行工作流并返回答案及文档来源。"""
    result = await graph.ainvoke(
        {"question": question, "context": "", "sources": [], "answer": ""}
    )
    return str(result["answer"]), list(result.get("sources", []))
