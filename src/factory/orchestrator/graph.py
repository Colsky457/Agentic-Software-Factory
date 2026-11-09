"""LangGraph orchestrator for the Agentic Software Factory.

Builds a stateful `StateGraph` with the four agents and HITL gates as nodes,
conditional edges for handoffs and self-healing loops, and an error handler for
recovery. Integrates with the observability dashboard for run registration.
"""

from __future__ import annotations

from typing import Any

from factory.agents.coder import CoderAgent
from factory.agents.devops import DevOpsAgent
from factory.agents.pm import ProductManagerAgent
from factory.agents.qa import QAAgent
from factory.config import settings
from factory.hitl.gates import HITLManager, GATE_SEQUENCE
from factory.observability.dashboard import register_run, update_run
from factory.observability.logger import get_logger
from factory.observability.metrics import MetricsRecorder
from factory.sandbox.worktree import WorktreeManager
from factory.state import (
    FactoryState,
    Phase,
    RunStatus,
)
from factory.tools.llm import build_llm_client

logger = get_logger("factory.orchestrator")

try:
    from langgraph.graph import StateGraph, END
except ImportError as exc:  # pragma: no cover
    raise ImportError("langgraph is required for the orchestrator") from exc


class FactoryOrchestrator:
    """Builds and runs the LangGraph agentic workflow."""

    def __init__(
        self,
        llm_client: Any | None = None,
        worktrees: WorktreeManager | None = None,
        hitl: HITLManager | None = None,
        metrics: MetricsRecorder | None = None,
    ) -> None:
        self.llm = llm_client or build_llm_client()
        self.worktrees = worktrees or WorktreeManager()
        self.hitl = hitl or HITLManager()
        self.metrics = metrics or MetricsRecorder()

        # Instantiate agents
        self.pm = ProductManagerAgent(llm=self.llm, worktrees=self.worktrees, metrics=self.metrics)
        self.coder = CoderAgent(llm=self.llm, worktrees=self.worktrees, metrics=self.metrics)
        self.qa = QAAgent(llm=self.llm, worktrees=self.worktrees, metrics=self.metrics)
        self.devops = DevOpsAgent(llm=self.llm, worktrees=self.worktrees, metrics=self.metrics)

        self.graph = self._build_graph()

    # ------------------------------------------------------------------
    # Graph construction
    # ------------------------------------------------------------------

    def _build_graph(self) -> Any:
        workflow = StateGraph(FactoryState)

        # Nodes
        workflow.add_node("ingest", self._ingest_node)
        workflow.add_node("pm_agent", self._pm_node)
        workflow.add_node("hitl_architecture", self._hitl_architecture_node)
        workflow.add_node("coder_agent", self._coder_node)
        workflow.add_node("qa_agent", self._qa_node)
        workflow.add_node("hitl_premerge", self._hitl_premerge_node)
        workflow.add_node("devops_agent", self._devops_node)
        workflow.add_node("hitl_deploy", self._hitl_deploy_node)
        workflow.add_node("finalize", self._finalize_node)
        workflow.add_node("error_handler", self._error_node)

        # Entry point
        workflow.set_entry_point("ingest")

        # Linear edges
        workflow.add_edge("ingest", "pm_agent")

        # Conditional edges
        workflow.add_conditional_edges(
            "pm_agent",
            self._after_pm,
            {
                "hitl_architecture": "hitl_architecture",
                "error_handler": "error_handler",
            },
        )

        workflow.add_conditional_edges(
            "hitl_architecture",
            self._after_architecture_gate,
            {
                "pm_agent": "pm_agent",  # revision loop on reject
                "coder_agent": "coder_agent",  # approved
                "error_handler": "error_handler",
            },
        )

        workflow.add_edge("coder_agent", "qa_agent")

        workflow.add_conditional_edges(
            "qa_agent",
            self._after_qa,
            {
                "qa_agent": "qa_agent",  # self-heal loop
                "hitl_premerge": "hitl_premerge",
                "error_handler": "error_handler",
            },
        )

        workflow.add_conditional_edges(
            "hitl_premerge",
            self._after_premerge_gate,
            {
                "coder_agent": "coder_agent",  # rework on reject
                "devops_agent": "devops_agent",  # approved
                "error_handler": "error_handler",
            },
        )

        workflow.add_edge("devops_agent", "hitl_deploy")

        workflow.add_conditional_edges(
            "hitl_deploy",
            self._after_deploy_gate,
            {
                "finalize": "finalize",
                "error_handler": "error_handler",
            },
        )

        workflow.add_edge("finalize", END)
        workflow.add_edge("error_handler", END)

        return workflow.compile()

    # ------------------------------------------------------------------
    # Nodes
    # ------------------------------------------------------------------

    async def _ingest_node(self, state: FactoryState) -> FactoryState:
        state.status = RunStatus.RUNNING
        state.phase = Phase.INGEST
        state.metrics.start_time = state.metrics.start_time or None
        logger.info("node.ingest", request_id=state.request_id, prompt=state.user_prompt[:100])
        register_run(state.request_id, {"status": "running", "phase": "ingest", "user_prompt": state.user_prompt})
        return state

    async def _pm_node(self, state: FactoryState) -> FactoryState:
        with self.metrics.time_node("pm_agent"):
            return await self.pm.run(state)

    async def _coder_node(self, state: FactoryState) -> FactoryState:
        with self.metrics.time_node("coder_agent"):
            return await self.coder.run(state)

    async def _qa_node(self, state: FactoryState) -> FactoryState:
        with self.metrics.time_node("qa_agent"):
            return await self.qa.run(state)

    async def _devops_node(self, state: FactoryState) -> FactoryState:
        with self.metrics.time_node("devops_agent"):
            return await self.devops.run(state)

    async def _hitl_architecture_node(self, state: FactoryState) -> FactoryState:
        self.hitl.record_gate(state, "architecture")
        state.phase = Phase.HITL_ARCHITECTURE
        state.status = RunStatus.PAUSED
        if self.hitl.should_auto_approve():
            self.hitl.decide(state, "architecture", __import__("factory.hitl.gates", fromlist=["GateDecision"]).GateDecision.APPROVE, reviewer="auto")
            state.status = RunStatus.RUNNING
        logger.info("node.hitl_architecture", request_id=state.request_id, auto_approve=self.hitl.should_auto_approve())
        register_run(state.request_id, {"status": state.status.value, "phase": state.phase.value})
        return state

    async def _hitl_premerge_node(self, state: FactoryState) -> FactoryState:
        self.hitl.record_gate(state, "premerge")
        state.phase = Phase.HITL_PREMERGE
        state.status = RunStatus.PAUSED
        if self.hitl.should_auto_approve():
            self.hitl.decide(state, "premerge", __import__("factory.hitl.gates", fromlist=["GateDecision"]).GateDecision.APPROVE, reviewer="auto")
            state.status = RunStatus.RUNNING
        logger.info("node.hitl_premerge", request_id=state.request_id, auto_approve=self.hitl.should_auto_approve())
        register_run(state.request_id, {"status": state.status.value, "phase": state.phase.value})
        return state

    async def _hitl_deploy_node(self, state: FactoryState) -> FactoryState:
        self.hitl.record_gate(state, "deploy")
        state.phase = Phase.HITL_DEPLOY
        state.status = RunStatus.PAUSED
        if self.hitl.should_auto_approve():
            self.hitl.decide(state, "deploy", __import__("factory.hitl.gates", fromlist=["GateDecision"]).GateDecision.APPROVE, reviewer="auto")
            state.status = RunStatus.RUNNING
        logger.info("node.hitl_deploy", request_id=state.request_id, auto_approve=self.hitl.should_auto_approve())
        register_run(state.request_id, {"status": state.status.value, "phase": state.phase.value})
        return state

    async def _finalize_node(self, state: FactoryState) -> FactoryState:
        state.status = RunStatus.COMPLETED
        state.phase = Phase.COMPLETED
        state.metrics.end_time = None  # recorder sets end on snapshot
        logger.info("node.finalize", request_id=state.request_id)
        register_run(state.request_id, {"status": "completed", "phase": "completed"})
        return state

    async def _error_node(self, state: FactoryState) -> FactoryState:
        state.status = RunStatus.FAILED
        state.phase = Phase.ERROR
        logger.error("node.error", request_id=state.request_id, errors=len(state.errors))
        register_run(state.request_id, {"status": "failed", "phase": "error", "errors": [e.model_dump() for e in state.errors]})
        return state

    # ------------------------------------------------------------------
    # Conditional edge routers
    # ------------------------------------------------------------------

    def _after_pm(self, state: FactoryState) -> str:
        if state.has_errors:
            return "error_handler"
        return "hitl_architecture"

    def _after_architecture_gate(self, state: FactoryState) -> str:
        if state.has_errors:
            return "error_handler"
        if self.hitl.is_approved(state, "architecture"):
            return "coder_agent"
        if self.hitl.is_pending(state, "architecture"):
            # Graph is paused; LangGraph will wait for external resume
            return "hitl_architecture"
        return "pm_agent"  # rejected -> revision

    def _after_qa(self, state: FactoryState) -> str:
        if state.has_errors:
            return "error_handler"
        retry = state.retry_counts.get("qa", 0)
        if not state.all_tests_passed and retry < settings.max_retries:
            return "qa_agent"  # self-heal loop
        return "hitl_premerge"

    def _after_premerge_gate(self, state: FactoryState) -> str:
        if state.has_errors:
            return "error_handler"
        if self.hitl.is_approved(state, "premerge"):
            return "devops_agent"
        if self.hitl.is_pending(state, "premerge"):
            return "hitl_premerge"
        return "coder_agent"  # rejected -> rework

    def _after_deploy_gate(self, state: FactoryState) -> str:
        if state.has_errors:
            return "error_handler"
        if self.hitl.is_approved(state, "deploy"):
            return "finalize"
        # rejected -> terminal (no re-deploy loop in MVP)
        return "error_handler"

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    async def run(self, user_prompt: str, request_id: str | None = None) -> FactoryState:
        """Execute the full factory workflow for a user prompt."""
        request_id = request_id or str(__import__("uuid").uuid4())
        initial = FactoryState(user_prompt=user_prompt)
        initial.request_id = request_id

        # Initialize worktrees
        self.worktrees.init()

        logger.info("orchestrator.run.start", request_id=request_id, prompt=user_prompt[:100])

        # LangGraph streams state updates; we capture the final state
        final_state: FactoryState | None = None
        async for update in self.graph.astream(initial, stream_mode="values"):
            final_state = update
            # Sync to dashboard
            update_run(request_id, {
                "status": final_state.status.value,
                "phase": final_state.phase.value,
                "state": final_state.model_dump(),
            })

        if final_state is None:
            raise RuntimeError("Orchestrator produced no final state")

        logger.info(
            "orchestrator.run.done",
            request_id=request_id,
            status=final_state.status.value,
            phase=final_state.phase.value,
        )

        # Cleanup worktrees unless there were errors (keep for debugging)
        if final_state.status == RunStatus.COMPLETED:
            self.worktrees.cleanup_all(force=True)

        return final_state

    async def resume_gate(
        self,
        request_id: str,
        gate: str,
        decision: str,
        reviewer: str = "dashboard-user",
        comments: str = "",
    ) -> FactoryState:
        """Resume a paused workflow after a HITL gate decision.

        Loads the last persisted state from the dashboard store, applies the
        decision, and re-runs the graph from the gate node.
        """
        from factory.observability.dashboard import _runs

        run = _runs.get(request_id)
        if run is None:
            raise ValueError(f"Run {request_id} not found")

        state = FactoryState(**run["state"])
        from factory.hitl.gates import GateDecision

        self.hitl.decide(
            state,
            gate,  # type: ignore[arg-type]
            GateDecision.APPROVE if decision == "approve" else GateDecision.REJECT,
            reviewer=reviewer,
            comments=comments,
        )
        state.status = RunStatus.RUNNING

        # Re-run from the gate node forward
        final_state: FactoryState | None = None
        async for update in self.graph.astream(state, stream_mode="values"):
            final_state = update
            update_run(request_id, {
                "status": final_state.status.value,
                "phase": final_state.phase.value,
                "state": final_state.model_dump(),
            })

        return final_state or state


__all__ = ["FactoryOrchestrator"]
