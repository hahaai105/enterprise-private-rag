# enterprise-private-rag

基于 **FastAPI + LangGraph + DeepSeek + Chroma + BGE** 的企业私有知识库智能问答系统。

当前为第二轮 MVP：在第一轮 FastAPI → LangGraph → DeepSeek 问答链路的基础上，加入本地 RAG（Markdown 加载、中文切分、BGE 向量化、Chroma 检索、来源返回）。

尚未包含飞书接入、RBAC 权限控制、Rerank 和混合检索。

## 目录结构

```text
enterprise-private-rag/
├── app/
│   ├── __init__.py
│   ├── main.py        # FastAPI 入口：/health、/chat
│   ├── config.py      # 环境变量 / .env 配置
│   ├── schemas.py     # 请求、响应与来源模型
│   ├── llm.py         # 构建 DeepSeek 模型
│   ├── rag.py         # 文档加载、切分、BGE Embedding、Chroma 检索
│   ├── ingest.py      # 知识库初始化命令
│   └── graph.py       # LangGraph：START → retrieve → answer → END
├── knowledge_base/    # 6 份虚构企业 Markdown 文档
├── tests/
├── data/chroma/       # 本地生成的向量库（不提交 Git）
├── .env.example
├── pyproject.toml
└── README.md
```

## 知识库文档

`knowledge_base/` 中包含星辰科技有限公司的 6 份虚构文档，均带 YAML Front Matter 元数据：

| 文件 | doc_id | 部门 | 访问范围 |
| --- | --- | --- | --- |
| `01_employee_handbook.md` | XC-HR-001 | 人力资源部 | 全体员工 |
| `02_leave_attendance.md` | XC-HR-002 | 人力资源部 | 全体员工 |
| `03_tech_standards.md` | XC-RD-001 | 研发中心 | 研发中心 |
| `04_project_architecture.md` | XC-RD-002 | 研发中心 | 研发中心 |
| `05_finance_budget.md` | XC-FIN-001 | 财务部 | 管理层 |
| `06_compensation.md` | XC-HR-003 | 人力资源部 | 管理层、人力资源部 |

元数据字段包括 `doc_id`、`title`、`department`、`access_scope`、`classification`、`owner`、`updated_at`、`version`。

> `access_scope` 仅为后续权限控制预留，本轮**不做权限过滤**，也不包含用户认证。

## 快速开始

需要 Python 3.11+ 与 [uv](https://docs.astral.sh/uv/)。

```powershell
cd D:\xiangmu\enterprise-private-rag

# 安装依赖
uv sync

# 创建本地配置并填入真实 DeepSeek Key
Copy-Item .env.example .env
# 编辑 .env，将 DEEPSEEK_API_KEY 改为真实 Key

# 初始化知识库（首次会下载 BGE 模型，约 100 MB）
uv run python -m app.ingest

# 启动服务
uv run uvicorn app.main:app --reload --port 8000
```

如果 Hugging Face 下载较慢，可在当前 PowerShell 会话中临时设置镜像后再初始化：

```powershell
$env:HF_ENDPOINT = "https://hf-mirror.com"
uv run python -m app.ingest
```

## 配置项

| 环境变量 | 默认值 | 说明 |
| --- | --- | --- |
| `DEEPSEEK_API_KEY` | 无 | DeepSeek API Key，必填 |
| `DEEPSEEK_BASE_URL` | `https://api.deepseek.com` | DeepSeek API 地址 |
| `DEEPSEEK_MODEL` | `deepseek-chat` | 模型名称 |
| `REQUEST_TIMEOUT` | `60` | 单次模型调用超时（秒） |
| `KNOWLEDGE_BASE_DIR` | `knowledge_base` | Markdown 知识库目录 |
| `CHROMA_DIR` | `data/chroma` | Chroma 本地持久化目录 |
| `CHROMA_COLLECTION` | `enterprise_knowledge_base` | 向量集合名称 |
| `EMBEDDING_MODEL` | `BAAI/bge-small-zh-v1.5` | 中文 Embedding 模型 |
| `EMBEDDING_DEVICE` | `cpu` | Embedding 运行设备 |
| `RAG_TOP_K` | `4` | 每次检索的切片数 |
| `RAG_SCORE_THRESHOLD` | `0.4` | 相似度阈值，低于该值丢弃 |

> 不要把真实 Key 写入代码、README 或提交到 Git。

## 知识库初始化

```powershell
# 增量写入 / 更新（切片 ID 固定，重复执行会覆盖）
uv run python -m app.ingest

# 删除本地向量集合并全量重建；仅在文档被删除或需要彻底重建时使用
uv run python -m app.ingest --rebuild
```

初始化只需执行一次，服务启动时不会重复生成向量。文档内容变更后重新执行即可；如果删除了文档，请使用 `--rebuild` 清掉残留切片。

## 接口

### GET /health

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
# {"status":"ok"}
```

不依赖模型或向量库，可用于存活检查。

### POST /chat

```powershell
$body = @{ question = "员工年假有多少天？" } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/chat `
  -ContentType "application/json; charset=utf-8" -Body $body
```

正常响应包含答案和来源：

```json
{
  "answer": "根据《请假与考勤制度》，……",
  "sources": [
    {
      "doc_id": "XC-HR-002",
      "title": "请假与考勤制度",
      "source": "02_leave_attendance.md",
      "department": "人力资源部",
      "access_scope": "全体员工",
      "snippet": "……",
      "score": 0.82
    }
  ]
}
```

当所有检索结果都低于阈值时，接口返回：

```json
{
  "answer": "知识库中未找到相关依据，暂时无法回答这个问题。",
  "sources": []
}
```

此场景不会调用 DeepSeek，避免模型凭空回答。

## 错误处理约定

| 场景 | HTTP 状态码 | 说明 |
| --- | --- | --- |
| 问题为空或超长 | 422 | 由 Pydantic 校验 |
| 未配置 `DEEPSEEK_API_KEY` | 503 | 提示检查环境变量 |
| 知识库未初始化 | 503 | 提示先运行 `uv run python -m app.ingest` |
| DeepSeek 或检索调用失败 | 502 | 统一返回“模型调用失败，请稍后重试” |

## 运行自动化测试

```powershell
uv run pytest -v
```

测试全部使用 Mock 模型与 Mock / 临时向量库，不消耗 DeepSeek 额度，覆盖：

- `/health` 正常返回；
- 正常检索后经过 LangGraph 调用 Mock 模型，返回答案与来源；
- 无检索结果时直接返回“未找到相关依据”，且不调用模型；
- 空问题返回 422；
- 缺少 API Key 返回 503；
- 知识库未初始化返回 503；
- 模型调用异常返回 502；
- 6 份文档的元数据、切分与来源去重；
- 使用临时 Chroma 验证入库、检索和阈值过滤。

## 真实 DeepSeek + RAG 手动测试

1. 在 `.env` 中配置真实 `DEEPSEEK_API_KEY`；
2. 执行 `uv run python -m app.ingest`；
3. 启动 `uv run uvicorn app.main:app --reload --port 8000`；
4. 调用 `POST /chat`，提问“员工年假有多少天？”；
5. 确认 `answer` 使用了年假相关内容，且 `sources` 中包含 `XC-HR-002`；
6. 提问“公司食堂今天有什么菜？”，确认返回“知识库中未找到相关依据”且 `sources` 为空；
7. 若返回 503，检查 Key 或知识库是否已初始化；若返回 502，检查网络、Key 余额和 `DEEPSEEK_BASE_URL`。
