"""Local browser-test server. Requires a disposable study_test_* database; never calls a real LLM."""
import json
import os
import sys
from contextlib import asynccontextmanager
from types import SimpleNamespace
from uuid import UUID

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.engine import make_url

from api.study import router as study_router
from api.documents import router as documents_router
from core.database import async_session_maker, init_db
from core.config import settings
from models.database import Document, DocumentChunk
from services import query_service

if not (make_url(settings.DATABASE_URL).database or "").startswith("study_test_"):
    raise RuntimeError("Browser fixture only runs against a study_test_* database")

DOC_ID = UUID("41000000-0000-4000-8000-000000000001")
EVIDENCE = "间隔复习是在一段时间后再次主动回忆。主动回忆比单纯重读更有助于检查知识缺口。"


async def fake_completion(*args, **kwargs):
    system = kwargs["messages"][0]["content"]
    payload = json.loads(kwargs["messages"][1]["content"])
    if "出题助手" in system:
        source = payload["sources"][0] if payload["sources"] else None
        original = payload.get("original")
        items = []
        for kind in payload["kinds"]:
            items.append({"kind": kind, "knowledge_point": "主动回忆",
                          "prompt": ("换个角度：" if original else "") + {
                              "flashcard": "用一句话解释间隔复习。",
                              "choice": "以下哪种做法属于主动回忆？",
                              "short_answer": "为什么要间隔一段时间再次回忆？"}[kind],
                          "answer": "合上资料，尝试回忆" if kind == "choice" else "在一段时间后再次主动回忆，检查知识缺口。",
                          "explanation": "先独立回忆，再对照资料检查遗漏，避免只凭熟悉感判断掌握程度。",
                          "options": ["合上资料，尝试回忆", "连续重读", "只收藏不学习", "只看答案"] if kind == "choice" else [],
                          "source_index": 0 if source else None, "evidence": source["excerpt"] if source else ""})
        result = {"items": items[:payload["count"]]}
    elif "复盘" in system:
        result = {"recap": "本轮练习提示：主动回忆与单纯重读需要区分。建议合上资料，先用自己的话解释概念，再检查遗漏。到期时按页面安排继续复习。"}
    else:
        if "模拟失败" in payload.get("user_answer", ""):
            raise RuntimeError("Simulated provider outage")
        result = {"summary": "你已提到主动回忆，还可以补充检查知识缺口。", "omissions": ["检查知识缺口"], "misconceptions": [], "suggested_rating": 2}
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(result, ensure_ascii=False)))])


@asynccontextmanager
async def lifespan(app):
    await init_db()
    async with async_session_maker() as session:
        if await session.get(Document, DOC_ID) is None:
            session.add(Document(id=DOC_ID, title="学习方法示例.md", file_type=".md", status="completed"))
            await session.flush()
            session.add(DocumentChunk(document_id=DOC_ID, chunk_index=0, content=EVIDENCE))
            await session.commit()
    query_service.acompletion = fake_completion
    yield


app = FastAPI(lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"], allow_methods=["*"], allow_headers=["*"])
app.include_router(study_router)
app.include_router(documents_router)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
