# Documentation source

This directory is the source for the ok-ww documentation website.

## Layout

- `index.md` is the language selector and site landing page.
- `en/`, `zh-CN/`, `zh-TW/`, and `ja/` contain localized user documentation.
- `development/` contains contributor documentation shared by all languages.
- `stylesheets/` contains website-only presentation styles.

Navigation and theme settings live in `mkdocs.yml` at the repository root.

## Architecture and code review

- [框架升级说明与验收方案](references/framework-upgrade-assessment-2026-09-11.md)

- [原版更新检查与融合方案（2026-09-11）](references/upstream-integration-assessment-2026-09-11.md)
- [账号提醒、任务入口与录像设置（1.56.00）](references/account-ui-1.56.md)
- [项目交接与发布状态（1.60.00）](项目交接与新对话上下文.md)
- [角色试用方案与实施记录（1.55.00）](superpowers/plans/2026-09-10-character-trial.md)

- [局域网自动日志与错误截图（1.54.00）](references/lan-diagnostics.md)
- [另一台电脑 AI：更新、配置与验收](superpowers/specs/2026-09-10-remote-ai-diagnostic-requirements.md)
- [完成检查与每日截图（1.58.00）](references/completion-evidence.md)
- [完成检查模块设计](superpowers/specs/2026-09-10-completion-evidence-design.md)
- [程序结构说明（1.60.00）](程序结构说明.md)
- [任务分类与活动辅助（1.56.00）](references/activity-tasks.md)
- [多账号失败恢复与队尾补跑（1.51.00）](references/multi-account-retry.md)
- [账号命名与配置规则（1.50.06）](references/account-naming-rules.md)
- [自动战斗手动重启保护（1.48.00）](references/auto-combat-recovery.md)
- [功能分类、统一 Fluent 控件与账号显示（1.50.06）](references/flat-ui.md)
- [UI 验收记录](references/ui-disclosure-verification.md)
- [全面代码审查报告（2026-09-06）](reviews/2026-09-06全面代码审查.md)
- [审查整改实施计划（2026-09-06）](superpowers/plans/2026-09-06-review-remediation-plan.md)

## Preview locally

From the repository root:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-docs.txt
.\.venv\Scripts\python.exe -m mkdocs serve
```

Open `http://127.0.0.1:8000/` in a browser. Changes are rebuilt automatically.

## Build static HTML

```powershell
.\.venv\Scripts\python.exe -m mkdocs build --strict
```

The generated website is written to `site/`. Do not edit that directory; edit the Markdown sources in `docs/` instead.

Pushes to `master` publish the site through the `docs.yml` GitHub Actions workflow after a successful strict build.

- [养成材料规划与手动验收（1.59.00）](references/material-planner-1.59.md)
- [材料规划发布与离线验收记录](reviews/2026-09-12-material-planner-acceptance.md)
