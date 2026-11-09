"""Observability dashboard: FastAPI application exposing run traces, metrics,
artifacts, and HITL approval endpoints.

Run with: `uvicorn factory.observability.dashboard:app --reload`
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException, Path
from fastapi.responses import JSONResponse, PlainTextResponse

from factory.config import settings
from factory.observability.logger import configure_logging, get_logger

configure_logging(level=settings.log_level)
logger = get_logger("factory.dashboard")

app = FastAPI(title="Agentic Software Factory - Observability", version="0.1.0")

# In-memory run store (MVP). Production would back this with Redis/Postgres.
_runs: dict[str, dict[str, Any]] = {}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _store_run(run_id: str, data: dict[str, Any]) -> None:
    _runs[run_id] = data


def _get_run(run_id: str) -> dict[str, Any]:
    run = _runs.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
    return run


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "factory": settings.factory_name}


@app.get("/api/runs")
async def list_runs() -> list[dict[str, Any]]:
    return [
        {
            "run_id": rid,
            "status": r.get("status"),
            "phase": r.get("phase"),
            "user_prompt": r.get("user_prompt", "")[:120],
            "created_at": r.get("created_at"),
        }
        for rid, r in _runs.items()
    ]


@app.get("/api/runs/{run_id}")
async def get_run(run_id: str = Path(...)) -> dict[str, Any]:
    return _get_run(run_id)


@app.get("/api/runs/{run_id}/trace")
async def get_trace(run_id: str = Path(...)) -> dict[str, Any]:
    run = _get_run(run_id)
    messages = run.get("state", {}).get("messages", [])
    return {
        "run_id": run_id,
        "message_count": len(messages),
        "messages": messages,
    }


@app.get("/api/runs/{run_id}/metrics")
async def get_metrics(run_id: str = Path(...)) -> dict[str, Any]:
    run = _get_run(run_id)
    return run.get("state", {}).get("metrics", {})


@app.get("/api/runs/{run_id}/artifacts/{module}")
async def get_artifact(run_id: str = Path(...), module: str = Path(...)) -> PlainTextResponse:
    run = _get_run(run_id)
    code_artifacts = run.get("state", {}).get("code_artifacts", {})
    module_art = code_artifacts.get(module)
    if not module_art:
        raise HTTPException(status_code=404, detail=f"No artifacts for module {module}")
    files = module_art.get("files", {})
    # Return a concatenated view of all files in the module
    parts = []
    for path, content in files.items():
        parts.append(f"===== {path} =====\n{content}\n")
    return PlainTextResponse(content="\n".join(parts))


@app.post("/api/runs/{run_id}/approve/{gate}")
async def approve_gate(
    run_id: str = Path(...),
    gate: str = Path(...),
    body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    run = _get_run(run_id)
    state = run.get("state", {})
    approvals = state.get("approvals", {})
    if gate not in approvals:
        raise HTTPException(status_code=400, detail=f"Unknown gate: {gate}")

    record = approvals[gate]
    decision = (body or {}).get("decision", "approve")
    reviewer = (body or {}).get("reviewer", "dashboard-user")
    comments = (body or {}).get("comments", "")

    record["status"] = "approved" if decision == "approve" else "rejected"
    record["reviewer"] = reviewer
    record["comments"] = comments
    from datetime import datetime, timezone

    record["decided_at"] = datetime.now(timezone.utc).isoformat()

    logger.info("dashboard.approve_gate", run_id=run_id, gate=gate, decision=decision, reviewer=reviewer)
    return {"run_id": run_id, "gate": gate, "status": record["status"]}


@app.get("/api/runs/{run_id}/gates")
async def get_gates(run_id: str = Path(...)) -> dict[str, Any]:
    run = _get_run(run_id)
    return run.get("state", {}).get("approvals", {})


# ---------------------------------------------------------------------------
# Registration helper used by the orchestrator
# ---------------------------------------------------------------------------

def register_run(run_id: str, data: dict[str, Any]) -> None:
    _store_run(run_id, data)


def update_run(run_id: str, data: dict[str, Any]) -> None:
    if run_id not in _runs:
        _store_run(run_id, data)
    else:
        _runs[run_id].update(data)


__all__ = ["app", "register_run", "update_run"]
