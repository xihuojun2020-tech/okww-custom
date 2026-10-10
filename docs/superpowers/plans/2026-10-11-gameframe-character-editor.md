# GameFrame 原生角色编辑实施计划

**Goal:** 独立游戏包恢复角色源码阅读、自定义编辑、保存、重置和模式选择；自动战斗只在释放输入后的明确请求边界应用新代码，保留启用意图。

**Architecture:** Qt 只编辑字符串和调用现有配置 JSONL 子进程。配置服务验证并发布角色源码，执行 owner 使用固定的已应用角色类映射；磁盘保存与每个 owner 的应用分别报告。显式重载先构造全部候选，在现有会话安全边界替换映射和角色对象，并失效队伍确认、重建轮转状态。

**Tech Stack:** 现有 NativeCombatHost、combat_api、CustomCharLoader、CharFactory、BaseChar、RotationState、Qt QPlainTextEdit、标准库、配置写锁与 Replay。

**执行约束:** 用户已授权自主实施和必要验证，不增加审批阶段。本阶段只写计划；v70 发布后由主代理分配存储、host、GUI 所有权。共享代码不回退他人修改。禁止游戏、模拟器、真实账号、NAS和真实系统输入；版本、备份和发布由主代理统一处理，不在计划中预定未授权版本号。

## 已核实行为与缺口

- `src/gui/CharacterCodeTab.py` 依赖 `ok.gui` 编辑器和 CustomTab，不能直接移入原生 Qt 进程。真实功能包括去重角色列表、内置只读、自定义编辑、切换时未保存确认、保存、重置、模式选择、与内置源码的差异高亮、复制 Ask AI 文本、帮助和贡献链接。头像功能当前默认关闭。
- 保存与内置源码完全一致会删除自定义文件并切回内置。没有自定义源码时选择自定义只打开可编辑草稿，保存前不启用自定义模式。
- `src/char/CustomCharLoader.py` 已通过 combat_api 取 Config/Logger；布局是 `data_dir/configs/custom_chars/<Class>.py` 和同目录 `custom_chars.json`。精确导出类名、BaseChar 继承、源码 compile、默认 solo 复用自定义 do_perform 可以复用。原 loader 的读错误 fallback 和模式 JSON 错误变空字典不能作为原生验证成功。
- loader 每次识别读磁盘模式和源码缓存，缓存是 mtime/size。配置进程保存可能让另一 owner 未经明确重载看到新代码，且完全相同时间和长度可命中旧缓存。
- `BaseCombatTask.load_chars()` 在 `_battle_roster_confirmed`、context 和人数匹配时直接返回；只 clear cache 或调用 `load_chars(reset_state=True)` 不足以更新角色。
- `_char_identity()` 仅比较 `(char_name, char.name)`。同名源码 v1/v2 不会触发现有 identity_changed，因此必须明确重建 RotationState。
- 真实 `BaseChar.perform()` 没有设置 `_in_action`。不能拿旧 GUI 的该标志作为原生安全边界。
- `NativeCombatExecutor.SessionPreempted` 是 BaseException，后台收到请求后从既有 checkpoint 退出；AutoCombatTask.run 的 finally 释放 task 输入，host 的 finally 再 release_all。这个已存在的边界可以复用。

## 最小接口和文件职责

| 文件 | 责任与最小接口 |
|---|---|
| `src/runtime/native_characters.py`（新增） | 明确 data_dir、允许编辑的注册类、源码读取、冲突 token、独立验证和发布；`NativeCharacterService(host)` 的 `list/read/save/reset/set_mode/load_snapshot` |
| `src/runtime/native_character_validation.py`（新增） | 独立 native 子进程，在临时配置与真实 no-device Host 下验证精确导出、BaseChar 类型和角色构造，不执行 perform |
| `src/char/CustomCharLoader.py` | 保留 legacy 行为；新增明确 native owner 绑定/读取已应用 class-map，严格候选加载复用精确类名和 solo 规则，缓存以源码 digest 识别 |
| `src/runtime/native_combat_host.py` | 启动绑定 snapshot；`reload_character_code()` 构造全部候选并在会话请求边界提交，报告 own applied_character_revision |
| `src/task/BaseCombatTask.py` | 必要的小接口负责角色对象候选/提交及 roster/RotationState 失效；不改普通轮转或做无关重构 |
| `src/runtime/native_configuration.py` | `character-list/read/save/reset/set-mode` JSONL 服务；配置 owner 可立即应用，结果区分 saved/applied |
| `src/gui/NativeCharacterCodeTab.py`（新增） | 原生角色列表、模式、只读/编辑状态、保存/重置和既有帮助功能；所有源码由配置子进程返回 |
| `src/gui/NativeConfigurationTab.py`、`src/gui/ManagementWindow.py` | response/schema/busy 接线；纳入 pending、维护冻结与关闭等待 |
| `gamepacks/wuthering_waves_native/plugin.py` | 启动配置/执行 owner 的 snapshot；实际单次任务明确重启后应用，session 允许显式 reload |
| 专用 `tests/TestNativeCharacter*.py` | 存储/验证、Qt 和 Replay 安全边界的独立验证，避免加载真实设备或模型 |

