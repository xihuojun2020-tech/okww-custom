# 文档总索引 / Documentation source

同步日期：2026-09-23；现行基线：`1.84.01`。版本以根目录 `config.py` 为准，功能变更见[更新日志](https://github.com/xihuojun2020-tech/okww-custom/blob/v1.84.01/更新日志.md)。本轮不是新程序发布；安装器、NAS 和实际运行版本须分别核实。

## 使用与交接

- [项目首页](https://github.com/xihuojun2020-tech/okww-custom/blob/v1.84.01/README.md) · [多语言入口](index.md)
- [当前项目交接](项目交接与新对话上下文.md) · [程序结构](程序结构说明.md)
- [运行端 AI 操作](https://github.com/xihuojun2020-tech/okww-custom/blob/v1.84.01/运行端AI任务文档.md) · [账号操作与总配置说明](https://github.com/xihuojun2020-tech/okww-custom/blob/v1.84.01/账号总配置运行端AI详细说明.md)
- [其他设备私有仓库更新](其他设备AI私有仓库更新操作文档.md)
- [NAS 诊断部署与读取](NAS诊断部署与读取说明.md)
- [贡献指南](development/contributing.md)

## 现行功能参考

- 账号：[配置/序列设计来源](references/pc-account-configuration-and-sequences.md)、[账号操作与总配置说明](https://github.com/xihuojun2020-tech/okww-custom/blob/v1.84.01/账号总配置运行端AI详细说明.md)、[命名规则](references/account-naming-rules.md)、[待办与界面](references/account-ui-1.56.md)、[账号安全](references/account-profile-security-references.md)
- 日常：[失败恢复与补跑](references/multi-account-retry.md)、[周本](references/weekly-boss-daily.md)、[完成检查](references/completion-evidence.md)、[材料规划](references/material-planner-1.59.md)
- 活动：[任务分类](references/activity-tasks.md)、[若梦仍有回声](若梦仍有回声-第一阶段制作文档.md)、[海墟](references/sea-ruins.md)、[海墟信物](references/sea-ruins-tokens.md)、[群声共振](references/resonance-simulation.md)、[角色试用](references/character-trial-scroll.md)
- 辅助：[剧情跳过](references/story-skip.md)、[单人战斗](references/solo-combat.md)、[战斗恢复](references/auto-combat-recovery.md)、[任务导航](references/task-navigation-reliability.md)
- 界面：[布局与控件](references/flat-ui.md)
- 运维：[诊断上传](references/lan-diagnostics.md)、[诊断验收边界](references/lan-diagnostics-verification.md)、[NAS 更新](references/lan-nas-update-runbook.md)、[发布流水线](references/personal-release-pipeline.md)、[敏感数据](references/sensitive-data-handling.md)

文件名中的旧版本（例如 `account-ui-1.56.md`）保留以兼容原链接，不表示内容只适用于该版本；以正文现行基线为准。支持功能不代表所有设备的完整实机流程已验收。

## 历史资料范围

`reviews/`、`superpowers/plans/`、`superpowers/specs/`、`handover/` 及根目录 `交接/` 保存当时的诊断、设计和执行记录，不统一替换版本、地址或测试结论。日期命名的框架/上游评估、[账号目录迁移评估](account-directory-migration-assessment.md)及[UI 验收记录](references/ui-disclosure-verification.md)也应按历史时点阅读。后续修复以当前更新日志和现行参考文档为准；计划不等于已实现，旧报告不证明新版本仍有同一问题或已完成实机验收。

唯一现行 NAS 是 `\\192.168.3.173\羲火君 共享给我\AI诊断`；历史旧地址不是备用目的地。历史证据不得为了文档同步而改写过去事实或重新标记 ZIP 已审阅。

## 网站来源、预览与检查

`index.md` 为语言入口；`en/`、`zh-CN/`、`zh-TW/`、`ja/` 是四种网站语言；程序 gettext 目录另在根目录 `i18n/`。`development/` 为开发说明，`stylesheets/` 为网站样式。导航由根目录 `mkdocs.yml` 定义。

在仓库根目录使用本地虚拟环境：

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-docs.txt
.\.venv\Scripts\python.exe -m mkdocs serve
.\.venv\Scripts\python.exe -m mkdocs build --strict
```

预览地址为 `http://127.0.0.1:8000/`，构建输出为 `site/`，不要直接编辑生成页。现有 `docs.yml` 在匹配路径的 `master` 推送、PR 或手动触发时构建；非 PR 成功后才执行 Pages 部署。配置中的网站域名/仓库链接继承上游，并非本次确认过的个人分支部署地址；推送文档分支不等于网站已更新。
