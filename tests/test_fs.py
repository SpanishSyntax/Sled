from pathlib import Path

from sled.tools.fs import cat, find, grep, head, ls, stat, tail, tree


def test_ls_compact_default(temp_workspace: Path):
    res = ls(str(temp_workspace))
    assert res["status"] == "ok"
    assert "entries" in res
    assert isinstance(res["entries"], list)
    # Check compact flat strings format
    assert all(isinstance(entry, str) for entry in res["entries"])
    assert "dir_a/" in res["entries"]
    assert "file1.txt" in res["entries"]
    assert ".hidden_file" not in res["entries"]

def test_ls_all_files(temp_workspace: Path):
    res = ls(str(temp_workspace), all_files=True)
    assert res["status"] == "ok"
    assert ".hidden_file" in res["entries"]

def test_ls_long_detailed(temp_workspace: Path):
    res = ls(str(temp_workspace), long=True)
    assert res["status"] == "ok"
    assert all(isinstance(entry, dict) for entry in res["entries"])
    names = [e["name"] for e in res["entries"]]
    assert "file1.txt" in names
    sample = next(e for e in res["entries"] if e["name"] == "file1.txt")
    assert "size_bytes" in sample
    assert "mode" in sample

def test_cat_slicing(temp_workspace: Path):
    target = temp_workspace / "file1.txt"
    res = cat(str(target), start_line=2, end_line=4)
    assert res["status"] == "ok"
    assert res["total_lines"] == 5
    assert res["start_line"] == 2
    assert res["end_line"] == 4
    lines = res["content"].splitlines()
    assert len(lines) == 3
    assert lines[0] == "Line 2"
    assert lines[1] == "Line 3"
    assert lines[2] == "TargetKeyword here"

def test_head_and_tail(temp_workspace: Path):
    target = temp_workspace / "file1.txt"
    h_res = head(str(target), lines=2)
    assert h_res["status"] == "ok"
    assert len(h_res["content"].splitlines()) == 2
    assert h_res["content"].splitlines()[0] == "Hello World"

    t_res = tail(str(target), lines=2)
    assert t_res["status"] == "ok"
    assert len(t_res["content"].splitlines()) == 2
    assert t_res["content"].splitlines()[-1] == "Line 5"

def test_grep_compact(temp_workspace: Path):
    res = grep(pattern="TargetKeyword", path=str(temp_workspace))
    assert res["status"] == "ok"
    assert res["count"] == 3
    # Compact format returns path:line: text strings
    assert all(isinstance(m, str) for m in res["matches"])
    assert any("file1.txt:4:" in m for m in res["matches"])
    assert any("file2.py:2:" in m for m in res["matches"])

def test_grep_detailed(temp_workspace: Path):
    res = grep(pattern="TargetKeyword", path=str(temp_workspace), compact=False)
    assert res["status"] == "ok"
    assert res["count"] == 3
    assert all(isinstance(m, dict) for m in res["matches"])
    sample = res["matches"][0]
    assert "file" in sample
    assert "line" in sample
    assert "text" in sample

def test_find_glob(temp_workspace: Path):
    res = find(pattern="*.py", path=str(temp_workspace))
    assert res["status"] == "ok"
    assert res["count"] == 1
    assert "file2.py" in res["matches"][0]

def test_tree_hierarchy(temp_workspace: Path):
    res = tree(path=str(temp_workspace), max_depth=2)
    assert res["status"] == "ok"
    assert "tree" in res
    assert "dir_a/" in res["tree"]
    assert "dir_a/nested/" in res["tree"] or "dir_a/subfile.txt" in res["tree"]

def test_stat_file(temp_workspace: Path):
    target = temp_workspace / "file1.txt"
    res = stat(str(target))
    assert res["status"] == "ok"
    assert res["type"] == "file"
    assert res["size_bytes"] > 0
