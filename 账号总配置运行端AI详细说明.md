# 账号总配置运行端 AI 详细说明（v1.08.00）

本文供运行端的 AI 工具、维护脚本和人工维护者理解账号总配置的安全边界。普通任务和普通配置保存不会创建或修改总配置；只有用户明确确认的旧版本首次锚定、遗漏序列恢复、账号配置包导入或完整备份恢复可以进入受控写事务。AI 在操作前必须先向用户说明影响并备份文件，不能替用户点击确认。

## 1. 四类文件及职责

所有相对路径均以程序根目录为起点：

| 路径 | 职责 | 主程序是否写入 |
| --- | --- | --- |
| `configs/account_master_config.json` | 所有账号的稳定意图和唯一可信来源 | 正常任务只读；仅用户确认的锚定、遗漏序列恢复、受控导入或备份恢复事务可修改 |
| `configs/daily_profiles.json` | 兼容旧版界面和任务代码的工作副本 | 只能由已确认事务依据总配置重建，不能反向覆盖总配置 |
| `configs/account_runtime_state.json` | 已接受总配置指纹、完成时间、断点和游标 | 可原子更新；不保存账号任务意图 |
| `config_integrity_incidents/` | 异常证据、快照、备份、差异和处理标记 | 出现异常或首次迁移时写入 |

总配置可以在程序外由 AI、文本编辑器或其他工具修改。这里的“只读”是指程序业务代码不能把界面状态、运行进度或污染后的工作副本静默写回总配置，不是操作系统文件权限锁定。

## 2. schema v1 字段

总配置必须是 UTF-8 JSON 对象，顶层字段如下：

- `schema_version`：固定为整数 `1`。
- `config_id`：非空字符串，标识这一套账号规划。首次锚定在旧文件没有合法值时生成 `legacy-bootstrap-<UUID>`。
- `timezone`：非空时区名；旧文件缺失时保守使用 `Asia/Shanghai`。
- `profiles`：对象，键必须是稳定 UUID；UUID 一经生成不得因显示名称、手机号或备用名变化而重新生成。
- `sequences`：对象，键是序列名称，值是按执行顺序排列的 `profile_id` 数组。不能引用未知账号或重复引用同一账号。
- `extensions`：预留扩展对象。未知扩展应原样保留，不能擅自删除。

每个 `profiles.<profile_id>` 必须包含：

- `display_name`：界面显示名称，如 `A1` 或 `【A1-示例-15300000001】`。
- `account_aliases`：登录识别备用身份数组，可包含短名、掩码手机号或 U 开头账号；不同账号不得共享同一身份。
- `task_config`：账号任务意图。必须至少包含下列受保护键：
  - `Which to Farm`
  - `Which Tacet Suppression to Farm`
  - `Which Forgery Challenge to Farm`
  - `Material Selection`
  - `Farm Nightmare Nest for Daily Echo`
  - `Nightmare Which to Farm`
  - `Tacet Discord Nests to Farm`
  - `Auto Farm all Nightmare Nest`
  - `Weekly Garden Check Day`
  - `Merge Echo on Sunday`
  - `备用识别名称`
  - `备用识别名称内容`
- `schedule`：账号时间安排对象。`mode` 可为 `""`、`disabled`、`daily`、`weekly`、`once`；`local_time` 使用 `HH:MM`；`weekdays` 是数组；未来字段放在 `schedule.extensions`。
- `extensions`：账号级预留扩展对象。

`Record After Daily Task`、`Record Pages`、`Record Duration`、`Logout PC After Daily Task` 和 `Last Completed - ...` 不属于账号稳定任务意图，不应手工加入受保护字段。完成记录和多账号断点属于运行状态。

## 3. 旧版本首次锚定

只有同时满足以下条件时，弹窗才允许“将当前账号配置锚定为总配置”：

