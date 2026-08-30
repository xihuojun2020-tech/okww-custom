import os
import threading
import webbrowser


HOST = "127.0.0.1"
PORT = 8000


def open_browser():
    webbrowser.open(f"http://{HOST}:{PORT}")


if __name__ == "__main__":
    try:
        import uvicorn
    except ImportError as exc:
        raise SystemExit(
            "The web UI requires FastAPI and Uvicorn. "
            "Install them with: pip install 'ok-script[web]'"
        ) from exc

    from config import config
    from ok.ui.web import create_web_app
    from src.runtime.account_runtime_bootstrap import initialize_account_runtime

    web_config = dict(config)
    # 生产默认关闭 debug（避免暴露堆栈/接口文档）；需要调试时用环境变量开启
    web_config["debug"] = os.environ.get("OKWW_WEB_DEBUG", "").lower() in ("1", "true", "yes")
    web_config["use_gui"] = False
    initialize_account_runtime()

    browser_timer = threading.Timer(1.0, open_browser)
    browser_timer.daemon = True
    browser_timer.start()

    uvicorn.run(create_web_app(web_config), host=HOST, port=PORT)
