# GameFrame v1.97.76 最终更新链路复核

本轮补齐配套环境更新、稳定登录和定时入口，并复核最终消费者。核心与鸣潮规则仍分别放在 MIT 核心和 AGPL 派生包；更新不会替换用户资料或清除自动战斗启用设置。全量结构扫描和此前各模块人工复核见第一轮、运行时、任务、角色、业务及各阶段报告；本轮人工审查限于新增更新链路与受影响入口，没有宣称每个历史分支均经过人工审查。

独立审查覆盖 release manifest/source/publisher、managed installer/bootstrap/owner、GUI 更新与登录控件、worker/package_process 身份、计划任务消费者。审查发现四个能复现的根因，修复后独立相关回归 26 项通过。

| 根因 | 修复及依据 |
| --- | --- |
| 环境准备未消费游戏包两份 requirements；缺依赖仍可能产生候选 | 从已验证 ZIP 读取锁定依赖，同一离线 resolver 安装 core extras 和包 requirements。真实缺失 requests wheel 时 pip 失败，候选清理，不生成 ready/pending。 |
| 迟到的旧候选覆盖较新 pending | 在共同 switch gate 内比较 active/pending 发行顺序，拒绝倒退和同身份不同内容；只清理本次未发布的候选。 |
| CLI source 失败覆盖 bootstrap 的失败候选标记 | 删除 CLI 写同一 marker 的机制，CLI 用原 JSONL 边界报告失败，bootstrap 的阻断与显式重试意图完整保留。 |
| 显式手动准备复用自动候选后，手动策略一直阻止提交 | 相同 bundle/ready 在 gate 内改为明确的 manual 意图；自动检查不覆盖用户显式意图。 |

稳定入口另有两个实际消费者问题：资料根变更后更新核对旧根，以及定时计划绑定版本化解释器。更新读取既有 launcher-context 的有效根；受管理计划改用版本目录外 bootstrap，并在执行时解析 active 及有效资料根。旧计划精确识别后显示重建提示，仅允许用户明确删除，没有自动改写系统计划。

登录启动项使用当前用户 HKCU 的自有值，受管理入口指向稳定 bootstrap。GUI、worker、配置、管理、总览和更新子进程分别持有环境租约；旧解释器在切换后迟到启动会明确拒绝。完整包身份在已知执行边界核对。捕获与输入仍只有一个 owner，普通错误、失败更新和暂停均不清除保存的战斗意图。

最后一个测试失败来自旧 fixture：`manifest.task` 仍接受一个参数，生产契约已接受 identifier/data_dir，测试在创建设备前返回 TypeError。仅修正测试替身，单项通过并确认原设备关闭异常对象保留、package/store 收尾和三类 lease 释放；没有为替身新增生产兼容分支。Overlay 的无构造 fixture 同样补齐新更新控件契约。

新增保护分支依据分别是：外部工件路径、SHA/size/包身份、wheel metadata 和锁定 requirements；系统租约和原子指针提交契约；持久用户策略；真实 source HTTP/SMB 错误分类。HTTP 404／真正 FileNotFound 表示未发布；权限、TLS、网络及缺选定工件均明确失败。没有将错误转换为最新、空结果或假成功，没有新增总重试次数关闭、自动强停任务或后台 NAS 检查。

定时与维护页使用既有 gettext；设备表单收尾也只接既有 schema labels，不建立第二语言配置。显示文案与 backend/key/capture/input 标识分开，参数和用户窗口标题保持原值。详细测试与最终工件证据见 [v76 验收](2026-10-11-gameframe-v76-acceptance.md) 与 [最终覆盖矩阵](2026-10-11-gameframe-final-coverage.md)。

真实 Windows 登录、Task Scheduler 触发、游戏输入和渲染、Child Session/RDP、硬件延迟、公网通知与 NAS 没有实测。离线复核只能支持其记录的契约和安装结论。
