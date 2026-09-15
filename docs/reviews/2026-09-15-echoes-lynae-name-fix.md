# 活动编队姓名复核：琳奈名称映射修复

版本：1.75.05。

## 原因与证据

本机打包版 13:19:53 日志识别队伍为爱弥斯、莫宁、Linnai，13:19:55 完成编队，13:20:03 报姓名不一致。运行摘要身份分别为 char_aemeath、char_moning、char_linnai，识别置信度 1.0、1.0、0.96。

失败截图 `13-20-03.626_echoes_remain_failed_original.png` 显示同顺序的爱弥斯、莫宁、琳奈。角色选对了，但活动代码直接使用类名 Linnai 查翻译，现有翻译表使用正式英文名 Lynae，因此英文原样返回，不能匹配中文琳奈。

## 修改

复用 BaseCombatTask 已有 mismatched_names，先将类名映射为正式名称，再调用当前语言翻译。DISPLAY_NAME 仍优先。覆盖已有 Linnai/Lynae、Douling/Buling、Xigelika/Sigrika 等映射，不增加第二套别名表，不改变战斗定位。现有中文翻译已经齐全，本次不改 PO/MO。

## 验证

TestEchoesContinuationImages 9 项、TestEchoesContinuation 18 项，合计 27 项通过。新增本次快速编队和返回编队截图，通过真实头像识别及真实 zh_CN gettext 串联验证爱弥斯、莫宁、琳奈与输出、治疗、辅助；打乱顺序仍拒绝。夹具遮盖监控和身份覆盖区域。图像测试退出有既有框架 GC ResourceWarning，结果通过。

未实机操作，需用户更新后验证声骸装配及后续挑战。未审阅 NAS ZIP，不执行 ZIP 已检查标记。

## 发布

提交 b68942db、注释标签 v1.75.05 已推送 GitHub；NAS `\\192.168.3.173\羲火君 共享给我\AI诊断\OKWW-Updates\stable\latest.json` 已读回确认版本 1.75.05。

更新包 SHA256：`df89286349046a4313763ee43baa11a8afb4f7c0e01f8bd27d159d28089235f5`，NAS 包哈希一致。405 个文件与账号配置保留验证通过。GitHub 安装器 CI 完成状态未检查。
