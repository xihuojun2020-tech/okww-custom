# OK-WW 1.20.00 安全、可靠性与易用性综合修复实施计划

> 对应用户已批准的“方案一：安全优先综合修复”。逐任务执行：先写失败测试，再做最小修改，再运行回归，再形成独立提交。Git 历史重写必须另行二次确认。

**目标：** 在不污染账号配置、不丢失当前 MuMu/Android 工作的前提下，完成隐私清理、账号快照原子发布、统一启动门禁、全局脱敏、五页 UI 修复、CI/发布修复、多账号结构优化和 A3/A4 打包版验收。

**设计规格：** docs/superpowers/specs/2026-08-30-security-reliability-ui-remediation-design.md

**技术栈：** Python 3.12、unittest、PySide6、ok-script、PowerShell、GitHub Actions、pyappify、Windows ACL/DPAPI、Android Java 工具链。

**版本：** 1.19.12 → 1.20.00。

## 全局约束

- 所有 Python 命令使用 E:\AI work\ok-wuthering-waves-master\.venv\Scripts\python.exe。
- 未完成全量验证前不创建正式 v1.20.00 标签。
- 正式标签使用 annotated tag；验证后推送分支和标签。
- 手机号、带星号手机号、U…A 备用名和游戏特征码不得原文出现在输出、测试报告、文档和提交信息。
- TestAccountSwitchTask 必须复用生产账号选择、别名匹配、验证、重试、登出和登录服务。
- 默认连续切换测试顺序保持 A1、A3、A4。
- 不使用 git reset --hard、git checkout -- 或无备份的强制历史操作。
- 未经逐文件审查，不纳入或回滚现有用户工作：
  - src/android/nemu.py
  - src/android/preflight.py
  - android/agent-app/
  - 三份 Android phase 计划
  - Android complete production spec
- 每次提交前运行 git diff --cached --name-only，确认没有意外路径。
- 所有账号、备份、事务和诊断操作先做只读检查。

## 依赖顺序

~~~text
基线保护
 -> 当前树隐私清理
 -> 崩溃安全发布
 -> 统一启动门禁
 -> 全局脱敏与安全存储
 -> UI / 测试 / CI
 -> 多账号结构优化
 -> 质量与 Android 边界
 -> 全量回归
 -> 本地候选包和 A3/A4
 -> 第二次确认
 -> Git 历史重写、标签、推送和发布
~~~

---

## Task 0：锁定基线并保护现有工作

**文件：** 只读检查 Git、config.py 和现有 Android 路径。

- [ ] 记录 git status --short、HEAD、origin/master、远端、标签和 config.version。
- [ ] 对已跟踪 Android 修改记录 diff 摘要；对未跟踪目录记录文件清单和 SHA-256，不记录正文。
- [ ] 检查 .gitignore 是否覆盖 Android build、debug keystore、APK、idsig、class 和 dex。
- [ ] 记录 v1.19.12 Actions 失败链接和仓库可见性。
- [ ] 不清理、不 stash、不提交用户文件。

验证命令：

~~~powershell
git status --short
git rev-parse HEAD
git rev-parse origin/master
git remote -v
git tag --list
& .\.venv\Scripts\python.exe -c "import config; print(config.version)"
~~~

---

## Task 1：建立 1.20.00 发布一致性基线

**文件：**

- Modify: config.py
- Modify: custom_ok/ok/gui/about/AboutTab.py
- Modify: 更新日志.md
- Modify: tests/TestReleaseReadiness.py
- Modify: tests/TestCodexLightUI.py

- [ ] TestReleaseReadiness 从 config.py 读取唯一版本，检查固定格式 X.YY.ZZ、About 和更新日志一致。
- [ ] TestCodexLightUI 删除 1.19.02 硬编码，改读 config.version。
- [ ] 先运行两个测试，锁定当前失败。
- [ ] config.py 更新为 1.20.00；About 和更新日志增加“验证中”段，不提前宣称发布。
- [ ] 重跑测试并提交。

~~~powershell
& .\.venv\Scripts\python.exe -m unittest tests.TestReleaseReadiness tests.TestCodexLightUI -v
git add -- config.py custom_ok/ok/gui/about/AboutTab.py tests/TestReleaseReadiness.py tests/TestCodexLightUI.py 更新日志.md
git diff --cached --name-only
git commit -m "chore: start 1.20.00 remediation release"
~~~

