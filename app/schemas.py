"""接口请求与响应模型。"""

from pydantic import BaseModel, Field, field_validator


class ChatRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=4000, description="用户问题")

    @field_validator("question")
    @classmethod
    def question_must_not_be_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("问题不能为空")
        return value


class Source(BaseModel):
    """回答引用的知识库文档来源。"""

    doc_id: str
    title: str
    source: str
    department: str
    access_scope: str
    snippet: str
    score: float


class ChatResponse(BaseModel):
    answer: str
    sources: list[Source] = Field(default_factory=list)
