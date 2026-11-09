# Workflow Example: "Build a real-time chat app"

This document traces, step by step, how the Agentic Software Factory transforms
the high-level prompt **"Build a real-time chat app"** into a tested, deployable
repository.

## Input

```
User prompt: "Build a real-time chat app"
Request ID:  a3f1c8e9-...
```

---

## Phase 1 — Ingest

The coordinator validates the prompt, initializes `FactoryState`, and creates
isolated Git worktrees for each module:

```
.factory/worktrees/frontend/   -> branch factory/frontend
.factory/worktrees/backend/    -> branch factory/backend
.factory/worktrees/database/   -> branch factory/database
.factory/worktrees/infra/      -> branch factory/infra
```

Worktrees share the object database (zero history duplication) but maintain
independent indexes, so agents can edit in parallel without branch collision.

State after ingest:
```
phase = INGEST, status = RUNNING
user_prompt = "Build a real-time chat app"
worktrees = {frontend: ..., backend: ..., database: ..., infra: ...}
```

---

## Phase 2 — Product Manager Agent

The coordinator routes to the PM agent. The PM LLM is invoked with `PM_SYSTEM`
and a user prompt built from the requirement.

**PM output (TechnicalSpec):**

```
title: Real-Time Chat App
summary: A web-based real-time chat application with rooms, presence, and message history.
user_stories:
  - id: us-1, title: Send/receive messages in real time, module: frontend, priority: high
  - id: us-2, title: Create and join chat rooms, module: frontend, priority: high
  - id: us-3, title: Persist messages and history, module: backend, priority: high
  - id: us-4, title: User presence (online/away), module: backend, priority: medium
  - id: us-5, title: Database schema for users/rooms/messages, module: database, priority: high
architecture:
  overview: React/Next.js frontend + FastAPI backend + Postgres + Redis + WebSockets
  components: [web-client, api-gateway, chat-service, message-service, presence-service, postgres, redis]
  data_flow: Client -> WebSocket -> API Gateway -> Chat Service -> Postgres/Redis
  tech_stack: {frontend: "Next.js 14 + Tailwind", backend: "FastAPI + Python", db: "PostgreSQL", cache: "Redis", realtime: "WebSocket/Socket.io"}
acceptance_criteria:
  - Messages appear in <200ms after send
  - Room join/leave reflected in presence within 1s
  - Message history loads on reconnect
  - 95th percentile API latency <100ms
non_functional_requirements:
  - Horizontal scalability via stateless API
  - JWT authentication
  - Structured logging + health endpoints
```

---

## HITL Gate #1 — Architecture Sign-off

The graph pauses at `hitl_architecture`. The PM's spec is surfaced in the
observability dashboard (`GET /api/runs/{id}/trace` and `/api/approve/architecture`).

A human reviewer:
- Inspects the tech stack and component diagram.
- Confirms acceptance criteria.
- Clicks **Approve** (POST `/api/runs/{id}/approve/architecture` with `{decision: "approve"}`).

If rejected, the graph routes back to `pm_agent` for revision.

State after approval:
```
approvals.architecture.status = APPROVED
phase = CODER (resumed), status = RUNNING
```

---

## Phase 3 — Coder Agent

The coordinator routes to the Coder agent in parallel across the four worktrees.
For each module the LLM generates idiomatic files.

**Frontend worktree** (`factory/worktrees/frontend/`):
```
package.json
src/app/page.tsx          # chat UI
src/app/layout.tsx
src/components/ChatRoom.tsx
src/components/MessageList.tsx
src/components/PresenceIndicator.tsx
src/lib/socket.ts         # WebSocket client
tailwind.config.ts
```

**Backend worktree** (`factory/worktrees/backend/`):
```
main.py                   # FastAPI app + health
api/routes/chat.py        # WebSocket chat endpoint
api/routes/auth.py        # JWT login
services/chat_service.py  # room/message business logic
services/presence.py      # Redis-backed presence
models/user.py, models/room.py, models/message.py
requirements.txt
alembic/versions/...      # DB migrations
```

**Database worktree** (`factory/worktrees/database/`):
```
schema.sql                # users, rooms, messages tables
seed.sql
migrations/001_init.sql
```

**Infra worktree** (`factory/worktrees/infra/`):
```
Dockerfile
docker-compose.yml
.github/workflows/ci.yml   # (placeholder; final CI from DevOps)
```

Each file is written via `write_file`, then `stage_and_commit` per module.

