from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import subprocess


@dataclass(frozen=True)
class ProjectContext:
    cwd: Path
    git_root: Path | None
    branch: str | None
    repo_name: str | None
    recent_files: tuple[str, ...]
    agents_files: tuple[Path, ...]


def detect_context(cwd: Path | None = None) -> ProjectContext:
    current = (cwd or Path.cwd()).resolve()
    git_root = _git_root(current)
    branch = _git_branch(current) if git_root else None
    recent_files = _recent_files(current) if git_root else ()
    agents_files = tuple(_find_agents_files(current, git_root))
    repo_name = _project_name(current, git_root)
    return ProjectContext(
        cwd=current,
        git_root=git_root,
        branch=branch,
        repo_name=repo_name,
        recent_files=recent_files,
        agents_files=agents_files,
    )


def _project_name(cwd: Path, git_root: Path | None) -> str:
    markers = ("pyproject.toml", "package.json", "go.mod", "Cargo.toml", ".git")
    current = cwd
    stop = git_root.parent if git_root else Path(cwd.anchor)
    while True:
        if any((current / marker).exists() for marker in markers):
            return current.name
        if current == stop or current.parent == current:
            break
        current = current.parent
    return git_root.name if git_root else cwd.name


def _git_root(cwd: Path) -> Path | None:
    result = _run_git(cwd, "rev-parse", "--show-toplevel")
    if not result:
        return None
    return Path(result).resolve()


def _git_branch(cwd: Path) -> str | None:
    return _run_git(cwd, "branch", "--show-current") or None


def _recent_files(cwd: Path) -> tuple[str, ...]:
    result = _run_git(cwd, "diff", "--name-only")
    if not result:
        result = _run_git(cwd, "status", "--short")
        if not result:
            return ()
        files = []
        for line in result.splitlines():
            if len(line) > 3:
                files.append(line[3:].strip())
        return tuple(files[:20])
    return tuple(line.strip() for line in result.splitlines() if line.strip())[:20]


def _find_agents_files(cwd: Path, git_root: Path | None) -> list[Path]:
    stop = git_root or cwd.anchor
    files: list[Path] = []
    current = cwd
    while True:
        for name in ("AGENTS.override.md", "AGENTS.md"):
            candidate = current / name
            if candidate.exists():
                files.append(candidate)
                break
        if current == stop or current.parent == current:
            break
        current = current.parent
    files.reverse()
    return files


def _run_git(cwd: Path, *args: str) -> str | None:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=str(cwd),
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout.strip()
