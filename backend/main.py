import os

# 必须在任何可能传递导入 huggingface_hub 的模块之前设置，
# 否则其 ENDPOINT 常量已被绑定为 huggingface.co，镜像不生效。
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from api.chat import router as chat_router
from api.documents import router as documents_router
from api.memories import router as memories_router
from api.conversations import router as conversations_router
from api.study import router as study_router
from api.ollama import router as ollama_router
from core.database import init_db

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    await init_db()
    # 后台预下载 reranker，不阻塞启动；下载期间问答降级为 RRF
    from services.retrieval_service import retrieval_service
    import asyncio as _asyncio
    _asyncio.create_task(retrieval_service.reranker.preload())
    yield
    # Shutdown

app = FastAPI(title="Knowledge Assistant API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:3001", "http://127.0.0.1:3000", "http://127.0.0.1:3001"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
    max_age=86400,
)

app.include_router(chat_router)
app.include_router(documents_router)
app.include_router(memories_router)
app.include_router(conversations_router)
app.include_router(study_router)
app.include_router(ollama_router)

@app.get("/")
async def root():
    return {"message": "Knowledge Assistant API"}

@app.get("/health")
async def health():
    return {"status": "ok"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
