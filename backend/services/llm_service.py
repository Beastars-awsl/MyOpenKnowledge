"""
LLM 编排服务：普通对话与完整 RAG 流水线（查询改写→混合检索→引用生成→幻觉校验）。
SSE 元信息帧以单独的行发送：<<META>>{json}
"""
import json
from typing import Any, Dict, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from core import config
from services import query_service
from services.embedding_service import embedding_service
from services.memory_service import memory_service
from services.retrieval_service import retrieval_service
from services.tools_service import tools_service

META_PREFIX = "<<META>>"


def is_meta_frame(text: str) -> bool:
    return text.lstrip("\n").startswith(META_PREFIX)


def _meta(payload: dict) -> str:
    return f"{META_PREFIX}{json.dumps(payload, ensure_ascii=False)}\n"


RAG_SYSTEM = (
    "你是个人文件助手。只能根据下面【资料】中的内容回答，使用与用户问题相同的语言。\n"
    "要求：\n"
    "1. 每条事实性结论后用 [n] 标注来源编号。\n"
    "2. 资料不足以回答时，直接说明资料不足，不要编造。\n"
    "3. 不要输出与问题无关的内容。\n"
    "【资料】\n{context}"
)

PLAIN_SYSTEM = "你是乐于助人的个人助手，使用与用户问题相同的语言回答。"


class LLMService:
    async def stream_chat(
        self,
        message: str,
        api_key: str,
        model: str,
        use_rag: bool = False,
        use_memory: bool = False,
        use_tools: bool = False,
        base_url: Optional[str] = None,
        session: Optional[AsyncSession] = None,
        history: Optional[List[Dict[str, str]]] = None,
        provider: str = "openai",
        use_local_embedding: bool = False,
        use_reranker: bool = True,
    ):
        history = history or []

        if use_rag and session is not None:
            async for chunk in self._stream_rag(
                message,
                api_key,
                model,
                provider,
                base_url,
                session,
                history,
                use_memory,
                use_local_embedding,
                use_reranker,
            ):
                yield chunk
            return

        system_prompt = PLAIN_SYSTEM
        if use_memory and session is not None:
            memories = await memory_service.search_relevant_memories(
                message,
                api_key,
                session,
                provider=provider,
                base_url=base_url,
            )
            if memories:
                facts = "\n".join(f"- {m.content}" for m in memories)
                system_prompt += f"\n\n已知的用户信息：\n{facts}"

        async for chunk in self._generate(
            message, system_prompt, history, model, provider, api_key, base_url,
            use_tools=use_tools,
        ):
            yield chunk

    async def _stream_rag(
        self, message, api_key, model, provider, base_url, session,
        history, use_memory, use_local_embedding, use_reranker,
    ):
        rewritten = await query_service.rewrite_query(
            message, model, provider, api_key, base_url
        )
        queries = rewritten["queries"]

        async def embed_fn(texts: List[str]):
            return await embedding_service.get_embeddings(
                texts,
                api_key or "",
                provider,
                base_url if base_url else None,
                use_local_embedding,
            )

        sources = await retrieval_service.hybrid_search(
            session, queries, embed_fn, use_reranker=use_reranker
        )

        if not sources:
            yield config.NO_CONTEXT_ANSWER
            return

        context = "\n\n".join(
            f"[{i + 1}] 来源：{s['title']}\n{s['content']}"
            for i, s in enumerate(sources)
        )
        system_prompt = RAG_SYSTEM.format(context=context)
        if use_memory:
            memories = await memory_service.search_relevant_memories(
                message, api_key, session, provider=provider, base_url=base_url
            )
            if memories:
                facts = "\n".join(f"- {m.content}" for m in memories)
                system_prompt += f"\n\n已知的用户信息（仅供参考）：\n{facts}"

        sources_meta = [
            {
                "id": s["chunk_id"],
                "document_id": s["document_id"],
                "title": s["title"],
                "chunk_index": s["chunk_index"],
                "snippet": s["snippet"],
                "score": round(float(s["score"]), 4),
            }
            for s in sources
        ]
        yield _meta({"sources": sources_meta, "intent": rewritten["intent"]})

        answer = ""
        async for chunk in self._generate(
            message, system_prompt, history, model, provider, api_key, base_url
        ):
            answer += chunk
            yield chunk

        verification = await query_service.verify_answer(
            message,
            answer,
            [s["content"] for s in sources],
            model,
            provider,
            api_key,
            base_url,
        )
        if verification is not None:
            yield "\n" + _meta({"verification": verification})

    async def _generate(
        self, message, system_prompt, history, model, provider, api_key, base_url,
        use_tools: bool = False,
    ):
        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(
            h for h in history if h.get("role") in ("user", "assistant") and h.get("content")
        )
        messages.append({"role": "user", "content": message})

        if use_tools:
            tool_messages = await self._run_tools(
                message, model, provider, api_key, base_url
            )
            messages.extend(tool_messages)

        stream = await query_service.acompletion(
            model, provider, api_key, base_url, messages, stream=True
        )
        async for event in stream:
            try:
                delta = event.choices[0].delta.content
            except (AttributeError, IndexError):
                delta = None
            if delta:
                yield delta

    async def _run_tools(self, message, model, provider, api_key, base_url) -> list:
        """单轮 function calling：命中工具就执行并把结果交回模型。"""
        try:
            schemas = tools_service.get_tools()
            response = await query_service.acompletion(
                model,
                provider,
                api_key,
                base_url,
                messages=[{"role": "user", "content": message}],
                tools=schemas,
                tool_choice="auto",
            )
            calls = getattr(response.choices[0].message, "tool_calls", None)
            if not calls:
                return []
            tool_messages = []
            for call in calls:
                import json as _json

                try:
                    args = _json.loads(call.function.arguments or "{}")
                    result = await tools_service.execute_tool(call.function.name, args)
                except Exception as exc:
                    result = {"error": str(exc)}
                tool_messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.id,
                        "name": call.function.name,
                        "content": _json.dumps(result, ensure_ascii=False),
                    }
                )
            return tool_messages
        except Exception:
            return []


llm_service = LLMService()
