# GameFrame 原生用户脚本包迁移计划

本计划承接 v1.97.70 单任务存储，实施时间在 v70 发布之后。本次只形成设计，未修改导入、执行或发布代码。目标是恢复旧用户脚本业务的导入、导出、多根 Python 任务、随附素材命名空间、脚本名分组和整组删除，同时保持稳定任务/配置/计划身份和单 catalog 原子发布。

## 已确认的旧业务与边界

| 事实 | 实际代码依据 |
|---|---|
| `.okscript` 是 ZIP，根 `manifest.json` 仅含 `file_name/script_name/version`；根选中的 `.py` 是任务，其他非 Python 文件均随包导出，跳过 `__pycache__` | `.venv/Lib/site-packages/ok/gui/tasks/ScriptPackager.py:66` |
| 导出界面选择本地 `ok_tasks` 根 Python 文件，输出 Downloads；旧编辑器只编辑该目录，不编辑导入包 | `EditTaskTab.py:446`、`:1021` |
| 旧导入将同名包删除后解压到 `cwd/ok_import/<file_name>`；根 Python 文件按 AST 顶层类顺序，实例化首个实际 BaseTask/TriggerTask 子类 | `ScriptPackager.py:130`、`TaskManger.py:163`、`:387` |
| `import_namespace=file_name` 是任务标记，`group_name=script_name` 是显示分组；没有自动给特征调用添加前缀 | `TaskManger.py:67`、`:177`；全仓 `import_namespace` 调用搜索 |
| 本地 `ok_tasks/assets/coco_annotations.json` 不加 namespace，导入素材使用实际包目录名 `<file_name>/<category>`；图片路径相对 COCO 文件夹 | `ok/feature/FeatureSet.py:146`、`:158`、`:423` |
| 旧导入会停全部一次性任务及自定义/导入服务，替换同名实例并刷新素材；整组删除卸载任务、删包目录、刷新素材 | `TaskManger.py:135`、`:211` |
| 旧新建任务模板实际生成 `from ok import BaseTask`；Box/Logger/配置/异常等已有包内原生实现 | `EditTaskTab.py:892`；`src/runtime/combat_api.py:37` |

导入归档是实际外部文件边界，需要安全解包和明确格式校验。验证会执行可信用户 Python，仍使用用户权限，不是安全沙箱。旧 importer 的直接删除目录、`extractall`、扫描 cwd 和停内置服务不迁移到原生实现。原生在已有 owner 重载边界应用新注册表，不因导入/删除而保存服务 disabled 偏好。

## 原生格式与不可变快照

原生归档仍可使用 `.okscript` 扩展名，必须以根 manifest 的 `format` 区分，不能靠扩展名猜测执行协议。根 Python 文件和 `assets/` 目录布局沿用旧包，原生 manifest 显式声明任务导出类与能力：

```json
{
  "format": "okww-native-user-bundle",
  "format_version": 1,
  "file_name": "daily-tools",
  "script_name": "我的每日工具",
  "version": "1.0.0",
  "tasks": [
    {
      "key": "daily",
      "path": "Daily.py",
      "class_name": "Daily",
      "required_capabilities": ["frames", "keyboard", "mouse"]
    },
    {
      "key": "watcher",
      "path": "Watcher.py",
      "class_name": "Watcher",
      "required_capabilities": ["frames"]
    }
  ]
}
```

`key` 是包作者保留的任务身份，必须唯一且非空；`path` 是根 Python 文件相对路径，`class_name` 是该文件精确导出。同文件可声明多个不同类，分别拥有 key；同文件重复导出同类拒绝，避免 Host 的按 class 注册去重吞掉任务。任务列表非空，能力使用当前 GameFrame 名称。类名或文件名改变时保留 key；`file_name` 是脚本包身份，`script_name/version` 仅为包元数据。

`file_name` 作为逻辑名称使用旧文件名字符集合，但拒绝空值、`.`、`..` 及路径分隔符。物理路径使用 UUID，不把名称拼成目录。保留名称大小写，身份按精确名称比较；导入界面展示同名替换，不默默把名称变化当成更新。

快照结构为：

