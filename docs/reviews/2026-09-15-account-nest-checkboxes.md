# 账号残象聚落勾选配置

版本：1.77.02。

账号任务“日常与声骸”的残象聚落目标原来使用 JSON 列表文本框，现在改为四个固定复选框：落渊南丘残象聚落、盲望之塌残象聚落、复生丘原残象聚落、陷足流川残象聚落。新账号模板使用相同控件。

勾选项按游戏顺序保存为既有 Tacet Discord Nests to Farm 列表，任务沿用原有名称过滤，只打选中聚落。全部取消保存 []，不会回退为全选。旧配置已有选择保持；字段缺失/None 与既有执行默认一致为全选。既有梦魇/每日任务开关仍负责是否执行这一任务阶段。

四个名称集中到 src/nightmare_nests.py，账号控件、DailyTask 与 NightmareNestTask 共用，避免不同页面名称漂移。保存草稿、保存后回读、模板保存均接入多选值读取；间距 4 像素，不增加分割线。

验证：TestAccountManagementTabs 29 项及 TestNightmareNestTask 19 项通过，共 48 项，覆盖旧选择、增加勾选、模板保存、清空选择和原有任务过滤。Qt 测试退出有既有 GC ResourceWarning，结果通过。未操作游戏实机刷取。

提交 5821258c 与注释标签 v1.77.02 已推送 GitHub。NAS .173 的 OKWW-Updates/stable/latest.json 已确认版本 1.77.02。更新包 SHA256：`76816390357d3f0b9ad0ecd4c14f1cce24faefd67da5715e40c46dd7d1b04628`，NAS 哈希一致；407 个文件及账号配置保留校验通过。安装器 CI 完成状态未确认。
