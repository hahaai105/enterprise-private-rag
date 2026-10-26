# enterprise-private-rag

基于 **LangGraph + RAG + 飞书** 的企业级私有知识库智能问答系统。

当前为第一轮 MVP：只实现 **FastAPI → LangGraph → DeepSeek** 的最小可运行问答链路。
尚未包含 RAG、向量库、飞书接入和权限控制。

## 目录结构

```text
enterprise-private-rag/
├── app/
│   ├── __init__.py
│   ├── main.py        # FastAPI 入口：/health、/chat
│   ├── config.py      # 从环境变量 / .env 读取配置
│   ├── schemas.py     # 请求、响应模型
│   ├── llm.py         # 构建 DeepSeek 模型（复用 ChatOpenAI）
│   └── graph.py       # LangGraph 最小问答工作流
├── tests/
│   ├── conftest.py    # Mock 模型与测试客户端
│   ├── test_health.py
│   └── test_chat.py
├── .env.example
├── .gitignore
├── pyproject.toml
└── README.md
```

## 快速开始

需要 Python 3.11+ 与 [uv](https://docs.astral.sh/uv/)。

```powershell
cd D:\xiangmu\enterprise-private-rag

# 安装依赖（含 pytest 等开发依赖）
uv sync

# 创建本地配置并填入真实 Key（.env 已被 .gitignore 忽略）
Copy-Item .env.example .env
# 编辑 .env，将 DEEPSEEK_API_KEY 改为你的真实 Key
```

### 配置项

| 环境变量 | 默认值 | 说明 |
| --- | --- | --- |
| `DEEPSEEK_API_KEY` | 无 | DeepSeek API Key，必填 |
| `DEEPSEEK_BASE_URL` | `https://api.deepseek.com` | DeepSeek API 地址 |
| `DEEPSEEK_MODEL` | `deepseek-chat` | 模型名称 |
| `REQUEST_TIMEOUT` | `60` | 单次模型调用超时（秒） |

> 不要把真实 Key 写入代码、README 或提交到 Git。

## 启动服务

```powershell
uv run uvicorn app.main:app --reload --port 8000
```

启动后访问：

- Swagger 文档：<http://127.0.0.1:8000/docs>
- 健康检查：<http://127.0.0.1:8000/health>

## 接口验证

### 1. 健康检查

PowerShell：

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
# 输出：status
#       ------
#       ok
```

Bash / curl：

```bash
curl http://127.0.0.1:8000/health
# {"status":"ok"}
```

### 2. 问答接口

PowerShell：

```powershell
$body = @{ question = "请用一句话介绍你自己" } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/chat `
  -ContentType "application/json; charset=utf-8" -Body $body
```

Bash / curl：

```bash
curl -X POST http://127.0.0.1:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"question":"请用一句话介绍你自己"}'
```

正常响应：

```json
{"answer":"……"}
```

### 3. 真实 DeepSeek API 手动测试

自动化测试全部使用 Mock 模型，不消耗额度；如需确认真实链路：

1. 在 `.env` 中配置真实 `DEEPSEEK_API_KEY`；
2. 启动服务（见上）；
3. 调用 `POST /chat`，确认返回内容为模型生成的真实回答；
4. 若返回 502，检查 Key 是否有效、账户余额、网络及 `DEEPSEEK_BASE_URL`；
5. 若返回 503，说明未读取到 `DEEPSEEK_API_KEY`，确认 `.env` 位于项目根目录。

## 运行自动化测试

```powershell
uv run pytest -v
```

测试覆盖：

- `GET /health` 正常返回 `{"status": "ok"}`；
- `POST /chat` 通过 LangGraph 调用 Mock 模型并返回答案；
- 空问题返回 422；
- 缺少 API Key 返回 503；
- 模型调用异常返回 502。

## 错误处理约定

| 场景 | HTTP 状态码 | 说明 |
| --- | --- | --- |
| 问题为空或超长 | 422 | 由 Pydantic 校验 |
| 未配置 `DEEPSEEK_API_KEY` | 503 | 服务暂不可用，提示检查环境变量 |
| DeepSeek 调用失败 | 502 | 统一返回“模型调用失败，请稍后重试” |

`/health` 不依赖模型，未配置 Key 时仍可用于存活检查。
