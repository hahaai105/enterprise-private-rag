# enterprise-private-rag

基于 **FastAPI + LangGraph + DeepSeek + Chroma + BGE** 的企业私有知识库智能问答系统。

当前为 MVP 版本：在 FastAPI → LangGraph → DeepSeek 问答链路、本地 RAG 和飞书机器人的基础上，增加部门级文档访问控制。检索时按用户部门过滤，只返回 public 文档和本部门文档。

尚未包含生产级用户认证、完整 RBAC、Rerank 和混合检索。

## 主要功能

- **企业知识库问答**：`POST /chat` 调用 LangGraph 工作流，由 DeepSeek 基于检索到的资料生成答案，并返回文档来源。
- **本地 RAG**：加载带 YAML Front Matter 的 Markdown 文档，切分后用 BGE 生成向量，存入本地 Chroma；检索按余弦相似度排序并过滤低分片段。
- **飞书机器人**：通过官方 SDK 的 WebSocket 长连接接收单聊文本消息，异步执行现有 RAG 并回复答案与来源。
- **部门权限隔离（MVP）**：为文档声明 `access_group`，在 Chroma 检索阶段按用户部门过滤，未授权文档不会进入候选集。
- **知识库管理**：`python -m app.ingest` 支持增量更新和 `--rebuild` 全量重建。

## 技术栈

| 层次 | 技术 |
| --- | --- |
| API | FastAPI、Uvicorn、Pydantic v2 |
| 工作流 | LangGraph |
| 大模型 | DeepSeek，经 `langchain-openai` 调用 |
| Embedding | `BAAI/bge-small-zh-v1.5`、sentence-transformers |
| 向量库 | Chroma PersistentClient（本地持久化） |
| 飞书接入 | `lark-oapi` WebSocket 长连接 |
| 文档处理 | PyYAML、langchain-text-splitters |
| 测试 | pytest |
| 运行环境 | Python 3.11+、uv |

## 架构

```text
飞书单聊 ──WebSocket──> app.feishu_bot ──┐
                                        ├──> LangGraph（retrieve → answer）──> DeepSeek
HTTP /chat ─────────────────────────────┘              │
                                                       └── KnowledgeBase.search
                                                              │
                                          Chroma 查询（where: access_group）
                                                              ▲
                                     BGE 向量化问题与文档切片 ──┘

knowledge_base/*.md ──app.ingest──> 切分 + BGE ──> data/chroma
```

- `/chat` 从可选 `user_id` 解析部门；飞书链路从发送者 `open_id` 解析部门。
- 部门信息进入 LangGraph 状态，`retrieve` 节点在检索时应用权限过滤。
- 飞书事件回调只做解析、去重和投递，耗时的 RAG 调用在线程池中执行。

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
│   ├── graph.py       # LangGraph：START → retrieve → answer → END
│   ├── permissions.py # 部门访问组与本地测试身份映射
│   └── feishu_bot.py  # 飞书机器人：WebSocket 长连接接收单聊消息
├── knowledge_base/    # 6 份虚构企业 Markdown 文档
├── tests/
├── data/chroma/       # 本地生成的向量库（不提交 Git）
├── .env.example
├── pyproject.toml
└── README.md
```

## 知识库文档

`knowledge_base/` 中包含星辰科技有限公司的 6 份虚构文档，均带 YAML Front Matter 元数据：

| 文件 | doc_id | 部门 | 访问范围 | access_group |
| --- | --- | --- | --- | --- |
| `01_employee_handbook.md` | XC-HR-001 | 人力资源部 | 全体员工 | `public` |
| `02_leave_attendance.md` | XC-HR-002 | 人力资源部 | 全体员工 | `public` |
| `03_tech_standards.md` | XC-RD-001 | 研发中心 | 研发中心 | `rd` |
| `04_project_architecture.md` | XC-RD-002 | 研发中心 | 研发中心 | `rd` |
| `05_finance_budget.md` | XC-FIN-001 | 财务部 | 财务部、管理层 | `finance` |
| `06_compensation.md` | XC-HR-003 | 人力资源部 | 管理层、人力资源部 | `hr` |

元数据字段包括 `doc_id`、`title`、`department`、`access_scope`、`access_group`、`classification`、`owner`、`updated_at`、`version`。

- `access_group` 是检索阶段实际使用的权限字段，可选值为 `public`、`finance`、`hr`、`rd`。
- `access_scope` 是人类可读的访问说明，不参与过滤。

> 权限隔离为本地测试版，身份映射可被伪造，**不是生产级安全方案**，也不包含用户登录。

## 快速开始

需要 Python 3.11+ 与 [uv](https://docs.astral.sh/uv/)。

```powershell
# 进入克隆后的项目目录
cd enterprise-private-rag

