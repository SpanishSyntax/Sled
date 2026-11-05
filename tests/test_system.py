from sled.tools.system import df, free, ps, uname, uptime, which


def test_uname():
    res = uname()
    assert res["status"] == "ok"
    assert "system" in res
    assert "machine" in res
    assert "python_version" in res

def test_uptime():
    res = uptime()
    assert res["status"] == "ok"
    assert "uptime_seconds" in res
    assert "load_average" in res

def test_ps_compact_tabular():
    res = ps(limit=5)
    assert res["status"] == "ok"
    assert "columns" in res
    assert "rows" in res
    assert "processes" not in res
    assert res["columns"] == ["pid", "user", "cpu%", "mem%", "rss_kb", "command"]
    assert len(res["rows"]) <= 5
    if res["rows"]:
        assert len(res["rows"][0]) == 6

def test_ps_detailed():
    res = ps(limit=3, compact=False)
    assert res["status"] == "ok"
    assert "processes" in res
    assert "columns" not in res
    assert len(res["processes"]) <= 3
    if res["processes"]:
        p = res["processes"][0]
        assert "pid" in p
        assert "command" in p

def test_df_compact_tabular():
    res = df()
    assert res["status"] == "ok"
    assert "columns" in res
    assert "rows" in res
    assert "filesystems" not in res
    assert "filesystem" in res["columns"]
    assert "mount" in res["columns"]

def test_free_memory():
    res = free()
    assert res["status"] == "ok"
    assert "memory" in res
    assert "MemTotal" in res["memory"]

def test_which_known_bins():
    res = which(binaries="git,python3")
    assert res["status"] == "ok"
    assert "results" in res
    assert res["results"]["git"]["available"] is True
    assert res["results"]["python3"]["available"] is True