```text
data_dir/user_tasks/
  catalog.json
  <standalone-source-UUID>/revisions/<source-SHA256>/task.py
  bundles/<bundle-UUID>/revisions/<bundle-SHA256>/
    manifest.json
    files.json
    Daily.py
    Watcher.py
    assets/coco_annotations.json
    assets/<image files>
```

`files.json` 沿用核心现有文件 SHA256 索引格式：相对路径到摘要，排除索引文件自身。`bundle_revision` 是排序、规范化索引 JSON 的 SHA256，涵盖 manifest、全部源码和资源文件；不由 ZIP 时间戳、压缩顺序或声明 version 决定。原生导出生成索引，导入必须验证；旧包迁移在转换完成后生成索引。拒绝输入归档的 `.pyc/__pycache__`，不把缓存当源码。

快照先在同文件系统临时兄弟目录写入并 fsync，再原子改名为摘要目录。现有同摘要目录核验内容一致后复用。快照提交不等于任务已发布，只有 catalog 的一次 `os.replace` 使整组可见；失败留下的未引用快照不构成假成功。本阶段不增加自动清理或新保留策略。

## 稳定身份与单 catalog

采用标准库确定性 UUID，避免新增映射文件、第二个发布指针或 catalog 墓碑表：

```python
bundle_id = uuid.uuid5(uuid.NAMESPACE_URL, 'okww:user-bundle:' + file_name)
source_id = uuid.uuid5(bundle_id, task_key)
task_id = 'user:' + str(source_id)
config_name = 'user_' + str(source_id)
```

身份作用域仍是明确 data_dir。相同 file_name/key 再导入必然绑定旧 source_id，即使源码、导出类、相对文件名、素材或包版本改变。删除整组再导入同身份可重新绑定原配置和计划；改 file_name 或 key 明确产生新身份。不按类名、显示名或文件 SHA 猜测对应关系。现有独立任务继续使用 v70 UUID4，不重算其身份。

catalog 顶层仍只有 `api_version/revision/tasks`，revision 继续是完整 tasks 列表规范化摘要。每个包任务增加以下字段，所有同 bundle_id 的有效行必须指向同一快照：

```text
bundle_id, bundle_revision, bundle_file_name, bundle_title, bundle_version,
bundle_task_key, source_path, asset_namespace
```

通用 `default_config` 继续为 `{}`；原生持久配置默认保留在 `metadata.default_config`。`source_revision` 是该导出文件真实 UTF-8 字节 SHA256；任务 `revision` 是完整行的定义摘要，包含 bundle_revision、类、key、能力和真实元数据。因此只改素材也会改变运行定义 revision，执行前核对不能误用旧素材。

同名重导入读取旧 catalog、计算全部新行，然后在现有 user_tasks writer mutex 内重新读取 catalog、核对 expected_revision，一次替换该 bundle 的全部旧行。其余独立任务和其他包行不变。新增 key 加任务；缺失 key 从有效 catalog 移除，但保留配置、旧源码和旧快照。不逐任务调用现有 save/delete，因为中途失败会发布半组。整个包的 validation、schema 或资源失败均保留旧 catalog 字节。

整组删除同样只在一次事务内移除所有 bundle 行，不删持久配置、计划记录或快照。界面不允许把导入包成员通过独立任务 save/delete 悄悄拆散；旧编辑器本来只编辑本地任务，因此本阶段导入包成员可读、可整组重导入/导出/删除，独立任务仍按 v70 编辑。

## Store 和配置 owner 接口

在 `NativeUserTaskStore` 中扩展事务入口，归档解析/迁移放入新包内文件 `src/runtime/native_user_task_bundles.py`，不另建管理器：