# 安装依赖
uv sync

# 创建本地配置并填入真实 DeepSeek Key
Copy-Item .env.example .env
# 编辑 .env，将 DEEPSEEK_API_KEY 改为真实 Key
# 如需启动飞书机器人，同时填写 FEISHU_APP_ID 与 FEISHU_APP_SECRET

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
| `FEISHU_APP_ID` | 无 | 飞书应用 App ID，启动机器人时必填 |
| `FEISHU_APP_SECRET` | 无 | 飞书应用 App Secret，启动机器人时必填 |
| `TEST_USER_DEPARTMENTS` | `{}` | 本地测试身份映射，JSON，例如 `{"ou_xxx": "finance"}` |
| `KNOWLEDGE_BASE_DIR` | `knowledge_base` | Markdown 知识库目录 |
| `CHROMA_DIR` | `data/chroma` | Chroma 本地持久化目录 |
| `CHROMA_COLLECTION` | `enterprise_knowledge_base` | 向量集合名称 |
| `EMBEDDING_MODEL` | `BAAI/bge-small-zh-v1.5` | 中文 Embedding 模型 |
| `EMBEDDING_DEVICE` | `cpu` | Embedding 运行设备 |
| `RAG_TOP_K` | `4` | 每次检索的切片数 |
| `RAG_SCORE_THRESHOLD` | `0.4` | 相似度阈值，低于该值丢弃 |
| `CHUNK_SIZE` | `500` | 文档切片大小（字符数） |
| `CHUNK_OVERLAP` | `80` | 相邻切片重叠字符数 |

> 不要把真实 Key 写入代码、README 或提交到 Git。

## 敏感信息与 Git

以下路径已在 `.gitignore` 中忽略，不会进入版本库：

- `.env` / `.env.*`（保留 `.env.example` 作为模板）
- `data/`（本地 Chroma 数据）
- `.venv/`

提交前可运行 `git status --ignored` 确认。

## 知识库初始化

```powershell
# 增量写入 / 更新（切片 ID 固定，重复执行会覆盖）
uv run python -m app.ingest

# 删除本地向量集合并全量重建；仅在文档被删除或需要彻底重建时使用
uv run python -m app.ingest --rebuild
```

初始化只需执行一次，服务启动时不会重复生成向量。文档内容变更后重新执行即可；如果删除了文档，请使用 `--rebuild` 清掉残留切片。

> 第四轮为文档新增了 `access_group` 元数据。已有本地向量库必须重新执行 `uv run python -m app.ingest`（增量更新元数据）或 `uv run python -m app.ingest --rebuild`（彻底重建），否则旧切片没有该字段，将无法被检索。

## 接口

### GET /health

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
# {"status":"ok"}
```

不依赖模型或向量库，可用于存活检查。

### POST /chat

```powershell
# 匿名 / 未映射用户：只能检索 public 文档
$body = @{ question = "员工年假有多少天？" } | ConvertTo-Json

# 财务部测试用户：可额外检索 finance 文档
$body = @{ question = "2026年公司总预算是多少？"; user_id = "ou_finance_demo" } | ConvertTo-Json

Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/chat `
  -ContentType "application/json; charset=utf-8" -Body $body
```

`user_id` 为可选字段，仅用于本地测试身份映射；不传或未映射时按 `public` 处理。

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

## 部门权限隔离（MVP）

### 实现方式

