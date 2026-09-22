"""
检索服务：向量召回 + BM25（jieba 分词）+ RRF 融合 + cross-encoder 精排。
BM25 公式移植自 ChainMind，分词器替换为 jieba 以支持中文。
"""
import asyncio
import math
import re
from typing import Awaitable, Callable, Dict, List, Optional

import jieba
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from core import config
from models.database import Document, DocumentChunk

CJK_RE = re.compile(r"[\u4e00-\u9fff]")
WORD_RE = re.compile(r"[a-z0-9_]+")


def tokenize(text: str) -> List[str]:
    """中英文混合分词：英文按词，中文按 jieba，单字/停用短词过滤。"""
    text = text.lower()
    tokens = WORD_RE.findall(text)
    for piece in jieba.cut(text):
        piece = piece.strip()
        if len(piece) >= 2 and CJK_RE.search(piece):
            tokens.append(piece)
    return tokens


def bm25_scores(
    query_tokens: List[str],
    docs_tokens: List[List[str]],
    k1: float = 1.5,
    b: float = 0.75,
) -> List[float]:
    """对已分词的候选文档集合计算 BM25 分数（idf 基于候选集合）。"""
    n = len(docs_tokens)
    if n == 0:
        return []
    lengths = [len(d) for d in docs_tokens]
    avgdl = sum(lengths) / n or 1.0

    doc_freq: Dict[str, int] = {}
    for tokens in docs_tokens:
        for term in set(tokens):
            doc_freq[term] = doc_freq.get(term, 0) + 1

    scores = [0.0] * n
    for term in query_tokens:
        df = doc_freq.get(term, 0)
        if df == 0:
            continue
        idf = math.log((n - df + 0.5) / (df + 0.5) + 1)
        for i, tokens in enumerate(docs_tokens):
            tf = tokens.count(term)
            if tf == 0:
                continue
            denom = tf + k1 * (1 - b + b * lengths[i] / avgdl)
            scores[i] += idf * (tf * (k1 + 1)) / denom
    return scores


def rrf_fuse(rank_lists: List[List[str]], k: int = config.RRF_K) -> Dict[str, float]:
    """多路 RRF 融合，rank_lists 为按相关度排序的 chunk id 列表。"""
    fused: Dict[str, float] = {}
    for ranked in rank_lists:
        for rank, chunk_id in enumerate(ranked):
            fused[chunk_id] = fused.get(chunk_id, 0.0) + 1.0 / (k + rank + 1)
    return fused


class EmbeddingDimensionMismatch(Exception):
    """库内向量维度与当前 embedding 模型不一致。"""


class Reranker:
    """bge-reranker cross-encoder，懒加载；失败后永久降级。"""

    def __init__(self):
        self._model = None
        self.disabled = False

    def _load(self):
        from sentence_transformers import CrossEncoder

        return CrossEncoder(config.RERANKER_MODEL)

    async def score(self, query: str, passages: List[str]) -> Optional[List[float]]:
        if self.disabled or not passages:
            return None
        try:
            if self._model is None:
                self._model = await asyncio.to_thread(self._load)
            pairs = [[query, p] for p in passages]
            return await asyncio.to_thread(self._model.predict, pairs)
        except Exception:
            # ponytail: 模型缺失/下载失败时静默退回 RRF 顺序
            self.disabled = True
            return None


