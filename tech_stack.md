# Agentic Software Factory — Tech Stack Recommendation

## 1. Orchestration Layer

| Component | Recommendation | Rationale |
|-----------|----------------|-----------|
| Workflow engine | **LangGraph** (Python) | Stateful, cyclic graphs, built-in checkpointers, human-in-the-loop interrupts, native LangChain integration |
| Alternative | **Temporal** | If durable, long-running execution with Java/Go SDKs is preferred over Python |
| Alternative | **CrewAI** | Simpler but less control over state/checkpointing; good for prototyping |

## 2. LLM Backends

| Tier | Provider | Model | Use Case |
|------|----------|-------|----------|
| Primary | **OpenAI** | GPT-4o / o1 | Complex reasoning, architecture, code generation |
| Secondary | **Anthropic** | Claude 3.5 Sonnet | Large-context code review, test generation |
| Fallback / Self-hosted | **Ollama** / **vLLM** | Llama-3.1-70B, Codestral | Privacy-sensitive or cost-sensitive workloads |
| Routing | **LiteLLM** | — | Unified interface, fallback, load balancing, cost tracking |

## 3. Language & Core Libraries

| Component | Recommendation | Version |
|-----------|----------------|---------|
| Runtime | **Python** | 3.11+ |
| State validation | **Pydantic** | v2 |
| Async runtime | **asyncio** + **anyio** | — |
| LLM client | **langchain-core** / **langchain-openai** | — |
| Workflow | **langgraph** | — |
| Git | **GitPython** | — |
| HTTP / API | **FastAPI** + **uvicorn** | — |
| HTTP client | **httpx** | — |
| Config | **pydantic-settings** | — |
| Logging | **structlog** + **loguru** | — |
| Metrics | **prometheus_client** | — |
| Tracing | **opentelemetry-sdk** | — |
| CLI | **typer** + **rich** | — |
| Testing | **pytest** + **pytest-asyncio** | — |
| Serialization | **pydantic** / **orjson** | — |

## 4. Execution Sandbox

| Component | Recommendation | Rationale |
|-----------|----------------|-----------|
| Version control | **Git** + **worktrees** | Lightweight, isolated per-module workspaces, shared object DB |
| Host | GitHub (remote) + local worktrees | PR-based review, CI/CD integration |
| Container runtime | **Docker** | For running test suites and builds in isolation |

## 5. Observability

| Component | Recommendation |
|-----------|----------------|
| Structured logging | **structlog** (JSON) |
| Dashboard UI | **FastAPI** + **React** (or Jinja2 templates for lightweight) |
| Metrics storage | **Prometheus** (or in-memory for MVP) |
| Trace backend | **OpenTelemetry Collector** -> **Jaeger** / **LangSmith** |
| Alerting | **Prometheus Alertmanager** |

## 6. CI/CD & Deployment

| Component | Recommendation |
|-----------|----------------|
| CI platform | **GitHub Actions** |
| Container registry | **GitHub Container Registry (GHCR)** / **Docker Hub** |
| Deployment target | **Kubernetes** / **AWS ECS** / **Render** / **Fly.io** |
| IaC | **Terraform** / **Pulumi** (optional, for production) |

## 7. Infrastructure (Docker Compose for local dev)

| Service | Image | Purpose |
|---------|-------|---------|
| factory-api | custom (Python) | Orchestrator + dashboard API |
| redis | redis:7-alpine | LangGraph checkpointer + state cache |
| prometheus | prom/prometheus | Metrics scraping |
| jaeger | jaegertracing/all-in-one | Distributed tracing |

## 8. Why This Stack

- **Python + LangGraph**: Best-in-class agent orchestration with state, memory, checkpoints, and HITL interrupts.
- **Pydantic**: Strict, self-documenting state models that prevent invalid agent handoffs.
- **Git worktrees**: Zero-copy isolation for concurrent agents; no branch/index pollution.
- **FastAPI + structlog**: High-performance observability dashboard with structured telemetry.
- **LiteLLM**: Vendor-agnostic LLM routing with fallback and cost tracking.