1. `account_master_config.json` 确实不存在；已有但 JSON 损坏不属于首次迁移。
2. `daily_profiles.json` 存在、JSON 合法且至少包含一个账号。
3. 账号身份不冲突：短名按完整令牌匹配（A1 不会匹配 A10），完整手机号会同时检查对应掩码，U 名和备用名按规范化后的完整文本检查。
4. 序列只引用可唯一识别的账号。
5. `account_runtime_state.json` 不存在或合法；损坏的运行状态必须先由用户明确选择重建。
6. 用户先点击“已知晓并查看迁移说明”，再亲自点击“将当前账号配置锚定为总配置”。

关闭弹窗、点击“退出并保持安全模式”或未点击确认都不会创建总配置，任务门禁继续生效。

确认后程序执行一个事务：

1. 重新读取文件，防止弹窗打开后文件已被外部修改。
2. 合法的已有 `profile_id` 原样复用；缺失 ID 的账号生成 UUID，并将该 UUID 持久化到工作副本。重复或非法的已有 ID 会阻止迁移，不能静默换号。
3. 旧版 profile 顶层任务字段会进入 `task_config`；若已经存在嵌套 `task_config`，以嵌套值为准，缺失的受保护键才从旧顶层补入。
4. 所有已有任务值原样保留，不做类型转换。缺失的必填键使用保守默认：刷取 `Tacet Suppression`、两个次数为 `1`、材料 `Shell Credit`、各自动/融合开关为 `false`、列表为空、每周乐园为 `无`、备用识别名称为 `无` 且内容为空。
5. `last_completed` 不进入总配置，但会在保留工作副本原字段的同时迁入 `account_runtime_state.json.completed_at.<profile_id>`，使新版本仍能按 UUID 读取历史完成时间；运行状态已有同名记录时以运行状态为准。已有账号别名、旧账号键、时间安排、扩展和序列成员顺序原样保留；旧序列成员只转换为对应 UUID。
6. 在事件目录写入原始工作副本、原始运行状态和候选总配置。
7. 用同目录临时文件、`fsync` 和原子替换创建总配置；再补齐工作副本并把已接受指纹写入运行状态。
8. 重新做完整性检查。只有后验检查为安全状态才完成，并在事件目录留下唯一标记 `RESOLVED_BY_LEGACY_BOOTSTRAP`。

任何一步失败都会删除本次新建的总配置，并把工作副本和运行状态恢复到操作前的精确字节。不要把失败后事件目录中的 `bootstrap_candidate.json` 直接当作正式总配置；先检查错误原因。

## 4. 外部修改总配置

首次锚定后，总配置的新增账号、删除账号、任务调整、时间调整和别名修改均应在程序外完成：

1. 停止任务并退出程序。
2. 备份 `configs` 和相关 `config_integrity_incidents`。
3. 复制总配置到候选文件，在候选文件上编辑。保留已有账号 UUID；新增账号才生成新 UUID。
4. 只读验证候选文件。
5. 验证通过后在程序外替换正式总配置，再启动程序。
6. 弹窗会报告总配置指纹改变及工作副本差异。用户查看后可选择“使用总配置覆盖全部账号配置”，一次完成指纹接受和所有账号工作副本重建。

不能把 `daily_profiles.json` 直接复制成总配置：两者 schema、序列引用方式和运行字段边界不同。也不能仅修改 `daily_profiles.json` 期待它覆盖已有总配置；这会被视为异常差异。

## 5. 验证命令

源码仓库使用本地虚拟环境：

```powershell
.\.venv\Scripts\python.exe scripts\validate_account_master_config.py .\configs\account_master_config.json
```

部署目录使用随程序提供的 Python：

```powershell
.\runtime\python\python.exe scripts\validate_account_master_config.py .\configs\account_master_config.json
```

验证器只读取文件，输出 schema 错误或语义指纹，不写入总配置。若要验证候选文件，把命令末尾路径换成候选文件路径。

## 6. 差异覆盖与运行状态保留

“使用总配置覆盖全部账号配置”仅在已有合法总配置时出现，与首次锚定按钮是两个互斥分支：

- 首次锚定：总配置缺失，信任当前合法旧配置并创建第一份总配置。
- 总配置覆盖：总配置已存在，以总配置为准重建工作副本。

