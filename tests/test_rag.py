from pathlib import Path

from app.config import Settings
from app.rag import (
    KnowledgeBase,
    load_documents,
    sources_from_chunks,
    split_documents,
)
from tests.conftest import make_chunk

PROJECT_ROOT = Path(__file__).resolve().parents[1]
KB_DIR = PROJECT_ROOT / "knowledge_base"


class FakeEmbedder:
    """用固定二维向量验证 Chroma 入库、检索与阈值过滤。"""

    def encode_documents(self, texts):
        return [[1.0, 0.0] for _ in texts]

    def encode_query(self, text):
        return [1.0, 0.0] if "年假" in text else [0.0, 1.0]


def test_knowledge_base_has_six_documents_with_metadata():
    documents = load_documents(KB_DIR)

    assert len(documents) == 6
    assert len({document.doc_id for document in documents}) == 6

    for document in documents:
        assert document.title
        assert document.department
        assert document.access_scope
        assert document.source.endswith(".md")
        assert document.body


def test_split_documents_produces_unique_chunks_with_doc_metadata():
    documents = load_documents(KB_DIR)
    chunks = split_documents(documents, chunk_size=500, chunk_overlap=80)

    assert chunks
    assert len({chunk.chunk_id for chunk in chunks}) == len(chunks)
    for chunk in chunks:
        assert chunk.text.strip()
        assert chunk.metadata["doc_id"]
        assert chunk.metadata["title"]
        assert chunk.metadata["source"].endswith(".md")


def test_sources_are_deduplicated_by_document():
    chunks = [
        make_chunk(text="年假 7 天。", score=0.90),
        make_chunk(text="年假可结转 5 天。", score=0.80),
        make_chunk(
            text="代码合并需要评审。",
            doc_id="XC-RD-001",
            title="技术开发规范",
            source="03_tech_standards.md",
            department="研发中心",
            access_scope="研发中心",
            score=0.70,
        ),
    ]

    sources = sources_from_chunks(chunks)

    assert [source["doc_id"] for source in sources] == ["XC-HR-002", "XC-RD-001"]
    assert len(sources) == 2
    assert sources[0]["snippet"] == "年假 7 天。"


def test_knowledge_base_ingest_and_search_with_fake_embedder(tmp_path):
    docs_dir = tmp_path / "kb"
    docs_dir.mkdir()
    (docs_dir / "leave.md").write_text(
        "---\n"
        "doc_id: XC-HR-002\n"
        "title: 请假与考勤制度\n"
        "department: 人力资源部\n"
        "access_scope: 全体员工\n"
        "---\n\n"
        "# 年假\n\n员工年假为 7 天。\n",
        encoding="utf-8",
    )

    settings = Settings(
        deepseek_api_key="",
        _env_file=None,
        knowledge_base_dir=str(docs_dir),
        chroma_dir=str(tmp_path / "chroma"),
        chroma_collection="test_collection",
        rag_top_k=4,
        rag_score_threshold=0.4,
        chunk_size=200,
        chunk_overlap=20,
    )
    knowledge_base = KnowledgeBase(settings, embedder=FakeEmbedder())

    count = knowledge_base.ingest(rebuild=True)
    assert count >= 1

    results = knowledge_base.search("年假有几天？")
    assert results
    assert results[0].metadata["doc_id"] == "XC-HR-002"
    assert results[0].score >= 0.99

    assert knowledge_base.search("食堂菜单") == []
