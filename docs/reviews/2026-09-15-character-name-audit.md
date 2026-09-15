# 角色名称跨任务审查与修复

版本：1.75.06。

## 范围与发现

检索 src 中角色类名、DISPLAY_NAME、翻译调用、名称别名表及姓名复核路径，检查深塔、战斗公共模块、若梦仍有回声、角色试用与角色代码页。

深塔扫描 CharacterScanRecord.display_name 原来直接翻译 Python 类名，因此 Linnai、Douling、Xigelika、Luhesi 等内部类名与正式翻译键不一致时会留下英文。深塔选队主要依赖 character_id，本次不能据此断言以往深塔战斗失败均由名称造成。

战斗模块与角色代码页各自维护相同别名表，存在以后新增角色只更新一处的风险。活动在 1.75.05 已借用战斗映射，但仍需统一入口。角色试用任务使用页面 OCR 和既有队伍状态，不以类名生成选人姓名，未发现相同原因。

## 修改

新增无 GUI/战斗依赖的 src/char/character_names.py，集中现有八组正式名称映射。深塔扫描、战斗显示、活动识别和角色代码页统一调用 character_display_name。

保留实例 display_name 动态形态优先，其次类 DISPLAY_NAME，再使用类名映射。角色代码文件名、类名、身份 ID、自定义代码加载和配置键不变。原有导出映射别名保留兼容。

## 完整性验证

CharFactory 共注册 52 个不同类；排除 BaseChar 通用占位后，51 个实际角色的正式名称在 zh_CN 和 zh_TW 均有翻译，无额外缺失，未修改 PO/MO。

测试：TestCharacterNames 2 项（遍历全部角色及别名/动态覆盖）、TestCharacterCodeTab 3 项、TestAutoAbyssTask 101 项、TestBaseCombatTask 11 项、TestEchoesContinuationImages 9 项，共 126 项通过。保留琳奈真实截图的头像、姓名、顺序复核。图像测试退出仍有既有框架 GC ResourceWarning，测试通过。

没有进行全部角色的游戏实机验收；这次修复保证名称生成和现有翻译键一致，不保证 OCR 对所有画面的文字识别均无误。未审阅 NAS ZIP。

## 发布

目标 GitHub v1.75.06、NAS .173 稳定通道，完成后记录。
