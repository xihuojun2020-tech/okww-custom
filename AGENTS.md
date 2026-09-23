# Agent Instructions

## 模型分工与执行要求

- 任务确实需要分工时可直接调用自定义 Agent，无需每次再次确认；小任务由当前模型完成，不强制执行多阶段代理流程。
- executor / gpt-6-luna 负责目标和方案明确的执行；implementer / gpt-6-sol 负责普通判断与实施；strategist / gpt-6-astra 只用于尚未解决的复杂根因和重大方案取舍。
- 独立工作按需并行，有依赖的工作顺序执行。交接仅包含目标、证据、必要上下文、约束和验收条件。各模型自行完成职责内的常规选择，决策后继续实施。
- 已授权工作持续推进至完成；可读取、检查或查询的信息先自行调查，非关键细节采用合理默认值。只有决定结果的缺失信息、新增费用或超范围不可逆操作才提问。
- 不为简单工作增加预审、备用方案或多轮交叉复核，不默认让 Astra 审查全部输出。只执行与改动直接相关且足够的验证，无新证据不重复检查。
- 失败先合理排查修复；整体方案受阻才升级，并明确需要决策的事项，不重复调查已确认事实。
- 先报告完成结果，再说明验证与剩余问题，区分事实、推断和建议。分工时说明实际模型及职责；指定模型不可用须明确说明，不用角色名称冒充模型切换。
- 涉及中转系统、可能中断 GPT 使用的重启、切换和部署安排在北京时间 01:00—06:00；05:00 后不开始新部署或负载测试，05:30 前收尾。白天继续调查、准备和不影响使用的工作。

## Python

- When running Python commands in this repository, use the local virtual environment if it exists.
- On Windows/PowerShell, prefer `.\.venv\Scripts\python.exe` when present.
- On POSIX shells, prefer `./.venv/bin/python` when present.
- Fall back to `python` only when no local `.venv` interpreter exists.
- Prefer invoking the interpreter directly, for example `.\.venv\Scripts\python.exe -m pytest`, instead of relying on shell activation.

## NAS

- Use only `\\192.168.3.173\羲火君 共享给我\AI诊断` for this project's NAS diagnostics, reading, handoffs and update publishing.
- `.172`, `.161` and `.170` are legacy addresses, not fallback destinations. Retain them only for migrating old configuration and reading saved credential aliases.
- Historical reports may contain old addresses; they are not current operating instructions.
- After actually reviewing a diagnostic ZIP, write a substantive Markdown report (scope, findings, evidence, fixes and verification limits), then run `.\.venv\Scripts\python.exe -m src.runtime.diagnostic_archive_retention --review <ZIP filename> --report <report path> --sha256 <verified ZIP SHA256>`. This stores the report and marks/moves only that reviewed package. Merely opening or listing evidence is not review completion. Reports remain; reviewed evidence expires after 3 days, unreviewed packages after 30 days from verified upload.

## Versioning and GitHub publishing

- Every change that modifies code must update the version in `config.py` in the same release.
- Version text uses fixed-width `X.YY.ZZ` (for example `1.04.02`).
- Small fixes increment the third component.
- Medium changes increment the second component and reset the third component to `00`.
- Major changes increment the first component and reset both later components to `00`; do this only when the user explicitly requests a major version change.
- Keep product-facing version text and release notes synchronized with `config.py`.
- After a verified version change, commit it, create the matching annotated `vX.YY.ZZ` tag, and push both the branch and tag to GitHub unless the user explicitly asks to keep the change local.

## Account-switch testing

- `TestAccountSwitchTask` is the focused test entry point for `MultiAccountDailyTask`; it must reuse the production account-selection, alias-matching, verification, retry, logout, and login methods instead of maintaining a separate switching implementation.
- Keep account-switch tests synchronized whenever the production multi-account switching path changes.
- The default continuous switching test order is A1, A3, A4. Resolve these as exact profile short names and cover both configured alternate login names and masked-phone identities.
