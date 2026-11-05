from sled.main import render_store_interactive
from sled.ui import ui


def test_ui_is_pure_prism():
    assert hasattr(ui, "multiselect")
    assert hasattr(ui, "select")
    assert hasattr(ui, "panel")
    assert hasattr(ui, "badge")


def test_render_store_interactive_non_tty(monkeypatch):
    # Non-TTY stdin in test environment falls back cleanly without hanging
    ret = render_store_interactive()
    assert ret == 0


def test_render_tools_panel():
    from sled.main import render_tools_panel
    assert render_tools_panel() == 0
    assert render_tools_panel(include_disabled=True) == 0
    assert render_tools_panel(as_json=True) == 0