class RetrievalService:
    def __init__(self):
        self.reranker = Reranker()

    async def _embedding_dim_in_db(self, session: AsyncSession) -> Optional[int]:
        row = (
            await session.execute(select(DocumentChunk.embedding).limit(1))
        ).scalar()
        if row is None:
            return None
        if isinstance(row, str):
            import json

            row = json.loads(row)
        return len(row)

    async def vector_search(
        self,
        session: AsyncSession,
        query_embedding: List[float],
        limit: int,
    ) -> List[Dict]:
        rows = (
            await session.execute(
                select(DocumentChunk, Document.title)
                .join(Document, DocumentChunk.document_id == Document.id)
                .order_by(DocumentChunk.embedding.cosine_distance(query_embedding))
                .limit(limit)
            )
        ).all()
        return [self._row_to_dict(chunk, title) for chunk, title in rows]

    async def bm25_search(
        self, session: AsyncSession, query: str
    ) -> List[Dict]:
        terms = tokenize(query)[: config.BM25_TERM_LIMIT]
        if not terms:
            return []

        candidates = (
            await session.execute(
                select(DocumentChunk, Document.title)
                .join(Document, DocumentChunk.document_id == Document.id)
                .where(or_(*[DocumentChunk.content.ilike(f"%{t}%") for t in terms]))
                .limit(config.BM25_CANDIDATE_LIMIT)
            )
        ).all()
        if not candidates:
            return []

        docs = [self._row_to_dict(chunk, title) for chunk, title in candidates]
        docs_tokens = [tokenize(d["content"]) for d in docs]
        scores = bm25_scores(terms, docs_tokens)
        for doc, score in zip(docs, scores):
            doc["bm25_score"] = score
        return [d for d in docs if d["bm25_score"] > 0]

    @staticmethod
    def _row_to_dict(chunk: DocumentChunk, title: str) -> Dict:
        return {
            "chunk_id": str(chunk.id),
            "document_id": str(chunk.document_id),
            "title": title or "未命名文档",
            "chunk_index": chunk.chunk_index,
            "content": chunk.content,
            "snippet": (chunk.content[:200] + "…") if len(chunk.content) > 200 else chunk.content,
        }

    async def hybrid_search(
        self,
        session: AsyncSession,
        queries: List[str],
        embed_fn: Callable[[List[str]], Awaitable[List[List[float]]]],
        use_reranker: bool = True,
    ) -> List[Dict]:
        """完整召回链路：向量多查询 + BM25 + RRF + 精排。"""
        embeddings = await embed_fn(queries)
        if embeddings:
            db_dim = await self._embedding_dim_in_db(session)
            if db_dim is not None and db_dim != len(embeddings[0]):
                raise EmbeddingDimensionMismatch(
                    f"嵌入模型维度不一致（库内 {db_dim} 维 / 当前 {len(embeddings[0])} 维），"
                    "请运行 backend/scripts/reindex.py 重建索引"
                )

        pool: Dict[str, Dict] = {}
        rank_lists: List[List[str]] = []

        per_query = config.VECTOR_CANDIDATES_PER_QUERY
        for embedding in embeddings:
            hits = await self.vector_search(session, embedding, per_query)
            ranked = []
            for hit in hits:
                pool.setdefault(hit["chunk_id"], hit)
                ranked.append(hit["chunk_id"])
            rank_lists.append(ranked)

        bm25_hits = await self.bm25_search(session, queries[0])
        bm25_hits.sort(key=lambda d: d["bm25_score"], reverse=True)
        bm25_ranked = []
        for hit in bm25_hits:
            pool.setdefault(hit["chunk_id"], hit)
            bm25_ranked.append(hit["chunk_id"])
        if bm25_ranked:
            rank_lists.append(bm25_ranked)

        fused = rrf_fuse(rank_lists)
        ordered_ids = sorted(fused, key=lambda cid: fused[cid], reverse=True)[
            : config.FUSION_TOP_K
        ]
        results = []
        for cid in ordered_ids:
            doc = pool[cid]
            doc["score"] = fused[cid]
            results.append(doc)

        if use_reranker and results:
            scores = await self.reranker.score(
                queries[0], [d["content"] for d in results]
            )
            if scores is not None:
                for doc, score in zip(results, scores):
                    doc["score"] = float(score)
                results.sort(key=lambda d: d["score"], reverse=True)

        return results[: config.RERANK_TOP_K]


retrieval_service = RetrievalService()
