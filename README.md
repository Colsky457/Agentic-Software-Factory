# Agentic Software Factory

An autonomous multi-agent platform that transforms high-level product requirements
into tested, deployable software. Built on a coordinator pattern with LangGraph,
specialized agents (PM, Coder, QA, DevOps), Git worktree sandboxes,
human-in-the-loop approval gates, and a structured observability dashboard.

## Deliverables

| File | Description |
|------|-------------|
| `architecture/system_design.md` | System architecture diagram & description (data flow, communication protocols, state management) |
| `tech_stack.md` | Tech stack recommendation (frameworks, LLM backends, infrastructure) |
| `src/factory/` | Core Python implementation: orchestrator, agents, sandbox, prompts, HITL, observability |
| `examples/workflow_example.md` | Step-by-step trace: "Build a real-time chat app" |
| `pyproject.toml`, `Dockerfile`, `docker-compose.yml`, `.github/workflows/ci.yml` | Project configuration |

## Core Agents

- **Product Manager** — requirements → technical spec + architecture + acceptance criteria
- **Software Engineer / Coder** — spec → idiomatic frontend/backend/database/infra code
- **QA / Tester** — tests → test execution → failure analysis → self-healing fix loops
- **DevOps / SRE** — tested code → Dockerfile, CI/CD, deployment scripts

## Quick Start

```bash
# Install
pip install -e ".[dev]"

# Configure
cp .env.example .env
# Edit .env with your LLM_API_KEY

# Run the factory
factory run "Build a real-time chat app" --auto-approve

# Or launch the observability dashboard
factory dashboard --port 8000
```

Then open http://localhost:8000 to inspect runs, traces, metrics, and approve
HITL gates.

## Architecture at a Glance

```
User prompt
    |
    v
[Ingest] -> [PM Agent] -> [HITL: Architecture] -> [Coder Agent]
                                                        |
                                                        v
                                                [QA Agent] <-> (self-heal loop)
                                                        |
                                                        v
                                                [HITL: Pre-merge] -> [DevOps Agent]
                                                        |
                                                        v
                                                [HITL: Deploy] -> [Finalize]
```

All nodes share a single `FactoryState` via LangGraph; Git worktrees provide
isolated per-module execution sandboxes; HITL gates pause for human approval.

## License

MIT — see `LICENSE`.