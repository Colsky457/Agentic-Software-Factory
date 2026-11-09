"""Command-line interface for the Agentic Software Factory.

Usage:
    python -m factory.main run "Build a real-time chat app"
    python -m factory.main dashboard
"""

from __future__ import annotations

import asyncio
import sys

import typer
from rich.console import Console
from rich.panel import Panel
from rich.json import JSON

from factory.config import settings
from factory.observability.logger import configure_logging
from factory.observability.dashboard import app as dashboard_app
from factory.orchestrator.graph import FactoryOrchestrator

configure_logging(level=settings.log_level)

app = typer.Typer(
    name="factory",
    help="Agentic Software Factory - autonomous multi-agent software generation",
)
console = Console()


@app.command()
def run(
    prompt: str = typer.Argument(..., help="High-level product requirement"),
    request_id: str | None = typer.Option(None, "--request-id", "-r", help="Optional request ID"),
    auto_approve: bool = typer.Option(False, "--auto-approve", help="Auto-approve all HITL gates (dev mode)"),
) -> None:
    """Run the factory workflow for a product requirement."""

    async def _run() -> None:
        orchestrator = FactoryOrchestrator()
        if auto_approve:
            orchestrator.hitl.auto_approve = True
        final_state = await orchestrator.run(user_prompt=prompt, request_id=request_id)

        console.print(Panel.fit(f"[bold green]Factory run complete[/bold green]"))
        console.print(f"Request ID: {final_state.request_id}")
        console.print(f"Status: {final_state.status.value}")
        console.print(f"Phase: {final_state.phase.value}")

        if final_state.technical_spec:
            console.print("\n[bold]Technical Spec:[/bold]")
            console.print(f"  Title: {final_state.technical_spec.title}")
            console.print(f"  User stories: {len(final_state.technical_spec.user_stories)}")

        if final_state.code_artifacts:
            total_files = sum(len(a.files) for a in final_state.code_artifacts.values())
            console.print(f"\n[bold]Code artifacts:[/bold] {total_files} files across {len(final_state.code_artifacts)} modules")

        if final_state.test_results:
            for module, result in final_state.test_results.items():
                console.print(f"  {module}: {result.passed}/{result.total} tests passed")

        if final_state.devops_artifacts:
            console.print("\n[bold]DevOps artifacts generated[/bold]")

        if final_state.errors:
            console.print(f"\n[bold red]Errors:[/bold red] {len(final_state.errors)}")
            for e in final_state.errors:
                console.print(f"  - {e.node}: {e.message}")

        console.print(f"\n[bold]Metrics:[/bold] {final_state.metrics.total_tokens} tokens, "
                      f"${final_state.metrics.estimated_cost_usd:.4f} estimated cost")

    asyncio.run(_run())


@app.command()
def dashboard(
    host: str = typer.Option(settings.dashboard_host, "--host", help="Bind host"),
    port: int = typer.Option(settings.dashboard_port, "--port", help="Bind port"),
) -> None:
    """Launch the observability dashboard."""
    import uvicorn

    console.print(f"[bold]Starting dashboard at http://{host}:{port}[/bold]")
    uvicorn.run(dashboard_app, host=host, port=port)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
