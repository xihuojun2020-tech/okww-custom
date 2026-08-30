# 个人仓库发布流水线

## 触发规则

- 普通 `master` 推送、拉取请求和手动运行只执行版本校验与全部测试。
- 只有与 `config.py` 完全一致的 `vX.YY.ZZ` 标签才会打包并创建 GitHub Release。
- 正式标签必须等待本地候选包与 A3/A4 实机验收完成后再创建。

## 发布阶段

1. `validate-version`：校验 `config.py`、About、更新日志和可选标签。
2. `tests`：通过 `run_tests.ps1 -Group all` 逐文件隔离运行。
3. `package`：使用固定提交版本的公开 PyAppify Action 生成未签名安装包。
4. `package-smoke`：确认发布文件存在，并检查 ZIP 中不含本机运行配置。
5. `checksums`：生成 `SHA256SUMS.txt`。
6. `github-release`：只向当前 GitHub 仓库发布已验证构件。

流水线不再访问原作者同步仓库、SignPath 组织或 MirrorChyan，也不需要这些服务的密钥。PyAppify Action 固定到明确提交，后续升级必须先在分支上完成打包烟测。

## 本地校验

~~~powershell
.\.venv\Scripts\python.exe .\scripts\validate_release.py
.\.venv\Scripts\python.exe -m unittest tests.TestReleaseReadiness -v
powershell -ExecutionPolicy Bypass -File .\run_tests.ps1 -Group all
~~~

候选包生成后：

~~~powershell
.\.venv\Scripts\python.exe .\scripts\package_smoke.py --dist .\pyappify_dist
~~~

## 参考

- GitHub Docs, “Publishing packages”：https://docs.github.com/actions/publishing-packages
- GitHub Docs, “Managing releases in a repository”：https://docs.github.com/repositories/releasing-projects-on-github/managing-releases-in-a-repository
- GitHub Docs, “Storing workflow data as artifacts”：https://docs.github.com/actions/using-workflows/storing-workflow-data-as-artifacts
- GitHub Docs, “Using jobs in a workflow”：https://docs.github.com/actions/using-jobs/using-jobs-in-a-workflow

访问日期：2026-08-30。
