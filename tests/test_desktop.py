from types import SimpleNamespace
from backend.desktop import WindowController


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
