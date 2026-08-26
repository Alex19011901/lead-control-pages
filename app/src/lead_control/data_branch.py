from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


DATA_BRANCH = "data"


def prepare_data_worktree(repo_root: Path, worktree_path: Path) -> tuple[Path, bool]:
    worktree_path = worktree_path.resolve()
    repo_root = repo_root.resolve()

    if worktree_path == repo_root:
        raise RuntimeError("Data worktree must not be the main repository path")

    if worktree_path.exists():
        raise RuntimeError(f"Data worktree path already exists: {worktree_path}")

    remote_exists = _remote_branch_exists(repo_root, DATA_BRANCH)
    if remote_exists:
        _run(["git", "fetch", "origin", DATA_BRANCH], repo_root)
        _run(
            ["git", "worktree", "add", "-B", DATA_BRANCH, str(worktree_path), f"origin/{DATA_BRANCH}"],
            repo_root,
        )
        return worktree_path / "data", False

    _run(["git", "worktree", "add", "--detach", str(worktree_path), "HEAD"], repo_root)
    _run(["git", "switch", "--orphan", DATA_BRANCH], worktree_path)
    _clear_worktree_files(worktree_path)
    return worktree_path / "data", True


def commit_data_if_changed(worktree_path: Path, message: str) -> bool:
    if not _is_dirty(worktree_path):
        return False

    _run(["git", "add", "-A"], worktree_path)
    if not _is_dirty(worktree_path):
        return False

    _run(["git", "commit", "-m", message], worktree_path)
    _run(["git", "push", "origin", DATA_BRANCH], worktree_path)
    return True


def _remote_branch_exists(repo_root: Path, branch: str) -> bool:
    result = subprocess.run(
        ["git", "ls-remote", "--exit-code", "--heads", "origin", branch],
        cwd=repo_root,
        text=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return result.returncode == 0


def _is_dirty(path: Path) -> bool:
    result = _run(["git", "status", "--porcelain"], path, capture_output=True)
    return bool(result.stdout.strip())


def _clear_worktree_files(worktree_path: Path) -> None:
    resolved = worktree_path.resolve()
    if len(resolved.parts) < 4:
        raise RuntimeError(f"Refusing to clear suspicious path: {resolved}")

    for child in resolved.iterdir():
        if child.name == ".git":
            continue
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()


def _run(
    args: list[str],
    cwd: Path,
    capture_output: bool = False,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE if capture_output else None,
        stderr=subprocess.PIPE if capture_output else None,
        check=True,
    )
