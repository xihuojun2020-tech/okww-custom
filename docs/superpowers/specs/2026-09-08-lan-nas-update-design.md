# 局域网 NAS 产品更新设计

## 1. 目标

让开发设备把已验证的 OK-WW 更新包发布到同一局域网中的 NAS，客户端直接从 NAS 检查、下载并安装产品更新，不依赖 GitHub 可达性。交换机仅负责转发网络流量，不保存或发布更新。

首版交付一条可回滚的稳定通道：开发机生成既有 `okww_update_vX.YY.ZZ.zip`，发布工具将其原子发布到 NAS；客户端显式检查并确认安装；独立更新进程在主程序退出后替换受控源码，失败时恢复原版本。

## 2. 范围与非目标

范围：

- 个人环境默认由客户端通过已有 Windows SMB 凭据只读访问 NAS，开发机通过同一共享写入；HTTPS 是可选的证书固定传输。
- 复用 `打包更新.py` 的 ZIP、包内 `update-manifest.json` 和 `scripts/verify_update_package.py`。
- 支持 `stable` 通道、手动检查、明确确认、下载、校验、安装、回滚和结果提示。
- 产品更新配置保存在 `configs/lan_update.json`，更新包不得覆盖它。
- GitHub 可以继续用于源码备份和完整安装器发布，但客户端 LAN 更新路径不得调用 GitHub。

非目标：

- 不把交换机当更新服务器。
- 不改造 `config['update_pyappify']`；它只升级 pyappify 启动框架。
- 首版不自动修改 `.venv`、runtime、Python、pyappify 或安装器。
- 首版不支持无人值守强制安装、跨网访问、HTTP 明文降级或版本降级。
- `requirements.txt`、`requirements.in`、Python 要求或 pyappify 要求变化时，不做源码热更新，提示安装完整版本。

## 3. 部署拓扑与目录

```text
开发设备 --UNC/SMB 写入--> NAS 发布目录 --UNC/SMB 只读--> 客户端
                         |
                         +-- stable/latest.json
                         +-- stable/releases/v1.40.03/
                             +-- okww_update_v1.40.03.zip
                             +-- SHA256SUMS.txt
```

建议 NAS 根目录：

```text
OKWW-Updates/
├─ stable/
│  ├─ latest.json
│  └─ releases/
│     └─ v1.40.03/
│        ├─ okww_update_v1.40.03.zip
│        └─ SHA256SUMS.txt
├─ beta/
└─ archive/
```

个人客户端默认读取 `\\192.168.3.161\xihuojun 共享给我\AI诊断\OKWW-Updates\stable\latest.json`。NAS 账户应限制为发布设备可写、客户端只读；可选 HTTPS 地址形如 `https://nas.lan/OKWW-Updates/stable/latest.json`。

## 4. 信任与威胁模型

SHA-256 只能发现传输损坏，不能阻止 NAS 上的清单和 ZIP 同时被替换。默认 SMB 模式信任 Windows 身份认证、共享权限和 NAS 本身；HTTPS 模式额外固定 NAS 叶证书的 DER SHA-256 指纹。客户端验证：

1. SMB 路径位于配置的 UNC 共享，或 TLS 证书链可信且叶证书指纹匹配；
2. `latest.json` 中 ZIP 的长度和 SHA-256 正确；
3. ZIP 路径、成员集合及包内 `update-manifest.json` 的逐文件 SHA-256 正确；
4. 发布版本严格高于当前版本，且包内版本等于外层清单版本。

证书续期需要先在 HTTPS 客户端受控更新指纹。若使用自签名证书，则把 CA/证书放在 `configs/lan-update-ca.pem`。任何 SMB、TLS、指纹、JSON、路径、长度或哈希错误都必须停止，不能回退到 HTTP 或 GitHub。

配置和日志不得包含 NAS 写入凭据。清单响应上限 64 KiB，ZIP 上限 512 MiB；连接超时 5 秒、读取总超时 120 秒。

## 5. 外层发布清单

`latest.json` 使用 UTF-8、确定性 JSON，字段固定如下：

```json
{
  "schema_version": 1,
  "channel": "stable",
  "version": "1.40.03",
  "package": "releases/v1.40.03/okww_update_v1.40.03.zip",
  "sha256": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
  "size": 1234567,
  "published_at": "2026-09-08T10:00:00Z"
}
```

约束：版本必须匹配 `^[0-9]+\.[0-9]{2}\.[0-9]{2}$`；`channel` 必须是 `stable`；`package` 必须是 POSIX 相对路径且位于 `releases/v{version}/`，不得含查询串、反斜线、空段、`.`、`..` 或百分号；哈希必须是 64 位小写十六进制；大小为 `1..536870912`；时间必须是带 `Z` 的 UTC RFC 3339；不接受未知字段，防止协议静默漂移。

