# 技术选型说明（面试视角）

> 结合 README「技术栈」与实际代码（`frontend/package.json`、`backend/requirements.txt`）整理。
> 回答口径：先说**业务约束**（本地优先的个人知识库 + RAG），再讲**技术如何匹配约束**，最后主动讲**权衡**。

---

## 0. 一句话主线

这是一个「本地优先、隐私可控」的 RAG 知识助手：文档在本地解析分块 → embedding 入向量库 → 混合检索 + 精排 → 注入上下文流式问答。
所有技术选型都围绕三个约束：**异步 IO 密集**（调 LLM、查库、流式返回）、**检索质量**（中英文混合、需要混合检索）、**本地可部署**（不绑定单一云厂商）。

---

## 1. 前端

### Next.js 16（App Router）+ React 19

- **选型理由**
  - App Router 天然按页面做代码分割与文件式路由，`chat / knowledge / memories / settings` 四个页面结构直接映射目录，零路由配置。
  - SSR/流式能力与后端 SSE 流式问答契合（后端用 `StreamingResponse(text/event-stream)`）。
  - React 19 + Next 16 是当前主线版本，`use client` 边界清晰，交互页（对话、上传）局部水合即可。
- **面试可讲的权衡**：本项目其实是「Next 当 SPA 用」，没有强 SEO 需求，选 Next 主要是工程规范、流式生态和后续可扩展 SSR；用纯 Vite + React 也能做，但路由、目录约定、生产构建要自己搭。
- **可能的追问**：为什么不全 SSR？——答：核心数据是登录后、强交互、实时流式的，SSR 收益低，所以页面基本是客户端组件。

### TypeScript 5（strict）

- 与后端 Pydantic 模型形成「双端契约」：`models/schemas.py` 定义请求/响应，前端 `types/` + `lib/api.ts` 对齐，编译期拦截字段漂移。RAG 链路里 `sources / verification / intent` 这类 meta 帧结构复杂，没有类型很容易在流式解析时出错。

### TailwindCSS 4 + shadcn/ui（Radix UI 原语）

- **Tailwind**：工具类原子化，改样式不动抽象、不产生命名负担；4.x 用 `@tailwindcss/postcss` 接入，构建链简单。
- **shadcn/ui（Radix）**：组件源码直接进仓库（不是黑盒 npm 依赖），可改可审计，契合「本地优先、长期可维护」；Radix 原语自带**键盘导航 / ARIA / 焦点管理**，可访问性不用自己补。
- **权衡**：代价是模板里 class 较长。相比直接用组件库（如 MUI/AntD），shadcn 不背运行时体积和主题强约束，bundle 更可控。

### Zustand 5（+ TanStack Query）

- **Zustand**：会话/设置这类跨页面、需被多处读写的**客户端 UI 状态**，用极简 store（无 boilerplate、无 Context 套娃）；相比 Redux 砍掉了 action/reducer 仪式，个人项目维护成本低。
- **职责划分（面试加分点）**：服务端数据（文档列表、消息）走 `@tanstack/react-query` 的缓存/重试/失效，**UI 状态与服务端状态分离**，而不是全塞进全局 store。
- **追问**：为什么不用 Redux Toolkit？——状态规模小，RTK 的样板和心智成本不划算；Zustand 配合 selector 即可避免无关重渲染。

---

## 2. 后端

### FastAPI 0.109 + Uvicorn（ASGI）

- **核心理由：整条链路是 IO 密集且需要流式**。一次 RAG 请求要串行/并行做：查询改写（LLM）→ embedding → 向量检索 → BM25 检索 → reranker → 再调一次 LLM 流式生成，全程大部分时间在「等网络 / 等模型」。
- `async def` + `async/await` 用单进程事件循环即可高并发挂起大量等待中的请求，不需要为每个请求开线程，省内存也避免 GIL 在等待场景的浪费（reranker 本地推理是 CPU/GPU 重活，放到线程池/后台任务，不阻塞 loop）。
- FastAPI 自带 OpenAPI 文档、依赖注入（`Depends(get_session)` 管理 DB 会话生命周期）、与 Pydantic 一体的请求校验，开发效率高。
- **追问：为什么不用 Django/Flask？** —— Django 异步生态重、ORM 与 pgvector 异步配合不顺；Flask 异步与流式、自动文档要自己拼。FastAPI 在「异步 + 类型契约 + SSE」这个组合上最顺手。

### Pydantic 2

- 边界校验：`ChatRequest / RAGChatRequest` 在进控制器前就完成类型与字段校验，错误前置；与 TS 双端呼应。Pydantic v2 用 Rust 核心（pydantic-core），校验性能比 v1 显著提升。

### SQLAlchemy 2.0（async）+ asyncpg + Alembic

- SQLAlchemy 2.0 的 async session / `select()` 风格与 FastAPI 异步模型统一；`asyncpg` 是 Python 生态性能最好的 async PostgreSQL 驱动。
- ORM 表达 `embedding.cosine_distance()` 这类向量算子很自然（见 `services/rag_service.py`）。
- Alembic 负责迁移，向量列、索引变更可追踪。
- **权衡 / 诚实点**：ORM 对复杂混合检索（向量 + 全文 BM25 自定义打分）表达力有限，所以 BM25 部分在 `retrieval_service` 里自己算，而不是硬塞进 ORM——选对工具边界。

### PostgreSQL 14 + pgvector

- **为什么不用专门的向量库（Milvus/Faiss/Pinecone）？**
  - 本地优先、个人规模数据量下，向量与业务数据（会话、消息、文档、记忆）放在同一个 Postgres 里，**一次查询就能做向量 + 元数据过滤 + 事务**，运维只需一个 `docker-compose` 服务。
  - pgvector 支持 IVFFlat/HNSW 索引和余弦/内积/L2 距离，个人知识库规模足够。
  - 数据备份、ACID、与 SQLAlchemy 生态都复用现成能力。
