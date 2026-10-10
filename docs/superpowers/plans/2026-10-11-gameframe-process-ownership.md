# GameFrame 跨进程所有权实施计划

**Goal:** 多个启动器、CLI和日历入口只能由一个实际执行进程控制同一输入设备；包更新与恢复不能替换正在使用的代码或数据。

**Architecture:** 使用操作系统内核锁，实际子进程持到全部cleanup完成。Windows桌面输入以会话内真实WindowStation/Desktop为键，ADB以serial、MuMu以安装目录与instance为键。包与数据目录采用文件共享/独占锁，固定package→data→device顺序。

**Tech Stack:** Python标准库ctypes/contextlib；Windows mutex/LockFileEx；POSIX flock；真实临时fixture进程。

**Spec:** 用户已授权框架/全功能迁移目标与单一输入owner约束；v67复核确认跨launcher锁缺口；现有AccountChangeLock只覆盖单次写事务，恢复空闲检查不能观察其他worker。

## 约束

不启动游戏/模拟器、不访问NAS、不操作真实账号。不重试、不用PID哨兵、不设过期时间、不删除锁文件。竞争立即明确失败。版本1.97.68。不同Windows用户按用户手动切换。ADB与MuMu没有同实例跨backend映射，不声称这一范围已互斥。

## 文件及接口

| 所属 | 文件 | 接口及接点 |
|---|---|---|
| 锁代理 | gameframe/process_locks.py、TestGameFrameProcessLocks.py | device_input_lease(options)、package_lease(root,exclusive=False)、data_lease(root,exclusive=False)，均contextmanager；LeaseUnavailable(RuntimeError) |
| 更新代理 | packages.py、package_updates.py及更新锁测试 | install最终exists/rename/read为EX；prepare读取旧包为SH；apply/recovery变更全过程EX，锁内重新读取journal/版本 |
| 主代理 | worker.py、controller.py、package_process.py、原生plugin/config UI及兼容bootstrap | worker包SH→数据SH→输入EX，在device构造前取得输入，device/store关闭后释放；管理/配置实际child在导入payload前包SH，锁内核对版本 |
| 备份调查代理 | 下一阶段只读设计 | 复用data锁设计恢复/存储迁移；配置owner停止后EX，提交和重绑定后释放，再启动owner |

## 实施与最小验收

- [x] 操作系统锁。两个真实fixture争相同设备失败、不同设备并行；两个包SH共存，EX被阻；父退出但child活着锁仍在；owner退出/被终止后释放。
- [x] worker生命周期接入。`main --package ... --task ... --device ...` 冲突发生在设备创建前；pause不释放；close阻塞期间不能第二次取得输入，cleanup异常也由finally释放。
- [x] 实际管理/config入口。`python -m gameframe.package_process --package ROOT --expected-version VERSION --module src.management -- ...` 在载荷导入前持包SH，管理模块结束后才释放；配置owner同样持数据SH。版本已变化明确拒绝。
- [x] 更新和安装接入。真实shared owner阻止rename；双updater/installer不同时成功；中断rollback依旧在EX内恢复；private data不变。
- [x] 本轮保护分支复核与相关旧路径检查，分发物安装验收、备份、发布。

包锁不能代替输入锁；路径不同的两套包仍争同一桌面输入。Replay只操作离线文件，不争真实输入。核心import不得加载src/ok/Qt或设备DLL。
