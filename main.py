# -*- coding: utf-8 -*-
"""okww 修改版启动入口。

启动前自动同步「定制 ok 框架」（ConfigItemFactory 支持项目级组件：
dropdown_multi_selection / account_sequence），防止 pip 标准版框架缺类型崩溃。
"""
import os
import shutil


def _sync_custom_ok():
    """把 custom_ok 里的定制框架文件同步到 site-packages 的 ok 包（缺才补，每次启动检查）。"""
    try:
        import ok

        base = os.path.dirname(os.path.abspath(__file__))
        custom_dir = os.path.join(base, 'custom_ok', 'ok')
        if not os.path.isdir(custom_dir):
            return
        ok_pkg_dir = os.path.dirname(ok.__file__)
        for dirpath, _dirnames, filenames in os.walk(custom_dir):
            rel = os.path.relpath(dirpath, custom_dir)
            for f in filenames:
                if not f.endswith('.py'):
                    continue
                src = os.path.join(dirpath, f)
                dst = os.path.join(ok_pkg_dir, rel, f)
                try:
                    with open(dst, encoding='utf-8') as fh:
                        existing = fh.read()
                    with open(src, encoding='utf-8') as fh:
                        custom = fh.read()
                    if existing != custom:
                        shutil.copy2(src, dst)
                        print(f'[okww] 已同步定制框架: {rel}\\{f}')
                except FileNotFoundError:
                    os.makedirs(os.path.dirname(dst), exist_ok=True)
                    shutil.copy2(src, dst)
                    print(f'[okww] 已安装定制框架: {rel}\\{f}')
                except Exception:
                    pass
    except Exception:
        pass


if __name__ == '__main__':
    _sync_custom_ok()
    from config import config
    from ok import OK

    config = config
    ok = OK(config)
    ok.start()
