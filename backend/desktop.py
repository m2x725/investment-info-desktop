"""Native window lifecycle. No API bridge or external page privileges are exposed."""
import threading
import secrets
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode
from contextlib import contextmanager

APP_VERSION = '0.1.5'


def fresh_window_url(url):
    """A new navigation key prevents a persistent WebView from reusing old HTML."""
    parts = urlsplit(url)
    query = [(key, value) for key, value in parse_qsl(parts.query)
             if key not in ('app_version', 'launch')]
    query.extend([('app_version', APP_VERSION), ('launch', secrets.token_hex(12))])
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


@contextmanager
def instance_guard(windows=False):
    """Keep an installer-visible mutex until the backend has fully stopped."""
    if not windows:
        yield
        return
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    kernel.CreateMutexW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.CreateMutexW(None, False, "Local\\RetirementWealthDesktop")
    error = ctypes.get_last_error()
    if not handle:
        raise RuntimeError("无法建立软件运行锁。")
    try:
        if error == 183:
            raise RuntimeError("投资信息台已在运行，请从托盘打开。")
        yield
    finally:
        kernel.CloseHandle(handle)



class WindowController:
    def __init__(self, window, server):
        self.window = window
        self.server = server
        self.tray = None
        self.quitting = threading.Event()

    def closing(self):
        # Only hide after a tray was successfully created; otherwise allow exit.
        if self.tray is not None and not self.quitting.is_set():
            self.window.hide()
            return False
        self.server.should_exit = True
        return True

    def show(self, *_):
        self.window.show()
        self.window.restore()

    def quit(self, *_):
        if self.quitting.is_set():
            return
        self.quitting.set()
        self.server.should_exit = True
        if self.tray is not None:
            self.tray.stop()
        self.window.destroy()


def start_window(server, app, url, storage_path, windows=False):
    import webview
    webview.settings['ALLOW_DOWNLOADS'] = True
    webview.settings['OPEN_EXTERNAL_LINKS_IN_BROWSER'] = True
    window = webview.create_window(f'投资信息台 · v{APP_VERSION}', fresh_window_url(url), width=1180, height=820,
                                  min_size=(760, 560), text_select=True, zoomable=True,
                                  background_color='#f5f5f7')
    controller = WindowController(window, server)
    window.events.closing += controller.closing

    def on_started():
        if windows:
            import pystray
            from PIL import Image, ImageDraw
            image = Image.new('RGB', (64, 64), '#ecefe6')
            ImageDraw.Draw(image).ellipse((14, 10, 50, 54), fill='#2e6245')

            def pause(icon, item):
                paused = bool(app.state.store.settings().get('scheduler_paused'))
                app.state.store.save_settings({'scheduler_paused': not paused})
                icon.update_menu()

            tray = pystray.Icon('RetirementWealth', image, '投资信息台', pystray.Menu(
                pystray.MenuItem('打开投资信息台', controller.show, default=True),
                pystray.MenuItem('暂停后台新任务', pause,
                    checked=lambda item: bool(app.state.store.settings().get('scheduler_paused'))),
                pystray.MenuItem('完全退出（停止后台更新）', controller.quit)))
            # pystray's Windows backend supports a detached event loop.
            try:
                tray.run_detached()
                controller.tray = tray
            except Exception:
                # Keep the window usable and let its close button stop the backend.
                tray.stop()
                window.title = f'投资信息台 · v{APP_VERSION}（托盘不可用，关闭即退出）'

        # A failed backend must not leave a working-looking window in the tray.
        def monitor():
            while not controller.quitting.wait(.5):
                if not server.started or server.should_exit:
                    controller.quit()
                    return
        threading.Thread(target=monitor, daemon=True).start()

    try:
        webview.start(on_started, gui='edgechromium' if windows else None,
                      private_mode=False, storage_path=str(storage_path), debug=False)
    finally:
        server.should_exit = True
        if controller.tray is not None:
            controller.tray.stop()
