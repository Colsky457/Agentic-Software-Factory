"""Telemetry metrics recorder.

Tracks LLM token usage, cost estimates, tool calls, and per-node latency.
Used by agents and the orchestrator; exposed via the observability dashboard.
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Self

from factory.state import UsageMetrics


@dataclass
class NodeTiming:
    node: str
    start: float = field(default_factory=time.perf_counter)
    end: float | None = None

    def stop(self) -> float:
        self.end = time.perf_counter()
        return self.end - self.start


class MetricsRecorder:
    """Accumulates usage metrics for a single factory run."""

    def __init__(self) -> None:
        self.metrics = UsageMetrics(start_time=time.time())
        self._node_timings: dict[str, list[float]] = {}
        self._active_timings: dict[str, NodeTiming] = {}

    # ---- LLM ----

    def record_llm_call(self, prompt_tokens: int, completion_tokens: int) -> None:
        self.metrics.record_llm_call(prompt_tokens, completion_tokens)

    # ---- Tool calls ----

    def increment_tool_calls(self, count: int = 1) -> None:
        self.metrics.tool_calls += count

    # ---- Node timing ----

    @contextmanager
    def time_node(self, node: str):
        timing = NodeTiming(node=node)
        self._active_timings[node] = timing
        try:
            yield timing
        finally:
            elapsed = timing.stop()
            self._node_timings.setdefault(node, []).append(elapsed)
            self._active_timings.pop(node, None)

    def get_node_avg(self, node: str) -> float | None:
        timings = self._node_timings.get(node)
        if not timings:
            return None
        return sum(timings) / len(timings)

    def get_all_node_timings(self) -> dict[str, list[float]]:
        return dict(self._node_timings)

    # ---- Snapshot ----

    def snapshot(self) -> UsageMetrics:
        self.metrics.end_time = time.time()
        return self.metrics

    def to_dict(self) -> dict:
        m = self.snapshot()
        return {
            "total_tokens": m.total_tokens,
            "prompt_tokens": m.prompt_tokens,
            "completion_tokens": m.completion_tokens,
            "estimated_cost_usd": round(m.estimated_cost_usd, 6),
            "tool_calls": m.tool_calls,
            "llm_calls": m.llm_calls,
            "start_time": m.start_time.isoformat() if m.start_time else None,
            "end_time": m.end_time.isoformat() if m.end_time else None,
            "node_timings": {k: [round(v, 4) for v in vs] for k, vs in self._node_timings.items()},
        }


__all__ = ["MetricsRecorder", "NodeTiming"]