---

## Task 2：清理当前树中的真实账号标识

**文件：**

- Modify: tests/fixture_support.py
- Modify: tests/TestMuMuDiscovery.py
- Modify: tests/TestMultiAccountDailyTask.py
- Modify: tests/TestAccountSwitch.py
- Modify: tests/TestAccountSwitchEvidence.py
- Modify: src/task/MultiAccountDailyTask.py
- Modify: 更新日志.md
- Create: tests/TestSensitiveIdentifierScan.py
- Create: docs/references/sensitive-data-handling.md

- [ ] 在 fixture_support.py 增加确定性的虚构身份工厂，覆盖 short name、昵称、带星号手机号、备用名、特征码和 profile UUID。
- [ ] 新扫描测试使用 git ls-files，只报告文件路径和规则名，不输出命中原文。
- [ ] 扫描测试禁止已确认真实标识的哈希指纹，禁止生产代码包含账号专属身份常量。
- [ ] 先运行并确认对当前残留失败。
- [ ] 替换所有测试和文档示例，仍保留手机号优先、备用名次优的覆盖。
- [ ] 删除 MultiAccountDailyTask 中账号专属回退，只从当前 profile 的 aliases、masked_phone、alternate_login_name 取候选。
- [ ] 运行身份、切换、MuMu 发现和扫描回归。
- [ ] 提交前人工查看差异，确认没有原文。

~~~powershell
& .\.venv\Scripts\python.exe -m unittest tests.TestSensitiveIdentifierScan tests.TestAccountSwitch tests.TestAccountSwitchEvidence tests.TestMultiAccountDailyTask tests.TestMuMuDiscovery -v
git add -- tests/fixture_support.py tests/TestSensitiveIdentifierScan.py tests/TestMuMuDiscovery.py tests/TestMultiAccountDailyTask.py tests/TestAccountSwitch.py tests/TestAccountSwitchEvidence.py src/task/MultiAccountDailyTask.py 更新日志.md docs/references/sensitive-data-handling.md
git commit -m "security: replace account identifiers with synthetic fixtures"
~~~

---

## Task 3：修复账号快照重复发布和断电窗口

**文件：**

- Modify: src/account_publish_service.py
- Modify: tests/TestAccountPublishService.py
- Modify: tests/TestAccountRepositoryRuntime.py
- Modify: tests/TestAccountRuntimeIntegration.py

- [ ] 增加故障测试：相同修订连续发布、安装前失败、指针切换失败、投影失败、复用有效同修订、隔离损坏非活动修订、活动目录永不被清理、保留最近两个有效修订。
- [ ] 先证明当前“目录存在即删除”在故障注入下失败。
- [ ] 增加 _validate_bundle_dir、_install_or_reuse_bundle、_write_active_pointer、_prune_inactive_bundles。
- [ ] 删除 bundle_dir 存在即 shutil.rmtree 的路径。
- [ ] 有效同修订直接复用；损坏且非活动的目录先隔离；损坏活动目录禁止覆盖。
- [ ] active.json 只在 bundle 完整校验后原子切换。
- [ ] 投影失败可由 recover_incomplete_transactions 重建，不能破坏活动 bundle。

~~~powershell
& .\.venv\Scripts\python.exe -m unittest tests.TestAccountPublishService tests.TestAccountRepositoryRuntime tests.TestAccountRuntimeIntegration tests.TestAccountConfigBundle -v
powershell -ExecutionPolicy Bypass -File .\run_tests.ps1 -Group fault_injection
git add -- src/account_publish_service.py tests/TestAccountPublishService.py tests/TestAccountRepositoryRuntime.py tests/TestAccountRuntimeIntegration.py
git commit -m "fix: make account publication crash safe"
~~~

---

## Task 4：建立统一账号运行时启动门禁

**文件：**

- Create: src/runtime/account_runtime_bootstrap.py
- Modify: src/runtime/__init__.py
- Modify: main.py
- Modify: src/task/MultiAccountDailyTask.py
- Modify: src/task/DailyTask.py
- Modify: custom_ok/ok/gui/MainWindow.py
- Create: tests/TestAccountRuntimeBootstrap.py
- Modify: tests/TestMainWindowStartup.py
- Modify: tests/TestAccountRuntimeIntegration.py

