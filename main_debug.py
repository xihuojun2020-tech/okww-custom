if __name__ == '__main__':
    from config import config
    from ok import OK
    from src.runtime.account_runtime_bootstrap import initialize_account_runtime

    config = config
    config['debug'] = True
    initialize_account_runtime()
    # config['click_screenshots_folder'] = "click_screenshots"  # debug用 点击后截图文件夹]
    ok = OK(config)
    ok.start()
