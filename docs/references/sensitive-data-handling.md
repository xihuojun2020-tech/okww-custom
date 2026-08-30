# 敏感账号标识处理参考

日期：2026-08-30
适用版本：1.20.00 起

## 数据分类

- 带星号手机号：账号切换的首要匹配依据。
- U…A 备用登录名：手机号不可见时的备用匹配依据。
- 游戏内特征码：游戏内唯一身份，当前只保存，不参与自动切换。
- 昵称和 short name：只用于用户识别和任务选择，不能代替唯一身份。

## 代码与测试规则

1. 生产代码不得包含账号专属身份回退常量。
2. 测试只使用 tests/fixture_support.py 中的虚构身份或同一命名规则。
3. 文档示例使用 1991… 测试手机号、199**** 测试掩码和 UTEST…A 备用名。
4. 扫描失败只报告文件和规则，不显示命中原文。
5. 日志、异常、诊断和 CI 输出在写出前统一脱敏。

## Git 历史

删除当前文件中的标识不能清除旧提交。公开历史清理必须在维护窗口内完成：先私有化和离线备份，再使用 git-filter-repo 重写，扫描全部引用后强制更新远端。该操作需要独立二次确认。

## 参考资料

- Python logging Filter：
  https://docs.python.org/3/library/logging.html#filter-objects
- git-filter-repo：
  https://github.com/newren/git-filter-repo
- GitHub 删除敏感数据：
  https://docs.github.com/authentication/keeping-your-account-and-data-secure/removing-sensitive-data-from-a-repository

访问日期：2026-08-30。
