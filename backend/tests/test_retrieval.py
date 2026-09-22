"""BM25 / RRF / 分词 / 结构分块的纯函数测试。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.document_service import document_service
from services.retrieval_service import bm25_scores, rrf_fuse, tokenize


def test_tokenize_chinese_and_english():
    tokens = tokenize("代码漏洞 SQL injection")
    assert "代码" in tokens or "漏洞" in tokens
    assert "sql" in tokens
    assert "injection" in tokens


def test_bm25_ranks_term_match_first():
    docs = [
        tokenize("完全无关的内容"),
        tokenize("本文讨论代码漏洞的成因与修复"),
        tokenize("代码漏洞在多个系统中反复出现"),
    ]
    scores = bm25_scores(tokenize("代码漏洞"), docs)
    assert scores[1] > scores[0]
    assert scores[2] > scores[0]


def test_bm25_no_match_returns_zero():
    scores = bm25_scores(tokenize("不存在的词xyz"), [tokenize("其它内容")])
    assert scores == [0.0]


def test_rrf_single_list_keeps_order():
    fused = rrf_fuse([["a", "b", "c"]])
    assert list(fused) == ["a", "b", "c"]


def test_rrf_overlap_and_disjoint():
    fused = rrf_fuse([["a", "b"], ["b", "c"]])
    assert fused["b"] > fused["a"]  # 双路命中排第一
    assert "c" in fused  # 单路也保留


def test_chunk_keeps_heading_intact():
    text = "# 标题一\n\n第一段内容。\n\n## 子标题\n\n第二段内容。"
    chunks = document_service.chunk_text(text, chunk_size=800, overlap=120)
    assert all("第" in c for c in chunks)
    joined = "\n".join(chunks)
    assert "# 标题一" in joined
    # 标题不应被切散到两个块的中间
    assert not any("# 标题" in c and c.count("# ") > 2 for c in chunks)


def test_long_paragraph_gets_overlap_windows():
    text = "字" * 2000
    chunks = document_service.chunk_text(text, chunk_size=800, overlap=120)
    assert len(chunks) >= 3
    assert all(len(c) <= 800 for c in chunks)