| 接口 | 行为 |
|---|---|
| `inspect_bundle(archive_path)` | 不执行 Python；识别 native/legacy，安全 stage、读取 manifest/源码，返回 archive SHA、任务声明或待选择类、迁移差异/未知导入、包信息和文件列表 |
| `import_bundle(archive_path, *, expected_revision, expected_archive_sha256, migration_tasks=None)` | 对用户刚审阅的归档重新核对 SHA；native 使用显式 tasks；legacy 使用用户确认的 key/class/capabilities；全组真实隔离验证后一次发布 |
| `list_bundles()` | 从当前 catalog 行按 bundle_id 聚合；返回分组、成员和当前 bundle/catalog revision，不扫描磁盘推断有效包 |
| `export_bundle(bundle_id, output_path, *, expected_revision)` | 从一个 catalog 快照导出完整同组快照与索引；核对 revision，不执行代码，不写原源包或 cwd |
| `export_tasks(source_ids, output_path, *, file_name, script_name, version, expected_revision)` | 对选中的独立任务生成原生包；key 使用现有 source UUID，文件名用 UUID 避免同类名冲突；首次导入该导出包拥有确定性包任务身份 |
| `delete_bundle(bundle_id, *, expected_revision)` | 一次移除整组 catalog 行，返回新 catalog revision；删除不清空 disabled/enabled 偏好 |

`export_tasks` 只处理独立任务，`export_bundle` 处理完整导入组；不把多个已有 namespace 的包合并成新包，因为这会改变源码中的素材名。导出先写目标目录临时 ZIP，再原子替换用户明确选定目标；不默认覆盖既有文件。界面已有保存文件对话框负责明确目标和覆盖确认。

`src/runtime/native_configuration.py` 增加 `user-bundle-inspect/import/list/export/delete` 以及独立任务选择导出命令，沿用现有 request_id、错误报告、disk catalog revision 与 applied revision。inspect 返回源码差异仅供审阅，import 才运行验证；hash 不匹配报告文件已变化，要求重新审阅，不自动重试。import/delete 成功后配置 owner 使用现有 `reload_user_tasks`；失败如实显示“磁盘已发布、当前进程未应用”，保持现有协议。

`NativeUserTaskTab` 增加导入、选中本地任务导出、整组导出/删除，列表按 bundle_title 分组并显示版本；脚本名可同名，动作绑定 bundle_id。legacy 审阅界面显示每文件 import 改动、显式类/key/capabilities、拒绝位置；不沿用旧 15 秒倒计时或把 AST 改写称为完整兼容。配置表单使用 metadata 的 group_name 显示包分组，任务选择保持稳定 task_id。核心仍读取通用 JSON，不导入 bundle 代码或解析 COCO；需要选择器显示分组时只增加可选通用 group 字段，不让核心依赖 bundle 实现。

## 安全 stage 与核心复用

核心现有 `gameframe/packages.py:168 extract_archive` 的解包循环已拒绝越界、反斜杠/盘符、symlink 和重复路径，并逐文件 exclusive 创建；函数后半段强制单个游戏包目录和 PackageManifest，不能直接拿来解脚本包。

最小修改是将该循环抽成 `extract_zip_members(archive_path, staging)`，要求 staging 是调用方新建的绝对空临时目录；现有 extract_archive 调它后保持原元数据/索引验证行为。脚本包调用同一个 helper，不复制另一套 extractall。脚本包 manifest 的路径严格限制在 stage 内，root task path 指向真实文件；COCO 的图片引用也解析到快照内，拒绝绝对/越界引用、缺失图片和无效 JSON。资源限制来自用户归档及实际 native read_from_json 契约，不新增无依据的大小配额、重试或外部路径 fallback。

`verify_index(root, required=True)` 已不依赖 PackageManifest，可以直接复用 native 脚本包；无需再写索引检查器。ZIP/path 失败只清理 stage，不动旧 catalog/快照，不删用户给出的源文件。

## 旧包一次性 AST 源码迁移

先读全部 Python 文件并 `ast.parse`，检查每一个 `Import`/`ImportFrom`，包括函数内部、条件分支和辅助文件。已确认的 import 符号只改 import 的模块路径，保留名字与 `as` 别名；不是 `sys.modules['ok']` 替身、运行时 monkey patch 或 legacy worker。

首版转换范围由当前 `combat_api` 的真实公共符号决定，明确固定清单，不“尝试 getattr 后兜底”：

