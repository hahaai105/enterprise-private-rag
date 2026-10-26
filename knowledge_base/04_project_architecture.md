---
doc_id: XC-RD-002
title: 项目架构说明
department: 研发中心
access_scope: 研发中心
classification: 内部
owner: 研发中心
updated_at: "2026-10-10"
version: v1.2
---

# 企业私有知识库问答系统架构说明

## 1. 项目目标

“星云知识库问答”是星辰科技面向内部员工的企业知识库问答系统。第一阶段目标是用 FastAPI + LangGraph + DeepSeek 打通最小问答链路，并基于本地 Chroma 向量库实现中文文档检索增强生成（RAG）。

## 2. 当前范围

- 支持 Markdown 知识库文档的加载、切分、向量化和检索。
- 使用 BAAI/bge-small-zh-v1.5 生成中文向量。
- 使用 Chroma 本地持久化向量库，目录为 data/chroma。
- LangGraph 工作流为 START → retrieve → answer → END。
- DeepSeek 仅依据检索片段回答，并返回文档来源。
- 暂不包含用户登录、RBAC 权限、飞书接入、Rerank 和混合检索。

## 3. 组件

| 组件 | 技术 | 职责 |
| --- | --- | --- |
| Web 接口 | FastAPI | 提供 /health 和 /chat |
| 工作流 | LangGraph | 编排检索与回答节点 |
| Embedding | BAAI/bge-small-zh-v1.5 | 将中文文本转为向量 |
| 向量库 | Chroma | 本地持久化与相似度检索 |
| 大模型 | DeepSeek deepseek-chat | 基于检索片段生成答案 |
| 知识库 | Markdown + YAML Front Matter | 存放制度、规范、报告等文档 |

## 4. 数据流

### 4.1 离线入库

1. 读取 knowledge_base 目录下的 Markdown 文件。
2. 解析 YAML Front Matter，获取 doc_id、title、department、access_scope 等元数据。
3. 使用 RecursiveCharacterTextSplitter 按中文标点切分，切片长度 500 字，重叠 80 字。
4. 使用 BGE 模型对切片生成归一化向量。
5. 将切片文本、向量和元数据写入 Chroma 集合 enterprise_knowledge_base。

### 4.2 在线问答

1. 用户向 POST /chat 提交 question。
2. retrieve 节点对问题生成查询向量，在 Chroma 中检索最相关的 4 个切片。
3. 相似度低于 0.4 的切片被丢弃。
4. 若没有可用切片，answer 节点直接返回“知识库中未找到相关依据”，不调用大模型。
5. 若有可用切片，将切片拼接为参考资料，连同问题发送给 DeepSeek。
6. answer 节点返回答案，接口同时返回去重后的文档来源。

## 5. 接口约定

### GET /health

返回 {"status":"ok"}，不依赖模型或向量库，可用于存活检查。

### POST /chat

请求：

```json
{"question":"<用户问题>"}
```

响应：

```json
{
  "answer":"……",
  "sources":[
    {
      "doc_id":"XC-HR-002",
      "title":"请假与考勤制度",
      "source":"02_leave_attendance.md",
      "department":"人力资源部",
      "access_scope":"全体员工",
      "snippet":"……",
      "score":0.82
    }
  ]
}
```

## 6. 存储与元数据

- 知识库源文件：knowledge_base/*.md，纳入 Git 管理。
- 向量库：data/chroma，属于本地生成数据，不纳入 Git。
- 文档元数据字段：doc_id、title、department、access_scope、classification、owner、updated_at、version。
- access_scope 为后续权限控制预留，当前阶段不做过滤。

## 7. 部署

- 运行环境：公司内网 Linux 服务器，Python 3.11 及以上，使用 uv 管理依赖。
- 服务监听 127.0.0.1:8000，通过内网反向代理访问，不直接暴露公网。
- 首次部署须执行知识库初始化命令，之后文档变更时重新执行。
- 当前阶段问题与检索片段会发送至 DeepSeek API；后续评估私有化模型部署方案。

## 8. 已知限制与后续规划

- 当前仅支持 Markdown，不支持 PDF、Word 和网页。
- 未实现权限过滤，access_scope 仅作元数据保留。
- 未实现查询改写、Rerank 和混合检索。
- 后续阶段：接入飞书机器人、增加 RBAC 权限、补充检索评测集。