## 6. 发布流程

发布入口为 `scripts/publish_lan_update.py ARCHIVE --destination UNC_PATH --base-url HTTPS_URL --certificate-sha256 HEX`。它执行：

1. 调用现有 `verify_update()` 校验 ZIP 和目标源码差异；
2. 拒绝覆盖已经存在但内容不同的版本目录；
3. 在同一 NAS 目录写 `*.tmp-<uuid>`，刷盘后重新计算哈希；
4. 原子重命名 ZIP，再写并重命名 `SHA256SUMS.txt`；
5. 最后写 `latest.json.tmp-<uuid>` 并原子替换 `latest.json`。

`latest.json` 永远最后发布，因此客户端只会看到旧的完整版本或新的完整版本。重复发布相同字节允许成功返回；同版本不同字节必须失败。发布工具不接收或保存 NAS 密码，由操作系统已挂载的 UNC 会话处理认证。

## 7. 客户端状态机

```text
IDLE -> CHECKING -> UP_TO_DATE
                 -> AVAILABLE -> DOWNLOADING -> VERIFIED -> AWAITING_CONFIRMATION
                                                        -> APPLY_SCHEDULED -> EXITING
任意检查/下载/校验失败 -> FAILED（当前安装不变）
下次启动读取结果文件 -> SUCCEEDED 或 ROLLED_BACK/FAILED
```

- 启动后不自动安装；设置页提供“检查局域网更新”按钮。
- 检查和下载均在后台线程进行，自动化任务运行期间禁止进入安装确认。
- 用户确认后，把经过校验的 ZIP 和不可变的 `apply-request.json` 放入 `configs/update-staging/vX.YY.ZZ/`。
- 主程序复制更新执行器到系统临时目录，启动它并正常退出；执行器等待父 PID 退出后再触碰产品文件。
- 取消、断网、超时或关闭窗口只删除未完成下载，不改变当前安装。

## 8. 应用、回滚与恢复

更新执行器只处理 `打包更新.py::SYNC_ITEMS` 中的受控文件，拒绝符号链接、结点链接、绝对路径、重复路径和大小写冲突。它先完成全部预检，再修改目标：

1. 验证请求文件、ZIP 哈希、包内清单和安装根目录；
2. 要求包内 `requirements.txt` 与当前文件字节完全相同，并要求框架 pin 相同；否则退出并提示完整安装；
3. 把将被覆盖或删除的受控文件复制到同卷 `configs/update-backups/v<old>-to-v<new>/`；
4. 将 ZIP 解到同卷 staging，逐个以 `os.replace()` 替换文件；
5. 删除旧版存在但新包清单不存在的 `src/**/*.py` 与 `custom_ok/**/*.py`，删除前必须已备份；
6. 写 `configs/update-result.json` 后重启应用；
7. 任一步失败则按日志逆序恢复备份，再写失败结果，保留当前版本可启动。

绝不删除或覆盖 `configs/`、`logs/`、`screenshots/`、诊断目录、`.venv/`、`runtime/`、用户自定义目录或 NAS 配置。恢复日志必须使用绝对规范化路径并确认每个目标均位于安装根目录内。成功启动并展示结果后才清理 staging；备份至少保留最近两份。

## 9. 配置与界面

`configs/lan_update.json` 默认值：

```json
{
  "enabled": true,
  "manifest_url": "\\\\192.168.3.161\\xihuojun 共享给我\\AI诊断\\OKWW-Updates\\stable\\latest.json",
  "certificate_sha256": "",
  "ca_file": "",
  "channel": "stable"
}
```

缺少配置文件时使用上述个人 UNC 默认值；显式配置可选择 UNC 或 HTTPS，HTTPS 必须提供指纹。设置页新增独立“局域网更新”卡片，显示当前版本、检查按钮、可用版本、下载/校验进度和最近安装结果。

## 10. 验收标准

- 断开互联网但保持 LAN 时，客户端可从 NAS 检查并更新到更高版本。
- 发布中途失败时 `latest.json` 仍指向上一完整版本。
- 截断下载、错误长度、错误 ZIP 哈希、错误包内哈希、错误证书、路径穿越、同版本和降级均被拒绝，安装目录不变。
- 更新执行中每个受控替换点的故障注入都能回滚，并保留 `configs` 合成标记。
- 依赖文件变化时自动更新被拒绝并明确提示完整安装。
- GitHub 不可达不会影响 LAN 检查、下载或安装；现有上游提醒和 pyappify 升级仍是独立功能。
- 在真实 NAS 和一台客户端完成一次成功更新、一次断网失败、一次错误指纹失败和一次人工回滚验证。