- [ ] 测试 initialize 幂等、事务恢复顺序、完整性失败拒绝启动、StartController hook 失败关闭、直接任务入口可用、旧投影直接写入被拒绝。
- [ ] bootstrap 公开 initialize_account_runtime、get_account_runtime 和 require_account_runtime_ready。
- [ ] 返回只读服务集合：integrity、repository、sequence snapshot、publish service。
- [ ] main.py 删除重复初始化，只调用 bootstrap。
- [ ] MultiAccountDailyTask 和 DailyTask 创建快照前调用 require_ready，不再回退到直接写 daily_profiles.json。
- [ ] MainWindow 只消费 bootstrap 状态，不创建第二套服务。
- [ ] 搜索全部任务入口，证明都直接接入或最终经过 StartController。

~~~powershell
rg -n "MultiAccountDailyTask|run_task|StartController|create_run_snapshot|get_default_service" main.py src custom_ok
& .\.venv\Scripts\python.exe -m unittest tests.TestAccountRuntimeBootstrap tests.TestMainWindowStartup tests.TestAccountRuntimeIntegration tests.TestScheduleSupport tests.TestMultiAccountDailyTask -v
git add -- src/runtime/account_runtime_bootstrap.py src/runtime/__init__.py main.py src/task/MultiAccountDailyTask.py src/task/DailyTask.py custom_ok/ok/gui/MainWindow.py tests/TestAccountRuntimeBootstrap.py tests/TestMainWindowStartup.py tests/TestAccountRuntimeIntegration.py
git commit -m "refactor: unify account runtime bootstrap"
~~~

---

## Task 5：把脱敏接入全部日志和异常链

**文件：**

- Modify: src/observability.py
- Modify: main.py
- Modify: 实际 ok Logger 实现文件
- Modify: tests/TestObservability.py
- Create: tests/TestLoggingRedaction.py

- [ ] 先用 inspect 定位本地 ok Logger 实现，禁止猜路径。
- [ ] 测试覆盖完整手机号、带星号手机号、多种合法长度备用名、特征码、嵌套容器、令牌字段、登录 URL 和普通文本。
- [ ] 建立真实 Handler 测试，覆盖 LogRecord.msg、args、exc_info、traceback。
- [ ] 增加 SensitiveValueRegistry、RedactingFilter 和幂等 install_redaction_filters。
- [ ] registry 仅内存持有，不把秘密列表写入日志或文件。
- [ ] _report_startup_error 在写文件和弹窗前脱敏。
- [ ] bootstrap 在任务对象创建前安装过滤器，创建新 Handler 后补装。

~~~powershell
& .\.venv\Scripts\python.exe -c "from ok.logging.Logger import Logger; import inspect; print(inspect.getsourcefile(Logger))"
& .\.venv\Scripts\python.exe -m unittest tests.TestObservability tests.TestLoggingRedaction -v
git add -- src/observability.py main.py tests/TestObservability.py tests/TestLoggingRedaction.py <实际Logger实现文件>
git commit -m "security: enforce logging redaction globally"
~~~

---

## Task 6：治理诊断文件和敏感事务目录

**文件：**

- Modify: src/diagnose.py
- Modify: main.py
- Modify: src/secure_backup.py
- Modify: src/config_integrity.py
- Modify: src/account_config_bundle.py
- Create: tests/TestDiagnosisRetention.py
- Modify: tests/TestSecureBackup.py
- Modify: tests/TestConfigIntegrity.py
- Modify: tests/TestAccountConfigBundle.py

- [ ] 测试正常启动不生成诊断；崩溃/主动诊断才生成；设备标识和用户路径脱敏；最多 10 份、14 天；清理不跟随 symlink/junction。
- [ ] 删除 main.py 的每次启动 save_diagnosis。
- [ ] 设备标识改为不可逆短哈希，不使用 mask=False。
- [ ] 在 secure_backup.py 增加统一 SecureStoragePolicy：ACL、路径边界、原子替换、留存清理、链接拒绝。
- [ ] configs_backup、config_integrity_incidents、config_bundle_transactions 全部使用同一 policy。
- [ ] ACL 失败时拒绝新明文敏感快照，保留旧数据并进入安全模式。

