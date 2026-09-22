"""RAG 编排链路测试：LLM 全部用 fake litellm 替换，不依赖网络/GPU。"""
import json
import os
import sys
import types

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class _Choice:
    def __init__(self, message=None, delta=None):
        self.message = message
        self.delta = delta


class _Message:
    def __init__(self, content):
        self.content = content
        self.tool_calls = None


class _Response:
    def __init__(self, content):
        self.choices = [_Choice(message=_Message(content))]


class _StreamChoice:
    def __init__(self, content):
        self.delta = types.SimpleNamespace(content=content)


class _FakeStream:
    def __init__(self, text):
        self.text = text

    def __aiter__(self):
        text = self.text

        async def gen():
            for ch in text:
                yield types.SimpleNamespace(choices=[_StreamChoice(ch)])

        return gen()


class FakeLiteLLM:
    drop_params = False

    def __init__(self):
        self.calls = []
        self.rewrite_should_fail = False
        self.verify_should_fail = False
        self.answer = "根据资料，答案如此。[1]"

    async def acompletion(self, *, model, messages, stream=False, **kwargs):
        system = messages[0]["content"] if messages and messages[0].get("role") == "system" else ""
        self.calls.append({"system": system, "stream": stream})
        if "查询改写" in system:
            if self.rewrite_should_fail:
                raise RuntimeError("rewrite boom")
            return _Response(json.dumps({
                "intent": "测试意图",
                "queries": ["原始问题", "改写问题A", "改写问题B"],
            }))
        if "事实核查" in system:
            if self.verify_should_fail:
                raise RuntimeError("verify boom")
            return _Response(json.dumps({
                "accuracy": "high", "has_hallucination": False, "issues": []
            }))
        if stream:
            return _FakeStream(self.answer)
        return _Response("ok")


fake = FakeLiteLLM()
fake_module = types.ModuleType("litellm")
fake_module.acompletion = fake.acompletion
fake_module.drop_params = False
sys.modules["litellm"] = fake_module

from core import config  # noqa: E402
from services import query_service  # noqa: E402
from services.llm_service import META_PREFIX, llm_service  # noqa: E402
from services.retrieval_service import retrieval_service  # noqa: E402

SOURCE = {
    "chunk_id": "c1",
    "document_id": "d1",
    "title": "测试文档",
    "chunk_index": 0,
    "content": "这是与问题直接相关的资料内容。",
    "snippet": "这是与问题直接相关的资料内容。",
    "score": 0.9,
}


async def _collect(**kwargs):
    out = []
    async for chunk in llm_service.stream_chat(
        message="原始问题",
        api_key="",
        model="qwen2.5:7b",
        provider="ollama",
        **kwargs,
    ):
        out.append(chunk)
    return out


def _split_frames(chunks):
    frames, text = [], ""
    for chunk in chunks:
        if chunk.lstrip("\n").startswith(META_PREFIX):
            frames.append(json.loads(chunk.lstrip("\n")[len(META_PREFIX):].strip()))
        else:
            text += chunk
    return frames, text


@pytest.fixture(autouse=True)
def reset_fake():
    fake.calls.clear()
    fake.rewrite_should_fail = False
    fake.verify_should_fail = False
    yield


async def test_rewrite_fallback_on_failure():
    fake.rewrite_should_fail = True
    result = await query_service.rewrite_query(
        "原始问题", "qwen2.5:7b", "ollama", "", None
    )
    assert result["queries"] == ["原始问题"]
    assert result["intent"] == "原始问题"


async def test_zero_hits_skips_generation(monkeypatch):
    async def no_hits(session, queries, embed_fn, use_reranker=True):
        return []

    monkeypatch.setattr(retrieval_service, "hybrid_search", no_hits)
    chunks = await _collect(use_rag=True, session=object())

    assert "".join(chunks) == config.NO_CONTEXT_ANSWER
    assert not any(call["stream"] for call in fake.calls)


async def test_sse_frame_order_and_verification(monkeypatch):
    async def one_hit(session, queries, embed_fn, use_reranker=True):
        return [SOURCE]

    monkeypatch.setattr(retrieval_service, "hybrid_search", one_hit)
    chunks = await _collect(use_rag=True, session=object())

    frames, text = _split_frames(chunks)
    assert len(frames) == 2
    assert "sources" in frames[0]
    assert frames[0]["sources"][0]["document_id"] == "d1"
    assert text == fake.answer
    assert "verification" in frames[1]
    assert frames[1]["verification"]["accuracy"] == "high"


async def test_verification_failure_emits_no_frame(monkeypatch):
    async def one_hit(session, queries, embed_fn, use_reranker=True):
        return [SOURCE]

    monkeypatch.setattr(retrieval_service, "hybrid_search", one_hit)
    fake.verify_should_fail = True
    chunks = await _collect(use_rag=True, session=object())

    frames, text = _split_frames(chunks)
    assert len(frames) == 1
    assert "sources" in frames[0]
    assert text == fake.answer
