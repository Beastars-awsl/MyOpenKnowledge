"""重建文档向量索引：清空所有 chunk，按当前分块/embedding 配置重新生成。

用法（在 backend 目录下）：
  python scripts/reindex.py --local                 # 默认，Ollama bge-m3
  python scripts/reindex.py --provider openai --api-key sk-xxx
"""
import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import delete, select  # noqa: E402

from core.database import async_session_maker, engine, init_db  # noqa: E402
from models.database import Document, DocumentChunk  # noqa: E402
from services.document_service import document_service  # noqa: E402
from services.embedding_service import embedding_service  # noqa: E402


async def reindex(use_local: bool, provider: str, api_key: str, base_url: str):
    await init_db()
    async with async_session_maker() as session:
        docs = (
            await session.execute(select(Document).where(Document.status == "completed"))
        ).scalars().all()
        print(f"待重建文档：{len(docs)} 篇")

        for doc in docs:
            if not doc.file_path or not os.path.exists(doc.file_path):
                print(f"  跳过（原文件缺失）：{doc.title}")
                continue
            text = await asyncio.to_thread(
                document_service.parse_document, doc.file_path, doc.file_type
            )
            chunks = document_service.chunk_text(text)
            embeddings = await embedding_service.get_embeddings(
                chunks, api_key, provider, base_url or None, use_local
            )
            await session.execute(
                delete(DocumentChunk).where(DocumentChunk.document_id == doc.id)
            )
            for i, (content, embedding) in enumerate(zip(chunks, embeddings)):
                session.add(
                    DocumentChunk(
                        document_id=doc.id,
                        content=content,
                        chunk_index=i,
                        embedding=embedding,
                    )
                )
            await session.commit()
            print(f"  完成：{doc.title}（{len(chunks)} 块）")

    await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--local", dest="use_local", action="store_true", default=True)
    parser.add_argument("--provider", default="openai")
    parser.add_argument("--api-key", default="")
    parser.add_argument("--base-url", default="")
    args = parser.parse_args()
    asyncio.run(reindex(args.use_local, args.provider, args.api_key, args.base_url))
