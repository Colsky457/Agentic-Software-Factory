"""Software Engineer / Coder Agent.

Generates clean, idiomatic code across frontend, backend, and database schemas
based on architectural specs.
"""

from __future__ import annotations

from typing import Any

from factory.agents.base import BaseAgent
from factory.observability.metrics import MetricsRecorder
from factory.prompts.templates import CODER_SYSTEM, build_coder_user_prompt
from factory.sandbox.worktree import WorktreeManager
from factory.state import (
    CodeArtifact,
    CodeArtifacts,
    FactoryState,
    Phase,
    TechnicalSpec,
)
from factory.tools.llm import LLMClient

MODULES = ("frontend", "backend", "database", "infra")


class CoderAgent(BaseAgent):
    def __init__(
        self,
        llm: LLMClient,
        worktrees: WorktreeManager,
        metrics: MetricsRecorder | None = None,
    ) -> None:
        super().__init__(role="coder", llm=llm, worktrees=worktrees, metrics=metrics)

    @property
    def phase(self) -> Phase:
        return Phase.CODER

    async def run(self, state: FactoryState) -> FactoryState:
        spec = state.technical_spec
        if spec is None:
            raise ValueError("No technical spec available for Coder agent")

        self._log.info("coder.run.start", request_id=state.request_id, spec_id=spec.spec_id)

        system_prompt = CODER_SYSTEM
        user_prompt = build_coder_user_prompt(spec)

        response = await self.generate(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            trace_id=state.request_id,
        )

        # Parse code artifacts from response. Best-effort: extract fenced code
        # blocks keyed by module/path. Fall back to a single placeholder file.
        artifacts_by_module = self._parse_artifacts(response.text, spec)

        # Write each artifact into its module worktree and record in state
        for module in MODULES:
            artifacts = artifacts_by_module.get(module)
            if not artifacts:
                continue
            wt_path = self.worktrees.get_path(module)
            for path, content in artifacts.files.items():
                abs_path = self.write_file(state, module, path, content)
                # Update the artifact with resolved info
                artifact = CodeArtifact(
                    path=path,
                    content=content,
                    language=self._guess_language(path),
                    module=module,  # type: ignore[arg-type]
                    description=f"Generated {path}",
                )
                artifacts.add(artifact)
            state.code_artifacts[module] = artifacts

        # Commit generated code into each worktree
        for module in MODULES:
            if module in state.code_artifacts:
                self.worktrees.stage_and_commit(module, f"factory: generate {module} code (spec {spec.spec_id})")

        state.phase = Phase.QA
        message = self.build_message(
            recipient="qa",
            msg_type="code",
            payload={
                "spec_id": spec.spec_id,
                "modules": {
                    m: list(a.files.keys()) for m, a in state.code_artifacts.items()
                },
                "worktrees": {m: str(p) for m, p in state.worktrees.items()},
            },
            correlation_id=state.request_id,
            trace_id=state.request_id,
        )
        self.emit(state, message)

        self._log.info(
            "coder.run.done",
            modules=list(state.code_artifacts.keys()),
            total_files=sum(len(a.files) for a in state.code_artifacts.values()),
        )
        return state

    # ------------------------------------------------------------------
    # Parsing helpers
    # ------------------------------------------------------------------

    def _parse_artifacts(self, text: str, spec: TechnicalSpec) -> dict[str, CodeArtifacts]:
        """Extract per-module file contents from the coder LLM response.

        Looks for markdown fenced blocks annotated with a path, e.g.
        ```path:frontend/src/App.tsx
        ...content```
        Falls back to generating a minimal scaffold per module if parsing fails.
        """
        artifacts: dict[str, CodeArtifacts] = {
            m: CodeArtifacts(module=m)  # type: ignore[arg-type]
            for m in MODULES
        }

        import re

        # Pattern: ```path:<module>/<relpath> or ```<module>/<relpath>
        pattern = re.compile(r"```(?::path:)?([\w./-]+)\n(.*?)```", re.DOTALL)
        for match in pattern.finditer(text):
            raw_path = match.group(1).strip()
            content = match.group(2).strip()
            parts = raw_path.split("/", 1)
            module = parts[0] if parts[0] in MODULES else "backend"
            relpath = parts[1] if len(parts) > 1 else raw_path
            artifact = CodeArtifact(
                path=relpath,
                content=content,
                language=self._guess_language(relpath),
                module=module,  # type: ignore[arg-type]
                description=f"Generated {relpath}",
            )
            artifacts[module].add(artifact)

        # Fallback: if nothing parsed, emit minimal scaffolds so the pipeline continues
        if all(len(a.files) == 0 for a in artifacts.values()):
            self._log.warning("coder.parse_fallback", reason="no_fenced_blocks")
            artifacts = self._default_scaffolds(spec)

        return artifacts

    def _default_scaffolds(self, spec: TechnicalSpec) -> dict[str, CodeArtifacts]:
        artifacts: dict[str, CodeArtifacts] = {
            m: CodeArtifacts(module=m)  # type: ignore[arg-type]
            for m in MODULES
        }

        # Backend scaffold
        artifacts["backend"].add(
            CodeArtifact(
                path="main.py",
                content='# Auto-generated backend scaffold\nfrom fastapi import FastAPI\n\napp = FastAPI(title="Factory App")\n\n@app.get("/health")\nasync def health():\n    return {"status": "ok"}\n',
                language="python",
                module="backend",  # type: ignore[arg-type]
            )
        )
        artifacts["backend"].add(
            CodeArtifact(
                path="requirements.txt",
                content="fastapi==0.104.1\nuvicorn==0.24.0\n",
                language="text",
                module="backend",  # type: ignore[arg-type]
            )
        )

        # Frontend scaffold
        artifacts["frontend"].add(
            CodeArtifact(
                path="package.json",
                content='{"name":"factory-app","private":true,"scripts":{"dev":"vite","build":"vite build"}}',
                language="json",
                module="frontend",  # type: ignore[arg-type]
            )
        )
        artifacts["frontend"].add(
            CodeArtifact(
                path="src/App.tsx",
                content="export default function App(){return <div>Factory App</div>}\n",
                language="typescript",
                module="frontend",  # type: ignore[arg-type]
            )
        )

        # Database scaffold
        artifacts["database"].add(
            CodeArtifact(
                path="schema.sql",
                content="-- Auto-generated schema\nCREATE TABLE IF NOT EXISTS messages (\n    id SERIAL PRIMARY KEY,\n    content TEXT NOT NULL,\n    created_at TIMESTAMP DEFAULT NOW()\n);\n",
                language="sql",
                module="database",  # type: ignore[arg-type]
            )
        )

        # Infra scaffold
        artifacts["infra"].add(
            CodeArtifact(
                path="Dockerfile",
                content="FROM python:3.11-slim\nWORKDIR /app\nCOPY . .\nRUN pip install -r requirements.txt\nEXPOSE 8000\nCMD [\"uvicorn\", \"main:app\", \"--host\", \"0.0.0.0\"]\n",
                language="dockerfile",
                module="infra",  # type: ignore[arg-type]
            )
        )

        return artifacts

    @staticmethod
    def _guess_language(path: str) -> str:
        ext = path.rsplit(".", 1)[-1].lower() if "." in path else ""
        mapping = {
            "py": "python",
            "ts": "typescript",
            "tsx": "typescript",
            "js": "javascript",
            "jsx": "javascript",
            "go": "go",
            "rs": "rust",
            "sql": "sql",
            "tf": "hcl",
            "yml": "yaml",
            "yaml": "yaml",
            "json": "json",
            "md": "markdown",
            "sh": "shell",
            "dockerfile": "dockerfile",
        }
        return mapping.get(ext, "text")


__all__ = ["CoderAgent"]