| 旧来源 | 可迁移名字 | 新来源与依据 |
|---|---|---|
| `ok` | `BaseTask`, `TriggerTask`, `Box`, `Logger`, `Config`, `find_boxes_by_name`, `sort_boxes`, `find_color_rectangles`, `safe_get`, `TaskDisabledException`, `FinishedException`, `CaptureException`, `WaitFailedException`, `CannotFindException` | `src.runtime.combat_api` 已有明确原生映射；新建模板的 BaseTask 是实际最小必须项 |
| `ok.task.task` | `BaseTask`, `TriggerTask` | 旧 TaskManager 使用的真实类来源，映射到同一 combat_api |
| `ok.feature.Box` | `Box`, `find_boxes_by_name`, `sort_boxes` | combat_api 已有真实原生几何实现 |
| `ok.util.logger` | `Logger` | combat_api → native_logging.Logger |
| `ok.util.config` | `Config` | combat_api → native_config.Config |
| `ok.task.exceptions` | 上列五个异常及 `HotkeyConfigException` | combat_api → native_errors 的同名真实类型 |
| `ok.util.collection` | `safe_get` | combat_api 已有实现 |
| `ok.util.color` | `find_color_rectangles` | combat_api → src.vision.color |

`BaseScene` 虽在 combat_api 中存在，但当前是仅 reset 的最小类型，不能据此宣称旧完整 scene 兼容，首版不迁移。`FindFeature/OCR/og/communicate/run_task/ConfigOption/FeatureSet`、设备/UI模块、未知 ok import、星号导入、`import ok` 及动态导入 ok 均明确报告需要人工迁移，不改成假对象。已观察的生产代码使用 `get_bounding_box/find_boxes_within_boundary` 等不在当前 combat_api 公共映射内，本阶段不为迁移顺手扩大 API。符号可导入不证明用户 run 行为已经等价；真实无设备构造、schema 验证之外的能力仍在 Replay 验收范围说明。

实现使用 AST 定位被允许的 ImportFrom，替换源文本中该节点的模块名范围，再重新 parse 确认变换；UTF-8 AST 列偏移按字节处理。不要整文件 ast.unparse，以免移除用户注释、格式和可审阅上下文。报告列出文件/行号、旧 import、新 import 及拒绝原因。不改方法体、特征字符串、业务流程或能力声明。

legacy 没有显式 classes/capabilities：inspect 展示根文件顶层类列表及直接已知原生基类候选，用户确认每文件的导出类和所需能力后 import。有多个候选、间接继承或缺能力时不能凭源码猜测直接发布。初次迁移 key 默认是根文件名（独立于类名）；后续 native 包保留这个 key，文件/类改名才能保持身份。未知导入或验证失败拒绝整组，源 `.okscript` 保持原字节，不生成“已兼容”包。原包 file_name 作为 namespace 保留，`self.find_feature('包名/特征')` 无需转换。

多根任务按独立模块精确加载，不往全局 sys.path 增加包根。模块名包含 bundle UUID、bundle_revision 与文件名，隔离同名模块和旧 snapshot；同文件多导出只执行一次源码再验证各类。首版不宣称旧包跨文件裸 `import OtherTask` 自动兼容；这类根内模块依赖在 inspect 中报告，需将代码整理为独立任务或在后续明确需求下实现标准相对包导入，不能靠根 sys.path/shim 悄悄解析到旧包。多根任务发布和资产共享本身不要求跨文件 Python 导入。

## 真实验证、素材注册与 owner 重载

扩展 `native_user_task_validation.py`，每个候选 bundle 只启动一次既有隔离子进程，使用 under-mutex 复制的 configs/accounts 和临时 AccountRuntime。先加载全部显式类，再通过同一个真实 NativeCombatHost 构造、after_init 并取得 TaskMetadata；一个失败即全组失败。没有真实 device、Scheduler 注册或账户切换。不能在验证脚本里构造一套简化 task 替身。

`load_tasks()` 读取一个 catalog 快照，核验每 bundle 的索引/摘要、各源码 SHA 后加载模块。descriptor 增加 `group_name` 和明确 `coco_path/asset_namespace`，只指向当前不可变快照。`asset_namespace` 对导入组固定为 file_name；不扫描 cwd，也不把素材名自动加前缀。对不带 COCO 的包不添加空 feature source。

NativeCombatHost 在构造 task 前将 bundle COCO 去重后调用现有 `FeatureSet.add_coco(path, namespace=file_name, overwrite=True)`，并在 after_init 前注入 group_name/import_namespace。既有主素材注册保持原规则。JSON/path/image 验证在 store 外部边界完成，Host 不逐层重复检查。

