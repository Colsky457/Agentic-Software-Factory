"""Human-in-the-Loop (HITL) approval gates.

Three checkpoints pause the LangGraph workflow for human review:
1. architecture - after the PM produces the technical spec
2. premerge - after QA passes tests, before DevOps
3. deploy - after DevOps produces deployment manifests

Each gate returns an `ApprovalRecord`. When `hitl_auto_approve` is enabled
(dev mode), gates auto-approve. Otherwise the graph pauses and waits for an
external decision via the dashboard API.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Literal

from factory.config import settings
from factory.observability.logger import get_logger
from factory.state import ApprovalRecord, ApprovalStatus, FactoryState

logger = get_logger("factory.hitl")

GATE_SEQUENCE = ("architecture", "premerge", "deploy")


class GateDecision(str, Enum):
    APPROVE = "approve"
    REJECT = "reject"


class HITLManager:
    """Manages human-in-the-loop approval gates."""

    def __init__(self, auto_approve: bool | None = None) -> None:
        self.auto_approve = settings.hitl_auto_approve if auto_approve is None else auto_approve

    def record_gate(self, state: FactoryState, gate: Literal["architecture", "premerge", "deploy"]) -> ApprovalRecord:
        """Create (or reset) an approval record for a gate."""
        record = ApprovalRecord(gate=gate, status=ApprovalStatus.PENDING)
        state.approvals[gate] = record
        logger.info("hitl.gate_requested", gate=gate, request_id=state.request_id)
        return record

    def is_approved(self, state: FactoryState, gate: Literal["architecture", "premerge", "deploy"]) -> bool:
        record = state.approvals.get(gate)
        return record is not None and record.status == ApprovalStatus.APPROVED

    def is_pending(self, state: FactoryState, gate: Literal["architecture", "premerge", "deploy"]) -> bool:
        record = state.approvals.get(gate)
        return record is None or record.status == ApprovalStatus.PENDING

    def decide(
        self,
        state: FactoryState,
        gate: Literal["architecture", "premerge", "deploy"],
        decision: GateDecision,
        reviewer: str = "human",
        comments: str = "",
    ) -> ApprovalRecord:
        """Record a human decision on a gate and update state phase/status."""
        record = state.approvals.get(gate)
        if record is None:
            record = ApprovalRecord(gate=gate)
            state.approvals[gate] = record

        record.status = ApprovalStatus.APPROVED if decision == GateDecision.APPROVE else ApprovalStatus.REJECTED
        record.reviewer = reviewer
        record.comments = comments
        record.decided_at = datetime.now(timezone.utc)

        logger.info(
            "hitl.gate_decided",
            gate=gate,
            decision=decision.value,
            reviewer=reviewer,
            request_id=state.request_id,
        )
        return record

    def should_auto_approve(self) -> bool:
        return self.auto_approve

    def next_gate_after(self, gate: Literal["architecture", "premerge", "deploy"]) -> str | None:
        idx = GATE_SEQUENCE.index(gate)
        if idx + 1 < len(GATE_SEQUENCE):
            return GATE_SEQUENCE[idx + 1]
        return None

    def all_approved(self, state: FactoryState) -> bool:
        return all(
            state.approvals.get(g) is not None and state.approvals[g].status == ApprovalStatus.APPROVED
            for g in GATE_SEQUENCE
        )


__all__ = ["HITLManager", "GateDecision", "GATE_SEQUENCE"]
