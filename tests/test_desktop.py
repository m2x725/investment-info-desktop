from types import SimpleNamespace
from backend.desktop import WindowController


def test_window_navigation_is_fresh_and_preserves_url():
    from backend.desktop import fresh_window_url, APP_VERSION
    from urllib.parse import urlsplit, parse_qs
    original = 'http://127.0.0.1:8765/?mode=research&app_version=old&launch=old#report'
    first, second = fresh_window_url(original), fresh_window_url(original)
    parts = urlsplit(first)
    query = parse_qs(parts.query)
    assert parts.netloc == '127.0.0.1:8765' and parts.fragment == 'report'
    assert query['mode'] == ['research']
    assert query['app_version'] == [APP_VERSION]
    assert len(query['launch']) == 1 and query['launch'][0] != 'old'
    assert query['launch'] != parse_qs(urlsplit(second).query)['launch']


class Window:
    def __init__(self): self.calls = []
    def hide(self): self.calls.append('hide')
    def show(self): self.calls.append('show')
    def restore(self): self.calls.append('restore')
    def destroy(self): self.calls.append('destroy')


def test_close_to_tray_keeps_backend_running():
    w, server = Window(), SimpleNamespace(should_exit=False)
    c = WindowController(w, server)
    c.tray = SimpleNamespace(stop=lambda: w.calls.append('stop-tray'))
    assert c.closing() is False
    assert not server.should_exit
    c.show()
    assert w.calls == ['hide', 'show', 'restore']
    c.quit()
    c.quit()
    assert server.should_exit
    assert w.calls.count('destroy') == 1
    assert c.closing() is True


def test_without_tray_close_stops_backend():
    w, server = Window(), SimpleNamespace(should_exit=False)
    c = WindowController(w, server)
    assert c.closing() is True
    assert server.should_exit
    assert 'hide' not in w.calls


def test_occupied_port_does_not_create_app(monkeypatch):
    import socket
    import run
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        port = listener.getsockname()[1]
        listener.listen()
        monkeypatch.setattr(run, 'create_app', lambda: (_ for _ in ()).throw(AssertionError('database opened')))
        import pytest
        with pytest.raises(RuntimeError, match='端口'):
            run.launch(port=port)
