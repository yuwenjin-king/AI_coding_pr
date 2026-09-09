"""Per-run git worktree isolation (Phase 4).

Each coding run gets its own worktree + branch (agent/<ticket>-run<N>):
- tools operate inside the worktree (thread-local), never on the main tree
- reject → worktree + branch deleted, zero pollution
- approve → branch merged back into the checked-out branch, then cleaned up
"""

from __future__ import annotations

import subprocess
import threading
from pathlib import Path

from app.config import ROOT, settings

_GIT_TIMEOUT = 30

_local = threading.local()


def current_shopai_path() -> Path:
    """ShopAI root for this thread: the run's worktree if set, else the main checkout."""
    ws = getattr(_local, "shopai_path", None)
    return Path(ws) if ws else settings.shopai_path


def set_current_shopai_path(path: Path | str | None) -> None:
    _local.shopai_path = str(path) if path else None


def _git(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=_GIT_TIMEOUT,
    )


def repo_root(shopai: Path | None = None) -> Path:
    shopai = shopai or current_shopai_path()
    proc = _git(["rev-parse", "--show-toplevel"], cwd=shopai)
    if proc.returncode != 0:
        raise RuntimeError(f"not a git repo: {shopai}")
    return Path(proc.stdout.strip())


class WorkspaceError(RuntimeError):
    pass


class Workspace:
    def __init__(self, run_id: int, ticket_code: str) -> None:
        self.run_id = run_id
        self.ticket_code = ticket_code
        self.branch = f"agent/{ticket_code}-run{run_id}"
        self.base_sha: str | None = None
        ws_root = Path(settings.agent_workspace_root)
        if not ws_root.is_absolute():
            ws_root = ROOT / ws_root
        self.path = ws_root / f"{ticket_code}-run{run_id}"
        main_shopai = settings.shopai_path
        self._repo_root = repo_root(main_shopai)
        self._shopai_rel = main_shopai.relative_to(self._repo_root)
        self.shopai_path = self.path / self._shopai_rel

    def create(self) -> Path:
        if self.path.exists():
            raise WorkspaceError(f"workspace already exists: {self.path}")
        head = _git(["rev-parse", "HEAD"], cwd=self._repo_root)
        if head.returncode != 0:
            raise WorkspaceError(f"cannot resolve HEAD: {head.stderr.strip()}")
        self.base_sha = head.stdout.strip()
        proc = _git(["worktree", "add", "-b", self.branch, str(self.path), "HEAD"], cwd=self._repo_root)
        if proc.returncode != 0:
            raise WorkspaceError(f"worktree add failed: {proc.stderr.strip()}")
        return self.shopai_path

    def commit_all(self, message: str) -> bool:
        """Stage and commit everything inside the worktree; False when nothing changed."""
        _git(["add", "-A"], cwd=self.path)
        proc = _git(["status", "--porcelain"], cwd=self.path)
        if not proc.stdout.strip():
            return False
        proc = _git(["commit", "-m", message], cwd=self.path)
        if proc.returncode != 0:
            raise WorkspaceError(f"commit failed: {proc.stderr.strip()}")
        return True

    def diff(self) -> str:
        """Diff of everything the agent changed relative to the base commit."""
        base = getattr(self, "base_sha", None)
        if base:
            proc = _git(["diff", base, "HEAD"], cwd=self.path)
        else:
            proc = _git(["diff", "HEAD"], cwd=self.path)
        return proc.stdout.strip()

    def remove(self) -> None:
        _git(["worktree", "remove", "--force", str(self.path)], cwd=self._repo_root)
        _git(["branch", "-D", self.branch], cwd=self._repo_root)
        set_current_shopai_path(None)

    def merge_into_main(self) -> str:
        """Merge the agent branch into the currently checked-out branch of the main tree."""
        status = _git(["status", "--porcelain"], cwd=self._repo_root)
        if status.stdout.strip():
            raise WorkspaceError(
                "主工作区有未提交改动，请先处理（commit/stash）再批准合并：\n"
                + status.stdout.strip()[:500]
            )
        proc = _git(
            ["merge", "--no-ff", "-m", f"merge {self.branch} (approved via HITL)", self.branch],
            cwd=self._repo_root,
        )
        if proc.returncode != 0:
            _git(["merge", "--abort"], cwd=self._repo_root)
            raise WorkspaceError(f"merge failed: {proc.stderr.strip()}")
        return proc.stdout.strip()