- 每份文档在 Front Matter 中声明 `access_group`：`public`、`finance`、`hr`、`rd`。
- `/chat` 与飞书消息都会先解析用户部门，再把部门传入 LangGraph 的 `retrieve` 节点。
- `KnowledgeBase.search()` 在 Chroma 查询时使用元数据过滤：

  ```python
  where={"access_group": {"$in": ["public", department]}}
  ```

- 过滤发生在向量检索阶段，未授权文档不会进入候选集，不依赖 Prompt 提示词。

### 可见范围

| 用户部门 | 可检索 access_group |
| --- | --- |
| `finance` | `public`、`finance` |
| `hr` | `public`、`hr` |
| `rd` | `public`、`rd` |
| 未知 / 未提供 | `public` |

### 本地测试身份映射

内置虚拟飞书 open_id：

| open_id | 部门 |
| --- | --- |
| `ou_finance_demo` | `finance` |
| `ou_hr_demo` | `hr` |
| `ou_rd_demo` | `rd` |
| 其他 | `public` |

真实飞书用户可在 `.env` 中追加自己的 open_id（JSON）：

```dotenv
TEST_USER_DEPARTMENTS={"ou_你的open_id": "finance"}
```

用户 open_id 可在飞书开放平台的事件日志中查看。

### 重新入库

`access_group` 写入 Chroma 元数据后才会生效：

```powershell
uv run python -m app.ingest            # 增量更新，适合本次仅新增元数据
uv run python -m app.ingest --rebuild  # 全量重建，会先删除本地集合
```

> 这是本地演示用的权限机制：身份映射由环境变量或内置字典提供，没有登录与签名校验，不能作为生产级安全方案。

## 飞书机器人

机器人使用飞书官方 Python SDK（`lark-oapi`）的 WebSocket 长连接接收事件，不需要公网服务器、内网穿透或事件回调地址。

### 1. 飞书开放平台配置

