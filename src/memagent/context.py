from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import hashlib
from pathlib import Path
import subprocess
from typing import Any


@dataclass(frozen=True)
class ProjectContext:
    cwd: Path
    git_root: Path | None
    branch: str | None
    repo_name: str | None
    recent_files: tuple[str, ...]
    agents_files: tuple[Path, ...]
    canonical_repo_id: str | None = None
    git_common_dir: Path | None = None
    is_worktree: bool = False


def detect_context(cwd: Path | None = None) -> ProjectContext:
    current = (cwd or Path.cwd()).resolve()
    git_root = _git_root(current)
    git_common_dir = _git_common_dir(current) if git_root else None
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
        canonical_repo_id=_canonical_repo_id(git_common_dir),
        git_common_dir=git_common_dir,
        is_worktree=bool(
            git_root
            and git_common_dir
            and (
                (git_root / ".git").is_file()
                or git_common_dir != (git_root / ".git").resolve()
            )
        ),
    )


def context_payload(context: ProjectContext) -> dict[str, object]:
    return {
        "cwd": str(context.cwd),
        "git_root": str(context.git_root) if context.git_root else None,
        "branch": context.branch,
        "repo_name": context.repo_name,
        "canonical_repo_id": context.canonical_repo_id,
        "is_worktree": context.is_worktree,
        "recent_files": [str(path) for path in context.recent_files],
        "agents_files": [str(path) for path in context.agents_files],
    }


def matches_project_context(payload: dict[str, Any], context: ProjectContext) -> bool:
    candidate_id = _text(payload.get("canonical_repo_id"))
    if context.canonical_repo_id and candidate_id:
        return candidate_id == context.canonical_repo_id

    candidate_root = _text(payload.get("git_root"))
    if context.canonical_repo_id and candidate_root:
        historical_id = _canonical_repo_id_for_root(candidate_root)
        if historical_id:
            return historical_id == context.canonical_repo_id

    if context.git_root and candidate_root:
        return Path(candidate_root).expanduser().resolve() == context.git_root.resolve()

    candidate_cwd = _text(payload.get("cwd"))
    if candidate_cwd:
        candidate_path = Path(candidate_cwd).expanduser().resolve()
        return (
            candidate_path == context.cwd
            or context.cwd.is_relative_to(candidate_path)
            or candidate_path.is_relative_to(context.cwd)
        )

    candidate_repo = _text(payload.get("repo_name"))
    return bool(
        context.git_root is None
        and context.repo_name
        and candidate_repo
        and candidate_repo == context.repo_name
    )


def repo_scope_matches(repo: str | None, context: ProjectContext) -> bool:
    value = (repo or "").strip()
    if not value:
        return False
    candidate = Path(value).expanduser()
    if candidate.is_absolute():
        if context.canonical_repo_id:
            candidate_id = _canonical_repo_id_for_root(str(candidate))
            if candidate_id:
                return candidate_id == context.canonical_repo_id
        return bool(context.git_root and candidate.resolve() == context.git_root.resolve())
    return bool(context.repo_name and value == context.repo_name)


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


def _git_common_dir(cwd: Path) -> Path | None:
    result = _run_git(cwd, "rev-parse", "--git-common-dir")
    if not result:
        return None
    path = Path(result).expanduser()
    return (cwd / path).resolve() if not path.is_absolute() else path.resolve()


def _git_branch(cwd: Path) -> str | None:
    return _run_git(cwd, "branch", "--show-current") or None


def _canonical_repo_id(common_dir: Path | None) -> str | None:
    if common_dir is None:
        return None
    digest = hashlib.sha256(str(common_dir.resolve()).encode("utf-8")).hexdigest()[:20]
    return f"git-common:{digest}"


@lru_cache(maxsize=256)
def _canonical_repo_id_for_root(root: str) -> str | None:
    path = Path(root).expanduser()
    if not path.exists():
        return None
    common_dir = _git_common_dir(path)
    return _canonical_repo_id(common_dir)


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


def _text(value: object) -> str | None:
    return str(value).strip() if value is not None and str(value).strip() else None
