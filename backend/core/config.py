import os
from pydantic_settings import BaseSettings

# ponytail: CN network mirror for HF model downloads; set HF_ENDPOINT to override
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")


class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql://postgres:postgres@localhost:5432/knowledge_assistant"

    class Config:
        env_file = ".env"


settings = Settings()

# ---- Ingestion / chunking ----
CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "800"))
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "120"))

# ---- Retrieval ----
VECTOR_CANDIDATES_PER_QUERY = 20
BM25_CANDIDATE_LIMIT = 200
BM25_TERM_LIMIT = 20  # max query terms pushed into SQL ILIKE
FUSION_TOP_K = 20
RRF_K = 60
RERANK_TOP_K = 5
REWRITE_QUERY_COUNT = 3

# ---- Local model defaults (Ollama) ----
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_LLM_MODEL = os.getenv("OLLAMA_LLM_MODEL", "qwen2.5:7b")
OLLAMA_EMBEDDING_MODEL = os.getenv("OLLAMA_EMBEDDING_MODEL", "bge-m3")
RERANKER_MODEL = os.getenv("RERANKER_MODEL", "BAAI/bge-reranker-v2-m3")

# OpenAI-compatible base URLs for cloud providers routed via LiteLLM
PROVIDER_BASE_URLS = {
    "deepseek": "https://api.deepseek.com/v1",
    "alibaba": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "zhipu": "https://open.bigmodel.cn/api/paas/v4",
    "moonshot": "https://api.moonshot.cn/v1",
}

NO_CONTEXT_ANSWER = "知识库中未找到与问题相关的内容。"
