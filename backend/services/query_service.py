"""
查询改写与回答校验：两个非流式 LLM JSON 调用，失败一律静默降级。
"""
import asyncio
import json
import re
from typing import Any, Dict, Optional, Tuple

from core import config


def _litellm():
    import litellm

    litellm.drop_params = True
    return litellm


def resolve_model(
    model: str, provider: str, api_key: Optional[str], base_url: Optional[str]
) -> Tuple[str, Dict[str, Any]]:
    """把 (model, provider) 映射为 LiteLLM 的 model 字符串与调用参数。"""
    provider = (provider or "openai").lower()
    kwargs: Dict[str, Any] = {"timeout": 30}

    if provider == "ollama":
        # 本地模型冷启动（加载数 GB 权重）较慢，给更宽裕的超时
        return f"ollama/{model}", {
            **kwargs,
            "timeout": 180,
            "api_base": base_url or config.OLLAMA_BASE_URL,
            "api_key": "ollama",
        }
    if provider in ("alibaba", "zhipu", "moonshot", "deepseek"):
        return f"openai/{model}", {
            **kwargs,
            "api_key": api_key,
            "api_base": base_url or config.PROVIDER_BASE_URLS.get(provider),
        }
    if provider == "anthropic":
        return f"anthropic/{model}", {**kwargs, "api_key": api_key}
    if provider == "google":
        return f"gemini/{model}", {**kwargs, "api_key": api_key}
    if provider in ("cohere", "mistral"):
        return f"{provider}/{model}", {**kwargs, "api_key": api_key}
    # openai 及其它 OpenAI 兼容端点
    openai_kwargs = {**kwargs, "api_key": api_key}
    if base_url:
        openai_kwargs["api_base"] = base_url
    return model, openai_kwargs


async def acompletion(
    model: str,
    provider: str,
    api_key: Optional[str],
    base_url: Optional[str],
    messages: list,
    stream: bool = False,
    **extra,
):
    litellm = _litellm()
    litellm_model, kwargs = resolve_model(model, provider, api_key, base_url)
    return await litellm.acompletion(
        model=litellm_model, messages=messages, stream=stream, **kwargs, **extra
    )


def _parse_json(text: str) -> Optional[dict]:
    if not text:
        return None
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None


async def llm_json(
    system_prompt: str,
    user_prompt: str,
    model: str,
    provider: str,
    api_key: Optional[str],
    base_url: Optional[str],
    timeout: int = 20,
) -> Optional[dict]:
    try:
        response = await asyncio.wait_for(
            acompletion(
                model,
                provider,
                api_key,
                base_url,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            ),
            timeout=timeout,
        )
        content = response.choices[0].message.content or ""
        return _parse_json(content)
    except Exception:
        return None


REWRITE_SYSTEM = (
    "你是查询改写助手。根据用户问题输出 JSON，不要输出任何其它内容：\n"
    '{"intent": "用户真实意图的简短概括", '
    '"queries": ["原问题", "改写1", "改写2"]}\n'
    "改写应：消除指代、补充上下文、换一种关键词表达；与原问题保持同一意图。"
)

VERIFY_SYSTEM = (
    "你是事实核查员。只依据给定资料判断回答是否准确，输出 JSON：\n"
    '{"accuracy": "high/medium/low", "has_hallucination": true/false, '
    '"issues": ["问题1"]}'
)


async def rewrite_query(
    message: str,
    model: str,
    provider: str,
    api_key: Optional[str],
    base_url: Optional[str],
) -> Dict[str, Any]:
    data = await llm_json(
        REWRITE_SYSTEM, message, model, provider, api_key, base_url
    )
    queries = [message]
    intent = message
    if isinstance(data, dict):
        raw_queries = data.get("queries")
        if isinstance(raw_queries, list):
            seen = set()
            for q in raw_queries:
                q = str(q).strip() if q is not None else ""
                if q and q not in seen:
                    seen.add(q)
                    queries.append(q)
        if isinstance(data.get("intent"), str) and data["intent"].strip():
            intent = data["intent"].strip()
    return {"intent": intent, "queries": queries[: config.REWRITE_QUERY_COUNT]}


async def verify_answer(
    query: str,
    answer: str,
    contexts,
    model: str,
    provider: str,
    api_key: Optional[str],
    base_url: Optional[str],
) -> Optional[dict]:
    context_str = "\n\n".join(f"[{i + 1}] {c}" for i, c in enumerate(contexts))
    user_prompt = f"资料：\n{context_str}\n\n问题：{query}\n\n回答：{answer}"
    data = await llm_json(
        VERIFY_SYSTEM, user_prompt, model, provider, api_key, base_url
    )
    if not isinstance(data, dict) or "accuracy" not in data:
        return None
    return {
        "accuracy": data.get("accuracy", "medium"),
        "has_hallucination": bool(data.get("has_hallucination", False)),
        "issues": data.get("issues", []) if isinstance(data.get("issues"), list) else [],
    }
