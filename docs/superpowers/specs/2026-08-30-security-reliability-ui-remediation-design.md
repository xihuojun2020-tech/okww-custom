# OK-WW 1.20.00 安全、可靠性与易用性综合修复设计

日期：2026-08-30  
状态：用户已批准采用推荐方案一  
当前基线：1.19.12  
目标版本：1.20.00

## 1. 设计结论

本次采用“安全优先、一次综合修复、按独立提交交付”的路线。隐私、账号数据原子性和统一启动门禁先于 UI、重构和发布；A3/A4 打包版实机验收是最终发布门禁。

本设计补充而不覆盖以下既有设计：

- docs/superpowers/specs/2026-08-26-comprehensive-hardening-design.md
- docs/superpowers/specs/2026-08-26-account-profile-security-and-identity-design.md
- docs/superpowers/plans/2026-08-30-multi-account-startup-and-lifecycle-repair.md

其中 1.19.12 的多账号启动专项修复继续作为回归基线，1.20.00 不允许重新实现一套独立账号切换逻辑。

## 2. 目标

1. 清除当前树和公开 Git 历史中的真实账号标识。
2. 确保重复发布、异常退出和断电不会破坏活动账号快照。
3. 让 GUI、CLI、计划任务、快捷方式和直接任务入口使用同一套账号完整性门禁。
4. 在所有日志、异常、诊断包和 GitHub Actions 输出中强制脱敏。
5. 修复五大顶层页面导航错误，保持固定浅色 Codex 风格和平铺式内容。
6. 修复本地测试发现与个人 GitHub 发布流水线。
7. 在回归测试保护下拆分多账号任务的身份、选择、验证、会话和编排职责。
8. 修复低风险质量问题并为 Android 控制服务建立安全边界。
9. 使用打包版完成 A3/A4 识别、切换、执行、停止和恢复验收。

## 3. 非目标

- 本版本不启用游戏内特征码强制校验，只保留字段、唯一性约束和未来验证接口。
- 不改变手机号掩码优先、备用登录名次优的现有账号选择规则。
- 不重写 OCR、坐标识别或自动战斗算法。
- 不删除、覆盖或擅自提交当前未提交的 MuMu/Android 工作。
- 不在未获得第二次确认前重写 Git 历史或强制推送。
- 不把日志重新放回 UI。

## 4. 安全与数据不变量

### 4.1 三类账号身份

每个账号继续保留三个用途不同的身份域：

1. 用户识别域：昵称和中间带星号的手机号，便于用户确认账号；带星号手机号也是切换账号的首要匹配依据。
2. 备用登录域：U 开头、A 结尾的备用识别名，用于登录列表没有手机号时匹配。
3. 游戏唯一身份域：游戏内固定特征码，未来用于任务执行前复核，本版本不参与自动点击。

任何日志、测试、诊断、文档和 Git 提交不得包含真实原文。程序内部只在完成匹配所需的最小生命周期中持有原值。

### 4.2 配置不变量

- 每个账号由单独 JSON 文件保存。
- 序列只引用稳定的 profile UUID，不复制账号配置。
- 运行中的任务只读启动时冻结的 SequenceRunSnapshot。
- 所有写入必须经过 repository 和 publish service。
- 任务代码不得直接覆盖 daily_profiles.json 或账号主配置。
- 修改一个账号不得改变其他账号 JSON 的内容或修订。
- 账号归属变化必须立即反映到账号页、序列页、任务页和测试页。

### 4.3 发布不变量

- active.json 始终指向一个完整且通过 manifest 校验的目录。
- 当前活动目录永远不能在指针切换前被删除。
- 相同修订的重复发布必须幂等。
- 任一发布步骤失败都保留旧活动修订可读。
- 至少保留两个最近有效修订用于恢复。

## 5. 目标架构

~~~text
GUI / CLI / 计划任务 / 快捷方式 / 直接任务
                       |
                       v
            AccountRuntimeBootstrap
                       |
          +------------+-------------+
          |                          |
          v                          v
 ConfigIntegrityService       LoggingRedactionFilter
          |
          v
 AccountRepository / SequenceRepository
          |
          v
 crash-safe AccountPublishService
          |
          v
 immutable SequenceRunSnapshot
          |
          v
 TaskRunCoordinator
          |
          v
 AccountSelection -> LoginSession -> Verification -> DailyTask
~~~

UI 和任务都不能绕过 AccountRuntimeBootstrap。活动 bundle 是运行时权威真源，独立账号 JSON 是可编辑投影；投影损坏时应从活动 bundle 重建，而不是反向污染活动数据。

## 6. 子系统设计

### 6.1 隐私处置

分为两个不同授权等级：

- 普通代码修改：替换当前树中的真实标识、引入虚构测试身份、增加敏感信息扫描测试。
- 破坏性仓库操作：临时私有、镜像备份、git-filter-repo、重建标签和强制推送。

第二部分必须在输出待处理引用数量、备份位置、远端和回滚方法后再次请求用户确认。

### 6.2 崩溃安全账号发布

发布流程固定为：

~~~text
准备唯一暂存目录
 -> 写入全部文件
 -> 写入 manifest
 -> 校验内容
 -> 安装或复用正式修订目录
 -> 原子切换 active.json
 -> 重建编辑投影
 -> 延迟清理非活动旧修订
~~~

已存在的同修订目录如果校验通过则直接复用；校验失败时不得删除活动目录，应将损坏的非活动目录隔离后重新创建。

### 6.3 统一启动门禁

新增 AccountRuntimeBootstrap，提供幂等 initialize() 和 require_ready()：

