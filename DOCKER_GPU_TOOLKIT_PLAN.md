# 用 NVIDIA Container Toolkit 优化 GPU 推理与本地部署（讨论计划书）

> 本文是**讨论评估型**文档：给出目标架构、方案对比、收益成本、风险与验收标准，
> 不直接产出可构建的完整 Dockerfile，也不改动任何现有代码。
> 定位：Windows 11 + NVIDIA 独显的本地单用户部署；默认 Docker Compose v2。

---

## 1. 背景与现状

当前项目的实际部署形态（对照代码核实）：

- `docker-compose.yml` 里**只有一个服务**：`pgvector/pgvector:pg16`（Postgres + pgvector），带 named volume 与健康检查。
- 仓库内**没有任何 Dockerfile**；前端靠 `start_fe.sh` / `npm run dev`，后端靠 `python main.py`，均为宿主机裸跑。
- 本地对话与嵌入模型依赖**宿主机安装的 Ollama**，默认地址 `http://localhost:11434`（`backend/core/config.py` 中 `OLLAMA_BASE_URL`，支持环境变量覆盖）。
- RAG 精排模型在**后端进程内**加载：`backend/services/retrieval_service.py` 用 `sentence_transformers.CrossEncoder`（torch，经 `asyncio.to_thread` 在线程中加载）；`requirements.txt` 目前注明 torch 装 **CPU 版**即可。Reranker 首次运行自动下载 `bge-reranker-v2-m3`（约 600MB）。
- 模型下载已有 HF 镜像约定：`config.py` 里通过 `HF_ENDPOINT` 走国内镜像。

由此带来的痛点：

| 痛点 | 说明 |
|---|---|
| 环境依赖重且分散 | Python 3.13、Node 20、torch、Ollama、模型文件散落在宿主机，换机/重装成本高 |
| GPU 闲置 | 7B 对话模型与 cross-encoder 精排都很吃算力，reranker 走 CPU 时是问答链路里明显的延迟点 |
| 版本耦合 | 本地 Python/Node/Ollama 版本与项目要求强绑定，容易出现「我机器上能跑」 |
| 启动步骤多 | 起 DB、起 Ollama、拉模型、起后端、起前端，缺一步就跑不通 |

---

## 2. NVIDIA Container Toolkit：能力与适用边界

**它解决什么**：让容器通过 NVIDIA container runtime 安全地调用宿主机的 NVIDIA GPU 与驱动，
**不需要在镜像里安装 NVIDIA 驱动**（驱动只存在于宿主机，镜像内只放 CUDA 用户态库 / 框架 wheel）。

**目标环境：Windows 11 + NVIDIA 独显 + Docker Desktop（WSL2 后端）**

- 宿主机只需安装**最新的 NVIDIA Windows 驱动**；Docker Desktop 借助 WSL2 的 GPU 直通（`/dev/dxg`）让 Linux 容器看到 GPU，**无需**在 WSL 里另装驱动。
- 在 Compose v2 里用 `deploy.resources.reservations.devices` 声明 GPU 即可，不需要再写老式的 `runtime: nvidia`。
- 验证手段：容器内执行 `nvidia-smi` 能看到卡与驱动版本。

**Linux 原生差异**（备机/服务器场景）：需安装发行版对应的 `nvidia-container-toolkit` 并配置 Docker daemon，然后用 `docker run --gpus all`；Compose 的 devices 声明写法一致。

**不适用场景**：Apple Silicon（Docker Desktop 仅通过 Metal 提供有限 GPU 支持，本地模型更适合直接用原生 Ollama）与纯 CPU 机器——这两类维持现有裸跑 / CPU 推理方案即可，本计划不覆盖。

---

## 3. 目标架构（讨论稿）

全栈收敛到一个 compose 网络，GPU 消费者有两个：**Ollama**（qwen3.5:7b 对话、bge-m3 嵌入）与**后端容器内的 reranker**（torch CUDA）。

```mermaid
graph TB
    subgraph Host["Windows 11 宿主机 (NVIDIA 驱动)"]
        subgraph Compose["docker compose 网络"]
            FE["frontend<br/>Node/Next.js :3000"]
            BE["backend<br/>FastAPI :8000<br/>(进程内 CrossEncoder, GPU)"]
            OL["ollama (GPU)<br/>qwen3.5:7b / bge-m3 :11434"]
            PG["postgres + pgvector :5432"]
        end
        GPU["NVIDIA GPU<br/>(Container Toolkit 直通)"]
    end

    Browser["浏览器"] --> FE
    FE -->|HTTP| BE
    BE -->|OpenAI 兼容 API| OL
    BE -->|SQL/向量| PG
    OL -. GPU 调用 .-> GPU
    BE -. GPU 调用 .-> GPU
```

要点：

