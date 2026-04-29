"""Data models for coding workflow."""
from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


class CodingWorkflowStatus(enum.Enum):
    """Status of a coding workflow request."""

    PENDING = "pending"
    ASSESSING_REPO = "assessing_repo"
    GENERATING_DIFF = "generating_diff"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class CodingRequest:
    """A coding workflow request triggered by a voice transcript."""

    request_id: str
    transcript: str
    source_device_id: str
    timestamp: datetime
    status: CodingWorkflowStatus = CodingWorkflowStatus.PENDING
    error_message: str | None = None


@dataclass
class RepoAssessment:
    """Result of repository state assessment."""

    repo_path: str | None
    is_git_repo: bool
    branch: str | None
    has_uncommitted_changes: bool
    staged_files: list[str] = field(default_factory=list)
    unstaged_files: list[str] = field(default_factory=list)
    untracked_files: list[str] = field(default_factory=list)
    recent_commits: list[str] = field(default_factory=list)
    modified_files: list[str] = field(default_factory=list)
    error: str | None = None


@dataclass
class DiffResult:
    """Result of diff generation."""

    summary: str  # Short summary for Stick
    full_diff: str  # Full diff for Pi screen
    files_changed: list[str]
    insertions: int
    deletions: int
    error: str | None = None


@dataclass
class CodingWorkflowState:
    """Current state of the coding workflow system."""

    active_request: CodingRequest | None = None
    current_assessment: RepoAssessment | None = None
    current_diff: DiffResult | None = None
    request_history: list[CodingRequest] = field(default_factory=list)
    max_history: int = 10

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for API response."""
        return {
            "active_request": {
                "request_id": self.active_request.request_id,
                "transcript": self.active_request.transcript,
                "source_device_id": self.active_request.source_device_id,
                "timestamp": self.active_request.timestamp.isoformat(),
                "status": self.active_request.status.value,
                "error_message": self.active_request.error_message,
            } if self.active_request else None,
            "current_assessment": {
                "repo_path": self.current_assessment.repo_path,
                "is_git_repo": self.current_assessment.is_git_repo,
                "branch": self.current_assessment.branch,
                "has_uncommitted_changes": self.current_assessment.has_uncommitted_changes,
                "staged_files": self.current_assessment.staged_files,
                "unstaged_files": self.current_assessment.unstaged_files,
                "untracked_files": self.current_assessment.untracked_files,
                "modified_files": self.current_assessment.modified_files,
                "error": self.current_assessment.error,
            } if self.current_assessment else None,
            "current_diff": {
                "summary": self.current_diff.summary,
                "files_changed": self.current_diff.files_changed,
                "insertions": self.current_diff.insertions,
                "deletions": self.current_diff.deletions,
            } if self.current_diff else None,
            "history_count": len(self.request_history),
        }


# Keywords that indicate a coding-related request
CODING_KEYWORDS = [
    "check code",
    "check the code",
    "review changes",
    "review the changes",
    "what changed",
    "what's changed",
    "show me the changes",
    "git diff",
    "git status",
    "code changes",
    "file changes",
    "modified files",
    "modified",
    "diff",
    "uncommitted",
    "staged",
    "unstaged",
    "commits",
    "last commit",
    "recent changes",
    "assess",
    "assess repo",
    "assess repository",
    "check repo",
    "check repository",
]


def is_coding_request(transcript: str) -> bool:
    """Check if a transcript is a coding-related request.

    Parameters
    ----------
    transcript : str
        The cleaned transcript text.

    Returns
    -------
    bool
        True if the transcript appears to be a coding request.
    """
    transcript_lower = transcript.lower()
    return any(keyword in transcript_lower for keyword in CODING_KEYWORDS)