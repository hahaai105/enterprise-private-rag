"""本地知识库 RAG：Markdown 加载、切分、BGE 向量化与 Chroma 检索。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import yaml
from langchain_text_splitters import RecursiveCharacterTextSplitter

from .config import Settings

PROJECT_ROOT = Path(__file__).resolve().parent.parent
QUERY_INSTRUCTION = "为这个句子生成表示以用于检索相关文章："
FRONT_MATTER_RE = re.compile(r"\A---\s*\r?\n(.*?)\r?\n---\s*\r?\n?(.*)\Z", re.S)
REQUIRED_METADATA = ("doc_id", "title", "department", "access_scope")
SNIPPET_LENGTH = 120


class KnowledgeBaseNotReadyError(RuntimeError):
    """向量库尚未初始化或为空时抛出。"""


class Embedder(Protocol):
    """Embedding 接口，便于测试时替换为确定性实现。"""

    def encode_documents(self, texts: list[str]) -> list[list[float]]: ...

    def encode_query(self, text: str) -> list[float]: ...


class BgeEmbedder:
    """懒加载的 BGE 中文向量模型。"""

    def __init__(self, model_name: str, device: str = "cpu") -> None:
        self.model_name = model_name
        self.device = device
        self._model: Any = None

    def _load(self) -> Any:
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self.model_name, device=self.device)
        return self._model

    def encode_documents(self, texts: list[str]) -> list[list[float]]:
        vectors = self._load().encode(
            texts,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return [vector.tolist() for vector in vectors]

    def encode_query(self, text: str) -> list[float]:
        vector = self._load().encode(
            QUERY_INSTRUCTION + text,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return vector.tolist()


@dataclass(frozen=True)
class KnowledgeDocument:
    doc_id: str
    title: str
    department: str
    access_scope: str
    classification: str
    owner: str
    updated_at: str
    version: str
    source: str
    body: str


@dataclass(frozen=True)
class KnowledgeChunk:
    chunk_id: str
    text: str
    metadata: dict[str, Any]


@dataclass(frozen=True)
class RetrievedChunk:
    text: str
    metadata: dict[str, Any]
    score: float


def _resolve_path(path_str: str) -> Path:
    path = Path(path_str)
    return path if path.is_absolute() else PROJECT_ROOT / path


def load_documents(kb_dir: Path) -> list[KnowledgeDocument]:
    """读取目录下所有 Markdown 文件并解析 YAML Front Matter。"""
    if not kb_dir.is_dir():
        raise FileNotFoundError(f"知识库目录不存在：{kb_dir}")

    documents: list[KnowledgeDocument] = []
    for path in sorted(kb_dir.glob("*.md")):
        text = path.read_text(encoding="utf-8-sig")
        match = FRONT_MATTER_RE.match(text)
        if match is None:
            raise ValueError(f"{path.name} 缺少 YAML Front Matter")

        metadata = yaml.safe_load(match.group(1)) or {}
        if not isinstance(metadata, dict):
            raise ValueError(f"{path.name} 的 Front Matter 必须是键值对")

        missing = [key for key in REQUIRED_METADATA if not str(metadata.get(key, "")).strip()]
        if missing:
            raise ValueError(f"{path.name} 缺少元数据字段：{', '.join(missing)}")

        documents.append(
            KnowledgeDocument(
                doc_id=str(metadata["doc_id"]),
                title=str(metadata["title"]),
                department=str(metadata["department"]),
                access_scope=str(metadata["access_scope"]),
                classification=str(metadata.get("classification", "内部")),
                owner=str(metadata.get("owner", metadata["department"])),
                updated_at=str(metadata.get("updated_at", "")),
                version=str(metadata.get("version", "")),
                source=path.name,
                body=match.group(2).strip(),
            )
        )

    if not documents:
        raise ValueError(f"知识库目录中没有 Markdown 文档：{kb_dir}")
    return documents


def split_documents(
    documents: list[KnowledgeDocument],
    chunk_size: int,
    chunk_overlap: int,
) -> list[KnowledgeChunk]:
    """按中文标点切分文档，保留文档元数据。"""
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=["\n\n", "\n", "。", "；", "，", " ", ""],
        keep_separator=True,
    )

    chunks: list[KnowledgeChunk] = []
    for document in documents:
        pieces = splitter.split_text(document.body)
        for index, piece in enumerate(pieces):
            text = piece.strip()
            if not text:
                continue
            chunks.append(
                KnowledgeChunk(
                    chunk_id=f"{document.doc_id}#{index:03d}",
                    text=text,
                    metadata={
                        "doc_id": document.doc_id,
                        "title": document.title,
                        "source": document.source,
                        "department": document.department,
                        "access_scope": document.access_scope,
                        "classification": document.classification,
                        "chunk_index": index,
                    },
                )
            )
    return chunks


def format_context(chunks: list[RetrievedChunk]) -> str:
    """将检索片段拼接为提示词中的参考资料。"""
    parts: list[str] = []
    for index, chunk in enumerate(chunks, start=1):
        title = chunk.metadata.get("title", "未知文档")
        doc_id = chunk.metadata.get("doc_id", "")
        source = chunk.metadata.get("source", "")
        parts.append(f"[资料{index}] 文档：{title}（{doc_id}，来源：{source}）\n{chunk.text}")
    return "\n\n".join(parts)


def sources_from_chunks(chunks: list[RetrievedChunk]) -> list[dict[str, Any]]:
    """按文档去重并生成接口返回的来源列表。"""
    sources: list[dict[str, Any]] = []
    seen: set[str] = set()

    for chunk in chunks:
        doc_id = str(chunk.metadata.get("doc_id", ""))
        if not doc_id or doc_id in seen:
            continue
        seen.add(doc_id)

        snippet = chunk.text[:SNIPPET_LENGTH]
        if len(chunk.text) > SNIPPET_LENGTH:
            snippet += "…"

        sources.append(
            {
                "doc_id": doc_id,
                "title": str(chunk.metadata.get("title", "")),
                "source": str(chunk.metadata.get("source", "")),
                "department": str(chunk.metadata.get("department", "")),
                "access_scope": str(chunk.metadata.get("access_scope", "")),
                "snippet": snippet,
                "score": round(max(0.0, min(1.0, chunk.score)), 4),
            }
        )
    return sources


class KnowledgeBase:
    """Chroma 本地向量库的入库与检索封装。"""

    def __init__(self, settings: Settings, embedder: Embedder | None = None) -> None:
        self.settings = settings
        self._embedder = embedder or BgeEmbedder(
            settings.embedding_model,
            settings.embedding_device,
        )
        self._client: Any = None
        self._collection: Any = None

    @property
    def knowledge_base_dir(self) -> Path:
        return _resolve_path(self.settings.knowledge_base_dir)

    @property
    def chroma_dir(self) -> Path:
        return _resolve_path(self.settings.chroma_dir)

    def _get_client(self) -> Any:
        if self._client is None:
            import chromadb
            from chromadb.config import Settings as ChromaSettings

            self.chroma_dir.mkdir(parents=True, exist_ok=True)
            self._client = chromadb.PersistentClient(
                path=str(self.chroma_dir),
                settings=ChromaSettings(anonymized_telemetry=False),
            )
        return self._client

    def _get_collection(self) -> Any:
        if self._collection is None:
            self._collection = self._get_client().get_or_create_collection(
                name=self.settings.chroma_collection,
                metadata={"hnsw:space": "cosine"},
            )
        return self._collection

    def ingest(self, rebuild: bool = False) -> int:
        """加载、切分并向量化知识库，返回写入的切片数。"""
        documents = load_documents(self.knowledge_base_dir)
        chunks = split_documents(
            documents,
            self.settings.chunk_size,
            self.settings.chunk_overlap,
        )
        if not chunks:
            raise ValueError("知识库文档切分后没有可用内容")

        client = self._get_client()
        if rebuild:
            try:
                client.delete_collection(self.settings.chroma_collection)
            except Exception:
                pass
            self._collection = None

        collection = self._get_collection()
        batch_size = 64
        for start in range(0, len(chunks), batch_size):
            batch = chunks[start : start + batch_size]
            embeddings = self._embedder.encode_documents([chunk.text for chunk in batch])
            collection.upsert(
                ids=[chunk.chunk_id for chunk in batch],
                embeddings=embeddings,
                documents=[chunk.text for chunk in batch],
                metadatas=[chunk.metadata for chunk in batch],
            )
        return len(chunks)

    def search(self, question: str) -> list[RetrievedChunk]:
        """按问题检索相关片段，低于阈值的片段会被丢弃。"""
        collection = self._get_collection()
        if collection.count() == 0:
            raise KnowledgeBaseNotReadyError(
                "知识库尚未初始化或为空，请先运行：uv run python -m app.ingest"
            )

        query_embedding = self._embedder.encode_query(question)
        result = collection.query(
            query_embeddings=[query_embedding],
            n_results=self.settings.rag_top_k,
            include=["documents", "metadatas", "distances"],
        )

        documents = (result.get("documents") or [[]])[0]
        metadatas = (result.get("metadatas") or [[]])[0]
        distances = (result.get("distances") or [[]])[0]

        chunks: list[RetrievedChunk] = []
        for text, metadata, distance in zip(documents, metadatas, distances):
            if text is None or metadata is None or distance is None:
                continue
            score = 1.0 - float(distance)
            if score < self.settings.rag_score_threshold:
                continue
            chunks.append(
                RetrievedChunk(
                    text=str(text),
                    metadata=dict(metadata),
                    score=score,
                )
            )
        return chunks
