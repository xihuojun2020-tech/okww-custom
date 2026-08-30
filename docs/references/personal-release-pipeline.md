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

## PyAppify 无标签候选限制

PyAppify 1.2.3 离线 setup 的安装阶段会克隆仓库并检出最新正式标签。候选提交只有 artifact、尚未创建匹配正式标签时，安装器可能安装上一个正式版本，而不是候选提交。候选验收必须核对安装后 `config.py`、窗口标题和实际 Git 提交；不得为绕过该限制提前创建、移动或临时重写正式标签。

当前候选的安全做法是：保留安装器生成的旧版本 working 基线，在隔离槽中显式检出候选 commit，再用隔离 Python 启动；1.20.02 已完成 A3/A4 两轮实机门禁，正式标签仍须等待匹配提交的 GitHub 候选构件下载、哈希校验和隔离复验。

1.20.02 实机门禁记录：2026-08-31 01:31:25 至 01:41:34，在隔离槽执行 A3→A4 完整序列 2 轮；只验证生产账号切换链路，不执行每日任务、不写完成进度。实测后按候选前清单复核打包版 326 项账号配置，缺失、变化、额外均为 0。日志引用必须脱敏，运行证据目录不计入账号配置清单。

## 参考

- GitHub Docs, “Publishing packages”：https://docs.github.com/actions/publishing-packages
- GitHub Docs, “Managing releases in a repository”：https://docs.github.com/repositories/releasing-projects-on-github/managing-releases-in-a-repository
- GitHub Docs, “Storing workflow data as artifacts”：https://docs.github.com/actions/using-workflows/storing-workflow-data-as-artifacts
- GitHub Docs, “Using jobs in a workflow”：https://docs.github.com/actions/using-jobs/using-jobs-in-a-workflow
- PyAppify 1.2.3 候选安装行为：本项目候选流水线 `33320437066` 与隔离安装记录（2026-08-31）。

访问日期：2026-08-31。
