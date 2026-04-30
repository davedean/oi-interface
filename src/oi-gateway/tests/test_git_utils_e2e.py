from __future__ import annotations

import subprocess

from coding.git import assess_repository, generate_diff, get_git_status, is_git_repository


def _git(repo, *args):
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)


def test_git_utils_work_against_real_repo(tmp_path):
    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "user.name", "Test User")

    file_path = tmp_path / "hello.txt"
    file_path.write_text("hello\n")
    _git(tmp_path, "add", "hello.txt")
    _git(tmp_path, "commit", "-m", "initial")

    file_path.write_text("hello\nworld\n")
    (tmp_path / "new.txt").write_text("new\n")

    assert is_git_repository(str(tmp_path)) is True
    status = get_git_status(str(tmp_path))
    assert status["unstaged"] == ["hello.txt"]
    assert status["untracked"] == ["new.txt"]

    assessment = assess_repository(str(tmp_path))
    assert assessment.is_git_repo is True
    assert assessment.has_uncommitted_changes is True
    assert "hello.txt" in assessment.modified_files

    diff = generate_diff(str(tmp_path))
    assert "1 file(s) changed: hello.txt" in diff.summary
    assert "diff --git" in diff.full_diff
