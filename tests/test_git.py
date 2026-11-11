from pathlib import Path

from sled.tools.git import git_branch, git_diff, git_log, git_stash, git_status


def test_git_status_clean(temp_git_repo: Path):
    res = git_status(repo_path=str(temp_git_repo))
    assert res["status"] == "ok"
    assert res["clean"] is True
    assert res["branch"] == "main"
    assert "head_commit" in res
    # Verify pruned empty collections in clean state
    assert "staged" not in res
    assert "unstaged" not in res
    assert "untracked" not in res


def test_git_status_dirty(temp_git_repo: Path):
    new_file = temp_git_repo / "dirty.txt"
    new_file.write_text("untracked content\n")

    res = git_status(repo_path=str(temp_git_repo))
    assert res["status"] == "ok"
    assert res["clean"] is False
    assert "untracked" in res
    assert "dirty.txt" in res["untracked"]
    assert "staged" not in res


def test_git_diff_clean(temp_git_repo: Path):
    res = git_diff(repo_path=str(temp_git_repo))
    assert res["status"] == "ok"
    assert res["diff"] == ""
    assert "stat" not in res


def test_git_diff_with_changes(temp_git_repo: Path):
    readme = temp_git_repo / "README.md"
    readme.write_text("# Test Repo\nModified line\n")

    res = git_diff(repo_path=str(temp_git_repo))
    assert res["status"] == "ok"
    assert "-Initial content" in res["diff"]
    assert "+Modified line" in res["diff"]


def test_git_log(temp_git_repo: Path):
    res = git_log(repo_path=str(temp_git_repo), limit=5)
    assert res["status"] == "ok"
    assert res["count"] == 1
    commit = res["commits"][0]
    assert commit["subject"] == "Initial commit"
    assert "commit" in commit
    assert "author" in commit


def test_git_branch(temp_git_repo: Path):
    res = git_branch(repo_path=str(temp_git_repo))
    assert res["status"] == "ok"
    assert res["current_branch"] == "main"
    assert any(b["name"] == "main" for b in res["branches"])


def test_git_stash_lifecycle(temp_git_repo: Path):
    # Make a modification
    readme = temp_git_repo / "README.md"
    readme.write_text("# Test Repo\nStashed content\n")

    # Stash push via unified dispatcher
    push_res = git_stash(
        action="push", message="stash test", repo_path=str(temp_git_repo)
    )
    assert push_res["status"] == "ok"

    # Status should now be clean
    status_res = git_status(repo_path=str(temp_git_repo))
    assert status_res["clean"] is True

    # Stash list
    list_res = git_stash(action="list", repo_path=str(temp_git_repo))
    assert list_res["status"] == "ok"
    assert list_res["count"] >= 1

    # Stash pop
    pop_res = git_stash(action="pop", repo_path=str(temp_git_repo))
    assert pop_res["status"] == "ok"

    # Modification should be restored
    assert "Stashed content" in readme.read_text()