~~~powershell
& .\.venv\Scripts\python.exe -m unittest tests.TestDiagnosisRetention tests.TestSecureBackup tests.TestConfigIntegrity tests.TestAccountConfigBundle tests.TestConfigBackup -v
git add -- src/diagnose.py main.py src/secure_backup.py src/config_integrity.py src/account_config_bundle.py tests/TestDiagnosisRetention.py tests/TestSecureBackup.py tests/TestConfigIntegrity.py tests/TestAccountConfigBundle.py
git commit -m "security: protect diagnostics and transaction snapshots"
~~~

---

## Task 7：修复五大页面顶层路由和布局

**文件：**

- Modify: custom_ok/ok/gui/MainWindow.py
- Modify: src/gui/GeneralSettingsTab.py
- Modify: 五大页面对应组件
- Modify: tests/TestFiveSectionMainWindow.py
- Modify: tests/TestNavigationSections.py
- Modify: tests/TestTaskNavigationClassification.py
- Modify: tests/TestAccountManagementTabs.py
- Modify: tests/TestUsabilityUI.py

- [ ] 测试 start/trigger → 通用设置，onetime → 任务，account/activity/test → 对应顶层页，schedule 不作为左侧页，executor_paused(False) 不产生 index -1。
- [ ] 建立显式顶层路由表；switchTo 只能接收五个顶层 QWidget。
- [ ] startup_task_tab 返回顶层任务页；内部 task_tab 仅保留兼容访问。
- [ ] 修复 starting_emulator 等直接切换内部 start_tab 的调用。
- [ ] 确认 MainWindow 中不再出现 switchTo(self.start_tab/trigger_tab/onetime_tab)。
- [ ] 布局覆盖 1280×720、1920×1080、2560×1440 和 100/125/150% 缩放。
- [ ] 禁止嵌套滚动；内容水平 expanding；账号和序列同页平铺并实时联动。
- [ ] 固定浅色 Codex 风格；UI 只显示错误摘要，不显示日志正文。

~~~powershell
rg -n "switchTo\\(self\\.(start_tab|trigger_tab|onetime_tab)" custom_ok/ok/gui/MainWindow.py
& .\.venv\Scripts\python.exe -m unittest tests.TestFiveSectionMainWindow tests.TestNavigationSections tests.TestTaskNavigationClassification tests.TestAccountManagementTabs tests.TestUsabilityUI tests.TestMainWindowStartup -v
git add -- custom_ok/ok/gui/MainWindow.py src/gui tests/TestFiveSectionMainWindow.py tests/TestNavigationSections.py tests/TestTaskNavigationClassification.py tests/TestAccountManagementTabs.py tests/TestUsabilityUI.py tests/TestMainWindowStartup.py
git diff --cached --name-only
git commit -m "fix: route tasks through five top level pages"
~~~

提交前从暂存区移除 src/gui 中与本任务无关的文件。

---

## Task 8：修复测试发现和图像测试隔离

**文件：**

- Modify: run_tests.ps1
- Modify: tests/TestTestGroups.py
- Modify: .github/workflows/test.yml
- Modify: .github/workflows/build.yml

