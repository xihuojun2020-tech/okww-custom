# ok-ww 易用性与数据安全综合优化设计

日期：2026-08-26  
目标版本基线：`1.18.00`  
适用范围：PC 端为主；Android/MuMu 保持独立、显式启用的实验链路

## 1. 目标与非目标

### 目标

1. 防止身份字段误修改、账号串线和运行目标漂移。
2. 让配置发布、导入、备份、恢复在中断或损坏后可验证、可回滚。
3. 让账号、序列、任务和测试页面不依赖内部 JSON/UUID 知识即可使用。
4. 将任务编排、账号选择、登录流程和 UI 解耦，降低后续维护风险。
5. 建立可重复的单元、集成、UI、图像和故障注入测试体系。

### 非目标

- 不重写现有识别、登录和战斗算法。
- 不把 Android 控制链路并入 PC 账号仓库。
- 不允许通过 UI 绕过账号完整性门禁。
- 不在本阶段启用游戏内特征码作为自动切换依据；该字段继续只读记录。

## 2. 当前实现基线

- 账号以 UUID 独立文件保存，序列引用 UUID。
- `AccountRepository` 提供 CAS 修订检查。
- `AccountPublishService` 生成 bundle、manifest 和原子 `active.json` 指针。
- 运行任务使用不可变 `SequenceRunSnapshot`。
- 带星号手机号是首要识别依据，`alternate_login_name` 是备用识别名。
- 五栏导航、固定浅色 Codex 风格和账号/序列实时联动已经存在。

需要优先修复的已知缺口：账号页身份输入框仍可编辑；后端锁定字段未覆盖全部身份字段；备份 JSON 未做用户级加密；多份配置投影的写入边界复杂；任务和 UI 通过全局对象耦合；大量异常被静默吞掉；完整测试存在未隔离的图像基线错误。

## 3. 总体架构

```text
UI 草稿
  -> AccountRepository / SequenceRepository
  -> schema + identity uniqueness validation
  -> transaction backup
  -> immutable bundle + SHA-256 manifest
  -> atomic active pointer
  -> read-only projections and AccountChangeEvent
  -> task consumers create a frozen SequenceRunSnapshot
```

`active bundle` 是运行时唯一真源；独立账号 JSON 和 working JSON 只作为编辑投影。所有配置写入必须经过 repository/publish service，禁止任务直接写 JSON。运行中的任务只读启动时快照，变更排队到下一次运行。

## 4. 安全设计

### 4.1 身份保护

以下字段在普通账号配置页只读，并在后端统一锁定：

`profile_id`、`phone`、`masked_phone`、`nickname`、`alternate_login_name`、`game_feature_code`、`account_aliases`。

未来需要更换身份时，必须走独立“重新绑定账号”流程：旧身份确认、新身份输入、冲突检查、影响序列预览、备份、CAS 发布和审计记录。

### 4.2 备份与恢复

- 本机备份使用 Windows DPAPI 保护敏感字段，目录权限限制为当前用户。
- 跨设备导出只输出脱敏数据，并显式标记不可用于登录。
- 保留 SHA-256 完整性校验，增加 manifest schema 和版本校验。
- 恢复前、暂存后、替换后各执行一次完整性检查。
- 恢复事务状态固定为 `prepared -> verified -> activated -> mirrored`；启动时可恢复中断事务。
- 所有恢复目标必须通过路径边界检查，不允许符号链接越界。

### 4.3 错误与日志

- 用明确异常类型替代无条件 `except Exception: pass`。
- 每次发布和任务运行带 correlation id、revision、run_id 和 profile UUID。
- UI 只显示脱敏错误摘要；日志不得包含完整手机号、密码、Cookie、Token 或登录链接。
- 提供“打开日志”和“复制脱敏诊断”操作，不在任务页显示滚动日志。

## 5. 运行层设计

逐步抽出以下服务，保持现有任务行为不变：

- `AccountSelectionService`：UUID、短名、带星号手机号、U…A 解析和歧义拒绝。
- `SequenceSnapshotService`：创建只读快照，分配 revision/run_id。
- `LoginFlowService`：退登、下拉框识别、选号、登录后复核。
- `TaskRunCoordinator`：启动、停止、取消、超时和失败恢复。
- `TaskStatusModel`：向 UI 提供状态，避免 UI 读取任务内部变量。

任务入口接收快照，不接收可变全局配置：

```python
snapshot = sequence_snapshot_service.create(sequence_id)
coordinator.run(snapshot)
```

## 6. UI 设计

### 账号设置

- 顶部显示账号短名、带星号手机号、U…A 备用名、所属序列和 revision。
- 身份信息使用只读卡片；任务字段使用中文表单。
- 增加搜索、序列筛选、未配置筛选、字段恢复默认和未保存状态提示。
- 高级 JSON 默认折叠，提供格式校验、字段说明和脱敏差异预览。
- 删除、恢复和重新绑定显示影响范围并要求二次确认。

### 序列设置

- 支持拖拽排序、添加/移除账号、复制、停用和删除。
- 成员同时显示短名、带星号手机号、U…A 备用名和启用状态。
- 删除前显示被哪些任务引用以及成员数量。

### 任务与测试

- 显示当前序列、账号、revision 和运行状态。
- 运行中禁用影响当前快照的控件。
- 完整性失败时进入可操作安全模式，提供检查、恢复和打开日志入口。

### 本地化

- 所有用户可见文字统一进入 gettext 目录。
- 内部 JSON 键保持稳定英文，不因界面语言改变。
- 固定浅色主题，不响应系统深色模式。

## 7. 分阶段交付

1. **基线与保护**：测试分组、运行目录忽略规则、版本和文档同步检查。
2. **身份与备份安全**：只读字段、后端锁定、DPAPI、ACL、路径边界和重新绑定入口。
3. **统一发布模型**：active bundle 真源、事务状态、投影重建和恢复验证。
4. **运行层解耦**：账号选择、快照、登录流程、协调器和状态模型。
5. **UI 易用性**：搜索筛选、只读身份卡、拖拽序列、差异预览、状态入口和中文统一。
6. **错误处理与可观测性**：异常分类、脱敏日志、correlation id 和诊断导出。
7. **测试与发布**：确定性/集成/UI/图像/故障注入分层，CI 和发版门禁。

每个阶段都必须有独立测试和可回滚提交，不跨阶段混合重写。

## 8. 验收标准

- 任意普通账号编辑操作无法修改身份字段；后端绕过 UI 也会拒绝。
- 任意发布中断不会产生半写入 active 配置，恢复后可回到旧 revision。
- A1 从序列1转到序列2后，账号页、序列页、任务页和测试页立即一致。
- 运行中的任务不因配置修改改变目标账号。
- 账号歧义、完整性失败、快照损坏和停止超时均进入明确安全状态。
- 核心确定性测试全绿；图像测试单独报告，不再掩盖核心回归。
- 版本号、更新日志、AboutTab、交接文档和 Git 标签保持一致。

## 9. 风险与回滚

- DPAPI 或权限策略不可用时，禁止静默退回明文保护；进入安全模式并提示用户。
- 投影重建失败时保留旧 active bundle，不覆盖可运行配置。
- 运行层拆分期间保留旧任务入口作为兼容适配层，逐个任务迁移。
- UI 重构只改变展示和编辑入口，不改变任务识别坐标和战斗算法。
- Android 继续使用独立预检和停止通道，只有通过独立验收后才考虑接入任务编排。
