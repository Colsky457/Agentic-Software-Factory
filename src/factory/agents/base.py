"""Base agent class for the Agentic Software Factory.

All specialized agents (PM, Coder, QA, DevOps) inherit from `BaseAgent`, which
provides:
- LLM invocation with telemetry
- Structured message emission
- Sandbox worktree file I/O
- Error handling and retry tracking against shared `FactoryState`
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any
from uuid import uuid4

from factory.config import settings
from factory.observability.logger import get_logger
from factory.observability.metrics import MetricsRecorder
from factory.sandbox.worktree import WorktreeManager
from factory.state import AgentMessage, FactoryState, Phase
from factory.tools.llm import LLMClient, LLMResponse

logger = get_logger("factory.agents.base")


class BaseAgent(ABC):
    """Abstract base for all factory agents."""

    def __init__(
        self,
        role: str,
        llm: LLMClient,
        worktrees: WorktreeManager,
        metrics: MetricsRecorder | None = None,
    ) -> None:
        self.role = role
        self.llm = llm
        self.worktrees = worktrees
        self.metrics = metrics or MetricsRecorder()
        self._log = logger.bind(agent=role)

    # ------------------------------------------------------------------
    # LLM invocation
    # ------------------------------------------------------------------

    async def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        trace_id: str | None = None,
    ) -> LLMResponse:
        """Call the LLM and record telemetry."""
        temp = settings.llm_temperature if temperature is None else temperature
        max_tok = settings.llm_max_tokens if max_tokens is None else max_tokens

        self._log.debug("llm.call", system_len=len(system_prompt), user_len=len(user_prompt))
        response = await self.llm.complete(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=temp,
            max_tokens=max_tok,
        )

        self.metrics.record_llm_call(response.prompt_tokens, response.completion_tokens)
        self._log.debug(
            "llm.done",
            prompt_tokens=response.prompt_tokens,
            completion_tokens=response.completion_tokens,
            trace_id=trace_id,
        )
        return response

    # ------------------------------------------------------------------
    # Messaging
    # ------------------------------------------------------------------

    def build_message(
        self,
        *,
        recipient: str,
        msg_type: str,
        payload: dict[str, Any],
        correlation_id: str,
        trace_id: str | None = None,
    ) -> AgentMessage:
        return AgentMessage(
            message_id=str(uuid4()),
            correlation_id=correlation_id,
            sender=self.role,  # type: ignore[arg-type]
            recipient=recipient,  # type: ignore[arg-type]
            type=msg_type,  # type: ignore[arg-type]
            payload=payload,
            trace_id=trace_id,
        )

    def emit(self, state: FactoryState, message: AgentMessage) -> None:
        state.add_message(message)
        self._log.info(
            "agent.message",
            to=message.recipient,
            type=message.type,
            correlation_id=message.correlation_id,
        )

    # ------------------------------------------------------------------
    # Sandbox I/O
    # ------------------------------------------------------------------

    def write_file(self, state: FactoryState, module: str, relative_path: str, content: str) -> str:
        """Write a file into the module's worktree and return its absolute path."""
        worktree_path = self.worktrees.get_path(module)
        abs_path = self.worktrees.write_file(worktree_path, relative_path, content)
        self._log.debug("file.write", module=module, path=relative_path, abs=abs_path)
        return abs_path

    def read_file(self, module: str, relative_path: str) -> str | None:
        worktree_path = self.worktrees.get_path(module)
        return self.worktrees.read_file(worktree_path, relative_path)

    def list_files(self, module: str) -> list[str]:
        worktree_path = self.worktrees.get_path(module)
        return self.worktrees.list_files(worktree_path)

    # ------------------------------------------------------------------
    # Abstract entry point
    # ------------------------------------------------------------------

    @abstractmethod
    async def run(self, state: FactoryState) -> FactoryState:
        """Execute the agent's work against shared state and return updated state."""
        raise NotImplementedError

    @property
    @abstractmethod
    def phase(self) -> Phase:
        """The workflow phase this agent is responsible for."""
        raise NotImplementedError
