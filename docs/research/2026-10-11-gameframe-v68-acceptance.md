# GameFrame 1.97.68 阶段验收

跨进程输入、包与数据锁已接入，真实进程和最终安装分发物离线验收通过。兼容路径补齐数据锁、写入者收尾及Windows stdin/NumPy冷启动问题；原生worker执行后游戏包索引仍完整。本阶段继续承接全部功能迁移，尚未将总目标标为完成。

| 检查 | 结果 | 验证范围 |
|---|---|---|
| OS锁真实进程 | 10项通过，2.434秒 | Windows输入范围、SH/EX、父死子活、owner死亡释放 |
| 更新/安装锁与事务 | 17项通过 | 含5项新增竞争检查，双updater、并发install与恢复 |
| 包模块进程 | 4项通过 | 导入与运行持锁、SystemExit(7)、stale/EX先于载荷导入拒绝 |
| worker设备与包close | 4项通过 | cleanup门闩期间保持三锁，原close异常不吞，store/package继续清理 |
| 原生诊断收尾 | 9项通过 | 队列drain、超时后补收尾、metadata失败、中文末帧；原生命周期另1项通过 |
| 相关worker/CLI/launcher/迁移/配置入口 | 38项通过，14.930秒 | 最后一次核心接线回归；与上方部分重复，不累计总数 |
| 兼容实际服务/session锁与failure | 5项通过，3.181秒 | 真实Evidence池/DiagnosticSession门闩、早期导入原异常、session输入互斥及finalize失败 |
| 兼容CLI独立冷启动 | 1项通过，0.163秒 | main内部晚导NumPy/cv2，ready前无需stdin输入，正常stop |
| 索引包相对导入 | 1项通过，0.048秒 | 真实安装、相对模块导入后SHA索引通过且无pyc |
| 最终ZIP生产轮转/管理配置 | 2项通过，10.660秒 | 使用最终artifact，阻旧ok/Qt导入的生产轮转；真实安装管理/config生命周期 |
| 最终v67→v68更新及诊断 | 交换通过；1项通过，0.766秒 | 索引/rename、私有数据哨兵保持、安装载荷真实离线归档 |
| 最终安装包实际worker.main | 通过 | 生产轮转至首次输入后停止；2动作，199个src模块全部来自payload；诊断session清空、证据池结束、索引仍通过 |
| MIT wheel | 隔离导入通过 | 无src/ok/assets；阻游戏代码与Qt，使用现有依赖环境 |

服务停止正常退出码为0，执行账本明确cancelled，启用意图仍为True；一次性worker取消约定仍为130。未更改现有服务退出语义。Qt污染的无Qt检查仍分进程/单模块执行，没有放宽断言。

## 分发物

备份目录：`E:/AI work/okww-framework-backups/20261011-v1.97.68`。源码ZIP逐文件SHA/CRC校验、Python解析、Git状态/patch和verified bundle保存在同目录；前次预构建已留存为superseded，以下为最终分发物。

| 文件 | 字节数 | SHA256 |
|---|---:|---|
| gameframe_runtime-1.97.68-py3-none-any.whl | 46611 | 6bd4ed4ea8bfb9739fb804dab32b4d582922ab8366382ced2c54166a99037b2d |
| wuthering_waves-1.97.68.zip | 38872783 | fc07f71f490aec7d4cb9f1e46ce2147778e707154b1bfc4226593cac182d2cce |
| wuthering_waves_native-1.97.68.zip | 38289662 | 1ebb3ddd906247181f607520412b9ebfd11a53d70e910639807c0fcce75e6c23 |

不启动游戏、模拟器、实际后台会话或真实账号，不访问NAS。本轮不能证明实战全分支、Windows后台兼容或硬件延迟。POSIX未实跑，ADB/MuMu同实例跨后端互斥尚未提供。备份恢复、动态任务/角色、日历与耗时视图继续推进；提醒和临时唤醒保持启用。核心自主代码MIT，鸣潮派生规则与管理AGPL，原素材来源清单295项继续保留。
