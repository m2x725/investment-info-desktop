"""Local launcher. Windows release stays in the notification area until explicitly exited."""
import os
import sys
import threading
import time
from pathlib import Path
import uvicorn
from backend.main import create_app

URL = "http://127.0.0.1:8765"


def launch(headless=False, port=8765):
    from backend.desktop import instance_guard
    with instance_guard(windows=sys.platform == "win32" and not headless):
        _launch(headless=headless, port=port)


def _launch(headless=False, port=8765):
    if sys.platform != "win32" and not os.getenv("WEALTH_DATA_DIR"):
        os.environ["WEALTH_DATA_DIR"] = str(Path(__file__).resolve().parent / "data")
    # Check before opening a database or starting scheduled jobs.
    import socket
    with socket.socket() as probe:
        try:
            probe.bind(("127.0.0.1", port))
        except OSError as exc:
            raise RuntimeError("软件已在运行或端口被占用，请先退出已有版本。") from exc
    if not headless:
        try:
            import webview
        except ImportError as exc:
            raise RuntimeError("桌面窗口组件未安装，请运行桌面环境配置脚本。") from exc
    app = create_app()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning",
                                           access_log=False, log_config=None))
    if headless:
        server.run()
        return
    from backend.desktop import start_window
    from backend.storage import default_data_dir
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        for _ in range(300):
            if server.started:
                break
            if not thread.is_alive():
                raise RuntimeError("后台启动失败。")
            time.sleep(.1)
        else:
            raise RuntimeError("后台启动超时。")
        profile = default_data_dir() / "desktop-profile"
        profile.mkdir(parents=True, exist_ok=True)
        start_window(server, app, f"http://127.0.0.1:{port}", profile,
                     windows=sys.platform == "win32")
    finally:
        server.should_exit = True
        thread.join(timeout=20)


if __name__ == "__main__":
    try:
        if '--restore-backup' in sys.argv:
            import argparse,json
            from backend.restore import restore
            from backend.storage import default_data_dir
            parser=argparse.ArgumentParser()
            parser.add_argument('--restore-backup',required=True)
            parser.add_argument('--data-dir',default=str(default_data_dir()))
            args=parser.parse_args()
            result=restore(args.restore_backup,args.data_dir)
            if sys.platform=='win32':
                import ctypes
                ctypes.windll.user32.MessageBoxW(0,'备份已恢复，旧数据库已另存。请重新打开软件。','投资信息台',64)
            else:print(json.dumps(result,ensure_ascii=False))
        else:
            import argparse
            parser = argparse.ArgumentParser()
            parser.add_argument('--headless', action='store_true', help='开发用：仅运行后台')
            parser.add_argument('--port', type=int, default=8765)
            args = parser.parse_args()
            launch(headless=args.headless, port=args.port)
    except KeyboardInterrupt:
        pass
    except Exception as exc:
        if sys.platform == "win32":
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, "启动失败：" + str(exc) + "\n若提示渲染组件缺失，请安装 Microsoft Edge WebView2 Runtime。", "投资信息台", 16)
        else:
            raise