- 创建并注册 ConfigIntegrityService。
- 恢复未完成事务。
- 校验活动 bundle、独立账号 JSON 和序列引用。
- 安装 StartController 保护。
- 初始化日志脱敏。
- 返回只读运行时服务集合。

所有运行入口只依赖该返回值，不再假定 main.py 已经执行。

### 6.4 日志与诊断

在 ok Logger 的所有 Handler 上安装统一 Filter，处理 msg、args、exception 和 traceback。脱敏规则由四层组成：

1. 字段名：password、token、cookie、credential 等。
2. 格式：完整手机号、带星号手机号、备用登录名、登录 URL。
3. 当前账号仓库加载的秘密集合。
4. 保守的长令牌规则。

诊断包改为按需生成，默认最多 10 份并保留 14 天；设备唯一标识、Windows 用户路径和账号标识全部脱敏。

### 6.5 敏感本地存储

configs_backup、config_integrity_incidents 和 config_bundle_transactions 使用同一个 SecureStoragePolicy：

- Windows ACL 限制为当前用户和 SYSTEM。
- 原子写入和目录边界检查。
- 数量与时间留存限制。
- 清理不跟随符号链接或 junction。
- DPAPI 作为本机备份可选层；跨设备导出必须走显式导出流程。

DPAPI 不可用时不能静默降级为无提示明文，应记录脱敏警告并进入受限模式或要求用户确认。

### 6.6 五页 UI

顶层 switchTo() 只接受：

- 通用设置
- 账号设置
- 任务
- 活动
- 测试功能

start、trigger 路由到通用设置；onetime 路由到任务页。内部面板只负责定位和聚焦，不再作为顶层 stackedWidget 页面。

所有页面使用窗口级滚动，禁止卡片或分组再创建嵌套滚动。内容宽度随右侧区域伸展，1280×720 到 2560×1440 均不得出现不可解释的大面积空白。

### 6.7 测试与发布

测试入口按显式清单运行，all 是各组并集，不再遍历 tests 目录中的所有 Python 文件。图像测试逐文件独立进程运行，避免共享已关闭 executor。

个人发布工作流只使用当前仓库可控制的资源：

- 测试
- 本地打包
- 构件校验值
- GitHub Release

原作者同步仓库、签名组织和 MirrorChyan 流程默认移除或改为显式关闭的可选工作流。

### 6.8 多账号任务拆分

拆分遵循“先测试、后搬移、不改变行为”：

- AccountIdentityMatcher
- AccountSelectionService
- AccountVerificationService
- AccountSessionService
- SequenceResolver
- SwitchRetryPolicy
- MultiAccountRunner

TestAccountSwitchTask 必须调用生产服务，不允许复制生产实现。默认测试顺序仍为 A1、A3、A4；A3/A4 实机验收使用用户现有序列快照。

### 6.9 Android 安全边界

Android agent-app 当前是用户未提交工作，必须增量合并。LocalControlServer 在未来发送游戏输入前必须具备：

- 每次启动生成的会话令牌。
- 有界线程池和请求队列。
- 连接、读取和空闲超时。
- 严格 JSON 解析和请求大小限制。
- 单调序号或 nonce 防重放。
- 心跳、预检和停止保持幂等。

未通过上述门禁时，控制服务只能提供只读状态、预检、心跳和停止，不能发送游戏点击。

## 7. 错误处理原则

- 宽泛异常只允许存在于进程、线程或任务最外层边界。
- 所有边界异常必须分类、脱敏、保留 cause 并更新任务状态。
- 内层不得 except Exception 后 pass。
- 可恢复错误执行有限次重试；不可恢复错误进入安全停止。
- 同类高频日志必须限速或聚合。
- UI 显示可操作摘要，不显示原始日志正文。

## 8. 实施顺序与门禁

1. 固化基线和保护当前未提交 Android 工作。
2. 当前树隐私替换和敏感扫描。
3. 第二次确认后执行 Git 历史清理。
4. 修复账号快照发布。
5. 接入统一启动门禁。
6. 接入全局日志脱敏和诊断治理。
7. 统一敏感目录保护。
8. 修复 UI 顶层路由与布局。
9. 修复测试发现和 GitHub Actions。
10. 在回归保护下拆分多账号任务。
11. 修复低风险质量问题和 Android 控制边界。
12. 全量回归、打包版 A3/A4 验收。
13. 同步文档、发布 1.20.00。

任何门禁失败都停止向后推进，修复后从当前门禁重新开始，不跳过测试。

## 9. 回滚策略

- 普通代码提交逐项使用 git revert 回滚，不使用 git reset --hard。
- 账号发布异常直接保留旧 active.json 和旧 bundle。
- UI 路由修复可独立回滚，不影响账号数据格式。
- 多账号拆分保留兼容适配层，直到打包版实机验收通过。
- Android 服务安全修改失败时继续保持只读控制模式。
- 历史重写回滚依赖操作前的离线 mirror 备份；不能依赖 GitHub 恢复。

## 10. 最终验收

- 敏感信息扫描覆盖当前树、历史、标签和构件并通过。
- 相同修订重复发布和全部故障注入均保留活动配置可读。
- GUI、CLI、计划任务和直接任务入口均通过统一完整性门禁。
- 日志和诊断中没有真实身份、令牌或设备唯一标识。
- 五大页面导航、暂停恢复和 1280×720 布局通过。
- all 测试不执行 fixture_support.py，图像测试无 executor 复用错误。
- GitHub Actions 能在个人仓库完成测试和发布。
- A3/A4 打包版完成预检、切换、每日任务、停止和恢复。
- config.py、About、更新日志、交接、参考文献、标签和 Release 全部一致为 1.20.00。
