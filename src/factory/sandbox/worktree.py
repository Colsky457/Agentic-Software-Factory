"""Git worktree sandbox manager.

Provides isolated, per-module Git worktree workspaces so that concurrent agents
can edit, test, and run code without branch collision or index pollution.

Worktrees share the object database (no history duplication) but maintain
independent working trees and indexes. Each module (frontend, backend,
database, infra) gets its own worktree under `<worktrees_dir>/<module>/`.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Self

from factory.config import settings

try:
    from git import Repo
    from git.exc import GitCommandError, InvalidGitRepositoryError
except ImportError as exc:  # pragma: no cover
    raise ImportError("GitPython is required for WorktreeManager") from exc


class WorktreeManager:
    """Manages Git worktree sandboxes for factory modules."""

    MODULES = ("frontend", "backend", "database", "infra")

    def __init__(
        self,
        repo_path: str | Path | None = None,
        worktrees_dir: str | Path | None = None,
        base_branch: str | None = None,
    ) -> None:
        self.repo_path = Path(repo_path or os.getcwd()).resolve()
        self.worktrees_dir = Path(worktrees_dir or settings.worktrees_dir).resolve()
        self.base_branch = base_branch or settings.default_branch
        self._repo: Repo | None = None
        self._worktrees: dict[str, Path] = {}

    # ------------------------------------------------------------------
    # Repo access
    # ------------------------------------------------------------------

    @property
    def repo(self) -> Repo:
        if self._repo is None:
            try:
                self._repo = Repo(self.repo_path, search_parent_directories=True)
            except InvalidGitRepositoryError as exc:
                raise RuntimeError(f"Not a git repository: {self.repo_path}") from exc
        return self._repo

    # ------------------------------------------------------------------
    # Worktree lifecycle
    # ------------------------------------------------------------------

    def init(self) -> Self:
        """Initialize the worktrees root directory and create module worktrees."""
        self.worktrees_dir.mkdir(parents=True, exist_ok=True)
        for module in self.MODULES:
            self.ensure_worktree(module)
        return self

    def ensure_worktree(self, module: str) -> Path:
        """Ensure a worktree exists for `module` and return its path."""
        if module not in self.MODULES:
            raise ValueError(f"Unknown module: {module}. Valid: {self.MODULES}")

        wt_path = self.worktrees_dir / module
        self._worktrees[module] = wt_path

        if wt_path.exists() and (wt_path / ".git").exists():
            return wt_path

        # Create a worktree tracking a branch named factory/<module>
        branch = f"factory/{module}"
        try:
            # Try to check out existing branch
            self.repo.git.branch(branch)
        except GitCommandError:
            pass  # branch may already exist

        try:
            self.repo.git.worktree("add", "--track", str(wt_path), branch)
        except GitCommandError:
            # Branch already tracked; force add without checkout tracking
            self.repo.git.worktree("add", "--force", str(wt_path), branch)

        return wt_path

    def remove_worktree(self, module: str, force: bool = False) -> None:
        """Remove a module worktree."""
        wt_path = self.worktrees_dir / module
        if not wt_path.exists():
            return
        branch = f"factory/{module}"
        args = ["worktree", "remove", str(wt_path)]
        if force:
            args.append("--force")
        try:
            self.repo.git.execute(args)
        except GitCommandError as exc:
            raise RuntimeError(f"Failed to remove worktree for {module}: {exc}") from exc
        if branch in [b.name for b in self.repo.branches]:
            try:
                self.repo.git.branch("-D", branch)
            except GitCommandError:
                pass
        self._worktrees.pop(module, None)

    def cleanup_all(self, force: bool = True) -> None:
        """Remove all module worktrees."""
        for module in list(self._worktrees.keys()):
            self.remove_worktree(module, force=force)

    # ------------------------------------------------------------------
    # Path & file helpers
    # ------------------------------------------------------------------

    def get_path(self, module: str) -> Path:
        """Return the absolute worktree path for `module`, ensuring it exists."""
        if module not in self._worktrees:
            self.ensure_worktree(module)
        return self._worktrees[module]

    def write_file(self, worktree_path: Path | str, relative_path: str, content: str) -> str:
        """Write `content` to `<worktree>/<relative_path>`, creating dirs."""
        base = Path(worktree_path)
        target = base / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return str(target.resolve())

    def read_file(self, worktree_path: Path | str, relative_path: str) -> str | None:
        """Read a file from the worktree, or None if missing."""
        target = Path(worktree_path) / relative_path
        if not target.exists():
            return None
        return target.read_text(encoding="utf-8")

    def list_files(self, worktree_path: Path | str) -> list[str]:
        """Recursively list relative file paths under the worktree."""
        base = Path(worktree_path)
        if not base.exists():
            return []
        return sorted(
            str(p.relative_to(base))
            for p in base.rglob("*")
            if p.is_file() and ".git" not in p.parts
        )

    def stage_and_commit(self, module: str, message: str) -> str | None:
        """Stage all changes in a module worktree and commit. Returns commit SHA."""
        wt_path = self.get_path(module)
        repo = self.repo
        # GitPython operates on the main repo; use --work-tree for worktree ops
        env = dict(os.environ)
        env["GIT_WORK_TREE"] = str(wt_path)
        env["GIT_DIR"] = str(wt_path / ".git")
        try:
            repo.git.add("--all", env=env)
            commit = repo.git.commit("-m", message, env=env)
            return commit.strip()
        except GitCommandError:
            # Nothing to commit
            return None

    def get_status(self, module: str) -> dict[str, bool]:
        """Return whether a worktree exists and has uncommitted changes."""
        wt_path = self.get_path(module)
        exists = wt_path.exists() and (wt_path / ".git").exists()
        dirty = False
        if exists:
            env = dict(os.environ)
            env["GIT_WORK_TREE"] = str(wt_path)
            env["GIT_DIR"] = str(wt_path / ".git")
            try:
                status = self.repo.git.status("--porcelain", env=env)
                dirty = bool(status.strip())
            except GitCommandError:
                dirty = False
        return {"exists": exists, "dirty": dirty}


__all__ = ["WorktreeManager"]
