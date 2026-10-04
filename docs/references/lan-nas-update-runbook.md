# 局域网 NAS 更新运维手册

## 角色与边界

开发设备构建并通过 UNC/SMB 写入 NAS；个人客户端直接复用“AI诊断”的 Windows SMB 凭据读取；交换机只转发流量。客户端不需要 NAS 写权限或 GitHub 网络。HTTPS 仍可作为可选读取方式。

局域网产品更新、`config.py` 中的 `update_pyappify` 启动框架升级、`src/upstream_check.py` 的上游提醒是三套独立机制。

## NAS 配置

1. 在 `AI诊断` 下建立 `OKWW-Updates`，发布设备可写，客户端复用既有账户只读访问。
2. 若同时使用 NAS Web 服务，只允许 HTTPS，禁止目录写入、脚本执行和 HTTP 降级。
3. 为 NAS 配置稳定主机名，例如 `nas.lan`。证书的 SAN 必须包含该主机名。
4. 公有或内网 CA 证书使用系统信任库；自签名 CA 导出为 PEM，放到客户端 `configs/lan-update-ca.pem`。
5. 在 Windows PowerShell 读取叶证书指纹：

```powershell
$tcp = [Net.Sockets.TcpClient]::new('nas.lan', 443)
$tls = [Net.Security.SslStream]::new($tcp.GetStream(), $false, { $true })
$tls.AuthenticateAsClient('nas.lan')
$bytes = $tls.RemoteCertificate.Export([Security.Cryptography.X509Certificates.X509ContentType]::Cert)
([Security.Cryptography.SHA256]::HashData($bytes) | ForEach-Object ToString x2) -join ''
$tls.Dispose(); $tcp.Dispose()
```

只允许在可信管理网络中执行这次初始取值，并与 NAS 管理界面显示的证书核对。

## 当前地址与旧地址迁移

当前唯一项目 NAS 目录是 `\\192.168.3.173\羲火君 共享给我\AI诊断`。172、161、170只用于旧配置迁移和保存凭据别名读取，不能作为访问或发布备用地址。

NAS 管理页面不是更新包源。已知旧默认地址和旧共享名会映射到当前共享；自定义服务器、共享和HTTPS配置保持原样。更新清单成功读取后，下载绑定该地址。SMB读取/下载在有超时的独立进程执行。Windows凭据从本NAS的已知旧/新别名读取，不写入明文配置。

旧版若无法连接原默认地址，先按下例修改本机`configs/lan_update.json`至173。若旧安装器自身无法启动，按下方“旧更新器一次性恢复”操作。保留该设备账号配置、运行环境和本地材料资料。

## 客户端配置

个人环境不创建配置时，程序默认读取 `\\192.168.3.173\羲火君 共享给我\AI诊断\OKWW-Updates\stable\latest.json`。需要改用其他共享或 HTTPS 时再创建 `configs/lan_update.json`：

```json
{
  "enabled": true,
  "manifest_url": "\\\\192.168.3.173\\羲火君 共享给我\\AI诊断\\OKWW-Updates\\stable\\latest.json",
  "certificate_sha256": "",
  "ca_file": "",
  "channel": "stable"
}
```

UNC 模式依赖 Windows SMB 身份认证和共享权限；HTTPS 模式要求有效信任链及 64 位小写叶证书 SHA-256 指纹。两种模式都拒绝 HTTP。

## 构建、验证与发布

以 `1.40.02` 更新到 `1.41.00` 为例：

```powershell
.\.venv\Scripts\python.exe .\打包更新.py .\dist\lan
.\.venv\Scripts\python.exe .\scripts\verify_update_package.py .\dist\lan\okww_update_v1.41.00.zip --previous-ref v1.40.02
.\.venv\Scripts\python.exe .\scripts\publish_lan_update.py .\dist\lan\okww_update_v1.41.00.zip --destination "\\NAS\OKWW-Updates" --previous-ref v1.40.02
```