- **什么时候会换**：数据量到百万/千万级 chunk、需要更高召回 QPS 或更复杂 ANN 调参时，再迁专用向量库；YAGNI，不过早上分布式组件。

### LiteLLM（+ OpenAI SDK，langchain-openai 保留）

- **选型理由：多供应商统一抽象是这个项目的硬需求**（README 明确支持 OpenAI/Claude/Qwen/Ollama 等）。LiteLLM 用 `provider/model` 统一了调用签名、重试、超时、流式格式，新增一家厂商基本只改映射（见 `query_service.resolve_model`），业务代码不感知。
- Ollama 走 `ollama/...` 即可本地推理，云厂商走各自 endpoint，**本地/云端可在设置里无缝切换**，直接服务「本地优先、可选用云」的产品定位。
- **追问：为什么还留 LangChain？** ——早期用 `langchain-openai`，实际 LLM 网关已收敛到 LiteLLM + 直接 SDK 调用（`query_service.acompletion`），减少黑盒抽象、便于控制查询改写/校验这些自定义 JSON 调用。这是一个「重框架 → 薄封装」的真实取舍，可主动讲。

### 中文检索：jieba + sentence-transformers（bge-m3 / bge-reranker-v2-m3）

- **为什么混合检索而不是只靠向量**：纯向量擅长语义模糊匹配，但对**专有名词、编号、精确关键词**不敏感；BM25 擅长词面命中。两者用 RRF 融合（`retrieval_service.rrf_fuse`）互补，是工业界 RAG 的标准稳妥方案。
- **为什么 jieba**：中文没有天然空格分词，BM25 必须先分词；jieba 轻量、离线、无需外部服务，契合本地部署。分词策略是「英文按词、中文 jieba、过滤单字/停用短词」。
- **为什么本地 reranker**：召回（bi-encoder，快）与精排（cross-encoder，准）分离是经典两阶段架构。embedding 模型把 query/doc 分别编码做粗排，reranker 把 query+passage 拼一起算相关性，Top-K 精度明显更高；本地 bge-reranker 保证隐私、可关闭。首次下载约 600MB，所以设置里提供开关。
- **embedding 维度一致性**：bge-m3 是 1024 维，切换云端 embedding 维度会变，因此提供 `scripts/reindex.py` 重建索引，并在检索侧用 `EmbeddingDimensionMismatch` 提前报错而不是查出垃圾结果——这是很实际的工程细节。

### 文档解析：PyMuPDF / pdfplumber / pymupdf4llm / python-docx / BeautifulSoup

- 不同格式用各自最成熟的解析库，而不是一个通用库硬吃：PDF 同时用 PyMuPDF（快、版面）与 pdfplumber（表格/坐标抽取更稳），Word 用 python-docx，HTML 用 bs4。分块（chunking）与解析解耦，输出统一的 chunk 再入库。

### Pydantic-settings + python-dotenv

- 配置走环境变量 / `.env`，本地默认连本地 Postgres 与 Ollama，云 Key 可选注入——12-factor 风格，本地和将来容器部署一套机制。

---

## 3. 架构层面的高频面试点

- **异步边界**：FastAPI 路由 async、SQLAlchemy async、LLM/embedding 都是 await；本地 CPU 重推理（reranker）不能堵事件循环，用后台/线程方式隔离。
- **流式协议**：后端 SSE（`text/event-stream`），前端边收边渲染；meta 帧（`sources / intent / verification`）与正文帧区分，引用来源随答案一起返回，提升可追溯性。
- **检索质量闭环**：查询改写（多查询）→ 向量+BM25 双路召回 → RRF 融合 → cross-encoder 精排 → 答案依据校验（`verify_answer`，无依据时降级为「无上下文」回答），降低幻觉。
- **可降级设计**：查询改写、答案校验失败都「静默降级」，reranker 可关、本地/云 embedding 可切——核心问答链路不因增强模块失败而崩。
- **单体优先**：一个 Next + 一个 FastAPI + 一个 Postgres 容器就能跑，没有上消息队列/微服务/独立向量库，符合规模，降低运维负担。

---

## 4. 「为什么不用 X」速答表

| 替代方案 | 不用的原因 |
|---|---|
| 纯 Vite SPA | 能做，但少了文件路由、流式/SSR 能力与工程约定；Next 边际成本低 |
| Redux Toolkit | 状态规模小，样板成本高于收益；Zustand + React Query 已覆盖 |
| Django/Flask | 异步流式 + 自动文档 + 类型校验组合上 FastAPI 更贴合 |
| Milvus/Faiss/Pinecone | 个人规模 + 本地优先 + 元数据/事务需求，pgvector 足够且少一个组件 |
| 只用向量检索 | 精确关键词/专名召回弱，BM25+向量 RRF 更稳 |
| 只用云 LLM API | 违背隐私/本地优先定位；LiteLLM + Ollama 让本地与云可替换 |
| 重型 LangChain 全家桶 | 自定义环节多，薄封装（LiteLLM/SDK）可控性和可调试性更好 |

---

## 5. 可主动承认的不足 / 演进方向（体现工程判断力）

- `services/rag_service.py` 是早期纯向量召回的遗留实现，实际链路已走 `retrieval_service` 混合检索，后续可删除以免误导。
- BM25 当前基于候选集合实时算 idf，规模上来后应落库做倒排/用 Postgres 全文检索加速。
- 生产化还缺：鉴权、限流、对象存储（上传文件目前落本地 `uploads/`）、向量索引参数调优与检索评测集（召回率/命中率回归）。