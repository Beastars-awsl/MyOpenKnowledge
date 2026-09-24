"""
本地 Ollama 模型探测接口。
Ollama 未启动或不可达时不报错，返回 available=false，前端静默降级。
"""
import httpx
from fastapi import APIRouter

from core.config import OLLAMA_BASE_URL

router = APIRouter(prefix="/ollama", tags=["ollama"])


@router.get("/models")
async def list_ollama_models():
    try:
        # Ollama 是本地服务，忽略环境代理，避免 localhost 请求被转发到代理
        async with httpx.AsyncClient(timeout=2.0, trust_env=False) as client:
            resp = await client.get(f"{OLLAMA_BASE_URL}/api/tags")
            resp.raise_for_status()
            data = resp.json()
    except Exception:
        return {"available": False, "models": []}

    models = []
    for item in data.get("models", []):
        name = item.get("name")
        if not name:
            continue
        capabilities = item.get("capabilities") or []
        # 仅有 embedding 能力的模型（如 bge）不能作为对话模型
        embedding_only = bool(capabilities) and all(
            c == "embedding" for c in capabilities
        )
        models.append(
            {
                "name": name,
                "size": item.get("size", 0),
                "modified_at": item.get("modified_at"),
                "embedding_only": embedding_only,
            }
        )
    return {"available": True, "models": models}
