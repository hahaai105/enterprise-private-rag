"""知识库初始化命令：python -m app.ingest [--rebuild]。"""

import argparse

from .config import get_settings
from .rag import KnowledgeBase


def main() -> None:
    parser = argparse.ArgumentParser(description="初始化本地知识库向量索引")
    parser.add_argument(
        "--rebuild",
        action="store_true",
        help="删除现有向量集合并全量重建",
    )
    args = parser.parse_args()

    settings = get_settings()
    knowledge_base = KnowledgeBase(settings)
    try:
        count = knowledge_base.ingest(rebuild=args.rebuild)
    except Exception as exc:
        raise SystemExit(f"知识库初始化失败：{exc}") from exc

    print(
        f"知识库初始化完成：{count} 个切片，"
        f"集合 {settings.chroma_collection}，目录 {knowledge_base.chroma_dir}"
    )


if __name__ == "__main__":
    main()