发布器写入 `stable/releases/v1.41.00/`，最后才替换 `stable/latest.json`。不得手工提前复制 `latest.json`。重复发布完全相同的包安全；同版本不同内容会被拒绝。

推送 GitHub 标签不更新 NAS，软件内“检查局域网更新”也不会读取 GitHub Release。每个版本必须单独执行上述 NAS 构建、验证和发布命令；发布后重新读取 `stable/latest.json`，核对版本、大小与 SHA-256，再推送或核对同版本 GitHub 标签。`1.42.03` 曾因只推 GitHub 而遗漏 NAS，已在 `1.42.04` 发布流程中纠正。

## 客户端验收

从 1.97.00 起，用户点击“下载并安装”即授权验证通过后安装和重启。下载期间自动化任务继续运行；安装器确认就绪时程序暂停执行器并退出，安装器等待旧进程结束后才替换文件。无需先手动关闭自动战斗，更新失败时当前程序保持运行。更新后的程序通过账号资料完整性检查后自动开启“开始(F9)”总开关，各辅助任务仍遵循原有独立开关。

在非主用客户端依次验证：

1. 断开互联网、保留局域网，检查并安装成功；确认 `configs` 标记和账号配置不变。
2. 下载中断网，确认当前版本和安装目录未改变。
3. 临时填入错误证书指纹，确认连接在读取响应前被拒绝。
4. 在测试副本注入替换失败，确认状态为 `rolled_back` 且旧版本可启动。

安装结果保存在 `configs/update-result.json`，备份位于 `configs/update-backups/`。至少保留最近两份备份；确认新版本正常启动和任务配置可读后，才可人工归档更旧备份。

1.92.02 起，安装器的标准输出和错误输出保存在本次暂存目录 `configs/update-staging/v版本/helper.log`。设置页“版本与更新”显示上次更新结果。NAS 子进程继承主程序已解析的依赖路径；主程序只在安装器完成包校验、依赖预检并写入就绪标志后退出。Windows 等待通过只读进程句柄实现，不发送任何退出信号。

## 旧更新器一次性恢复

旧代码不能保证自行安装修复自己的新版本。首次升级到1.92.02可在Windows资源管理器打开当前NAS的 `OKWW-Updates\stable\releases\v1.92.02`，复制源码更新ZIP到本机：

1. 关闭OKWW及启动器，备份目标程序目录，尤其是 `configs` 和 `okww监控室`。
2. 在PowerShell用 `Get-FileHash -Algorithm SHA256 '本地ZIP完整路径'` 核对 `stable/latest.json` 对应版本的 `sha256`。
3. 确认旧程序的 `requirements.txt`、`requirements.in` 与ZIP内文件一致；不一致时使用完整安装版本，不手动跳过依赖限制。
4. ZIP先解压到单独临时目录，再将解压内容复制覆盖真正的源码工作目录：打包版是安装目录下 `data\apps\okww-custom\working`，不是安装器EXE所在目录。ZIP不含 `configs`、虚拟环境或监控证据。
5. 保留所有原目录和配置，仅覆盖ZIP包含的源码文件。启动原启动器，确认“版本与更新”为1.92.02、账号和证据存在。随后用新更新器安装后续版本。

这一步不需要访问GitHub。不要把运行设备的整个工作目录复制为新目录后启动，那会造成配置路径变化。

## 证书轮换

先把新证书/CA 和新叶证书指纹以受控配置方式送达所有客户端，确认客户端配置生效后再切换 NAS 证书。证书切换前未取得新指纹的客户端会安全拒绝更新，不能通过关闭 TLS 校验恢复。

## 故障恢复

- `failed`：安装前验证失败，当前安装未改变；修正 NAS 文件或客户端配置后重试。
- `rolled_back`：替换失败但旧文件已恢复；保存日志和对应备份，确认旧版本启动后再调查。
- `rollback_incomplete`：停止继续更新，不删除备份；从 `backup_dir/files` 按 `journal.json` 恢复，或使用完整安装包覆盖源码。恢复时继续保留整个 `configs` 目录。
