from __future__ import annotations

import subprocess
from unittest.mock import patch

from coding.git import (
    assess_repository,
    generate_diff,
    get_current_branch,
    get_diff_stats,
    get_full_diff,
    get_git_status,
    get_modified_files_list,
    get_recent_commits,
    is_git_repository,
    run_git_command,
    run_git_command_async,
)


class DummyCompletedProcess:
    def __init__(self, stdout: str = "", stderr: str = "", returncode: int = 0) -> None:
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


def test_run_git_command_success(tmp_path):
    with patch("coding.git.subprocess.run", return_value=DummyCompletedProcess("ok\n", "", 0)) as mock_run:
        stdout, stderr, returncode = run_git_command(str(tmp_path), "status")
    assert (stdout, stderr, returncode) == ("ok\n", "", 0)
    mock_run.assert_called_once()


def test_run_git_command_timeout(tmp_path):
    with patch("coding.git.subprocess.run", side_effect=subprocess.TimeoutExpired("git", 30)):
        assert run_git_command(str(tmp_path), "status") == ("", "Command timed out", 124)


def test_run_git_command_git_not_installed(tmp_path):
    with patch("coding.git.subprocess.run", side_effect=FileNotFoundError):
        assert run_git_command(str(tmp_path), "status") == ("", "git not installed", 127)


def test_run_git_command_generic_error(tmp_path):
    with patch("coding.git.subprocess.run", side_effect=RuntimeError("boom")):
        assert run_git_command(str(tmp_path), "status") == ("", "boom", 1)


def test_run_git_command_async_delegates(tmp_path):
    with patch("coding.git.run_git_command", return_value=("x", "", 0)) as mock_run:
        assert run_git_command_async(str(tmp_path), "status") == ("x", "", 0)
    mock_run.assert_called_once_with(str(tmp_path), "status")


def test_is_git_repository_true_and_false(tmp_path):
    with patch("coding.git.run_git_command", return_value=("true\n", "", 0)):
        assert is_git_repository(str(tmp_path)) is True
    with patch("coding.git.run_git_command", return_value=("false\n", "", 1)):
        assert is_git_repository(str(tmp_path)) is False


def test_get_current_branch_handles_success_and_failure(tmp_path):
    with patch("coding.git.run_git_command", return_value=("main\n", "", 0)):
        assert get_current_branch(str(tmp_path)) == "main"
    with patch("coding.git.run_git_command", return_value=("", "err", 1)):
        assert get_current_branch(str(tmp_path)) is None


def test_get_git_status_parses_all_sections(tmp_path):
    responses = iter([
        ("a.py\nb.py\n", "", 0),
        ("b.py\nc.py\n", "", 0),
        ("d.py\n", "", 0),
    ])
    with patch("coding.git.run_git_command", side_effect=lambda *args, **kwargs: next(responses)):
        status = get_git_status(str(tmp_path))
    assert status == {
        "staged": ["a.py", "b.py"],
        "unstaged": ["b.py", "c.py"],
        "untracked": ["d.py"],
    }


def test_get_git_status_ignores_failed_commands(tmp_path):
    responses = iter([
        ("", "", 1),
        ("", "", 1),
        ("", "", 1),
    ])
    with patch("coding.git.run_git_command", side_effect=lambda *args, **kwargs: next(responses)):
        status = get_git_status(str(tmp_path))
    assert status == {"staged": [], "unstaged": [], "untracked": []}


def test_get_recent_commits_handles_success_and_empty(tmp_path):
    with patch("coding.git.run_git_command", return_value=("one\ntwo\n", "", 0)):
        assert get_recent_commits(str(tmp_path), 2) == ["one", "two"]
    with patch("coding.git.run_git_command", return_value=("", "", 1)):
        assert get_recent_commits(str(tmp_path)) == []


def test_get_modified_files_list_deduplicates_and_sorts(tmp_path):
    with patch("coding.git.get_git_status", return_value={"staged": ["b.py", "a.py"], "unstaged": ["b.py", "c.py"], "untracked": []}):
        assert get_modified_files_list(str(tmp_path)) == ["a.py", "b.py", "c.py"]


def test_get_full_diff_for_staged_and_error(tmp_path):
    with patch("coding.git.run_git_command", return_value=("diff", "", 0)) as mock_run:
        assert get_full_diff(str(tmp_path), staged=True) == "diff"
    mock_run.assert_called_once_with(str(tmp_path), "diff", "--cached", "--color=never")
    with patch("coding.git.run_git_command", return_value=("", "bad", 1)):
        assert get_full_diff(str(tmp_path)) == "Error getting diff: bad"


def test_get_diff_stats_parses_insertions_and_deletions(tmp_path):
    with patch("coding.git.run_git_command", return_value=(" 2 files changed, 15 insertions(+), 7 deletions(-)\n", "", 0)):
        assert get_diff_stats(str(tmp_path)) == (15, 7)
    with patch("coding.git.run_git_command", return_value=("", "", 1)):
        assert get_diff_stats(str(tmp_path)) == (0, 0)


def test_assess_repository_success(tmp_path):
    with patch("coding.git.is_git_repository", return_value=True), patch("coding.git.get_current_branch", return_value="main"), patch(
        "coding.git.get_git_status",
        return_value={"staged": ["a.py"], "unstaged": ["b.py"], "untracked": ["c.py"]},
    ), patch("coding.git.get_recent_commits", return_value=["c1", "c2"]), patch(
        "coding.git.get_modified_files_list", return_value=["a.py", "b.py"]
    ):
        result = assess_repository(str(tmp_path))
    assert result.is_git_repo is True
    assert result.branch == "main"
    assert result.has_uncommitted_changes is True
    assert result.staged_files == ["a.py"]
    assert result.unstaged_files == ["b.py"]
    assert result.untracked_files == ["c.py"]
    assert result.recent_commits == ["c1", "c2"]
    assert result.modified_files == ["a.py", "b.py"]


def test_generate_diff_variants(tmp_path):
    clean_assessment = assess_repository.__annotations__  # just to keep import used
    assert clean_assessment is not None
    with patch(
        "coding.git.assess_repository",
        return_value=type("A", (), {"is_git_repo": True, "modified_files": []})(),
    ), patch("coding.git.get_full_diff", return_value=""), patch("coding.git.get_diff_stats", return_value=(0, 0)):
        result = generate_diff(str(tmp_path))
    assert result.summary == "No changes in repository"
    assert result.full_diff == "No changes"

    with patch(
        "coding.git.assess_repository",
        return_value=type("A", (), {"is_git_repo": True, "modified_files": ["a.py", "b.py", "c.py", "d.py"]})(),
    ), patch("coding.git.get_full_diff", return_value="patch"), patch("coding.git.get_diff_stats", return_value=(3, 2)):
        result = generate_diff(str(tmp_path))
    assert result.summary == "4 file(s) changed: a.py, b.py, c.py (+1 more) (3 insertions, 2 deletions)"
    assert result.files_changed == ["a.py", "b.py", "c.py", "d.py"]
    assert result.full_diff == "patch"