### 来源服务

固定身份是安装包当前 CharFactory 注册的内置类名，例如 Mortefi。先去重注册类；客户端只能提交这个允许列表中的名字，不接受任意路径、任意导出类改名或新增视觉 Label。

```python
service.list() -> {characters: [...], saved_revision: str}
service.read(class_name) -> {
    class_name, display_name, builtin_code, custom_code, has_custom,
    use_custom, source_revision, saved_revision
}
service.save(class_name, code, *, expected_revision) -> read_result
service.reset(class_name, *, expected_revision) -> read_result
service.set_mode(class_name, use_custom, *, expected_revision) -> read_result
service.load_snapshot() -> {revision: str, classes: {builtin_class: effective_class}}
```

- revision 是一致源码/模式快照的 digest；source_revision 是该角色源码 digest。read 的 token 才绑定当前编辑稿，list 刷新不能悄悄升级旧稿 token。
- 保留既有源码/模式路径。原生读、保存、重置、模式更改和 load_snapshot 都在同一个 `get_account_change_lock(custom_root)` 下取一致快照。验证在写锁外运行；发布前再次核对 expected_revision，避免验证期间另一窗口的修改被覆盖。
- 写源码用同目录临时文件和 os.replace；模式用已有 atomic JSON 写法。借用现有失败回滚语义保留旧源码和模式，不吞异常；不宣称两个文件具备额外的掉电原子事务保证。
- save 先语法和独立语义验证；精确 class 必须继承 BaseChar。通过后发布并选 custom。save == builtin 与 reset 均移除 custom、选择 builtin。set_mode(False) 保留已保存 custom 便于再次选用；不存在 custom 时 GUI 只进入草稿，不调用 set_mode(True)。
- validator 配置 native provider 后才 import 角色，使用临时复制的配置和 AccountRuntime，采用真实 Host.task 作为 ctor 参数，传 index、canonical char_name、confidence、ring_index、char_type、buff_time。设备 None；不运行角色动作。可信 Python 验证不是安全沙箱。
- 模式 JSON 损坏、源码读取或 class 构造失败明确报告；不得用 legacy fallback 的 builtin 返回值冒充自定义已应用。

### 已应用 owner 与安全提交

`CustomCharLoader` 的 native 分支只取显式绑定的 class-map；构造候选 snapshot 时才读磁盘。legacy loader 保持既有路径和行为。native startup 必须绑定 snapshot 后才允许第一次角色识别。每个进程保有自己的 map 和 revision，不广播、不每秒扫盘。

`NativeCombatHost.reload_character_code()` 使用以下顺序：

1. 在既有 session 请求分派处处理 `reload-character-code`。后台 checkpoint 退出当前动作，等待 AutoCombatTask.run finally 和 host release_all；前台等待 run_once/on_destroy/finally 完成。暂停时只做验证、内存更改和既有输入释放，不捕获帧或发送新按下动作。
2. 严格构造新 snapshot，再为所有受影响已加载角色构造替换实例。此时旧 map、chars、RotationState、selection 和 revision 仍完整可用。
3. 使用旧 GUI 的 ctor 参数并复制下列 12 个观察字段：`is_current_char`、`has_intro`、`has_sub_dps_intro`、`last_switch_time`、`last_switch_in_time`、`last_res`、`last_echo`、`last_liberation`、`last_buff_time`、`last_full_con_switch_time`、`last_perform`、`last_outro_time`。已有死亡拒绝和切换冷却标志须保留其实际语义，不能把已死亡队友恢复为可切入目标。未受影响对象保持原对象。
4. 所有候选成功后确认 task 原后端 held input bookkeeping 已释放；已有 release 失败留下 held 项时明确拒绝提交。不要 disable/enable，不修改 `_enabled`、配置偏好、manual generation 或任务拥有者。
5. 一次提交新 class-map 和各任务 chars。每个受影响任务显式结束旧 rotation tracking，设置 `_battle_roster_confirmed=False`、`_rotation_roster_recheck=True`，创建 `RotationState(new_chars)`。不得依赖同名 identity_changed，也不得伪造共享账号 roster context。
6. 下一动作沿现有 prepare_character_rotation/load_chars 重新确认队伍。该检查失败沿原有战斗恢复路径等待，不执行旧脚本。
7. 成功事件 `character-code-reloaded` 附 own applied_character_revision；失败事件明确旧 applied revision。构造或输入释放失败不改旧 map/char/state，也不改自动战斗意图。