State after coding:
```
code_artifacts.frontend.files = {package.json, src/app/page.tsx, ...}
code_artifacts.backend.files  = {main.py, api/routes/chat.py, ...}
code_artifacts.database.files = {schema.sql, migrations/001_init.sql}
worktrees.<module> = <absolute path>
phase = QA
```

---

## Phase 4 — QA / Tester Agent

The QA agent writes unit + integration tests per module and executes them.

**Tests generated:**
- `backend/tests/test_chat_service.py` — message persistence, room join/leave
- `backend/tests/test_presence.py` — online/away transitions
- `frontend/tests/ChatRoom.test.tsx` — message rendering
- `database/tests/schema_test.sql` — migration idempotency

**Execution results (simulated/runner):**

| Module | Passed | Failed | Errored |
|--------|--------|--------|---------|
| backend | 12 | 0 | 0 |
| frontend | 8 | 0 | 0 |
| database | 3 | 0 | 0 |
| infra | 2 | 0 | 0 |

All tests pass on first run. If any failed, the self-healing loop would trigger:
QA analyzes the failure → Coder applies a fix in the worktree → QA re-runs — up to
`max_retries` (default 3) before HITL escalation.

State after QA:
```
test_results.backend.success = true
test_results.frontend.success = true
phase = HITL_PREMERGE
```

---

## HITL Gate #2 — Pre-Merge Code Review

The graph pauses at `hitl_premerge`. The dashboard shows:
- Diff summary of generated code per module
- Test results
- Fix-loop history (empty in this run)

A human reviews and approves. On approval:
```
approvals.premerge.status = APPROVED
phase = DEVOPS
```

---

## Phase 5 — DevOps / SRE Agent

The DevOps agent generates deployment-ready artifacts in the infra worktree:

```
Dockerfile (multi-stage, non-root user)
docker-compose.yml (app + postgres + redis)
.github/workflows/ci.yml (lint, test, build, push to GHCR)
deploy.sh (build + push + rollback)
.env.example (PORT, DATABASE_URL, REDIS_URL, JWT_SECRET)
README.md (setup + deploy instructions)
k8s/manifests.yaml (Deployment, Service, HPA, ConfigMap)
```

Committed to `factory/infra` worktree.

State after DevOps:
```
devops_artifacts.dockerfile = "..."
devops_artifacts.github_actions_ci = "..."
phase = HITL_DEPLOY
```

---

## HITL Gate #3 — Pre-Production Deploy

The graph pauses at `hitl_deploy`. The human reviews deployment manifests and
approves production rollout.

On approval:
```
approvals.deploy.status = APPROVED
phase = FINALIZE
```

---

## Phase 6 — Finalize

The coordinator:
1. Commits all module worktrees (if not already committed).
2. Optionally pushes branches to GitHub and opens a PR.
3. Captures final observability trace (agent reasoning steps, token usage,
   tool calls, artifacts).
4. Cleans up worktrees (retains on failure for debugging).

Final state:
```
status = COMPLETED
phase = COMPLETED
metrics.total_tokens = ~45,000
metrics.estimated_cost_usd = $0.45
```

---

## Observability Trace (summary)

Retrievable via `GET /api/runs/{request_id}/trace`:

```
[ingest]        user_prompt received
[pm_agent]      LLM call 1 (2.1k prompt / 1.8k completion tokens) -> TechnicalSpec
[hitl_architecture] PAUSED -> human approved
[coder_agent]   4 LLM calls (one per module) -> 28 files generated
[qa_agent]      1 LLM call -> tests; test run: 25 passed, 0 failed
[hitl_premerge] PAUSED -> human approved
[devops_agent]  1 LLM call -> Docker/CI/CD/deploy artifacts
[hitl_deploy]   PAUSED -> human approved
[finalize]      artifacts committed, worktrees cleaned
```

## Key Design Properties Demonstrated

| Property | How it's shown |
|----------|----------------|
| Coordinator pattern | LangGraph StateGraph routes between agents; no direct agent-to-agent calls |
| Isolated sandboxes | Git worktrees per module enable concurrent edits without index pollution |
| HITL | 3 explicit approval gates pause/resume the graph |
| Self-healing | QA failures route back to Coder via conditional edge (loop up to max_retries) |
| Observability | Structured logs + metrics + dashboard trace every node |
| State persistence | `FactoryState` is the single source of truth; checkpointer enables resume |