两种操作都会重新检查当前文件，不能使用弹窗打开时的旧快照。覆盖账号配置时保留工作副本顶层全局字段；账号任务、别名、时间、序列和扩展以总配置为准。`account_runtime_state.json` 中的 `completed_at`、`progress` 及未知未来字段原样保留，仅更新已接受指纹和最近完整性事件。

若运行状态损坏，程序不能证明进度安全，会禁用首次锚定/覆盖按钮。用户可选择“确认重建损坏的运行状态（可能重复执行）”，但这可能导致任务重复执行，AI 不得代替用户确认。

## 7. 事件、备份与恢复

事件目录位于 `config_integrity_incidents/<时间>_<事件ID>_PENDING_REVIEW/`。常见内容：

- `manifest.json`：事件 ID、程序版本、指纹、错误和处理状态。
- `integrity.log`：文本摘要。
- `master.snapshot.json`、`working.snapshot.json`、`runtime.snapshot.json`：检查时快照。
- `normalized_diff.json`：语义差异。
- `before_bootstrap/`：首次锚定前的原始工作副本和运行状态。
- `bootstrap_candidate.json`：首次锚定候选总配置，仅供诊断。
- `PENDING_REVIEW`：仍需处理。
- `RESOLVED_BY_LEGACY_BOOTSTRAP`、`RESOLVED_BY_MASTER_RESTORE` 或 `RESOLVED_BY_MASTER_APPLY`：明确处理结果。

遇到失败时：停止任务，保留整个事件目录，记录弹窗文字和日志；先验证三份正式文件，再决定恢复。不要删除唯一备份，不要手工伪造 `RESOLVED_*` 标记，不要只修改运行状态中的指纹来绕过门禁。

## 8. 最小示例

```json
{
  "schema_version": 1,
  "config_id": "primary-account-plan",
  "timezone": "Asia/Shanghai",
  "profiles": {
    "00000000-0000-4000-8000-000000000001": {
      "display_name": "A1",
      "account_aliases": ["A1", "153****9621", "U123456789A"],
      "task_config": {
        "Which to Farm": "Tacet Suppression",
        "Which Tacet Suppression to Farm": 1,
        "Which Forgery Challenge to Farm": 1,
        "Material Selection": "Shell Credit",
        "Farm Nightmare Nest for Daily Echo": true,
        "Nightmare Which to Farm": ["Tacet Discord Nest"],
        "Tacet Discord Nests to Farm": [],
        "Auto Farm all Nightmare Nest": false,
        "Weekly Garden Check Day": "无",
        "Merge Echo on Sunday": false,
        "备用识别名称": "使用",
        "备用识别名称内容": "U123456789A"
      },
      "schedule": {
        "mode": "daily",
        "local_time": "04:00",
        "weekdays": [],
        "extensions": {}
      },
      "extensions": {}
    }
  },
  "sequences": {
    "序列一": ["00000000-0000-4000-8000-000000000001"]
  },
  "extensions": {}
}
```

示例 UUID 和账号名仅用于展示，不能复制到多个真实账号。

## 9. v1.08.00 序列恢复、配置包和备份

### 9.1 遗漏序列恢复

首次锚定会同时检查 `daily_profiles.json` 顶层 `sequences` 与
`MultiAccountDailyTask.json` 的 `序列 N 账号`：只有一方有数据时采用该方；两方规范化后一致时正常迁移；两方都非空但不同、成员未知或身份歧义时停止并报告，不能自动取并集。

如果总配置已经存在且合法，但 `sequences` 为空，程序会只读检查旧多账号任务文件。能够把所有成员唯一映射到现有 UUID 时，启动前向用户显示序列数和账号数。用户确认后，总配置、工作副本和运行状态作为同一事务更新并复检；失败时三份文件按原始字节回滚。总配置已有非空序列时该恢复入口不会覆盖它。

### 9.2 账号配置包 v2

v2 导出文件是可读 JSON，顶层包含：

