import subprocess
import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def temp_workspace():
    """Create a temporary directory tree with various files for fs testing."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir)
        (root / "dir_a").mkdir()
        (root / "dir_b").mkdir()
        (root / "dir_a" / "nested").mkdir()

        (root / "file1.txt").write_text("Hello World\nLine 2\nLine 3\nTargetKeyword here\nLine 5\n")
        (root / "file2.py").write_text("def main():\n    print('TargetKeyword in python')\n")
        (root / ".hidden_file").write_text("hidden secret")
        (root / "dir_a" / "subfile.txt").write_text("TargetKeyword in subfile\n")

        yield root

@pytest.fixture
def temp_git_repo():
    """Create an isolated temporary Git repository with an initial commit."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir)
        subprocess.run(["git", "init", "-b", "main", str(root)], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(root), "config", "user.name", "Sled Test"], check=True)
        subprocess.run(["git", "-C", str(root), "config", "user.email", "test@sled.local"], check=True)

        initial_file = root / "README.md"
        initial_file.write_text("# Test Repo\nInitial content\n")
        subprocess.run(["git", "-C", str(root), "add", "README.md"], check=True)
        subprocess.run(["git", "-C", str(root), "commit", "-m", "Initial commit"], check=True)

        yield root
