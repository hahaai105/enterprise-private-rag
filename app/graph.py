"""LangGraph 问答工作流：START -> answer -> END。

模型通过参数注入，便于测试时替换为 Mock，不消耗真实 API 额度。
"""

from typing import Any, TypedDict

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph

SYSTEM_PROMPT = (
    "你是一个企业知识库智能助手。请使用简洁、准确的中文回答用户问题。"
    "如果无法确定答案，请如实说明，不要编造。"
)


class ChatState(TypedDict):
    question: str
    answer: str


def build_graph(model: Any):
    """编译一个最小问答图；model 只需提供 async ainvoke(messages)。"""

    async def answer_node(state: ChatState) -> dict[str, str]:
        messages = [
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(content=state["question"]),
        ]
        response = await model.ainvoke(messages)
        return {"answer": response.content}

    builder = StateGraph(ChatState)
    builder.add_node("answer", answer_node)
    builder.add_edge(START, "answer")
    builder.add_edge("answer", END)
    return builder.compile()


async def run_chat(graph, question: str) -> str:
    """执行工作流并返回最终答案。"""
    result = await graph.ainvoke({"question": question, "answer": ""})
    return result["answer"]
