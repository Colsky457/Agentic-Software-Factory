# Agentic Software Factory — System Architecture

## 1. Overview

The Agentic Software Factory is an autonomous multi-agent platform that transforms high-level product requirements into tested, deployable software. It uses a **coordinator pattern** orchestrated by **LangGraph**, with four specialized agents, Git worktree sandboxes for isolated execution, human-in-the-loop approval gates, and a structured observability layer.

## 2. Core Components

```
+---------------------------------------------------------------------------+
|                          HUMAN-IN-THE-LOOP (HITL)                         |
|  (approval gates: architecture sign-off, pre-merge, pre-production deploy) |
+---------------------------------------------------------------------------+
                                  |
                                  v
+---------------------------------------------------------------------------+
|                         OBSERVABILITY LAYER                               |
|  Structured logging | Token/usage metrics | FastAPI dashboard UI | Traces |
+---------------------------------------------------------------------------+
                                  |
                                  v
+---------------------------------------------------------------------------+
|                        ORCHESTRATION LAYER (LangGraph)                    |
|                                                                           |
|  +----------------+      +----------------+      +----------------+       |
|  |   Coordinator  |----->|   PM Agent     |----->|   Coder Agent  |       |
|  |  (StateGraph)  |      | (Requirements) |      | (Code Gen)     |       |
|  +----------------+      +----------------+      +----------------+       |
|        |                                                     |            |
|        |                                                     v            |
|        |                                          +----------------+      |
|        |                                          |   QA Agent     |      |
|        |                                          | (Tests/Fixes)  |      |
|        |                                          +----------------+      |
|        |                                                     |            |
|        |                                                     v            |
|        |                                          +----------------+      |
|        |                                          |   DevOps Agent |      |
|        |                                          | (Docker/CI/CD) |      |
|        |                                          +----------------+      |
|        |                                                     |            |
|        +-----------------------------------------------------+            |
|                           Shared State (TypedDict)                        |
+---------------------------------------------------------------------------+
                                  |
                                  v
+---------------------------------------------------------------------------+
|                      EXECUTION SANDBOX (Git Worktrees)                    |
|  Isolated per-agent worktrees | Concurrent editing | No branch collision   |
+---------------------------------------------------------------------------+
                                  |
                                  v
+---------------------------------------------------------------------------+
|                      LLM BACKEND (OpenAI / Anthropic / Local)             |
+---------------------------------------------------------------------------+
```

## 3. Data Flow

1. **Ingestion**: A user submits a high-level product requirement (e.g., "Build a real-time chat app") via CLI or API.
2. **PM Agent**: The coordinator routes to the PM agent, which produces a `TechnicalSpec` (user stories, architecture plan, acceptance criteria, tech stack).
3. **HITL Gate #1**: The spec is presented for human architecture sign-off. On approval, the workflow continues; on rejection, the PM revises.
4. **Coder Agent**: The coordinator spawns isolated Git worktrees per frontend/backend/database module. The coder generates idiomatic code from the spec.
5. **QA Agent**: Writes unit/integration tests, runs the suite, analyzes failures, and triggers self-healing bug-fix loops until tests pass or max retries are reached.
6. **DevOps Agent**: Generates Dockerfiles, CI/CD pipelines (GitHub Actions), and deployment scripts.
7. **HITL Gate #2**: Pre-merge code review approval.
8. **HITL Gate #3**: Pre-production deployment approval.
9. **Artifact Output**: Final repository, test reports, deployment manifests, and observability traces are committed/pushed.

## 4. Agent Communication Protocol

Agents do not call each other directly. All communication flows through the **Coordinator (LangGraph StateGraph)**:

- **State**: A shared `FactoryState` TypedDict carries artifacts between nodes.
- **Messages**: Agents exchange `AgentMessage` objects (sender, recipient, type, payload, timestamp, correlation_id).
- **Handoffs**: The coordinator decides the next node based on state conditions (conditional edges).
- **Error recovery**: On failure, the graph routes to a recovery node that increments retry counters and either retries or escalates to HITL.

### Message Schema

| Field | Type | Description |
|-------|------|-------------|
| `message_id` | UUID | Unique message identifier |
| `sender` | str | Agent role (pm/coder/qa/devops/coordinator) |
| `recipient` | str | Target agent or "broadcast" |
| `type` | str | `spec`, `code`, `test`, `fix`, `deploy`, `review_request`, `approval` |
| `payload` | dict | Typed artifact (see state models) |
| `timestamp` | ISO8601 | Message send time |
| `correlation_id` | UUID | Links to the originating request |
| `trace_id` | UUID | Observability trace span |

## 5. State Management

LangGraph `StateGraph` manages a single `FactoryState` object that is read and updated by each node. State is persisted to a checkpointer (Redis or SQLite) for resumability and error recovery.

### FactoryState Fields

