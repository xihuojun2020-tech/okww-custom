# 书架风格界面实施验收 · 1.97.16

## 范围与结论

按用户确认的书架风格方案完成账号界面与共享控件改造。参考资源库项目 `E:/AI work/抖音下载` 的漫画／文档书架真实 CSS；保留 PySide6、QFluentWidgets 和原有账号、任务、序列仓库。

主工作区与本机打包版最终使用 **1.97.16**。发布前另一个分支已发布 `v1.97.15` 周度乐园修正，因此合入该标签后使用下一补丁版本，没有覆盖既有标签。

## 实施内容

| 部分 | 结果 |
| --- | --- |
| 主题 | 浅灰蓝背景、白色圆角面板、蓝色操作；导航选中使用书架的 `#EDF2FF / #E0E9FF / #285ECB` |
| 账号导航 | 上方账号选择保留；左侧分类、右侧总览／设置；明确展开图标和选中态 |
| 总览 | 全部、待完成、需要处理、已完成筛选；运行、异常、日常、周常与独立任务、人工提醒、已完成分组 |
| 任务行 | 文字状态标签、实际完成／尝试时间、运行耗时、展开记录；小窗口允许操作与说明换行 |
| 账号归属 | 默认显示序列／槽位／参与摘要，展开编辑；原有草稿和冲突检查保留 |
| 固定序列 | A、B 横向选择，有效执行链，槽位列对齐；窄窗口两行；旧自定义序列入口保留 |
| 参与操作 | 复用原生列表模型、复选框、键盘操作和现有保存路径；执行顺序页只读 |
| 共享页面 | 任务、辅助、设置、工具采用相同分区、间距、圆角及按钮规范 |
| 高度问题 | 保留 1.97.14 修复，并限制展开标题的拉伸；诊断弹窗恢复紧凑间距以适应 640px 窗口 |

任务选择、每日／每周重置、深塔独立启动、人工提醒与材料累计逻辑继续使用已有实现。界面刷新不启动任务。未新增可靠的独立核验时间字段，因此页面明确显示“最近完成记录”，不把 UI 刷新时间写成游戏核验时间。

## 自动化验证

以下 11 个文件共 **134 项界面相关测试**通过：

| 测试 | 数量 |
| --- | ---: |
| TestAccountUIPolish | 7 |
| TestAccountTaskOverview | 15 |
| TestAccountManagementTabs | 36 |
| TestFlatUI | 38 |
| TestCodexLightUI | 5 |
| TestFiveSectionMainWindow | 7 |
| TestForgeryQuotaUI | 3 |
| TestWorldBossMaterialUI | 7 |
| TestLanUpdateUI | 7 |
| TestDiagnosticDetailsUI | 1 |
| TestCompletionCheckUI | 8 |

新增回归覆盖混合状态筛选、首次运行耗时、人工标记、完成组展开、固定序列选择、原生 Space 切换参与、只读页不写入、旧自定义序列入口。现有测试覆盖草稿、过期异步读取、记录失败、周期与独立任务展示。

最终基础控件改动后，重新执行 100%、125%、150% 缩放下的 1280×800、1440×900、1920×1080 **九组窗口矩阵**，均通过；检查正文横向溢出、展开／收起高度及路由切换。重复运行的测试不重复计入 134 项。

合入 1.97.15 后，另通过 `TestWeeklyDailyIntegration` 21 项及 `TestGardenPageImages` 4 项，共 **25 项**。OCR 图像回放确认漏字标题仍能读取当前游历值。

验证结果保存在忽略目录 `test_out/bookshelf-ui-tests/`。日志中的 Qt 弃用／退出回收警告和更新器注入失败场景未导致测试失败。

## 图像验收

提交的图片由实际 Qt 组件和临时测试账号生成，图上明确标注测试／示例数据：

- [实际总览组件](../images/bookshelf-account-overview-implemented.png)
- [实际执行顺序组件](../images/bookshelf-account-order-implemented.png)

本机程序实测已查看账号总览、可编辑序列、只读顺序、设置字段、任务页、自动辅助、工具和全局设置。最终 1.97.16 的固定槽位收起截图确认：标题、参与数、执行链和说明按内容排列，未再撑满窗口。

真实账号截图仅留在忽略目录，包括 `bookshelf-final-order.png`、`bookshelf-final-order-collapsed.png`、`bookshelf-final-task.png`、`bookshelf-final-assistant.png`、`bookshelf-final-tools.png`、`bookshelf-final-settings.png`；没有把用户账号信息提交到 GitHub。

## 更新包与本机安装

- 更新包：`test_out/release-1.97.16/okww_update_v1.97.16.zip`。
- SHA256：`759966199180d1f0ceb93ff888cb89b40a9a6def53b443e145e9cada2073f7fa`。
- 与 `v1.97.15` 对照，**481 个文件**通过更新清单与本机安装后哈希核验。
- 包内容检查通过：assets=1，zip_contents_checked=1，installer_payloads_unverified=0。
- 安装位置：`E:/game/okww owener/data/apps/okww-custom/working`。
- 最终配置备份：`E:/game/okww owener/backups/bookshelf-ui-1.97.16-20261006-111110`。
- 通过原有 `lan_apply.apply_request` 安装，正常关闭并自动重新启动；窗口标题确认 `OK-WW 1.97.16`。

首次临时安装时为 1.97.15；随后检测到该标签已被周度乐园版本使用，完成合入并安装最终 1.97.16。每次安装即时均验证账号主图、运行账本、自动战斗与角色配置一致。

首次安装后参与列表出现新的交互变更；未恢复旧列表。最终安装以最新配置为基准，实际执行链为 A1 → A2 → A3 → A4。最终启动和页面验收后的复核再次确认账号主图、运行账本、偏好与该安装基准完全一致。

## 验证限度

本次没有执行游戏内每日、深塔或真实战斗；自动战斗保留启用意图，在游戏窗口断开时等待恢复。截图与 OCR 回放不能替代实机游戏任务验收。

没有重跑全仓库全部测试；验证集中于改动涉及的界面、保存路径、更新器以及合入的乐园流程。GitHub 推送和远程构建分别核验，远程安装器是否完成以 Actions 结果为准。