1. 在 [飞书开放平台](https://open.feishu.cn/) 创建企业自建应用，并启用「机器人」能力。
2. 在「权限管理」中开通：
   - `im:message.p2p_msg:readonly`：读取用户发给机器人的单聊消息；
   - `im:message:send_as_bot`：以机器人身份发送消息。
3. 在「事件与回调」中订阅 `im.message.receive_v1`（接收消息），订阅方式选择「使用长连接接收事件」，无需填写请求地址。
4. 创建并发布应用版本，将机器人可用范围设置到需要测试的成员，否则单聊中看不到机器人。

### 2. 本地配置

在 `.env` 中填写（仅保存在本地，不要提交 Git）：

```dotenv
FEISHU_APP_ID=cli_xxxxxxxxxxxx
FEISHU_APP_SECRET=xxxxxxxxxxxxxxxx
```

### 3. 启动

```powershell
# 首次或文档变更后先初始化知识库
uv run python -m app.ingest

# 启动飞书机器人
uv run python -m app.feishu_bot
```

启动前会依次检查飞书配置、`DEEPSEEK_API_KEY` 和本地向量库；知识库未初始化时会提示先执行 `uv run python -m app.ingest`。

### 4. 行为说明

- 只处理用户发给机器人的单聊（`p2p`）文本消息，群聊消息和机器人自身消息直接忽略。
- 文本消息根据发送者 open_id 解析部门（未知用户为 `public`），再交给现有 LangGraph RAG 工作流，回复答案并附带「参考来源」（文档标题、doc_id、相似度）。
- 非文本消息回复提示，不调用 RAG。
- 事件回调只做解析、去重和投递，检索与模型调用在线程池中执行，避免阻塞事件接收。
- 使用内存中固定容量的 event_id / message_id 去重表避免重复回复，不引入 Redis 或数据库。

> 部门权限使用 `access_group` 在 Chroma 检索阶段过滤；本地身份映射可被伪造，仅为演示，不是生产级鉴权。

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
- 使用临时 Chroma 验证入库、检索和阈值过滤；
- 飞书消息解析、单聊过滤、机器人消息与群聊消息忽略；
- 非文本消息与空文本提示；
- 飞书消息触发现有 LangGraph RAG，并回复答案与文档来源；
- 重复 event_id / message_id 不重复回复；
- 知识库未初始化与 RAG 异常时给出提示；
- 飞书回复报文的构造（不发起真实网络请求）；
- 部门身份映射与访问组计算（finance / hr / rd / 未知用户）；
- `TEST_USER_DEPARTMENTS` 环境变量中的 JSON 身份映射能正确解析；
- Chroma 元数据过滤：财务部、人事部、未知用户之间的文档隔离；
- `/chat` 与飞书链路把解析出的部门传入检索节点；
- 非法 `access_group` 会被拒绝入库。

> 飞书相关用例全部使用 Mock SDK 与本地函数，不连接真实飞书；测试也不调用真实 DeepSeek。真实飞书收发消息请按下方手动联调步骤验收。

## 当前限制

- 部门权限是演示机制：用户 ID 到部门的映射由本地字典或 `TEST_USER_DEPARTMENTS` 提供，可被伪造，没有登录、签名校验或审计，**不能用于生产环境**。
- 权限粒度只到部门级，没有文档级 ACL、用户组或管理后台。
- 飞书事件去重表保存在进程内存中，多实例部署时不共享。
- 知识库使用单机 Chroma + 本地文件，未处理多实例并发入库。
- 未实现 Rerank、混合检索、流式输出和多轮会话。
- 飞书机器人只处理单聊文本消息，群聊及非文本消息仅提示或忽略。

## 真实 DeepSeek + RAG 手动测试

1. 在 `.env` 中配置真实 `DEEPSEEK_API_KEY`；
2. 执行 `uv run python -m app.ingest`；
3. 启动 `uv run uvicorn app.main:app --reload --port 8000`；
4. 调用 `POST /chat`，提问“员工年假有多少天？”；
5. 确认 `answer` 使用了年假相关内容，且 `sources` 中包含 `XC-HR-002`；
6. 提问“公司食堂今天有什么菜？”，确认返回“知识库中未找到相关依据”且 `sources` 为空；
7. 若返回 503，检查 Key 或知识库是否已初始化；若返回 502，检查网络、Key 余额和 `DEEPSEEK_BASE_URL`。

### 部门隔离手动验证

启动服务后，使用内置测试身份调用 `/chat`（需要真实 DeepSeek Key），检查返回的 `sources`：

```powershell
# 财务部：应返回 XC-FIN-001
$body = @{ question = "2026年公司总预算是多少？"; user_id = "ou_finance_demo" } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/chat -ContentType "application/json; charset=utf-8" -Body $body

# 人事部：不应返回 XC-FIN-001
$body = @{ question = "2026年公司总预算是多少？"; user_id = "ou_hr_demo" } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/chat -ContentType "application/json; charset=utf-8" -Body $body

# 人事部：应返回 XC-HR-003
$body = @{ question = "薪酬等级如何划分？"; user_id = "ou_hr_demo" } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/chat -ContentType "application/json; charset=utf-8" -Body $body

# 财务部：不应返回 XC-HR-003
$body = @{ question = "薪酬等级如何划分？"; user_id = "ou_finance_demo" } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/chat -ContentType "application/json; charset=utf-8" -Body $body

# 未知用户：只能看到 public 文档
$body = @{ question = "2026年公司总预算是多少？"; user_id = "ou_stranger" } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/chat -ContentType "application/json; charset=utf-8" -Body $body
```

### 飞书真实联调（需先完成开放平台配置）

1. 按「飞书机器人」一节的说明创建应用、开通权限、订阅事件并发布版本；
2. 在 `.env` 中填写 `FEISHU_APP_ID` 与 `FEISHU_APP_SECRET`；
3. 执行 `uv run python -m app.feishu_bot`，看到「飞书机器人已启动」；
4. 在飞书中单聊机器人，提问「员工年假有多少天？」；
5. 确认收到答案和「参考来源」，且来源包含 `XC-HR-002`；
6. 再发送一张图片，确认收到「目前只支持文本消息」的提示。
