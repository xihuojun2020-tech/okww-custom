# GameFrame 第二轮鸣潮业务代码审查

日期：2026-10-11。范围按迁移盘点中的业务边界核对：`src/gui` 47 个模块、`src/evidence` 6 个、`src/materials` 6 个，以及顶层 `src` 中 23 个账号、配置、序列、提醒、状态、备份与存储模块，共 82 个模块。以文件级职责和副作用入口扫描全部范围，并沿账号发布/删除、身份绑定、截图保存/导出、材料账本、Qt 后台回调的调用链重点阅读。`main`、`runtime`、`task`、`char`、`custom_ok` 由其他审查范围负责；本报告没有修改它们。

## 发现与修复

完成证据的原图写入原先固定使用 `原图.png.pending`。若进程在写入或重命名之前中断，残留文件会让后续每次 `_write_new` 的独占创建都抛出 `FileExistsError`。核验证据虽有 `pending_verified` 持久日志，恢复时仍会走到同一写入函数，因而原图无法补存。这是从确定的失败路径直接推得的恢复阻断，而非增加重试猜测。

`src/evidence/repository.py` 现为每次写入使用唯一临时名，并在本次写入结束时清理自己的临时文件。已存在的最终原图仍不能覆盖；旧的中断文件留作存储检查证据。`tests/TestCompletionEvidence.py` 增加一个残留固定临时文件后的原图写入回归，验证新内容成功保存且残留证据未被清除。

审查中没有证据支持再改账号发布、身份匹配、材料累计或 GUI 线程模型。特别是证据导出先校验 ZIP 再推进收据；账号编辑和序列发布使用 revision 校验，删除前备份；材料完整结算要求原图和有效奖励单位。没有把这些静态判断写成真实运行成功。

## 核对重点与边界

| 路径 | 本轮核对点 | 结论 |
|---|---|---|
| 账号/配置/序列 | UUID 归属、别名冲突、序列引用、草稿 revision、发布快照与回滚、恢复日志、备份 | 未发现可由当前离线证据证明的新增错误；真实账号未读取 |
| 完成证据 | 保存队列、截图账号归属、原图/缩略图、回收区、导出收据和 ZIP 校验、周期 | 修复中断临时文件阻断后续原图保存；手选账号截图的归属仍由界面选中值明确决定 |
| 材料 | 领取身份、不可变帧、完整结算前提、最新解析版本、跨账号查询 | 文件和 SQLite 使用合成临时目录核对；未操作实际材料页 |
| GUI | `BackgroundOperation` 的 Qt queued 回调、超时行为、账号切换时异步结果、保存与删除入口 | 后台工作没有直接操作 QWidget；未启动完整桌面界面 |

文件级覆盖包括 `src/gui/*.py`、`src/evidence/*.py`、`src/materials/*.py`，以及顶层 `src/account_*.py`、`src/config_*.py`、`src/sequence_repository.py`、`src/secure_backup.py`、`src/storage.py`。这覆盖盘点中的本次业务分工，并不等于逐个业务分支、OCR 画面或设备状态已验收。

## 离线验证

使用仓库 `.venv`，未启动游戏或模拟器，未读取真实配置，未访问 NAS：

```powershell
.\.venv\Scripts\python.exe -m unittest tests.TestCompletionEvidence
.\.venv\Scripts\python.exe -m unittest tests.TestAccountConfigBundle tests.TestConfigIntegrity tests.TestAccountRepositoryRuntime tests.TestSequenceRepository tests.TestAccountReminders tests.TestMaterialRepository
```

分别通过 32 项和 106 项。第一组覆盖残留临时文件修复及证据现有行为；第二组使用 mock/临时目录验证账号、配置、序列、提醒和材料仓库的既有契约。测试通过只证明这些离线路径，没有证明真实切号、截图设备、Qt 完整交互、NAS 上传或游戏任务完成。