角色重载不重建整个任务 registry。配置 owner 没有真实战斗 chars，验证后可以立即绑定自己的 snapshot。保存成功只证明磁盘与这个配置 owner 更新；另一 session worker 要明确请求 reload，单次 worker 要明确重启。单次任务不接受虚假的即时应用结果。

### JSONL 与 GUI

- COMMANDS 增加上述五个 character IO 命令；真实后台及暂停请求在现有 input owner 边界执行，不触发游戏动作。返回 schema 和 result，分别带 saved_revision、applied_character_revision、applied。
- 发布成功但配置 owner 构造新候选失败：返回 ok=False，但保留 result 的新 saved_revision、applied=False 和旧 own applied revision；GUI 必须说明磁盘保存与运行应用的差异。
- NativeCharacterCodeTab 只读服务返回的 JSON/源码，不在 Qt 父进程 import CharFactory、用户角色或旧 CharacterCodeTab。
- 列表按 display_name 显示、class_name 绑定选择；内置 code 合法且可只读查看。新 custom 草稿来自 builtin；dirty selection/mode/reset 保留既有确认行为。diff 高亮用现有 difflib 算法和 Qt ExtraSelection；复制/帮助/贡献按钮沿原有内容，不新增网络后台动作。
- busy_changed 在回复回调完成、可能链式请求发出后报告真实 busy。configuration pending 与角色页 busy 都纳入 ManagementWindow._operations_busy，沿 v70 的维护冻结/关闭状态规则接线。成功 save/reset/mode 可更新 schema，但 list/read 不升级编辑 token。

## 实施顺序与验收

### 1. 服务、快照与独立验证

- [ ] 实现注册角色 allowlist、read/list 和固定路径，验证内置源码能读取。
- [ ] 实现独立 temp/no-device validator，复用源码精确导出与 solo 规则。
- [ ] 实现带 expected_revision 的 save/reset/set_mode，以及 native strict load_snapshot。
- [ ] 验证 invalid syntax/import/base/ctor 保留旧源码和模式；两个编辑者 token 冲突不覆盖；same mtime/same length 仍得到新源码类；mode=False 保留 custom，reset 和 save==builtin 转回 builtin，其他角色不变。

### 2. owner 启动与安全重载

- [ ] 启动绑定 owner map，角色识别使用已应用 snapshot；验证另一 owner 保存不改变这个 map。
- [ ] 抽取必要的 loaded-char candidate/commit 小接口，不修改通用角色调度。
- [ ] 把 reload 接到既有 session checkpoint/request 边界；提交 roster 和 RotationState 失效。
- [ ] 用真实 Replay 和真实 BaseChar 动作检查 key_down → checkpoint preempt → task finally release → host release_all → commit 顺序。构造/release 失败保留原 map/objects/state/revision；自动战斗 enabled 与持久化偏好不变。
- [ ] 用 confirmed roster 和同名 v1/v2 验证新实例、12 字段、未受影响对象及新 RotationState；暂停时不捕获/按下；前台 finally 前不应用。

### 3. 配置协议与 Qt 编辑页

- [ ] 接 character IO、saved/own applied 回复和 ManagementWindow busy/pending/freeze。
- [ ] 做真实 Qt 保存、builtin/custom mode、reset、只读 builtin、invalid/error/conflict、dirty discard 和 refresh 不升级旧 token 检查。
- [ ] 验证配置子进程 no ok/no Qt/no 模型/no 设备；Qt 父进程不导入自定义源码；验证正常关闭及维护期间不丢 pending 请求。
- [ ] 实际 installed payload 运行 metadata/configuration 路径；session 显式 reload 与单次任务 restart 提示一致。

### 4. 必要回归与发布交接

- [ ] 只运行相关 legacy `TestCustomCharLoader`、`TestCharacterCodeTab`，确认没有改变旧 UI 或 solo 行为；使用截图的现有识别检查仅在本次修改触及识别时运行。
- [ ] 复核新增保护分支的依据：源码/JSON/路径是外部输入边界，revision 是真实并发编辑边界，held input 是既有释放故障，confirmed/name identity 是已核实缓存路径。
- [ ] 主代理统一更新版本、发布说明和包清单；必要检查完成后按 AGENTS 备份、commit、annotated tag 和 push。不以离线 Replay 通过冒充真实游戏运行通过。

测试一律使用仓库 `.venv/Scripts/python.exe -I -X utf8`，在测试入口明确加入仓库 sys.path。各 native/legacy provider 检查独立进程运行，避免已 import 的 provider 模式互相污染。无新证据不扩展全套测试。
