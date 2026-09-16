# 若梦仍有回声：洛瑟菈姓名识别修复

## 范围与证据

检查本机 `E:/game/okww owener` 打包版 1.79.02 的日志与散装截图，未审阅新的 NAS ZIP，不触发归档审阅或删除。

- 2026-09-16 21:40:24、21:41:21 两次在“燃核兽形·浅梦”抛出“编队页三个姓名未能连续确认，未装配声骸”。两次运行记录 `formation_name_observation` 都停在“洛瑟拉”。
- 源截图位于 `E:/OKWW-Data/14caed06b36648828f3621dcce84b949/screenshots`：`21-40-24.543_echoes_remain_failed_original.png`、`21-41-21.956_echoes_remain_failed_original.png`。
- 生产 OCR 重放：洛瑟拉 0.8958/0.8979，绯雪 0.9556/0.9561，千咲 0.9945/0.9976。正式名称表已有“洛瑟菈”，不是缺角色，而是“菈”误读成“拉”后精确匹配失败。

## 修复

用户批准定向别名方案。仅在若梦任务现有 `character_name_key` 添加完整名称映射“洛瑟拉→洛瑟菈”，初次角色识别和后续编队复核共用；不修改官方显示名、不做全局文字替换、不降低 0.8 置信度阈值、不放宽唯一身份、队伍顺序及连续确认要求。版本与更新日志同步为 1.79.03。

基于已发布 1.79.02，分支 `codex/echoes-lucilla-name`；原工作区未提交修改保持不变。

## 验证

先新增测试，旧代码明确因“洛瑟拉 != 洛瑟菈”失败，再实施修复。

7 个测试文件、87 项全部通过，无跳过、失败或错误：TestEchoesContinuation、TestEchoesContinuationImages、TestEchoesRemainTask、TestEchoesRemainImages、TestCharacterNames、TestReleaseReadiness、TestTestGroups。

两张真实截图均能识别三名正确角色，并通过后续复核；颠倒顺序、低置信度、重复角色、未知名称仍被拒绝。测试只离线回放，未启动游戏或操作真实账号；未宣称完整挑战实跑成功或本机已安装补丁。本次为局部修复，未重跑仓库全量测试。

更新包使用 v1.79.02 为覆盖升级基线，发布回执见下方补充。
