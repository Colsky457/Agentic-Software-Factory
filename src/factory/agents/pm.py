"""Product Manager Agent.

Breaks down user stories into detailed technical requirements, architecture
plans, and acceptance criteria.
"""

from __future__ import annotations

from typing import Any

from factory.agents.base import BaseAgent
from factory.observability.metrics import MetricsRecorder
from factory.prompts.templates import PM_SYSTEM, build_pm_user_prompt
from factory.sandbox.worktree import WorktreeManager
from factory.state import (
    ArchitecturePlan,
    FactoryState,
    Phase,
    TechnicalSpec,
    UserStory,
)
from factory.tools.llm import LLMClient


class ProductManagerAgent(BaseAgent):
    def __init__(
        self,
        llm: LLMClient,
        worktrees: WorktreeManager,
        metrics: MetricsRecorder | None = None,
    ) -> None:
        super().__init__(role="pm", llm=llm, worktrees=worktrees, metrics=metrics)

    @property
    def phase(self) -> Phase:
        return Phase.PM

    async def run(self, state: FactoryState) -> FactoryState:
        self._log.info("pm.run.start", request_id=state.request_id)

        system_prompt = PM_SYSTEM
        user_prompt = build_pm_user_prompt(state.user_prompt)

        response = await self.generate(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            trace_id=state.request_id,
        )

        # Parse the LLM response into a TechnicalSpec. In production this would
        # use structured output (PydanticOutputParser / function calling). Here
        # we perform a best-effort parse with fallback to a heuristic spec.
        spec = self._parse_spec(response.text)

        state.technical_spec = spec
        state.phase = Phase.HITL_ARCHITECTURE
        state.status = state.status  # unchanged; HITL gate will set PAUSED

        message = self.build_message(
            recipient="human",
            msg_type="spec",
            payload={
                "spec_id": spec.spec_id,
                "title": spec.title,
                "summary": spec.summary,
                "user_stories": [s.model_dump() for s in spec.user_stories],
                "architecture": spec.architecture.model_dump(),
                "acceptance_criteria": spec.acceptance_criteria,
            },
            correlation_id=state.request_id,
            trace_id=state.request_id,
        )
        self.emit(state, message)

        self._log.info(
            "pm.run.done",
            spec_id=spec.spec_id,
            stories=len(spec.user_stories),
            components=len(spec.architecture.components),
        )
        return state

    # ------------------------------------------------------------------
    # Parsing helpers
    # ------------------------------------------------------------------

    def _parse_spec(self, text: str) -> TechnicalSpec:
        """Best-effort parse of the PM LLM response into a TechnicalSpec.

        Falls back to a sensible default if parsing fails, so the factory can
        continue and the human can revise at the HITL gate.
        """
        try:
            import json

            # Attempt to extract a JSON block from the response
            start = text.find("{")
            end = text.rfind("}") + 1
            if start != -1 and end > start:
                data = json.loads(text[start:end])
                return TechnicalSpec(
                    title=data.get("title", "Untitled Product"),
                    summary=data.get("summary", text[:500]),
                    user_stories=[
                        UserStory(
                            title=s.get("title", ""),
                            description=s.get("description", ""),
                            acceptance_criteria=s.get("acceptance_criteria", []),
                            priority=s.get("priority", "medium"),
                            module=s.get("module", "backend"),
                        )
                        for s in data.get("user_stories", [])
                    ],
                    architecture=ArchitecturePlan(
                        overview=data.get("architecture", {}).get("overview", ""),
                        components=data.get("architecture", {}).get("components", []),
                        data_flow=data.get("architecture", {}).get("data_flow", ""),
                        tech_stack=data.get("architecture", {}).get("tech_stack", {}),
                        diagram_text=data.get("architecture", {}).get("diagram_text"),
                    ),
                    acceptance_criteria=data.get("acceptance_criteria", []),
                    non_functional_requirements=data.get("non_functional_requirements", []),
                )
        except Exception:  # noqa: BLE001 - intentional fallback
            self._log.warning("pm.parse_fallback", error="json_parse_failed")

        return TechnicalSpec(
            title="Product Specification",
            summary=text[:1000],
            architecture=ArchitecturePlan(
                overview="See human-reviewed specification at HITL gate.",
                components=[],
                data_flow="",
                tech_stack={},
            ),
            acceptance_criteria=["Human to define acceptance criteria at architecture gate."],
        )


__all__ = ["ProductManagerAgent"]