| Field | Type | Purpose |
|-------|------|---------|
| `request_id` | UUID | Top-level request identifier |
| `user_prompt` | str | Original high-level requirement |
| `phase` | str | Current workflow phase |
| `technical_spec` | TechnicalSpec | PM output |
| `code_artifacts` | dict[str, CodeArtifact] | Coder output keyed by module |
| `test_results` | TestResult | QA output |
| `devops_artifacts` | DevOpsArtifacts | DevOps output |
| `messages` | list[AgentMessage] | Agent communication log |
| `worktrees` | dict[str, str] | Module -> worktree path |
| `approvals` | dict[str, ApprovalRecord] | HITL gate states |
| `retry_counts` | dict[str, int] | Per-agent retry counters |
| `metrics` | UsageMetrics | Token/cost/timing telemetry |
| `errors` | list[FactoryError] | Accumulated errors |
| `status` | str | `pending`, `running`, `paused`, `completed`, `failed` |

## 6. Orchestration Graph (LangGraph)

Nodes:
- `ingest` — validate and normalize the user prompt
- `pm_agent` — produce technical spec
- `hitl_architecture_gate` — pause for architecture sign-off
- `coder_agent` — generate code per module in worktrees
- `qa_agent` — write + run tests, self-heal
- `hitl_premerge_gate` — pause for pre-merge review
- `devops_agent` — generate Docker/CI/CD/deploy scripts
- `hitl_deploy_gate` — pause for production deploy approval
- `finalize` — commit artifacts, emit traces, finish

Edges:
- `ingest` -> `pm_agent`
- `pm_agent` -> `hitl_architecture_gate` (conditional on spec quality)
- `hitl_architecture_gate` -> `pm_agent` (revision loop) or `coder_agent` (approved)
- `coder_agent` -> `qa_agent`
- `qa_agent` -> `qa_agent` (self-heal loop on failure) or `hitl_premerge_gate`
- `hitl_premerge_gate` -> `coder_agent` (rework) or `devops_agent` (approved)
- `devops_agent` -> `hitl_deploy_gate`
- `hitl_deploy_gate` -> `finalize` (approved) or terminal (rejected)
- `finalize` -> END

Error handling: any node raising an exception routes to `error_handler`, which increments retry counters and either retries (up to max) or transitions to `failed` with HITL escalation.

## 7. Execution Sandbox — Git Worktrees

Each module (frontend, backend, database, infra) gets its own Git worktree under `.factory/worktrees/<module>/`. Worktrees:

- Share the object database (no duplication of history)
- Have independent working trees and index (no index pollution)
- Allow concurrent agent edits without branch collision
- Are cleaned up after workflow completion (or retained on failure for debugging)

Manager responsibilities:
- Create/delete worktrees
- Track worktree -> module mapping in state
- Stage/commit changes per module
- Expose worktree paths to agents for file I/O

## 8. Observability & Logging

- **Structured logging**: JSON logs with `trace_id`, `span_id`, `agent_role`, `phase`, `event`, `metadata`.
- **Metrics**: token usage (prompt/completion), cost estimates, tool call counts, latency per node, retry counts.
- **Dashboard**: FastAPI web UI with endpoints:
  - `GET /api/runs` — list workflow runs
  - `GET /api/runs/{run_id}` — run detail + state snapshot
  - `GET /api/runs/{run_id}/trace` — agent reasoning steps
  - `GET /api/runs/{run_id}/metrics` — token/cost/latency charts
  - `POST /api/runs/{run_id}/approve/{gate}` — HITL approval
  - `GET /api/artifacts/{run_id}/{module}` — download code artifacts
- **Tracing**: OpenTelemetry-compatible spans per agent turn and tool call.

## 9. Human-in-the-Loop (HITL) Gates

Three approval checkpoints:

1. **Architecture Sign-off** — after PM produces the technical spec. Human reviews architecture, tech stack, and acceptance criteria before code generation begins.
2. **Pre-Merge Code Review** — after QA passes tests. Human reviews generated code before DevOps artifacts are produced.
3. **Pre-Production Deploy** — after DevOps produces deployment manifests. Human approves production deployment.

Each gate:
- Pauses the LangGraph run (breakpoint/interrupt)
- Writes an `ApprovalRecord` (pending/approved/rejected with reviewer and comments)
- Resumes on approval; routes back to the responsible agent on rejection

## 10. Error Recovery & Self-Healing

- QA test failures trigger a self-healing loop: QA analyzes the failure, produces a fix request, Coder applies the fix in the worktree, QA re-runs tests.
- Max retries per agent (default 3) before escalating to HITL.
- LangGraph checkpointer enables resume from the last successful state after infrastructure failures.

## 11. Security Considerations

- Agents run in isolated worktrees; no direct host filesystem write outside `.factory/`.
- LLM prompts are sanitized; no secret material is passed to agents.
- Generated code is scanned (basic pattern check) before commit.
- HITL gates prevent unauthorized production deployment.