- 四服务：`frontend` / `backend` / `ollama` / `postgres`，服务间用服务名通信；后端访问模型改为 `http://ollama:11434`。
- 持久化走 named volume：Ollama 模型目录、`backend/uploads/`、Postgres 数据，容器重建不丢数据、不重复下模型。
- `HF_ENDPOINT` 作为环境变量注入后端容器，reranker 模型走镜像站，避免 600MB 重复下载。

---

## 4. 方案对比与推荐路线

### 方案 A — 最小改动：仅容器化 Ollama 并申请 GPU

- 只在 compose 增加 `ollama` 服务（官方镜像 + GPU devices 声明 + 模型卷），暴露 `11434`；前端、后端继续在宿主机裸跑，经 `localhost:11434` 访问（与现状地址一致，零代码改动）。
- 价值：最快验证「Windows/WSL2 → 容器 → GPU」链路是否打通，风险最低；后端暂不需要 CUDA 镜像。
- 局限：reranker 仍在宿主机、仍走 CPU；环境复现问题大部分没解决。

### 方案 B — 推荐目标：全栈 compose，reranker 上 GPU

- `frontend`（Node 镜像）、`backend`（**基于 `nvidia/cuda` + Python** 的镜像）、`ollama`、`postgres` 全部进 compose；一条 `docker compose up` 起全套。
- 后端镜像 torch 从 CPU wheel 换成 **CUDA wheel**，进程内 `CrossEncoder` 直接吃 GPU。
- 通过环境变量 `OLLAMA_BASE_URL=http://ollama:11434` 让后端走 compose 服务名。
- `depends_on` + 健康检查保证 ollama/postgres 就绪后再起后端。
- 代价：后端镜像含 CUDA 运行库 + torch，体积达数 GB。

### 方案 C — 远期：reranker 独立成 GPU 推理服务

- 用独立的推理服务（如 Hugging Face TEI，或自建一个轻量 FastAPI 包装 CrossEncoder）承载精排，后端回归为**不含 torch 的轻量镜像**，两者独立伸缩、独立排队。
- 结论：当前是**单机单用户**场景，额外一个常驻 GPU 服务带来的运维复杂度不划算（YAGNI）。仅当未来出现多用户并发、或后端要频繁发版而不想每次背大镜像时再做。

### 对比简表

| | 方案 A：容器化 Ollama | 方案 B：全栈 compose（推荐） | 方案 C：独立精排服务 |
|---|---|---|---|
| 改动面 | compose 加 1 个服务，代码零改 | 新增前后端 Dockerfile、compose、1 处配置修复 | B 之上再拆服务、定义内部 API |
| 镜像体积代价 | 小（仅 ollama 镜像） | 大（CUDA+torch 后端，数 GB） | 后端轻、推理服务镜像大 |
| 主要收益 | 验证 GPU 链路、对话模型上 GPU | 一键复现环境；对话 + 精排都用 GPU；版本解耦 | 后端轻量、可独立扩精排 |
| 主要风险 | 几乎无 | WSL2 直通、显存竞争、首次模型拉取 | 多一跳网络与运维成本，当前过剩 |

**推荐路线**：先做 **A** 打通并验证 GPU 直通，再做 **B** 达成全栈一键部署；**C** 仅作为演进项记录。

---

## 5. 关键改造点（评估，不落地完整配置）

### 5.1 Compose 的 GPU 声明（A、B 通用）

Compose v2 推荐写法（关键片段，示意）：

```yaml
services:
  ollama:
    image: ollama/ollama:latest
    ports: ["11434:11434"]
    volumes:
      - ollama_data:/root/.ollama
    healthcheck:
      test: ["CMD", "ollama", "list"]
      interval: 10s
      retries: 5
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: all
              capabilities: [gpu]
volumes:
  ollama_data:
```

> 不再需要 Compose v1 时代的 `runtime: nvidia`；方案 B 中后端服务要吃 GPU 也用同一段 devices 声明。

### 5.2 后端容器化（方案 B）

- 基础镜像在「`nvidia/cuda:*-runtime` + 自行装 Python」与「官方 Python 镜像 + pip 装 CUDA 版 torch」之间取舍：
  - 前者 CUDA 库匹配最省心，但镜像大、需自己配 Python；
  - 后者构建简单，靠 pip 的 CUDA wheel 自带用户态库。评估阶段倾向**后者**（Dockerfile 更短、可维护），最终以 `torch.cuda.is_available()` 实测为准。
- **前置修复项（容器化时才需要，本次不改）**：`backend/core/config.py` 已支持 `OLLAMA_BASE_URL` 覆盖，但 `backend/services/embedding_service.py:23` 另有一处硬编码 `OLLAMA_BASE_URL = "http://localhost:11434"`，未读 config。容器内服务名是 `ollama` 而非 `localhost`，实施 B 时必须把这里改为引用 `config.OLLAMA_BASE_URL`，否则嵌入调用连不到模型容器。
- 通过环境注入：`DATABASE_URL=postgresql+asyncpg://postgres:postgres@postgres:5432/knowledge_assistant`、`OLLAMA_BASE_URL=http://ollama:11434`、`HF_ENDPOINT=<镜像站>`。
- `uploads/` 挂卷，保证上传文档在容器重建后仍在。

