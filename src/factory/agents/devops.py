"""DevOps / SRE Agent.

Generates Dockerfiles, CI/CD pipelines (GitHub Actions), and deployment
scripts for production-ready delivery.
"""

from __future__ import annotations

from typing import Any

from factory.agents.base import BaseAgent
from factory.observability.metrics import MetricsRecorder
from factory.prompts.templates import DEVOPS_SYSTEM, build_devops_user_prompt
from factory.sandbox.worktree import WorktreeManager
from factory.state import CodeArtifacts, DevOpsArtifacts, FactoryState, Phase
from factory.tools.llm import LLMClient


class DevOpsAgent(BaseAgent):
    def __init__(
        self,
        llm: LLMClient,
        worktrees: WorktreeManager,
        metrics: MetricsRecorder | None = None,
    ) -> None:
        super().__init__(role="devops", llm=llm, worktrees=worktrees, metrics=metrics)

    @property
    def phase(self) -> Phase:
        return Phase.DEVOPS

    async def run(self, state: FactoryState) -> FactoryState:
        self._log.info("devops.run.start", request_id=state.request_id)

        artifacts_summary = self._summarize_artifacts(state.code_artifacts)
        test_summary = self._summarize_tests(state.test_results)

        system_prompt = DEVOPS_SYSTEM
        user_prompt = build_devops_user_prompt(artifacts_summary, test_summary)

        response = await self.generate(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            trace_id=state.request_id,
        )

        devops = self._parse_devops(response.text)

        # Write DevOps artifacts into the infra worktree
        wt_path = self.worktrees.get_path("infra")
        files_to_commit: list[tuple[str, str]] = []

        if devops.dockerfile:
            files_to_commit.append(("Dockerfile", devops.dockerfile))
        if devops.docker_compose:
            files_to_commit.append(("docker-compose.yml", devops.docker_compose))
        if devops.github_actions_ci:
            files_to_commit.append((".github/workflows/ci.yml", devops.github_actions_ci))
        if devops.deployment_script:
            files_to_commit.append(("deploy.sh", devops.deployment_script))
        if devops.k8s_manifests:
            files_to_commit.append(("k8s/manifests.yaml", devops.k8s_manifests))
        if devops.env_example:
            files_to_commit.append((".env.example", devops.env_example))
        if devops.readme:
            files_to_commit.append(("README.md", devops.readme))

        for rel_path, content in files_to_commit:
            self.write_file(state, "infra", rel_path, content)

        # Commit infra worktree
        self.worktrees.stage_and_commit(
            "infra", f"factory: devops artifacts (request {state.request_id})"
        )

        state.devops_artifacts = devops
        state.phase = Phase.HITL_DEPLOY

        message = self.build_message(
            recipient="human",
            msg_type="deploy",
            payload={
                "artifacts": {
                    "dockerfile": bool(devops.dockerfile),
                    "docker_compose": bool(devops.docker_compose),
                    "ci_pipeline": bool(devops.github_actions_ci),
                    "deployment_script": bool(devops.deployment_script),
                    "k8s_manifests": bool(devops.k8s_manifests),
                    "env_example": bool(devops.env_example),
                    "readme": bool(devops.readme),
                },
                "infra_worktree": str(wt_path),
            },
            correlation_id=state.request_id,
            trace_id=state.request_id,
        )
        self.emit(state, message)

        self._log.info(
            "devops.run.done",
            files=len(files_to_commit),
        )
        return state

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _summarize_artifacts(artifacts: dict[str, CodeArtifacts]) -> str:
        lines = []
        for module, art in artifacts.items():
            lines.append(f"## {module} ({len(art.files)} files)")
            for path in sorted(art.files):
                lines.append(f"- {path}")
        return "\n".join(lines)

    @staticmethod
    def _summarize_tests(results: dict[str, Any]) -> str:
        if not results:
            return "No test results available."
        lines = []
        for module, r in results.items():
            lines.append(
                f"- {module}: {r.passed}/{r.total} passed, {r.failed} failed, {r.errored} errored (success={r.success})"
            )
        return "\n".join(lines)

    def _parse_devops(self, text: str) -> DevOpsArtifacts:
        """Best-effort extraction of DevOps artifacts from fenced code blocks."""
        import re

        devops = DevOpsArtifacts()
        pattern = re.compile(r"```(?::path:)?([\w./-]+)\n(.*?)```", re.DOTALL)
        mapping = {
            "Dockerfile": "dockerfile",
            "docker-compose.yml": "docker_compose",
            ".github/workflows/ci.yml": "github_actions_ci",
            "deploy.sh": "deployment_script",
            "k8s/manifests.yaml": "k8s_manifests",
            ".env.example": "env_example",
            "README.md": "readme",
        }
        for match in pattern.finditer(text):
            raw_path = match.group(1).strip()
            content = match.group(2).strip()
            field = mapping.get(raw_path)
            if field:
                setattr(devops, field, content)

        # Fallback defaults if nothing parsed
        if not any(
            [
                devops.dockerfile,
                devops.docker_compose,
                devops.github_actions_ci,
                devops.deployment_script,
            ]
        ):
            self._log.warning("devops.parse_fallback", reason="no_fenced_blocks")
            devops = self._default_devops()

        return devops

    def _default_devops(self) -> DevOpsArtifacts:
        return DevOpsArtifacts(
            dockerfile=(
                "FROM python:3.11-slim\n"
                "WORKDIR /app\n"
                "COPY requirements.txt .\n"
                "RUN pip install --no-cache-dir -r requirements.txt\n"
                "COPY . .\n"
                "EXPOSE 8000\n"
                "CMD [\"uvicorn\", \"main:app\", \"--host\", \"0.0.0.0\"]\n"
            ),
            docker_compose=(
                "version: '3.8'\n"
                "services:\n"
                "  app:\n"
                "    build: .\n"
                "    ports:\n"
                "      - \"8000:8000\"\n"
                "    env_file: .env\n"
            ),
            github_actions_ci=(
                "name: CI\n"
                "on: [push, pull_request]\n"
                "jobs:\n"
                "  test:\n"
                "    runs-on: ubuntu-latest\n"
                "    steps:\n"
                "      - uses: actions/checkout@v4\n"
                "      - name: Run tests\n"
                "        run: python -m pytest -q\n"
            ),
            deployment_script=(
                "#!/usr/bin/env bash\nset -euo pipefail\ndocker build -t app:latest .\ndocker push app:latest\n",
            ),
            env_example=("PORT=8000\nLOG_LEVEL=INFO\n"),
            readme=("# Agentic Software Factory Output\n\nBuild: `docker-compose up --build`\n"),
        )


__all__ = ["DevOpsAgent"]
