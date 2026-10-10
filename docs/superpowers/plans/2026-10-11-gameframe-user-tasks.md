# GameFrame 用户任务迁移计划

**Goal:** 独立游戏包提供原用户任务编辑/注册/执行能力，配置与计划绑定不随源码类名改变，运行中可以在输入释放边界明确重载。

**Architecture:** 包声明相对于data_dir的task_catalog文件；核心只读取通用JSON任务元数据，不导入用户代码来发现任务。游戏包把来源UUID、不可变源码revision和导出类写入同一catalog。源码先独立验证并保存到revision目录，再原子发布catalog；运行owner构造候选注册表后在现有会话请求边界替换。配置owner和实际worker分别报告已加载revision，保存不等于所有进程已应用。

**Tech Stack:** Python标准库、已有NativeBaseTask/NativeTriggerTask、现有配置JSONL/Qt编辑器与Replay。不新增脚本运行时或伪造ok API。版本1.97.70，禁止游戏/模拟器、NAS与真实账号。

## 明确接口

任务catalog为`user_tasks/catalog.json`，其通用字段是`api_version`、`revision`及`tasks`，每项保留核心TaskDefinition字段；包内扩展source_id、source_revision、class_name。ID为`user:<UUID>`，配置名为`user_<UUID>`。不可变代码在`user_tasks/<UUID>/revisions/<SHA256>/task.py`。catalog发布为单一原子提交，修改/删除保留配置和旧revision，不删除私人数据。

`NativeUserTaskStore(data_dir)`提供`list/read/save/delete/load_tasks`。save输入code、class_name、可选source_id和expected_revision、required_capabilities；新建生成UUID，编辑保持UUID。独立验证子进程使用临时配置和明确native provider，验证精确导出类、BaseTask类型、构造与JSON元数据；此进程执行可信用户代码，不是安全沙箱。无效语法/构造/元数据不会发布catalog。

`load_tasks()`返回descriptor列表，每项包含`task_class/id/config_name/source_revision/required_capabilities`。NativeCombatHost构造增加`user_tasks=()`并接受class形式task_entry；task_id与Config文件名在after_init前显式注入。reload_user_tasks先构造所有候选，再更新tasks、executor registry、requirements、metadata actions和选择。失败保持旧运行注册表，报告保存revision与运行revision的差异。不能调用disable来卸载服务，也不能清空自动战斗偏好。

核心PackageManifest增加可选task_catalog相对路径，`task(task_id, data_dir=None)`和`available_tasks(data_dir=None)`合并内置和纯JSON外部定义，拒绝覆写内置ID/重复项及越界路径。Controller、worker和Runtime把明确data_dir传给解析；GUI读取所选包的数据目录catalog，保持稳定ID选择。worker在共享数据锁内再次解析，执行前核对实际定义和capabilities。

## 责任和实施

| 负责人 | 文件 | 本阶段交付 |
|---|---|---|
| 来源/存储代理 | src/runtime/native_user_tasks.py、native_user_task_validation.py、专用tests | 不可变源码revision、UUID身份、原子catalog、独立无设备验证、读取/删除及加载descriptor |
| 运行owner代理 | native_task.py、native_metadata.py、native_combat_host.py、对应tests | Config独立命名、候选构造与安全替换、按当前稳定ID处理队列和服务、明确applied revision |
| 核心代理 | packages.py、controller.py、worker.py、runtime.py、gui.py、对应tests | 动态任务贯通GUI/CLI/worker/Runtime，保持metadata-only发现与能力核验 |
| 主代理 | native_configuration.py、NativeConfigurationTab.py、NativeUserTaskTab.py、ManagementWindow.py、plugin.py、manifest/build/version/docs | 编辑/保存/删除接口与Qt页、源码/运行状态区分、包启动实际加载用户任务、整合验收备份发布 |

## 验收

- 两来源同类名配置隔离；同来源改类名保留配置、任务和计划ID；同mtime/长度更改实际加载新revision。
- 语法/导入/构造/元数据失败保留旧catalog；版本冲突不覆写另一个窗口的新编辑；删除后稳定ID明确不可运行，旧配置保留。
- 真实Replay主入口与安装payload执行动态ID，框架实际核验其capabilities；启动器可选择用户任务。
- 重载等待前台finally与后台checkpoint/release_all，候选失败保持旧注册表；新registry、schema/actions、延迟请求均按稳定ID一致更新。各worker只报告自己的applied revision。
- pause期间保存不触发设备输入；服务替换和删除不保存disabled偏好，内置自动战斗意图不变。
- 独立复核、最终分发物与已有关键路径必要回归，本地备份和按AGENTS发布。随后继续角色编辑、设备/设置与其他剩余迁移。
