# 2026-10-11 角色、战斗状态与 custom_ok 第二轮审查

本轮完整阅读 `src/char` 的 57 个 Python 文件、`src/combat` 的 3 个文件和 `custom_ok` 的 27 个文件，按技能返回值、队伍身份、轮转交接、输入释放、任务启用状态、截图资源和通知结果追踪实际调用关系。确认并修复 4 处错误，6 项离线回归通过。完整阅读不等于全部运行路径已验证，也不能替代游戏实机验收。

## 已确认错误与修复

| 位置 | 实际错误路径与依据 | 最小修复及检查 |
| --- | --- | --- |
| `src/char/Ciaccona.py:169` | `Cartethyia.is_cartethyia` 在实例初始化和形态切换时赋值；原代码对类执行 `hasattr`，队友存在且为小形态时仍返回 `False`。 | 从 `task.has_char` 返回的队友实例读取形态。fake 覆盖小形态、大形态、队友缺席；修复前小形态断言失败。 |
| `src/char/ShoreKeeper.py:46` | `BaseChar.click_resonance` 明确返回 `(clicked, duration, animated)`；`(False, .5, False)` 仍为真，原来的 `if not tuple` 永不进入既有重击分支。 | 判定 `[0]`。fake 覆盖失败时重击、成功时不重击及切人；修复前失败分支断言失败。 |
| `src/char/Cantarella.py:38` | 循环中 `resonance_available=True`、`click_resonance=(False, 0, False)` 时，原代码按 tuple 真值提前切人，漏掉循环后的声骸处理。 | 判定 `[0]`。fake 覆盖成功时提前切人、失败时继续既有声骸分支；修复前失败场景漏掉 `click_echo`。 |
| `custom_ok/ok/notification/windows_messenger.py:90,134,136` | `_send_content` 在停止请求时返回 `False`，两个 `_send` 入口随后都返回 `True`；正常完成的 `_send_content` 则隐式返回 `None`。因此取消被记为发送成功。 | 两入口直接返回 `_send_content` 结果，正常完成显式 `True`。fake 覆盖普通/会话头快捷入口的成功和取消、内容完成、开始前取消、图片循环取消时恢复剪贴板。修复前两个入口取消场景及内容成功结果失败。 |

这些修改没有增加等待、重试、配置、兼容层或兜底。Ciaccona 的队友缺席分支保留原有行为；另外三处只修正已存在接口的返回值判定。`Ciaccona.py` 的纯颜色函数导入迁移属于同轮其他工作，已保留。

## 共享契约与调用链检查

- `BaseChar.perform` 先调用 `prepare_character_rotation`。后者核验队伍上下文并在角色对象被替换时拒绝旧对象继续轮转。专属单人轴还受 `solo_rotation_enabled` 与角色职责约束。通用角色复用同一技能和切人接口，未确认身份使用短技能超时。
- `CharFactory` 的身份更新使用模板别名与独立帧证据；`CustomCharLoader` 的缓存包含纳秒时间和文件大小，直接执行源码以避免粗粒度 pyc 时间戳，检查继承关系并在类型变化时刷新对象。自定义脚本的轴选择和内置脚本加载失败处理已逐项阅读；本轮未新增兜底。
- `BaseCombatTask.load_chars` 会在未确认身份时保留观测信息并采用通用角色；动作前重试身份识别时会替换列表对象，`prepare_character_rotation` 随即检查当前对象。死亡目标、复活物品冷却及无物品提示分别影响切人资格；死亡、原地复苏和正常战斗结束使用不同信号交接。
- `BaseCombatTask` 记录按住的键、鼠标和原交互后端，轮转准备、恢复和销毁会释放；释放失败保留待释放记录。因此，单个角色缺少局部 `finally` 不能直接认定为永久按键残留。异常恢复会传播任务停止、流程中断、死亡和配置阻断等信号；普通异常的有界退避没有总重试次数关停。
- `Augusta.perform_majesty` 的局部成功路径不清 `in_liberation` 曾列为候选。正常队伍切换在 `BaseCombatTask.switch_next_char:1033` 明确清理，恢复也会重置，故本轮没有按局部遗漏修改；单人实机行为未验证。
- `CombatCheck` 的帧需求由执行器真实边界承担，显式结束与目标暂失分别处理；`RotationState` 记录动作尝试，不能据此证明技能在游戏中释放成功。
- `TaskExecutor` 串行派发前台/后台任务，持久触发任务的普通探测或执行异常不覆盖启用偏好。`TaskCard` 回显启用状态使用 `QSignalBlocker`，重置持久任务保留 `_enabled`；用户开关经 `set_enabled_from_ui` 保存。对 `AutoCombatTask` 的支持性阅读确认其持久启用及普通错误恢复契约，但本轮没有启动它。
- WGC 实现的请求锁、代次检查、复制后解除映射、清除旧帧和关闭唤醒均已阅读。配置控件与安装的 ok API 对照后确认：此处 `FlowLayout` 是 `QWidget`，`LabelAndMultiSelection.add_widget` 调用有效；活动占位卡也有 `.task` 属性，未将这两点列为缺陷。