### 5.3 启动顺序与依赖

- 后端 `dep_on`：`postgres`（`pg_isready` 健康检查，已存在）与 `ollama`（`ollama list` 或探活 `/api/tags`）都 healthy 后再启动，避免后端启动即连库/连模型失败。
- 模型预拉取：compose 起后仍需 `ollama pull qwen3.5:7b`、`ollama pull bge-m3`；可在文档里提供一次性初始化命令，**不**建议在镜像构建期内联拉模型（镜像与模型应解耦）。

---

## 6. 收益 / 成本 / 风险

**收益**

- 一条 `docker compose up` 完成全栈环境复现，新机上手从「装半天」变「拉镜像」。
- GPU 同时加速 7B 对话生成与 cross-encoder 精排，缩短 RAG 响应中的精排延迟与首 token 等待。
- Python/Node/Ollama 版本与宿主机解耦，依赖冲突、他人机器路径问题消失。

**成本**

- 含 CUDA+torch 的后端镜像体积达**数 GB**，首次构建/拉取慢；可后续用多阶段构建、`.dockerignore` 瘦身（属于实施阶段）。
- 首次需下载对话/嵌入/精排模型（7B 模型数 GB + reranker 约 600MB），但走 named volume 只下一次。
- Ollama 与 reranker **共享同一张卡**：需要用量化模型（当前 qwen3.5:7b 已较小）、控制并发；显存吃紧时优先保证对话，精排可回退 CPU 或在设置中关闭 reranker（产品已有开关）。

**风险与注意**

- WSL2 GPU 直通对 Windows 版本与 NVIDIA 驱动版本有要求；老版本/老卡可能不满足，方案 A 就是用来提前排雷。
- Windows 下 volume 挂载的文件权限与路径差异需实测；`uploads/` 与模型卷建议用 named volume 而非宿主目录绑定，规避权限坑。
- `start_fe.sh` 内含他人 macOS 绝对路径（`/Users/lv/Workspace/...`），**不可复用**为容器入口；容器入口应直接 `npm run dev` / `npm start`。
- **镜像内不要安装 NVIDIA 驱动**——驱动由宿主机/WSL 提供，镜像只放 CUDA 用户态库，装错会导致与宿主机驱动不兼容。

---

## 7. 验证与验收标准

**环境级（GPU 直通是否成立）**

- Ollama 容器内 `nvidia-smi` 能看到显卡与驱动版本。
- 后端容器（方案 B）内 `python -c "import torch; print(torch.cuda.is_available())"` 输出 `True`，且加载后的 `CrossEncoder.device` 为 `cuda`。

**功能级（链路不回归）**

- 全栈 compose 下完成一次 `POST /chat/rag`：查询改写 → 向量+BM25 召回 → RRF → GPU 精排 → 流式回答 + sources/verification meta 帧，全链路正常。
- 在后端容器内跑通现有测试：`backend/tests/test_retrieval.py`、`backend/tests/test_pipeline.py`。
- 上传文档 → 建索引 → 命中文档的问答闭环可用，`uploads/` 卷持久化生效。

**性能级（只定方法，不杜撰数字）**

- 固定一组相同问题，分别在「CPU 基线」与「GPU 方案」下记录：reranker 单批耗时、首 token 延迟（TTFT）、总响应时长，填入下表对比（数值实施时实测填写）。

| 指标 | CPU 基线 | GPU（方案 B） | 备注 |
|---|---|---|---|
| Reranker 耗时 (ms) | 待测 | 待测 | 固定 Top-K 候选数 |
| 首 token 延迟 TTFT (ms) | 待测 | 待测 | 同一 7B 模型 |
| 端到端响应时长 (ms) | 待测 | 待测 | 同一问题集 |

**回滚**

- `docker compose down` 后，宿主机现有裸跑方式（本机 Ollama + `python main.py` + `npm run dev`）完全不受影响；方案 A/B 均为增量，不修改宿主机已安装环境。

---

## 8. 结论与建议下一步

1. 先落地方案 A：compose 增加 GPU 版 Ollama，用 `nvidia-smi` + 一次本地问答确认 WSL2 GPU 直通。
2. A 通过后再评估方案 B：新增前后端 Dockerfile、修复 `embedding_service.py:23` 的硬编码地址、补齐健康检查与卷，实现一键全栈。
3. 方案 C（独立精排服务）暂不实施，待出现多用户并发或后端发版频率上升的真实需求再议。