"""Git and filesystem utilities for coding workflow assessment."""
from __future__ import annotations

import logging
import os
import subprocess
from typing import Any

from .models import RepoAssessment, DiffResult

logger = logging.getLogger(__name__)

# Default repo path (configurable)
DEFAULT_REPO_PATH = os.environ.get("OI_CODING_REPO_PATH", os.getcwd())


def run_git_command(repo_path: str, *args: str) -> tuple[str, str, int]:
    """Run a git command and return stdout, stderr, and return code.

    Parameters
    ----------
    repo_path : str
        Path to the git repository.
    *args : str
        Git command arguments.

    Returns
    -------
    tuple[str, str, int]
        Tuple of (stdout, stderr, return_code).
    """
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=30,
        )
        return result.stdout, result.stderr, result.returncode
    except subprocess.TimeoutExpired:
        logger.warning("git command timed out: git %s", args)
        return "", "Command timed out", 124
    except FileNotFoundError:
        logger.warning("git command not found")
        return "", "git not installed", 127
    except Exception as e:
        logger.exception("Error running git command")
        return "", str(e), 1


def run_git_command_async(repo_path: str, *args: str) -> tuple[str, str, int]:
    """Run a git command asynchronously.

    Parameters
    ----------
    repo_path : str
        Path to the git repository.
    *args : str
        Git command arguments.

    Returns
    -------
    tuple[str, str, int]
        Tuple of (stdout, stderr, return_code).
    """
    return run_git_command(repo_path, *args)


def is_git_repository(path: str) -> bool:
    """Check if a path is a git repository.

    Parameters
    ----------
    path : str
        Path to check.

    Returns
    -------
    bool
        True if path is a git repository.
    """
    stdout, _, returncode = run_git_command(path, "rev-parse", "--is-inside-work-tree")
    return returncode == 0 and stdout.strip().lower() == "true"


def get_current_branch(repo_path: str) -> str | None:
    """Get the current branch name.

    Parameters
    ----------
    repo_path : str
        Path to the git repository.

    Returns
    -------
    str | None
        Current branch name or None if not a git repo.
    """
    stdout, _, returncode = run_git_command(repo_path, "rev-parse", "--abbrev-ref", "HEAD")
    if returncode == 0:
        return stdout.strip()
    return None


def get_git_status(repo_path: str) -> dict[str, list[str]]:
    """Get git status information.

    Parameters
    ----------
    repo_path : str
        Path to the git repository.

    Returns
    -------
    dict[str, list[str]]
        Dict with 'staged', 'unstaged', 'untracked' file lists.
    """
    staged = []
    unstaged = []
    untracked = []

    # Get staged files
    stdout, _, returncode = run_git_command(
        repo_path, "diff", "--cached", "--name-only"
    )
    if returncode == 0 and stdout:
        staged = [f.strip() for f in stdout.strip().split("\n") if f.strip()]

    # Get unstaged files (modified but not staged)
    stdout, _, returncode = run_git_command(
        repo_path, "diff", "--name-only"
    )
    if returncode == 0 and stdout:
        unstaged = [f.strip() for f in stdout.strip().split("\n") if f.strip()]

    # Get untracked files
    stdout, _, returncode = run_git_command(
        repo_path, "ls-files", "--others", "--exclude-standard"
    )
    if returncode == 0 and stdout:
        untracked = [f.strip() for f in stdout.strip().split("\n") if f.strip()]

    return {
        "staged": staged,
        "unstaged": unstaged,
        "untracked": untracked,
    }


def get_recent_commits(repo_path: str, count: int = 5) -> list[str]:
    """Get recent commit messages.

    Parameters
    ----------
    repo_path : str
        Path to the git repository.
    count : int
        Number of commits to retrieve.

    Returns
    -------
    list[str]
        List of recent commit messages.
    """
    stdout, _, returncode = run_git_command(
        repo_path, "log", f"-{count}", "--oneline", "--format=%s"
    )
    if returncode == 0 and stdout:
        return [line.strip() for line in stdout.strip().split("\n") if line.strip()]
    return []


def get_modified_files_list(repo_path: str) -> list[str]:
    """Get list of modified files (staged + unstaged).

    Parameters
    ----------
    repo_path : str
        Path to the git repository.

    Returns
    -------
    list[str]
        List of modified file paths.
    """
    status = get_git_status(repo_path)
    all_modified = set(status["staged"] + status["unstaged"])
    return sorted(all_modified)