- [ ] TestTestGroups 检查 all 等于各组有序去重并集，fixture_support.py 和工具脚本不在 all，所有清单文件存在。
- [ ] run_tests.ps1 的 all 不再遍历 tests/*.py。
- [ ] 每个测试文件独立 Python 进程，image 组逐文件运行。
- [ ] 任一子进程非零立即返回失败。
- [ ] 两个 workflow 只调用 run_tests.ps1，不维护第二份发现逻辑。

~~~powershell
& .\.venv\Scripts\python.exe -m unittest tests.TestTestGroups -v
powershell -ExecutionPolicy Bypass -File .\run_tests.ps1 -Group unit
powershell -ExecutionPolicy Bypass -File .\run_tests.ps1 -Group image
powershell -ExecutionPolicy Bypass -File .\run_tests.ps1 -Group all
git add -- run_tests.ps1 tests/TestTestGroups.py .github/workflows/test.yml .github/workflows/build.yml
git commit -m "ci: make test discovery deterministic"
~~~

---

## Task 9：改造个人 GitHub 发布流水线

**文件：**

- Modify: .github/workflows/build.yml
- Modify or disable: .github/workflows/mirrorchyan_uploading.yml
- Modify or disable: .github/workflows/mirrorchyan_release_note.yml
- Modify: pyappify.yml
- Create: docs/references/personal-release-pipeline.md
- Modify: tests/TestReleaseReadiness.py

- [ ] 静态测试禁止默认流程引用原作者 partial-sync、CNB/更新仓库、SignPath 组织和 MirrorChyan。
- [ ] build.yml 拆为 validate-version、tests、package、package-smoke、checksums、github-release。
- [ ] 普通 push/PR 只测试；vX.YY.ZZ 标签才发布。
- [ ] validate-version 对比标签、config.py、About 和更新日志。
- [ ] package-smoke 检查入口、导入、版本，且包内不存在 working/configs。
- [ ] 生成 SHA-256 清单。
- [ ] MirrorChyan 自动触发删除或改为默认关闭的手动任务。
- [ ] 使用 YAML 解析和 workflow_dispatch 验证。

~~~powershell
& .\.venv\Scripts\python.exe -m unittest tests.TestReleaseReadiness -v
git add -- .github/workflows/build.yml .github/workflows/mirrorchyan_uploading.yml .github/workflows/mirrorchyan_release_note.yml pyappify.yml docs/references/personal-release-pipeline.md tests/TestReleaseReadiness.py
git commit -m "ci: replace upstream publishing dependencies"
~~~

---

## Task 10：在现有运行服务上瘦身 MultiAccountDailyTask

**文件：**

- Modify: src/runtime/account_selection_service.py
- Modify: src/runtime/login_flow_service.py
- Modify: src/runtime/sequence_snapshot_service.py
- Modify: src/runtime/task_run_coordinator.py
- Modify: src/runtime/task_status_model.py
- Create if needed: src/runtime/account_verification_service.py
- Modify: src/account_identity.py
- Modify: src/task/MultiAccountDailyTask.py
- Modify: tests/TestRuntimeServices.py
- Modify: tests/TestMultiAccountDailyTask.py
- Modify: tests/TestAccountSwitch.py
- Modify: tests/TestAccountRuntimeIntegration.py

- [ ] 先锁定 short name 精确匹配、手机号优先、备用名次优、歧义拒绝、特征码只记录、A1/A3/A4 顺序、A3→A4 旋转和运行状态释放。
- [ ] AccountSelectionService 只解析 profile 和身份候选，不点击。
- [ ] LoginFlowService 协调生产流程，OCR/点击仍调用任务设备接口。
- [ ] AccountVerificationService 负责登录后匹配和歧义拒绝，feature_code 默认关闭。
- [ ] SequenceSnapshotService 是运行目标唯一来源。
- [ ] MultiAccountDailyTask 只保留编排和框架生命周期；兼容方法仅委托服务。
- [ ] TestAccountSwitchTask 使用同一服务，不复制算法。
- [ ] 只修迁移路径的宽泛异常，其他异常进入 Task 11 审查。

~~~powershell
& .\.venv\Scripts\python.exe -m unittest tests.TestRuntimeServices tests.TestAccountSwitch tests.TestMultiAccountDailyTask tests.TestAccountRuntimeIntegration -v
git add -- src/runtime src/account_identity.py src/task/MultiAccountDailyTask.py tests/TestRuntimeServices.py tests/TestMultiAccountDailyTask.py tests/TestAccountSwitch.py tests/TestAccountRuntimeIntegration.py
git commit -m "refactor: extract multi account runtime services"
~~~

---

## Task 11：修复低风险质量问题和 Android 控制边界

### 11A：PC 端

**文件：** src/task/DiagnosisTask.py、src/task/BaseCombatTask.py、main.py、快捷键状态组件和对应测试。

- [ ] DiagnosisTask 使用有效 logger，增加最小运行测试。
- [ ] 协奏值越界仍裁剪到 0～1，但相同日志限速并聚合计数。
- [ ] F9 冲突在通用设置显示状态和换键入口。
- [ ] main.py 只修改本程序拥有的 http.proxy 键，不重写整个 [http] 段。
- [ ] 检查 .venv 的无效 distribution 和 PySide6 声明；只修依赖文件或重建说明，不直接删除未知文件。

~~~powershell
& .\.venv\Scripts\python.exe -m unittest tests.TestBaseCombatTask tests.TestKey tests.TestMainWindowStartup -v
git add -- <11A实际文件>
git commit -m "fix: improve runtime diagnostics and controls"
~~~

### 11B：Android agent-app

**文件：** 当前未提交 Android 源码、README、.gitignore、src/android/runtime.py、tests/TestAndroidPreflight.py。

- [ ] 实施前逐文件审查当前用户差异，不用仓库版本覆盖。
- [ ] LocalControlServer 增加进程会话令牌、有界线程池/队列、超时、最大请求体、严格 JSON 数字解析和 nonce/sequence 防重放。
- [ ] 未认证请求不泄露状态。
- [ ] 本阶段只允许 install、preflight、heartbeat、stop、只读 status；游戏点击保持禁用。
- [ ] build、keystore、APK、idsig、class、dex 写入 .gitignore，不提交构建产物或调试密钥。
- [ ] 若无法确认用户差异的意图，停止 11B 并原样保留；不得阻塞 PC 1.20.00 或猜测合并。

~~~powershell
& .\.venv\Scripts\python.exe -m unittest tests.TestAndroidPreflight -v
powershell -ExecutionPolicy Bypass -File .\android\agent-app\build.ps1
git diff --cached --name-only
~~~

只有差异可安全归属时才使用独立提交 security: harden android local control server。

---

## Task 12：全量回归

- [ ] 编译 main.py、config.py、src、custom_ok、tests。
- [ ] 依次运行 unit、integration、ui、fault_injection、image、all。
- [ ] 新增失败全部阻止发布。
- [ ] 扫描本次修改路径的宽泛异常，禁止新增静默 pass。
- [ ] 运行敏感扫描、安全基线和发布一致性测试。
- [ ] 运行 git diff --check、git status --short，核对 Android 边界。

~~~powershell
& .\.venv\Scripts\python.exe -m compileall -q main.py config.py src custom_ok tests
powershell -ExecutionPolicy Bypass -File .\run_tests.ps1 -Group unit
powershell -ExecutionPolicy Bypass -File .\run_tests.ps1 -Group integration
powershell -ExecutionPolicy Bypass -File .\run_tests.ps1 -Group ui
powershell -ExecutionPolicy Bypass -File .\run_tests.ps1 -Group fault_injection
powershell -ExecutionPolicy Bypass -File .\run_tests.ps1 -Group image
powershell -ExecutionPolicy Bypass -File .\run_tests.ps1 -Group all
& .\.venv\Scripts\python.exe -m unittest tests.TestSensitiveIdentifierScan tests.TestSecurityBaseline tests.TestReleaseReadiness -v
git diff --check
git status --short
~~~

---

## Task 13：本地 1.20.00 候选包和安装烟测

- [ ] 记录候选 commit SHA。
- [ ] 使用 build.yml 相同的 pyappify 命令本地构建；若只能在 CI 构建，使用不创建 Release 的 workflow_dispatch artifact。
- [ ] 候选包装入隔离槽位，不覆盖 E:\game\okww owener 的 working/configs。
- [ ] 安装前后对当前打包版账号配置计算 SHA-256，Expected：完全一致。
- [ ] 验证 UI 启动、版本、五页导航、账号/序列读取、正常启动不生成诊断、UI 不显示日志、关闭后无运行锁。
- [ ] 失败时不创建标签，回到对应任务并重新执行 Task 12。

---

## Task 14：A3/A4 打包候选版实机验收

- [ ] 只读预检：版本、A3/A4 精确 short name、独立 UUID/JSON、active manifest；不点击。
- [ ] 登录列表识别：带星号手机号优先，U…A 备用名次优，歧义时安全停止。
- [ ] A3→A4：复用生产选择/登录/验证服务，按模拟人手节奏点击；A3 配置不得进入 A4 上下文。
- [ ] A4→A3 回切：验证重复切换和恢复。
- [ ] 多账号每日任务：序列联动、无音区有限恢复、单账号失败不污染另一账号。
- [ ] 停止与恢复：运行中、登录页、网络断开、窗口消失、识别失败、程序重启、快照回退。
- [ ] 日志不得出现残留运行锁、index -1、真实身份、设备唯一标识和协奏刷屏。
- [ ] 验收前后账号配置 SHA-256 一致。
- [ ] 交接日志记录时间、候选 SHA、A3/A4 顺序、结果、日志路径和哈希结论；只写短名。

---

## Task 15：完成文档和发布候选提交

**文件：**

- Modify: 更新日志.md
- Modify: custom_ok/ok/gui/about/AboutTab.py
- Modify: 交接/综合优化实施交接日志_2026-08-26.md
- Modify: docs/references/account-profile-security-references.md
- Modify: docs/references/pc-account-configuration-and-sequences.md
- Modify: 新增安全与发布参考文献
- Modify: tests/TestReleaseReadiness.py

- [ ] 更新日志从“验证中”改为真实最终结果。
- [ ] About 只显示用户摘要，不显示内部路径或敏感规则值。
- [ ] 交接记录修改文件、迁移兼容、测试、候选包、回滚、特征码未启用逻辑和原版 OK-WW 对照版本。
- [ ] 参考文献记录原子替换、ACL/DPAPI、logging Filter、GitHub Actions、git-filter-repo 的官方资料和访问日期。
- [ ] 运行发布一致性和敏感扫描，提交 docs: finalize 1.20.00 release records。

---

## Task 16：隐私历史维护窗口、正式标签和 GitHub 发布

**危险级别：高。执行前必须再次向用户确认。**

### 16.1 二次确认报告

- [ ] 只报告命中类别/提交/分支/标签/构件数量，不显示原文。
- [ ] 报告当前用户文件、备份绝对路径、受影响远端引用和回滚方式。
- [ ] 明确询问是否同意：临时私有、git-filter-repo、强制推送、删除/重建受影响 Release 构件。
- [ ] 未获得明确确认立即停止。

### 16.2 维护操作

- [ ] 临时设为私有并确认匿名访问关闭。
- [ ] 创建全引用 mirror/bundle 备份，以及 Android 用户文件补丁、清单和 SHA-256 备份。
- [ ] 替换映射放在仓库外，权限仅当前用户，日志不打印内容。
- [ ] 在独立 mirror clone 运行 git-filter-repo，不在带用户未提交文件的工作树运行。
- [ ] 扫描重写后的全部提交、分支、标签和当前树。
- [ ] 推送前比较远端引用；出现未知新提交立即停止。
- [ ] 强制更新受影响分支和标签，删除受影响旧构件。
- [ ] 从清理后的最终提交创建 annotated v1.20.00 标签并推送。

### 16.3 发布验证

- [ ] GitHub Actions 的 tests、package、package-smoke、checksums、release 全部 PASS。
- [ ] 下载正式 Release，校验版本和 SHA-256。
- [ ] Release 不含 working/configs、诊断、日志、密钥、调试签名和真实身份。
- [ ] 从匿名视角再次扫描；通过后，只有用户仍要求公开时才恢复 public。
- [ ] 其他设备文档说明历史已重写，旧 clone 应重新克隆，不能普通 pull 后强行合并。
- [ ] 最终交接记录 Actions、Release、tag SHA、构件 SHA-256 和可见性。

---

## 完成定义

- [ ] 当前树和 Git 历史无真实账号标识。
- [ ] 重复发布和全部断电窗口故障注入通过。
- [ ] 所有启动入口经过统一门禁。
- [ ] 全部日志与诊断脱敏并受留存限制。
- [ ] 三个敏感目录使用统一 ACL 和路径保护。
- [ ] 五页导航无 index -1，1280×720 到 2560×1440 平铺正常。
- [ ] all 测试发现正确，图像测试隔离。
- [ ] 个人 Actions 可测试、打包和发布。
- [ ] 多账号任务复用生产服务，测试入口没有第二套切换实现。
- [ ] A3/A4 候选包验收通过，配置未污染。
- [ ] 版本、About、更新日志、交接、参考文献、tag 和 Release 均为 1.20.00。
- [ ] 分支和 annotated tag 已推送，Actions 全绿。

## 提交顺序摘要

1. chore: start 1.20.00 remediation release
2. security: replace account identifiers with synthetic fixtures
3. fix: make account publication crash safe
4. refactor: unify account runtime bootstrap
5. security: enforce logging redaction globally
6. security: protect diagnostics and transaction snapshots
7. fix: route tasks through five top level pages
8. ci: make test discovery deterministic
9. ci: replace upstream publishing dependencies
10. refactor: extract multi account runtime services
11. fix: improve runtime diagnostics and controls
12. security: harden android local control server（仅在用户改动可安全合并时）
13. docs: finalize 1.20.00 release records

正式 v1.20.00 标签只在候选包、A3/A4、历史清理和全部测试通过后创建。
