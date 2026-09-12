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

## 1.59.00 地址迁移

2026-09-12 已验证 `\\192.168.3.172\羲火君 共享给我\AI诊断` 可访问。172/173 为用户指定的同一 NAS 候选地址；当前172为首选，173为备用，备用路径尚未完成实际下载验收。

`http://192.168.3.172:5666/` 是飞牛管理页面，不是更新包源。已知旧默认161/170和旧共享名会映射到新共享；自定义服务器、共享和HTTPS配置保持原样。更新清单成功读取后，下载绑定该地址。SMB读取/下载在有超时的独立进程执行；诊断上传也在既有超时内尝试候选地址。Windows凭据从本NAS的已知旧/新别名读取，不写入明文配置。

另一台设备需要先取得1.59.00代码才具备回退能力：旧版若连不上原默认地址，先按下例修改本机`configs/lan_update.json`至172的新共享，或手动安装NAS上的更新包。升级后不再需要跟随172/173变动反复改地址。保留该设备账号配置、运行环境和本地材料资料。

## 客户端配置

个人环境不创建配置时，程序默认读取 `\\192.168.3.172\羲火君 共享给我\AI诊断\OKWW-Updates\stable\latest.json`。需要改用其他共享或 HTTPS 时再创建 `configs/lan_update.json`：

```json
{
  "enabled": true,
  "manifest_url": "\\\\192.168.3.172\\羲火君 共享给我\\AI诊断\\OKWW-Updates\\stable\\latest.json",
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

在非主用客户端依次验证：

1. 断开互联网、保留局域网，检查并安装成功；确认 `configs` 标记和账号配置不变。
2. 下载中断网，确认当前版本和安装目录未改变。
3. 临时填入错误证书指纹，确认连接在读取响应前被拒绝。
4. 在测试副本注入替换失败，确认状态为 `rolled_back` 且旧版本可启动。

安装结果保存在 `configs/update-result.json`，备份位于 `configs/update-backups/`。至少保留最近两份备份；确认新版本正常启动和任务配置可读后，才可人工归档更旧备份。

## 证书轮换

先把新证书/CA 和新叶证书指纹以受控配置方式送达所有客户端，确认客户端配置生效后再切换 NAS 证书。证书切换前未取得新指纹的客户端会安全拒绝更新，不能通过关闭 TLS 校验恢复。

## 故障恢复

- `failed`：安装前验证失败，当前安装未改变；修正 NAS 文件或客户端配置后重试。
- `rolled_back`：替换失败但旧文件已恢复；保存日志和对应备份，确认旧版本启动后再调查。
- `rollback_incomplete`：停止继续更新，不删除备份；从 `backup_dir/files` 按 `journal.json` 恢复，或使用完整安装包覆盖源码。恢复时继续保留整个 `configs` 目录。