def get_full_diff(repo_path: str, staged: bool = False) -> str:
    """Get full diff output.

    Parameters
    ----------
    repo_path : str
        Path to the git repository.
    staged : bool
        If True, get staged diff. If False, get unstaged diff.

    Returns
    -------
    str
        Full diff output.
    """
    if staged:
        stdout, stderr, returncode = run_git_command(
            repo_path, "diff", "--cached", "--color=never"
        )
    else:
        stdout, stderr, returncode = run_git_command(
            repo_path, "diff", "--color=never"
        )

    if returncode == 0:
        return stdout
    return f"Error getting diff: {stderr}"


def get_diff_stats(repo_path: str) -> tuple[int, int]:
    """Get diff statistics (insertions, deletions).

    Parameters
    ----------
    repo_path : str
        Path to the git repository.

    Returns
    -------
    tuple[int, int]
        Tuple of (insertions, deletions).
    """
    stdout, _, returncode = run_git_command(
        repo_path, "diff", "--stat", "--color=never"
    )
    if returncode != 0 or not stdout:
        return 0, 0

    # Parse stat line like "3 files changed, 15 insertions(+), 7 deletions(-)"
    lines = stdout.strip().split("\n")
    last_line = lines[-1] if lines else ""

    insertions = 0
    deletions = 0

    if "insertion" in last_line:
        # Extract insertions
        import re
        match = re.search(r"(\d+) insertion", last_line)
        if match:
            insertions = int(match.group(1))

    if "deletion" in last_line:
        # Extract deletions
        import re
        match = re.search(r"(\d+) deletion", last_line)
        if match:
            deletions = int(match.group(1))

    return insertions, deletions


def assess_repository(repo_path: str = DEFAULT_REPO_PATH) -> RepoAssessment:
    """Assess the current state of a git repository.

    Parameters
    ----------
    repo_path : str, optional
        Path to the repository. Defaults to DEFAULT_REPO_PATH.

    Returns
    -------
    RepoAssessment
        Repository assessment result.
    """
    # Normalize path
    repo_path = os.path.abspath(repo_path)

    # Check if it's a git repo
    if not is_git_repository(repo_path):
        return RepoAssessment(
            repo_path=repo_path,
            is_git_repo=False,
            branch=None,
            has_uncommitted_changes=False,
            error="Not a git repository",
        )

    # Get branch
    branch = get_current_branch(repo_path)

    # Get status
    status = get_git_status(repo_path)

    # Get recent commits
    recent_commits = get_recent_commits(repo_path)

    # Get modified files
    modified_files = get_modified_files_list(repo_path)

    # Check for uncommitted changes
    has_uncommitted = len(status["staged"]) > 0 or len(status["unstaged"]) > 0

    return RepoAssessment(
        repo_path=repo_path,
        is_git_repo=True,
        branch=branch,
        has_uncommitted_changes=has_uncommitted,
        staged_files=status["staged"],
        unstaged_files=status["unstaged"],
        untracked_files=status["untracked"],
        recent_commits=recent_commits,
        modified_files=modified_files,
    )


def generate_diff(repo_path: str = DEFAULT_REPO_PATH) -> DiffResult:
    """Generate diff output for the repository.

    Parameters
    ----------
    repo_path : str, optional
        Path to the repository. Defaults to DEFAULT_REPO_PATH.

    Returns
    -------
    DiffResult
        Diff result with summary and full diff.
    """
    repo_path = os.path.abspath(repo_path)

    # Get assessment first
    assessment = assess_repository(repo_path)

    if not assessment.is_git_repo:
        return DiffResult(
            summary="Not a git repository",
            full_diff="",
            files_changed=[],
            insertions=0,
            deletions=0,
            error="Not a git repository",
        )

    # Get full diff
    full_diff = get_full_diff(repo_path)

    # Get stats
    insertions, deletions = get_diff_stats(repo_path)

    # Build summary
    files = assessment.modified_files
    file_count = len(files)

    if file_count == 0:
        summary = "No changes in repository"
    else:
        file_list = ", ".join(files[:3])
        if file_count > 3:
            file_list += f" (+{file_count - 3} more)"
        summary = f"{file_count} file(s) changed: {file_list}"

        if insertions > 0 or deletions > 0:
            summary += f" ({insertions} insertions, {deletions} deletions)"

    return DiffResult(
        summary=summary,
        full_diff=full_diff if full_diff else "No changes",
        files_changed=files,
        insertions=insertions,
        deletions=deletions,
    )