- `manifest`：程序版本、导出时间、配置 ID、能力和分区 SHA-256；
- `master_config`：账号、任务设置、备用名和序列的权威快照；
- `runtime_data`：按稳定 UUID 保存的完成记录和断点；
- `preferences`：当前序列等非权威偏好，不包含过期的“当前执行账号”；
- `extensions`：未来扩展。

`runtime_data` 只携带可跨设备的进度和未来可移植字段；`accepted_master_fingerprint`、
`last_accepted_fingerprint`、`last_integrity_event` 和 `last_bundle_import` 属于当前安装，导出时删除，
导入后由目标设备重新生成。旧 v1 账号内的 `last_completed` 会迁移到该账号 UUID 对应的
`runtime_data.completed_at`，不会继续混入总配置。

导入先做纯内存预检，不写文件。原生 v2 缺少任一分区校验、格式过新、未知类型、账号 ID 非法、别名歧义或序列引用悬空时必须阻止。导出后被外部工具修改会显示 SHA-256 变化；结构仍合法时，只有用户再次明确选择信任才可导入。旧 `okww_account_config` v1 会先转换为稳定 UUID schema。

确认导入后，程序先制作事务快照，再替换总配置、从总配置重建工作副本、按 UUID 恢复运行状态并执行完整性复检。包内不存在的 UUID 运行记录进入隔离字段，不能按相似名称错配给其他账号。

### 9.3 完整配置备份

每日快照和导入/恢复前事务快照都复制完整 `configs`，并以 `manifest.json` 记录每个文件的相对路径、长度、修改时间和 SHA-256。临时目录验证通过后才发布为完整快照。

- 每日快照最多 30 份；
- 事务快照最多 20 份；
- 两类快照总量最多 2GB；
- 超限时删除最旧的完整快照目录，不拆散快照内容。

恢复预检会显示快照内总配置是否存在、账号数、序列数和各序列成员数；总配置存在但完整性图不合法时禁止恢复。完整恢复会先重校验暂存副本，再替换整个配置树并执行最终完整性检查，失败时立即换回原目录；成功后必须重启程序。`.restore-journal.json` 只允许引用本配置目录及本备份目录内的暂存路径，用于进程中断后的受限恢复。运行端 AI 不得手工删除 journal、staging 或 rollback 目录。

### 9.4 账号切换失败证据

切换期间最近 60 秒、最多 30 帧只保存在内存，成功后立即丢弃。失败或用户安全停止时才写入
`screenshots/account_switch_failures/<时间>_<事件ID>_<阶段>/`：

- `event.json` 记录目标、最后识别身份、失败阶段、重试和交互方式；
- JPEG 红框标出目标 OCR 框；
- 红色圆圈和十字标出尝试/实际点击位置；
- `delivered` 区分实际投递成功与只尝试未送达；
- 同时记录窗口坐标和屏幕坐标，便于判断换算偏差。

失败证据按 7 天、20 个完整事件、500MB 三重上限清理，启动时立即检查，运行中每 6 小时检查一次。运行端 AI 报告切换问题时应连同脱敏日志提供完整事件目录，不要只提供最后一张截图。

## 10. 运行端 AI 禁止事项

- 不得替用户点击首次锚定、总配置覆盖、运行状态重建或异常知晓按钮。
- 不得在总配置缺失、损坏、身份歧义或差异未解决时绕过任务门禁。
- 不得删除或重建合法已有 UUID，不得依赖账号列表固定行号，不得把 A1 与 A10 模糊匹配。
- 不得把完成时间、游标、密码、PAT、鉴权 URL 或二维码凭证写进总配置、日志或回复。
- 不得为了“让检查通过”只改 `accepted_master_fingerprint`。
- 不得删除事件目录、原始工作副本或运行状态来掩盖失败。
- 不得使用程序内部通用 JSON 写入接口修改总配置；正常修改必须由程序外工具完成并重新验证。

运行端 AI 不确定时，应保持安全模式，收集 `manifest.json`、`integrity.log` 和三份配置的结构性摘要（敏感值脱敏），再请求测试端分析。
