# 1.70.01 若梦仍有回声启动入口修复

问题：1.69.00 已注册 EchoesRemainTask，但 src/gui/activity_catalog.py 仍保留 echoes_remain 占位项。活动页同时生成仅支持保存截图的旧卡和可执行任务卡；旧占位修订号较高，排在真实任务之前，造成没有开始按钮的误解。

修复：删除该活动的占位项，保留群声共振模拟域占位；为 EchoesRemainTask 添加活动修订号，排在已有活动之前。复用标准 TaskCard 开始按钮，不增加另一套运行逻辑。

使用：更新并重启，在「任务 → 活动」展开「若梦仍有回声」，点击开始。自动换上三个试用角色、截图复核并完成编队后停止；不开启挑战。完成检查中的截图入口不是任务启动入口。

验证：TestTaskNavigationClassification、TestNavigationSections、TestEchoesRemainTask 共 16 项通过，1 条既有 pytest 收集警告。检查活动归属、无同名占位、排序及编队流程。不操作真实游戏，用户手动验收。

发布版本为 1.70.01，遵循固定宽度版本格式。保留工作区无关改动。