重载需要同时替换任务与素材 registry：用主 COCO 加新 descriptors 创建候选 FeatureSet；在现有 owner 请求边界、输入释放后暂时绑定候选用于 task 构造/metadata 检查，失败还原旧 FeatureSet 和注册表。全部成功才提交候选 FeatureSet、task registry、requirements、metadata actions、选择和 applied_revision。不能对现有 FeatureSet 逐个 add_coco 再遇错返回，因为删除素材和失败回滚都会留下部分新状态。既有 builtin task 持有同 executor，提交后自然使用新 FeatureSet，不需重构所有 builtin 实例。

保存/删除不主动 disable 内置或自动战斗，不清偏好。运行 worker 和配置 owner 各自显式应用整个 catalog；暂停时能保存但不触发游戏输入。单次执行前仍使用完整 task revision 核对，asset-only 更新也会使旧运行定义拒绝启动并提示重新选择/加载。

## 最小实施文件与顺序

| 步骤 | 文件 | 交付 |
|---|---|---|
| 1 | `gameframe/packages.py`、现有 archive tests | 提取安全 ZIP 成员 helper，保持游戏包单根/索引契约 |
| 2 | 新 `src/runtime/native_user_task_bundles.py`、新 `tests/TestNativeUserTaskBundles.py` | native manifest、索引/tree digest、只读 inspect、AST迁移、原生导出 |
| 3 | `native_user_tasks.py`、`native_user_task_validation.py`、`TestNativeUserTaskStore.py` | UUID5身份、全组 isolated validation、一次 catalog import/delete、bundle descriptor |
| 4 | `native_combat_host.py`、`native_metadata.py`、Host/Replay tests | group元数据、显式素材注册与任务/素材一起重载 |
| 5 | `native_configuration.py`、`NativeUserTaskTab.py`、配置Qt测试；需要核心选择器分组时 `packages.py/gui.py` | 审阅、导入导出、按ID分组及整组删除，applied/disk状态一致 |
| 6 | 既有 installed payload/build tests、版本/发布文档 | 最终分发物验证后再按 AGENTS 更新版本与发布，不抢占 v70 |

## 必要检查与验收限度

1. 合成两根 task Python 加小 COCO/PNG，真实独立验证进程和 Host；导入同名更新、改类名保留 key、仅改资产、新增/移除 key，确认 ID/config/计划绑定与完整 revision 行为。
2. 第二个任务构造失败、未知 ok import、非法 schema、失配索引、越界 ZIP/manifest/COCO引用、catalog 原子替换失败时，旧 catalog 原字节、旧运行 registry 和旧素材都保留；源归档不被改写。
3. 并发两个真实 writer 持相同 catalog expected_revision 时仅一个全组发布成功；没有半组或丢失其他包/独立任务。
4. AST fixture 覆盖实际 BaseTask 模板、TriggerTask、Box/Logger、别名、多行和非ASCII注释；逐项核验明确允许模块与未知拒绝，差异只含 import 目标变化。迁移后当前进程不得加载 `ok`/Qt legacy provider。
5. 导出→新 data_dir 导入→再导出，核验 manifest类/能力、源码字节、资源索引、任务数量、namespace特征与整组删除。独立任务导出成为新包身份，不能断言跨data_dir复制私人配置。
6. 真 FeatureSet 使用内存合成帧确认 `<file_name>/<category>` 可找到、不同包同category不串用；同包asset更新应用新模板、删除组去掉旧模板；候选失败回到旧模板。owner reload保持显式pause/stop信号、输入释放和自动战斗偏好。
7. Qt无设备选择/审阅/导入/导出/删除与 installed payload 各做最小有效验收，报告已保存与已应用区别。全部使用临时配置、合成账户、Replay/无设备进程；不做游戏/模拟器、真实账号、NAS 或真实Scheduler操作。

这些检查通过证明归档、构造、元数据和合成 Replay 路径成立，不能声明任意旧脚本战斗业务已兼容或已在真实游戏运行成功。遇到真实待迁移包的新 ok 符号/根模块依赖，再按具体证据扩充范围。