支持性阅读包括 `BaseCombatTask` 的输入/恢复、`combat_once`、切人、死亡、身份加载和轮转准备相关方法，`BaseWWTask`、`AutoCombatTask` 的相关部分，以及安装的 ok `task.py`、配置控件 API。未宣称完整阅读这些范围外文件。

## 完整源码阅读清单

以下各行均表示对应文件全文已读，包含被工具截断后补读的部分；不是仅运行 AST 或搜索得到的覆盖。表内文件名按左列目录解析。

| 目录 | 全文阅读的文件 |
| --- | --- |
| `src/char`（1） | `Aemeath.py`、`Augusta.py`、`Baizhi.py`、`BaseChar.py`、`Brant.py`、`Calcharo.py`、`Camellya.py`、`Cantarella.py` |
| `src/char`（2） | `Carlotta.py`、`Cartethyia.py`、`Changli.py`、`character_names.py`、`CharFactory.py`、`Chisa.py`、`Chixia.py`、`Ciaccona.py` |
| `src/char`（3） | `CustomCharLoader.py`、`Danjin.py`、`Denia.py`、`Douling.py`、`Encore.py`、`Galbrena.py`、`HavocRover.py`、`Hiyuki.py` |
| `src/char`（4） | `Hsin.py`、`Iuno.py`、`Jianxin.py`、`JingRan.py`、`Jinhsi.py`、`Jiyan.py`、`Linnai.py`、`Lucilla.py` |
| `src/char`（5） | `Lucy.py`、`Luhesi.py`、`Lupa.py`、`Mornye.py`、`Mortefi.py`、`Phoebe.py`、`Phrolova.py`、`Qingxiao.py` |
| `src/char`（6） | `Qiuyuan.py`、`Rebecca.py`、`Roccia.py`、`Sanhua.py`、`ShoreKeeper.py`、`Suisui.py`、`Taoqi.py`、`TrialGenericChar.py` |
| `src/char`（7） | `Verina.py`、`Xiangliyao.py`、`Xigelika.py`、`YangYangSp.py`、`Yinlin.py`、`Youhu.py`、`Yuanwu.py`、`Zani.py`、`Zhezhi.py` |
| `src/combat` | `CombatCheck.py`、`roster_context.py`、`rotation_state.py` |
| `custom_ok/ok/device/capture_methods` | `windows_graphics.py` |
| `custom_ok/ok/gui/about` | `AboutTab.py` |
| `custom_ok/ok/gui/common` | `design_system.py` |
| `custom_ok/ok/gui/debug` | `Screenshot.py` |
| `custom_ok/ok/gui` | `MainWindow.py` |
| `custom_ok/ok/gui/settings` | `SettingTab.py` |
| `custom_ok/ok/gui/start` | `SelectCaptureListView.py`、`SelectInteractionListView.py`、`StartCard.py`、`StartTab.py` |
| `custom_ok/ok/gui/tasks` | `ConfigCard.py`、`ConfigItemFactory.py`、`LabelAndDropDown.py`、`LabelAndLabel.py`、`LabelAndMultiSelection.py`、`LabelAndTextEdit.py`、`LabelAndWidget.py`、`OneTimeTaskTab.py`、`TaskCard.py`、`TaskTab.py`、`TriggerTaskTab.py` |
| `custom_ok/ok/gui/widget` | `Card.py`、`FlowLayout.py`、`Tab.py` |
| `custom_ok/ok/notification` | `windows_messenger.py` |
| `custom_ok/ok/task` | `TaskExecutor.py` |
| `custom_ok/ok/util` | `window.py` |

## 验证结果和边界

执行环境为仓库 `.venv`。`tests/TestCharacterReview.py` 的 3 项测试、`tests/TestMessengerReview.py` 的 3 项测试均通过。测试从实际源码提取方法体，以 fake 对象运行，未导入游戏、设备或账户配置模块；这是方法契约与错误分支回归，不能证明真实设备或角色机制正确。

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p TestCharacterReview.py
.\.venv\Scripts\python.exe -m unittest discover -s tests -p TestMessengerReview.py
```

本轮未启动游戏/模拟器，未实例化 OK 或 TaskTestCase，未读取真实账户配置，未进行实际截图或输入，未访问 NAS，也未真实发送通知。Qt 线程/布局、Windows COM 与捕获延迟、实际轮转时序和机制仍需受控实机验证。源码未发现新证据的视觉循环和恢复逻辑没有因“可能卡住”而加等待、重试或兜底。
